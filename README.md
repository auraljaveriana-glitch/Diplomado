# Bot del diplomado — Aural

El bot de WhatsApp pide autorización de datos, nombre, profesión, teléfono, dirección y ciudad. Después hace la encuesta de satisfacción y envía el diploma en PDF. Claude evalúa cada encuesta y todo se ve en el panel `/panel`.

## Archivos
| Archivo | Qué hace |
|---|---|
| `app.py` | Webhook de WhatsApp, flujo de conversación y API del panel |
| `encuesta.py` | **Preguntas de la encuesta** (edítalas aquí) |
| `evaluar.py` | Instrucciones y llamadas a Claude (evaluación individual y análisis general) |
| `db.py` | Base de datos (Postgres en Railway, SQLite en local) |
| `diploma.py` | Genera el PDF |
| `panel.html` | Panel con la red neuronal |
| `assets/` | Fuentes; opcional `plantilla.png` y `logo.png` |

## Variables en Railway
```
WHATSAPP_TOKEN=token permanente
WHATSAPP_PHONE_NUMBER_ID=1409542185583550
WEBHOOK_VERIFY_TOKEN=aural-diplomas
ANTHROPIC_API_KEY=clave de Claude (puede ser la misma de Amanda)
PANEL_USER=aural
PANEL_PASSWORD=una contraseña fuerte
POLITICA_URL=https://... (política de tratamiento de datos de Aural, opcional)
DATABASE_URL=la agrega Railway automáticamente al crear Postgres
CLAUDE_MODEL=claude-sonnet-5-5 (opcional)
```

## Base de datos (obligatorio en Railway)
En el proyecto de Railway: **+ New → Database → PostgreSQL**. Luego, en el servicio del bot → Variables → **Add reference** → `DATABASE_URL` de Postgres.
Sin esto los datos se guardan en un archivo que se borra en cada despliegue.

## Panel
- Entrada: `https://TU-URL/login` (o `/panel`, que te lleva al login). Usuario y contraseña = `PANEL_USER` / `PANEL_PASSWORD`. La sesión dura 12 horas; "Salir" la cierra.
- `https://TU-URL/panel?demo` (después de ingresar) muestra datos de ejemplo.
- Red: participante → profesión → temas que detecta Claude → sentimiento. Pasa el mouse para ver la ruta y haz clic para ver el detalle.
- **Evaluar pendientes**: evalúa con Claude las encuestas que todavía no tienen evaluación.
- **Análisis general con Claude**: hallazgos, temas recurrentes, riesgos y recomendaciones.
- **Exportar CSV**: todos los datos, con las columnas de Claude, para abrir en Excel.
- Logos en `web/` (sacados del certificado oficial).

## Flujo del bot
1. Autorización Ley 1581 → 2. Datos → confirmación → 3. Encuesta (8 preguntas, ver encuesta.py) → 4. Diploma → 5. Claude evalúa en segundo plano.
Si alguien ya terminó y escribe *diploma*, se le reenvía el PDF.
