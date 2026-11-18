"""Preguntas de la encuesta. Edita esta lista para cambiar la encuesta.

Tipos:
  escala   -> lista desplegable 1 a 5
  nps      -> lista desplegable 1 a 10
  opciones -> hasta 3 botones (WhatsApp no permite más de 3)
  lista    -> lista desplegable de hasta 10 opciones (cada opción máx. 24 caracteres)
  abierta  -> respuesta escrita
"""

# Módulos del diplomado (cronograma oficial). "corto" se muestra en WhatsApp (máx. 24 caracteres).
MODULOS = [
    {"corto": "M1 Visión de mercado", "fecha": "16 de junio",
     "titulo": "La audiología como mercado: visión estratégica y evolución a 10 años"},
    {"corto": "M2 Marketing", "fecha": "1 de julio",
     "titulo": "Marketing en audiología: competir en un mercado en integración"},
    {"corto": "M3 Finanzas", "fecha": "15 de julio",
     "titulo": "Finanzas de la adaptación auditiva: indicadores, rentabilidad y gestión comercial"},
    {"corto": "M4 Proveedores", "fecha": "29 de julio",
     "titulo": "Proveedor como cadena de valor: decisiones que impactan el negocio"},
    {"corto": "M5 Oferta y negociación", "fecha": "12 de agosto",
     "titulo": "Diseño de oferta y negociación: cómo construir valor en audiología"},
    {"corto": "M6 Neurociencia decisión", "fecha": "26 de agosto",
     "titulo": "Neurociencia de la decisión: cómo funciona el cerebro del paciente en consulta"},
    {"corto": "M7 Círculo Dorado", "fecha": "8 de septiembre",
     "titulo": "El Círculo Dorado en audiología: estructurar conversaciones que generan decisiones"},
    {"corto": "M8 Método REEC", "fecha": "22 de septiembre",
     "titulo": "Método REEC: gestión estructurada de objeciones en consulta"},
    {"corto": "M9 Consultorio rentable", "fecha": "6 de octubre",
     "titulo": "De consulta a negocio: cómo estructurar un consultorio rentable y sostenible"},
    {"corto": "M10 Escalar tu práctica", "fecha": "20 de octubre",
     "titulo": "Dirección estratégica: cómo escalar tu práctica profesional en audiología"},
]

PREGUNTAS = [
    {"id": "general", "tipo": "escala", "texto": "¿Cómo calificas el diplomado en general?"},
    {"id": "aplicara", "tipo": "opciones", "texto": "¿Qué tanto vas a aplicar lo aprendido en tu consulta?",
     "opciones": ["Mucho", "Algo", "Poco"]},
    {"id": "experiencia", "tipo": "abierta",
     "texto": "✍️ Cuéntanos con tus palabras *cómo te fue en el diplomado*: qué te llevas, "
              "qué te sorprendió y qué cambiarías."},
    {"id": "aporte", "tipo": "lista", "texto": "¿Qué *módulo* te aportó más?",
     "opciones": [m["corto"] for m in MODULOS],
     "descripciones": [m["titulo"] for m in MODULOS]},
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
