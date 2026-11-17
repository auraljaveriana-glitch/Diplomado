"""Preguntas de la encuesta. Edita esta lista para cambiar la encuesta.

Tipos:
  escala   -> lista desplegable 1 a 5
  nps      -> lista desplegable 1 a 10
  opciones -> hasta 3 botones (WhatsApp no permite más de 3)
  lista    -> lista desplegable de hasta 10 opciones (cada opción máx. 24 caracteres)
  abierta  -> respuesta escrita
"""

PREGUNTAS = [
    {"id": "general", "tipo": "escala", "texto": "¿Cómo calificas el diplomado en general?"},
    {"id": "aplicara", "tipo": "opciones", "texto": "¿Qué tanto vas a aplicar lo aprendido en tu consulta?",
     "opciones": ["Mucho", "Algo", "Poco"]},
    {"id": "experiencia", "tipo": "abierta",
     "texto": "✍️ Cuéntanos con tus palabras *cómo te fue en el diplomado*: qué te llevas, "
              "qué te sorprendió y qué cambiarías."},
    {"id": "aporte", "tipo": "lista", "texto": "¿Qué parte te aportó más?",
     "opciones": ["Casos clínicos", "Tecnología en audífonos", "Estrategia y gestión",
                  "Experiencia del paciente", "Networking"]},
    {"id": "formato", "tipo": "opciones", "texto": "¿Qué formato prefieres para el próximo diplomado?",
     "opciones": ["Presencial", "Virtual", "Mixto"]},
    {"id": "volveria", "tipo": "opciones", "texto": "¿Te gustaría participar en otro diplomado de Aural?",
     "opciones": ["Sí", "Tal vez", "No"]},
    {"id": "gusto", "tipo": "abierta", "texto": "¿Qué fue lo que *más te gustó* del diplomado?"},
    {"id": "mejorar", "tipo": "abierta",
     "texto": "¿Qué *mejorarías* o qué tema te gustaría ver en el próximo?"},
]

ETIQUETAS_ESCALA = {
    5: "Excelente", 4: "Bueno", 3: "Regular", 2: "Malo", 1: "Muy malo",
}

POR_ID = {p["id"]: p for p in PREGUNTAS}
