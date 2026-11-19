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
import base64
import hashlib
import hmac
import time

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

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
app.mount("/static", StaticFiles(directory=BASE / "web", check_dir=False), name="static")
if not (BASE / "web").exists():
    logging.getLogger("bot-diplomas").warning("Falta la carpeta web/ (logos): sube web/logo-blanco.png y web/logo-color.png")
procesados: set[str] = set()
tareas: set[asyncio.Task] = set()
enviados: dict[str, dict] = {}       # id de mensaje enviado -> {to, alterno}
reintentados: set[str] = set()
fallos: list[dict] = []              # fallas de entrega reportadas por Meta
candados: dict[str, asyncio.Lock] = {}


# ============================ Envío de mensajes ============================
async def _post(payload: dict, alterno: str | None = None):
    """Envía un mensaje. `alterno` es la versión en texto que se reenvía si Meta no logra entregarlo."""
    ultimo = None
    for intento in range(3):
        try:
            async with httpx.AsyncClient(timeout=30) as cli:
                r = await cli.post(f"{API}/messages", headers=HEADERS,
                                   json={"messaging_product": "whatsapp", **payload})
            if r.status_code < 400:
                try:
                    mid = r.json()["messages"][0]["id"]
                    enviados[mid] = {"to": payload.get("to"), "alterno": alterno}
                    if len(enviados) > 5000:
                        for k in list(enviados)[:1000]:
                            enviados.pop(k, None)
                except Exception:
                    pass
                return
            log.error("Error WhatsApp %s para %s: %s", r.status_code, payload.get("to"), r.text)
            ultimo = r
            if r.status_code < 500 and r.status_code != 429:
                break  # error del mensaje: reintentar no sirve
        except httpx.HTTPError as e:
            log.warning("Fallo de red enviando a %s (intento %s): %s", payload.get("to"), intento + 1, e)
        await asyncio.sleep(1.5 * (intento + 1))
    if alterno and payload.get("type") == "interactive":
        # si el mensaje con botones no se pudo enviar, se manda como texto
        await _post({"to": payload["to"], "type": "text", "text": {"body": alterno}})
        return
    if ultimo is not None:
        ultimo.raise_for_status()


def _alterno(body, opciones, nota="Responde con el número de tu opción"):
    lineas = "\n".join(f"*{n}.* {t}" for n, t in enumerate(opciones, 1))
    return f"{body}\n\n{lineas}\n\n_{nota}_"


async def texto(to, body):
    await _post({"to": to, "type": "text", "text": {"body": body}})


async def botones(to, body, opciones: list[tuple[str, str]]):
    await _post({"to": to, "type": "interactive", "interactive": {
        "type": "button", "body": {"text": body},
        "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t[:20]}}
                               for i, t in opciones[:3]]}}},
        alterno=_alterno(body, [t for _, t in opciones[:3]]))


async def lista(to, body, boton, filas: list[tuple[str, str]], descripciones: list[str] | None = None,
                alterno: str | None = None):
    filas_api = []
    for n, (i, t) in enumerate(filas[:10]):
        fila = {"id": i, "title": t[:24]}
        if descripciones and n < len(descripciones):
            d = descripciones[n]
            fila["description"] = d if len(d) <= 72 else d[:71] + "…"
        filas_api.append(fila)
    await _post({"to": to, "type": "interactive", "interactive": {
        "type": "list", "body": {"text": body},
        "action": {"button": boton[:20], "sections": [{"title": "Opciones", "rows": filas_api}]}}},
        alterno=alterno or _alterno(body, [t for _, t in filas[:10]]))


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
        # en la versión de texto, responder "1" usa el mismo número
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
                    [(str(n), f"{n} - {ETIQUETAS_ESCALA[n]}") for n in range(5, 0, -1)],
                    alterno=f"{encabezado}\n\nResponde con un número del *1 al 5*:\n"
                            "5 = Excelente · 4 = Bueno · 3 = Regular · 2 = Malo · 1 = Muy malo")
    elif q["tipo"] == "nps":
        await lista(tel, encabezado, "Elegir número", [(str(n), str(n)) for n in range(10, 0, -1)],
                    alterno=f"{encabezado}\n\nResponde con un número del *1 al 10*.")
    elif q["tipo"] == "opciones":
        await botones(tel, encabezado, [(f"op{i}", o) for i, o in enumerate(q["opciones"])])
    elif q["tipo"] == "lista":
        await lista(tel, encabezado, "Ver módulos" if q["id"] == "aporte" else "Elegir",
                    [(f"op{i}", o) for i, o in enumerate(q["opciones"])], q.get("descripciones"))
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
        t = (txt or "").strip().rstrip(".").lower()
        if t.isdigit() and 1 <= int(t) <= len(q["opciones"]):
            return q["opciones"][int(t) - 1]
        for o in q["opciones"]:
            if t == o.lower() or (len(t) >= 4 and t in o.lower()):
                return o
        return None
    return txt.strip() if txt and len(txt.strip()) >= 3 else None


async def entregar_diploma(tel, p):
    await texto(tel, "¡Gracias por tus respuestas! 🙌 Estoy generando tu certificado... ⏳")
    doc = nombre_archivo(p["nombre"])
    with tempfile.TemporaryDirectory() as tmp:
        ruta = await asyncio.to_thread(generar_diploma, p["nombre"], Path(tmp) / doc)
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

    if t in {"1", "2"} and not rid:
        mapa = {"consentimiento": ["acepto", "no_acepto"], "confirmar_datos": ["datos_ok", "datos_corregir"],
                "telefono": ["tel_wa"]}
        ids = mapa.get(paso, [])
        if int(t) <= len(ids):
            rid = ids[int(t) - 1]

    if paso == "consentimiento":
        if rid == "acepto" or t.lower() in {"si", "sí", "acepto", "autorizo", "sí, autorizo", "si autorizo"}:
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


async def procesar(tel, txt, rid):
    candado = candados.setdefault(tel, asyncio.Lock())
    async with candado:  # los mensajes de una misma persona se atienden en orden
        try:
            await manejar(tel, txt, rid)
        except Exception:
            log.exception("Error manejando mensaje de %s", tel)


async def estado_fallido(st: dict):
    err = (st.get("errors") or [{}])[0]
    info = {"wa_id": st.get("recipient_id"), "codigo": err.get("code"),
            "detalle": err.get("title") or err.get("message") or "",
            "hora": db.ahora().isoformat(), "reenviado": False}
    log.error("Meta NO entregó un mensaje a %s: código %s · %s", info["wa_id"], info["codigo"], info["detalle"])
    env = enviados.get(st.get("id"))
    if env and env.get("alterno") and st.get("id") not in reintentados:
        reintentados.add(st["id"])
        try:
            await _post({"to": env["to"], "type": "text", "text": {"body": env["alterno"]}})
            info["reenviado"] = True
            log.info("Reenviado como texto a %s", env["to"])
        except Exception:
            log.exception("Tampoco se pudo reenviar como texto a %s", env["to"])
    fallos.append(info)
    del fallos[:-200]


@app.post("/webhook")
async def recibir(request: Request):
    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            valor = change.get("value", {})
            for st in valor.get("statuses", []):
                if st.get("status") == "failed":
                    lanzar(estado_fallido(st))
            for msg in valor.get("messages", []):
                if msg["id"] in procesados:
                    continue
                procesados.add(msg["id"])
                log.info("Mensaje de %s (%s)", msg["from"], msg["type"])
                txt = msg.get("text", {}).get("body") if msg["type"] == "text" else None
                rid = None
                if msg["type"] == "interactive":
                    i = msg["interactive"]
                    rid = (i.get("button_reply") or i.get("list_reply") or {}).get("id")
                elif msg["type"] == "button":
                    txt = msg.get("button", {}).get("text")
                lanzar(procesar(msg["from"], txt, rid))  # responde a Meta de inmediato
    return {"status": "ok"}


@app.get("/")
def salud():
    return {"ok": True}


# ============================ Panel ============================
SECRETO = (os.getenv("SESSION_SECRET") or hashlib.sha256(f"aural:{PANEL_PASSWORD}".encode()).hexdigest()).encode()
COOKIE = "aural_panel"
DURACION = 12 * 3600  # la sesión dura 12 horas


def _firmar(usuario: str, vence: int) -> str:
    cuerpo = f"{usuario}|{vence}"
    firma = hmac.new(SECRETO, cuerpo.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{cuerpo}|{firma}".encode()).decode()


def usuario_sesion(request: Request) -> str | None:
    try:
        usuario, vence, firma = base64.urlsafe_b64decode(request.cookies.get(COOKIE, "")).decode().split("|")
        esperado = hmac.new(SECRETO, f"{usuario}|{vence}".encode(), hashlib.sha256).hexdigest()
        if PANEL_PASSWORD and hmac.compare_digest(firma, esperado) and int(vence) > time.time():
            return usuario
    except Exception:
        pass
    return None


def autorizado(request: Request):
    if not usuario_sesion(request):
        raise HTTPException(401, "Sesión vencida")


@app.get("/login")
def login_pagina(request: Request):
    if usuario_sesion(request):
        return RedirectResponse("/panel", 303)
    return FileResponse(BASE / "login.html")


@app.post("/login")
async def login(usuario: str = Form(...), clave: str = Form(...)):
    ok = bool(PANEL_PASSWORD) and secrets.compare_digest(usuario.strip().lower(), PANEL_USER.lower()) \
        and secrets.compare_digest(clave, PANEL_PASSWORD)
    if not ok:
        await asyncio.sleep(1.2)  # frena intentos repetidos
        return RedirectResponse("/login?error=1" if PANEL_PASSWORD else "/login?error=config", 303)
    r = RedirectResponse("/panel", 303)
    r.set_cookie(COOKIE, _firmar(PANEL_USER, int(time.time()) + DURACION), max_age=DURACION,
                 httponly=True, samesite="lax", secure=os.getenv("COOKIE_INSEGURA") != "1")
    return r


@app.get("/logout")
def logout():
    r = RedirectResponse("/login", 303)
    r.delete_cookie(COOKIE)
    return r


@app.get("/panel")
def panel(request: Request):
    if not usuario_sesion(request):
        return RedirectResponse("/login", 303)
    return FileResponse(BASE / "panel.html")


@app.get("/api/datos", dependencies=[Depends(autorizado)])
def api_datos():
    return {"preguntas": PREGUNTAS, "participantes": db.todos(), "analisis": db.ultimo_analisis(),
            "claude": bool(os.getenv("ANTHROPIC_API_KEY")), "fallos": fallos[-50:]}


@app.post("/api/evaluar/{wa_id}", dependencies=[Depends(autorizado)])
async def api_evaluar(wa_id: str):
    from evaluar import evaluar_participante
    p = db.obtener(wa_id)
    if not p:
        raise HTTPException(404)
    ev = await evaluar_participante(p)
    db.guardar(wa_id, evaluacion=ev)
    return ev


@app.delete("/api/participantes/{wa_id}", dependencies=[Depends(autorizado)])
def api_borrar(wa_id: str):
    if not db.obtener(wa_id):
        raise HTTPException(404, "No existe")
    db.borrar(wa_id)
    log.info("Registro eliminado desde el panel: %s", wa_id)
    return {"eliminado": wa_id}


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
