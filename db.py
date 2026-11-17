"""Base de datos: SQLite en local, Postgres en Railway (variable DATABASE_URL)."""
import json
import os
from datetime import datetime, timezone

from sqlalchemy import (Column, DateTime, MetaData, String, Table, Text, create_engine,
                        insert, select, update, delete)

url = os.getenv("DATABASE_URL", "sqlite:///datos.db")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(url, pool_pre_ping=True)
meta = MetaData()

participantes = Table(
    "participantes", meta,
    Column("wa_id", String(32), primary_key=True),   # número de WhatsApp
    Column("paso", String(40), nullable=False),
    Column("nombre", String(120)),
    Column("profesion", String(120)),
    Column("telefono", String(30)),
    Column("direccion", String(200)),
    Column("ciudad", String(80)),
    Column("respuestas", Text, default="{}"),          # JSON {id_pregunta: valor}
    Column("evaluacion", Text),                        # JSON con la evaluación de Claude
    Column("creado", DateTime(timezone=True)),
    Column("completado", DateTime(timezone=True)),
)

analisis = Table(
    "analisis_general", meta,
    Column("id", String(40), primary_key=True),
    Column("creado", DateTime(timezone=True)),
    Column("contenido", Text),
)

meta.create_all(engine)


def ahora():
    return datetime.now(timezone.utc)


def _fila(r):
    if r is None:
        return None
    d = dict(r._mapping)
    d["respuestas"] = json.loads(d.get("respuestas") or "{}")
    d["evaluacion"] = json.loads(d["evaluacion"]) if d.get("evaluacion") else None
    for k in ("creado", "completado"):
        if d.get(k):
            d[k] = d[k].isoformat()
    return d


def obtener(wa_id):
    with engine.begin() as c:
        return _fila(c.execute(select(participantes).where(participantes.c.wa_id == wa_id)).first())


def crear(wa_id, paso):
    with engine.begin() as c:
        c.execute(insert(participantes).values(wa_id=wa_id, paso=paso, respuestas="{}", creado=ahora()))
    return obtener(wa_id)


def guardar(wa_id, **campos):
    if "respuestas" in campos:
        campos["respuestas"] = json.dumps(campos["respuestas"], ensure_ascii=False)
    if "evaluacion" in campos and campos["evaluacion"] is not None:
        campos["evaluacion"] = json.dumps(campos["evaluacion"], ensure_ascii=False)
    with engine.begin() as c:
        c.execute(update(participantes).where(participantes.c.wa_id == wa_id).values(**campos))


def borrar(wa_id):
    with engine.begin() as c:
        c.execute(delete(participantes).where(participantes.c.wa_id == wa_id))


def todos():
    with engine.begin() as c:
        filas = c.execute(select(participantes).order_by(participantes.c.creado.desc())).all()
    return [_fila(f) for f in filas]


def guardar_analisis(contenido: dict):
    with engine.begin() as c:
        c.execute(insert(analisis).values(id=ahora().strftime("%Y%m%d%H%M%S%f"), creado=ahora(),
                                          contenido=json.dumps(contenido, ensure_ascii=False)))


def ultimo_analisis():
    with engine.begin() as c:
        r = c.execute(select(analisis).order_by(analisis.c.creado.desc()).limit(1)).first()
    if not r:
        return None
    return {"creado": r.creado.isoformat(), **json.loads(r.contenido)}
