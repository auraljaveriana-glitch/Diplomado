"""Evaluación de respuestas con Claude (API de Anthropic)."""
import json
import os
import re

from anthropic import AsyncAnthropic

from encuesta import PREGUNTAS

MODELO = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
_cliente = None


def cliente():
    global _cliente
    if _cliente is None:
        _cliente = AsyncAnthropic()  # usa ANTHROPIC_API_KEY
    return _cliente


def _json(texto: str) -> dict:
    m = re.search(r"\{.*\}", texto, re.S)
    return json.loads(m.group(0) if m else texto)


def _respuestas_legibles(p: dict) -> str:
    lineas = []
    for q in PREGUNTAS:
        v = p["respuestas"].get(q["id"], "—")
        escala = {"escala": " (de 1 a 5)", "nps": " (de 1 a 10)"}.get(q["tipo"], "")
        lineas.append(f"- {q['texto'].replace('*', '')}{escala}: {v}")
    return "\n".join(lineas)


SISTEMA_INDIVIDUAL = """Eres analista de calidad educativa de Aural Centros Auditivos (Colombia).
Evalúas la encuesta de satisfacción de un participante del Diplomado Audiología Estratégica.
Responde SOLO con un objeto JSON válido, sin texto adicional, con estas claves:
{
  "sentimiento": "positivo" | "neutral" | "negativo",
  "satisfaccion": número entero de 1 a 10 (tu lectura global, combinando notas y comentarios),
  "temas": lista de 1 a 4 temas cortos (2-3 palabras, minúscula, en español, reutilizables entre participantes, p. ej. "docentes", "casos clínicos", "logística", "duración", "material de apoyo", "networking"),
  "fortalezas": lista corta de lo que valoró,
  "mejoras": lista corta de lo que pide mejorar,
  "alerta": true si hay una queja seria o algo que requiera contactar a la persona,
  "motivo_alerta": texto corto o "",
  "calidad_respuesta": "alta" | "media" | "baja" (qué tan útil y detallada es la retroalimentación),
  "resumen": una frase de máximo 25 palabras
}"""


async def evaluar_participante(p: dict) -> dict:
    perfil = f"Profesión: {p.get('profesion')}\nCiudad: {p.get('ciudad')}"
    msg = await cliente().messages.create(
        model=MODELO, max_tokens=800, system=SISTEMA_INDIVIDUAL,
        messages=[{"role": "user", "content": f"{perfil}\n\nRespuestas:\n{_respuestas_legibles(p)}"}],
    )
    datos = _json(msg.content[0].text)
    datos["modelo"] = MODELO
    return datos


SISTEMA_GENERAL = """Eres analista de calidad educativa de Aural Centros Auditivos (Colombia).
Recibes todas las encuestas del Diplomado Audiología Estratégica (con la evaluación previa de cada una).
Responde SOLO con JSON válido:
{
  "titular": una frase que resuma cómo les fue,
  "hallazgos": lista de 3 a 6 hallazgos concretos, cada uno con datos (conteos, promedios),
  "temas_recurrentes": lista de objetos {"tema": str, "menciones": int, "tono": "positivo"|"neutral"|"negativo"},
  "riesgos": lista de puntos críticos o personas a contactar (usa el nombre),
  "recomendaciones": lista de 3 a 5 acciones concretas para la próxima edición,
  "por_segmento": texto corto con diferencias por profesión o ciudad si las hay
}"""


async def analisis_general(lista: list[dict]) -> dict:
    compacto = []
    for p in lista:
        compacto.append({
            "nombre": p.get("nombre"), "profesion": p.get("profesion"), "ciudad": p.get("ciudad"),
            "respuestas": p.get("respuestas"),
            "evaluacion": {k: (p.get("evaluacion") or {}).get(k)
                           for k in ("sentimiento", "satisfaccion", "temas", "alerta", "resumen")},
        })
    claves = "\n".join(f"- {q['id']}: {q['texto'].replace('*', '')}" for q in PREGUNTAS)
    msg = await cliente().messages.create(
        model=MODELO, max_tokens=2500, system=SISTEMA_GENERAL,
        messages=[{"role": "user", "content":
                   f"Preguntas:\n{claves}\n\n{len(compacto)} encuestas:\n"
                   + json.dumps(compacto, ensure_ascii=False)}],
    )
    datos = _json(msg.content[0].text)
    datos["total"] = len(compacto)
    datos["modelo"] = MODELO
    return datos
