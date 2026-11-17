"""Bot de WhatsApp (Cloud API de Meta) para el diplomado + panel de resultados.

Flujo del bot:
  1. Autorización de datos (Ley 1581 de 2012).
  2. Datos: nombre, profesión, teléfono, dirección, ciudad -> confirmación.
  3. Encuesta de satisfacción (preguntas en encuesta.py).
  4. Envío del diploma en PDF.
  5. En segundo plano, Claude evalúa las respuestas.

Panel: /panel (usuario y contraseña con PANEL_USER / PANEL_PASSWORD).
"""
import asyncio
import csv
import io
import logging
import os
import re
import secrets
import tempfile
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import db
from diploma import generar_diploma, limpiar_nombre, nombre_archivo
from encuesta import ETIQUETAS_ESCALA, POR_ID, PREGUNTAS

TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "aural-diplomas")
PANEL_USER = os.getenv("PANEL_USER", "aural")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
POLITICA_URL = os.getenv("POLITICA_URL", "")
API = f"https://graph.facebook.com/v21.0/{PHONE_ID}"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
BASE = Path(__file__).parent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot-diplomas")
app = FastAPI()
procesados: set[str] = set()
tareas: set[asyncio.Task] = set()


# ============================ Envío de mensajes ============================
async def _post(payload: dict):
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.post(f"{API}/messages", headers=HEADERS,
                           json={"messaging_product": "whatsapp", **payload})
        if r.status_code >= 400:
            log.error("Error WhatsApp %s: %s", r.status_code, r.text)
        r.raise_for_status()


async def texto(to, body):
    await _post({"to": to, "type": "text", "text": {"body": body}})


async def botones(to, body, opciones: list[tuple[str, str]]):
    await _post({"to": to, "type": "interactive", "interactive": {
        "type": "button", "body": {"text": body},
        "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t[:20]}}
                               for i, t in opciones[:3]]}}})


async def lista(to, body, boton, filas: list[tuple[str, str]]):
    await _post({"to": to, "type": "interactive", "interactive": {
        "type": "list", "body": {"text": body},
        "action": {"button": boton[:20], "sections": [{"title": "Opciones", "rows": [
            {"id": i, "title": t[:24]} for i, t in filas[:10]]}]}}})


async def enviar_pdf(to, ruta: Path, nombre_doc, caption):
    async with httpx.AsyncClient(timeout=60) as cli:
        with open(ruta, "rb") as f:
            up = await cli.post(f"{API}/media", headers=HEADERS,
                                data={"messaging_product": "whatsapp", "type": "application/pdf"},
                                files={"file": (nombre_doc, f, "application/pdf")})
        up.raise_for_status()
    await _post({"to": to, "type": "document", "document": {
        "id": up.json()["id"], "filename": nombre_doc, "caption": caption}})


# ============================ Pasos del flujo ============================
CAMPOS = [  # (paso, campo, pregunta)
    ("nombre", "nombre", "Escríbeme tu *nombre completo* tal como quieres que aparezca en el diploma."),
    ("profesion", "profesion", "¿Cuál es tu *profesión*? (por ejemplo: Fonoaudióloga, Audiólogo, Otorrino)"),
    ("telefono", "telefono", None),
    ("direccion", "direccion", "¿Cuál es tu *dirección*?"),
    ("ciudad", "ciudad", "¿En qué *ciudad* vives?"),
]
SIGUIENTE = {CAMPOS[i][0]: CAMPOS[i + 1][0] for i in range(len(CAMPOS) - 1)}


def valido(campo, v):
    if campo == "nombre":
        partes = v.split()
        return 2 <= len(partes) <= 8 and len(v) <= 70 and all(
            p.replace("-", "").replace("'", "").isalpha() for p in partes)
    if campo == "telefono":
        return 7 <= len(re.sub(r"\D", "", v)) <= 13
    if campo in ("profesion", "ciudad"):
        return 3 <= len(v) <= 80
    if campo == "direccion":
        return 5 <= len(v) <= 200
    return bool(v)


ERRORES = {
    "nombre": "Escríbeme tu *nombre y apellido* (solo letras), por ejemplo: _María Fernanda Gómez_.",
    "telefono": "Escríbeme un número de teléfono válido (solo números).",
    "profesion": "Escríbeme tu profesión, por favor.",
    "direccion": "Escríbeme tu dirección completa, por favor.",
    "ciudad": "Escríbeme el nombre de tu ciudad, por favor.",
}


async def preguntar_campo(tel, paso):
    if paso == "telefono":
        await botones(tel, f"¿Cuál es tu *teléfono* de contacto?\n\nPuedes usar este mismo número "
                           f"(+{tel}) o escribir otro.", [("tel_wa", "Usar este número")])
        return
    pregunta = next(q for p, _, q in CAMPOS if p == paso)
    await texto(tel, pregunta)


def norm(v):
    v = " ".join(v.split())
    return v[:1].upper() + v[1:]


async def confirmar_datos(tel, p):
    resumen = (f"Confirma tus datos:\n\n👤 *{p['nombre']}*\n💼 {p['profesion']}\n📞 {p['telefono']}\n"
               f"🏠 {p['direccion']}\n📍 {p['ciudad']}\n\n¿Están correctos?")
    await botones(tel, resumen, [("datos_ok", "Sí, continuar"), ("datos_corregir", "Corregir")])


async def preguntar_encuesta(tel, idx):
    q = PREGUNTAS[idx]
    encabezado = f"*Pregunta {idx + 1} de {len(PREGUNTAS)}*\n\n{q['texto']}"
    if q["tipo"] == "escala":
        await lista(tel, encabezado, "Calificar",
                    [(str(n), f"{n} - {ETIQUETAS_ESCALA[n]}") for n in range(5, 0, -1)])
    elif q["tipo"] == "nps":
        await lista(tel, encabezado, "Elegir número", [(str(n), str(n)) for n in range(10, 0, -1)])
    elif q["tipo"] == "opciones":
        await botones(tel, encabezado, [(f"op{i}", o) for i, o in enumerate(q["opciones"])])
    elif q["tipo"] == "lista":
        await lista(tel, encabezado, "Elegir", [(f"op{i}", o) for i, o in enumerate(q["opciones"])])
    else:
        await texto(tel, encabezado)


def leer_respuesta(q, txt, rid):
    """Devuelve el valor de la respuesta o None si no es válida."""
    if q["tipo"] in ("escala", "nps"):
        tope = 5 if q["tipo"] == "escala" else 10
        crudo = rid or txt
        if crudo and crudo.strip().isdigit() and 1 <= int(crudo) <= tope:
            return int(crudo)
        return None
    if q["tipo"] in ("opciones", "lista"):
        if rid and rid.startswith("op"):
            return q["opciones"][int(rid[2:])]
        for o in q["opciones"]:
            if txt and txt.strip().lower() == o.lower():
                return o
        return None
    return txt.strip() if txt and len(txt.strip()) >= 3 else None


async def entregar_diploma(tel, p):
    await texto(tel, "¡Gracias por tus respuestas! 🙌 Estoy generando tu certificado... ⏳")
    doc = nombre_archivo(p["nombre"])
    with tempfile.TemporaryDirectory() as tmp:
        ruta = generar_diploma(p["nombre"], Path(tmp) / doc)
        await enviar_pdf(tel, ruta, doc, f"🎓 ¡Felicitaciones, {p['nombre'].split()[0]}!")


async def evaluar_en_segundo_plano(wa_id):
    if not os.getenv("ANTHROPIC_API_KEY"):
        return
    from evaluar import evaluar_participante
    try:
        p = db.obtener(wa_id)
        db.guardar(wa_id, evaluacion=await evaluar_participante(p))
        log.info("Evaluación de Claude guardada para %s", wa_id)
    except Exception:
        log.exception("No se pudo evaluar a %s", wa_id)


def lanzar(coro):
    t = asyncio.create_task(coro)
    tareas.add(t)
    t.add_done_callback(tareas.discard)


async def manejar(tel: str, txt: str | None, rid: str | None):
    p = db.obtener(tel)
    t = (txt or "").strip()

    if p is None:
        db.crear(tel, "consentimiento")
        politica = f"\n\nPolítica de tratamiento de datos: {POLITICA_URL}" if POLITICA_URL else ""
        await botones(
            tel,
            "¡Hola! 👋 Soy el asistente de *Aural Centros Auditivos*.\n\n"
            "Para entregarte tu diploma del *Diplomado Audiología Estratégica* te pediré algunos datos "
            "y tu opinión sobre el diplomado (toma unos 2 minutos).\n\n"
            "Conforme a la Ley 1581 de 2012, ¿autorizas a Aural a tratar tus datos personales para "
            f"emitir tu certificado y enviarte información académica?{politica}",
            [("acepto", "Sí, autorizo"), ("no_acepto", "No autorizo")])
        return

    paso = p["paso"]

    if paso == "consentimiento":
        if rid == "acepto" or t.lower() in {"si", "sí", "acepto", "autorizo"}:
            db.guardar(tel, paso="nombre")
            await preguntar_campo(tel, "nombre")
        elif rid == "no_acepto" or t.lower() in {"no", "no autorizo"}:
            db.borrar(tel)
            await texto(tel, "Entendido. Sin tu autorización no podemos emitir el diploma. "
                             "Si cambias de opinión, escríbenos de nuevo. 🙏")
        else:
            await botones(tel, "Por favor elige una opción:",
                          [("acepto", "Sí, autorizo"), ("no_acepto", "No autorizo")])
        return

    if paso in SIGUIENTE or paso == "ciudad":
        campo = paso
        valor = f"+{tel}" if (campo == "telefono" and rid == "tel_wa") else t
        if not valido(campo, valor):
            await texto(tel, ERRORES[campo])
            return
        valor = limpiar_nombre(valor) if campo == "nombre" else norm(valor)
        if paso == "ciudad":
            db.guardar(tel, ciudad=valor, paso="confirmar_datos")
            await confirmar_datos(tel, db.obtener(tel))
        else:
            db.guardar(tel, **{campo: valor, "paso": SIGUIENTE[paso]})
            await preguntar_campo(tel, SIGUIENTE[paso])
        return

    if paso == "confirmar_datos":
        if rid == "datos_ok" or t.lower() in {"si", "sí"}:
            db.guardar(tel, paso="encuesta:0")
            await texto(tel, "¡Perfecto! ✅ Ahora cuéntanos cómo te pareció el diplomado. "
                             "Tus respuestas nos ayudan a mejorar.")
            await preguntar_encuesta(tel, 0)
        elif rid == "datos_corregir" or t.lower() in {"no", "corregir"}:
            db.guardar(tel, paso="nombre")
            await texto(tel, "Sin problema ✍️ Vamos de nuevo.")
            await preguntar_campo(tel, "nombre")
        else:
            await confirmar_datos(tel, p)
        return

    if paso.startswith("encuesta:"):
        idx = int(paso.split(":")[1])
        q = PREGUNTAS[idx]
        valor = leer_respuesta(q, t, rid)
        if valor is None:
            await texto(tel, "Por favor responde usando las opciones 👇" if q["tipo"] != "abierta"
                        else "Cuéntame un poco más, por favor 🙏")
            await preguntar_encuesta(tel, idx)
            return
        resp = p["respuestas"]
        resp[q["id"]] = valor
        if idx + 1 < len(PREGUNTAS):
            db.guardar(tel, respuestas=resp, paso=f"encuesta:{idx + 1}")
            await preguntar_encuesta(tel, idx + 1)
        else:
            db.guardar(tel, respuestas=resp, paso="terminado", completado=db.ahora())
            await entregar_diploma(tel, p)
            await texto(tel, "¡Listo! 🎉 Si necesitas que te lo enviemos de nuevo, escribe *diploma*.")
            lanzar(evaluar_en_segundo_plano(tel))
        return

    # terminado
    if t.lower() == "diploma":
        await entregar_diploma(tel, p)
    else:
        await texto(tel, "Ya completaste el proceso ✅ Escribe *diploma* si quieres que te lo enviemos de nuevo.")


# ============================ Webhook ============================
@app.get("/webhook")
async def verificar(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(q.get("hub.challenge"), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def recibir(request: Request):
    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                if msg["id"] in procesados:
                    continue
                procesados.add(msg["id"])
                txt = msg.get("text", {}).get("body") if msg["type"] == "text" else None
                rid = None
                if msg["type"] == "interactive":
                    i = msg["interactive"]
                    rid = (i.get("button_reply") or i.get("list_reply") or {}).get("id")
                elif msg["type"] == "button":
                    txt = msg.get("button", {}).get("text")
                try:
                    await manejar(msg["from"], txt, rid)
                except Exception:
                    log.exception("Error manejando mensaje de %s", msg["from"])
    return {"status": "ok"}


@app.get("/")
def salud():
    return {"ok": True}


# ============================ Panel ============================
seguridad = HTTPBasic()


def autorizado(cred: HTTPBasicCredentials = Depends(seguridad)):
    ok = PANEL_PASSWORD and secrets.compare_digest(cred.username, PANEL_USER) and \
        secrets.compare_digest(cred.password, PANEL_PASSWORD)
    if not ok:
        raise HTTPException(401, "No autorizado", headers={"WWW-Authenticate": "Basic"})


@app.get("/panel", dependencies=[Depends(autorizado)])
def panel():
    return FileResponse(BASE / "panel.html")


@app.get("/api/datos", dependencies=[Depends(autorizado)])
def api_datos():
    return {"preguntas": PREGUNTAS, "participantes": db.todos(), "analisis": db.ultimo_analisis(),
            "claude": bool(os.getenv("ANTHROPIC_API_KEY"))}


@app.post("/api/evaluar/{wa_id}", dependencies=[Depends(autorizado)])
async def api_evaluar(wa_id: str):
    from evaluar import evaluar_participante
    p = db.obtener(wa_id)
    if not p:
        raise HTTPException(404)
    ev = await evaluar_participante(p)
    db.guardar(wa_id, evaluacion=ev)
    return ev


@app.post("/api/evaluar-pendientes", dependencies=[Depends(autorizado)])
async def api_evaluar_pendientes():
    from evaluar import evaluar_participante
    n = 0
    for p in db.todos():
        if p["paso"] == "terminado" and not p["evaluacion"]:
            db.guardar(p["wa_id"], evaluacion=await evaluar_participante(p))
            n += 1
    return {"evaluados": n}


@app.post("/api/analisis-general", dependencies=[Depends(autorizado)])
async def api_analisis():
    from evaluar import analisis_general
    completos = [p for p in db.todos() if p["paso"] == "terminado"]
    if not completos:
        raise HTTPException(400, "Todavía no hay encuestas completas")
    res = await analisis_general(completos)
    db.guardar_analisis(res)
    return db.ultimo_analisis()


@app.get("/api/exportar.csv", dependencies=[Depends(autorizado)])
def exportar():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["whatsapp", "estado", "nombre", "profesion", "telefono", "direccion", "ciudad",
                *[q["id"] for q in PREGUNTAS], "sentimiento", "satisfaccion_claude", "temas",
                "alerta", "resumen_claude", "creado", "completado"])
    for p in db.todos():
        ev = p["evaluacion"] or {}
        w.writerow([p["wa_id"], p["paso"], p["nombre"], p["profesion"], p["telefono"], p["direccion"],
                    p["ciudad"], *[p["respuestas"].get(q["id"], "") for q in PREGUNTAS],
                    ev.get("sentimiento", ""), ev.get("satisfaccion", ""), ", ".join(ev.get("temas", [])),
                    ev.get("alerta", ""), ev.get("resumen", ""), p["creado"], p["completado"]])
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=diplomado.csv"})
