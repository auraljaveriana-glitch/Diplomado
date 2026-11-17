"""Bot de WhatsApp (Cloud API de Meta) que pide el nombre y envía un diploma en PDF.

Flujo:
  1. Usuario escribe cualquier cosa  -> bot saluda y pide el nombre completo.
  2. Usuario envía el nombre         -> bot pide confirmación (botones Sí / Corregir).
  3. Usuario confirma                -> bot genera el PDF y lo envía como documento.
  Escribir "diploma" o "reiniciar" en cualquier momento vuelve a empezar.
"""
import logging
import os
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response

from diploma import generar_diploma, limpiar_nombre, nombre_archivo

TOKEN = os.environ["WHATSAPP_TOKEN"]
PHONE_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "aural-diplomas")
API = f"https://graph.facebook.com/v21.0/{PHONE_ID}"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot-diplomas")
app = FastAPI()

# Estado en memoria: {telefono: {"paso": ..., "nombre": ...}}
# Para producción con varios workers, cámbialo por Redis o Supabase.
estados: dict[str, dict] = {}
procesados: set[str] = set()  # evita responder dos veces si Meta reintenta

MSG_BIENVENIDA = (
    "¡Hola! 👋 Soy el asistente de *Aural Centros Auditivos*.\n\n"
    "Voy a generar tu diploma. Por favor escríbeme tu *nombre completo* "
    "tal como quieres que aparezca."
)


# ---------------------------- Envío de mensajes ----------------------------
async def enviar_texto(to: str, texto: str):
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.post(f"{API}/messages", headers=HEADERS, json={
            "messaging_product": "whatsapp", "to": to,
            "type": "text", "text": {"body": texto},
        })
        r.raise_for_status()


async def enviar_confirmacion(to: str, nombre: str):
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.post(f"{API}/messages", headers=HEADERS, json={
            "messaging_product": "whatsapp", "to": to, "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": f"Tu diploma saldrá a nombre de:\n\n*{nombre}*\n\n¿Está correcto?"},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": "ok", "title": "Sí, generar"}},
                    {"type": "reply", "reply": {"id": "corregir", "title": "Corregir"}},
                ]},
            },
        })
        r.raise_for_status()


async def enviar_pdf(to: str, ruta: Path, nombre_doc: str, caption: str):
    async with httpx.AsyncClient(timeout=60) as cli:
        with open(ruta, "rb") as f:
            up = await cli.post(f"{API}/media", headers=HEADERS,
                                data={"messaging_product": "whatsapp", "type": "application/pdf"},
                                files={"file": (nombre_doc, f, "application/pdf")})
        up.raise_for_status()
        media_id = up.json()["id"]
        r = await cli.post(f"{API}/messages", headers=HEADERS, json={
            "messaging_product": "whatsapp", "to": to, "type": "document",
            "document": {"id": media_id, "filename": nombre_doc, "caption": caption},
        })
        r.raise_for_status()


# ---------------------------- Lógica del flujo ----------------------------
def nombre_valido(texto: str) -> bool:
    partes = texto.split()
    return (2 <= len(partes) <= 6 and 5 <= len(texto) <= 60
            and all(p.replace("-", "").replace("'", "").isalpha() for p in partes))


async def manejar(tel: str, texto: str | None, boton: str | None):
    estado = estados.get(tel)
    t = (texto or "").strip()

    if estado is None or t.lower() in {"diploma", "reiniciar", "inicio"}:
        estados[tel] = {"paso": "esperando_nombre"}
        await enviar_texto(tel, MSG_BIENVENIDA)
        return

    if estado["paso"] == "esperando_nombre":
        if not nombre_valido(t):
            await enviar_texto(tel, "Por favor escríbeme tu *nombre y apellido* (solo letras), "
                                    "por ejemplo: _María Fernanda Gómez_.")
            return
        estado.update(paso="confirmando", nombre=limpiar_nombre(t))
        await enviar_confirmacion(tel, estado["nombre"])
        return

    if estado["paso"] == "confirmando":
        if boton == "corregir" or t.lower() in {"no", "corregir"}:
            estado["paso"] = "esperando_nombre"
            await enviar_texto(tel, "Sin problema ✍️ Escríbeme de nuevo tu nombre completo.")
            return
        if boton == "ok" or t.lower() in {"si", "sí", "ok"}:
            nombre = estado["nombre"]
            await enviar_texto(tel, "Generando tu diploma... ⏳")
            doc = nombre_archivo(nombre)
            with tempfile.TemporaryDirectory() as tmp:
                ruta = generar_diploma(nombre, Path(tmp) / doc)
                await enviar_pdf(tel, ruta, doc, f"🎓 ¡Felicitaciones, {nombre.split()[0]}!")
            estado["paso"] = "terminado"
            await enviar_texto(tel, "¡Listo! Si necesitas generarlo otra vez, escribe *diploma*.")
            return
        await enviar_confirmacion(tel, estado["nombre"])
        return

    # paso == terminado
    await enviar_texto(tel, "Tu diploma ya fue enviado ✅ Escribe *diploma* si quieres generar otro.")


# ---------------------------- Webhook ----------------------------
@app.get("/webhook")
async def verificar(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(p.get("hub.challenge"), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def recibir(request: Request):
    data = await request.json()
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    if msg["id"] in procesados:
                        continue
                    procesados.add(msg["id"])
                    tel = msg["from"]
                    texto = msg.get("text", {}).get("body") if msg["type"] == "text" else None
                    boton = None
                    if msg["type"] == "interactive":
                        boton = msg["interactive"].get("button_reply", {}).get("id")
                    await manejar(tel, texto, boton)
    except Exception:
        log.exception("Error procesando webhook")
    return {"status": "ok"}  # siempre 200 para que Meta no reintente en bucle


@app.get("/")
def salud():
    return {"ok": True}
