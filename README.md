# Bot de diplomas por WhatsApp — Aural

Cuando alguien escribe al número, el bot pide su nombre completo, se lo confirma con botones (**Sí, generar** / **Corregir**) y le envía el diploma en PDF.

## Archivos
- `app.py` — webhook de WhatsApp Cloud API (FastAPI) y flujo de conversación.
- `diploma.py` — genera el PDF. Se prueba solo con: `python diploma.py "Nombre Apellido"`.
- `assets/` (opcional):
  - `plantilla.png` — si pones aquí el diseño del diploma (horizontal, tamaño carta), el bot solo escribe el nombre encima. Ajusta la altura con `DIPLOMA_NOMBRE_Y` (0.50 = mitad de la hoja).
  - `logo.png` — logo de Aural para el diseño por defecto.
  - `fonts/Gotham-Bold.otf`, `Gotham-Book.otf`, `Gotham-Light.otf` — si están, se usan en vez de la fuente de respaldo.

## Configuración (.env)
```
WHATSAPP_TOKEN=token_permanente_del_usuario_del_sistema
WHATSAPP_PHONE_NUMBER_ID=id_del_numero
WEBHOOK_VERIFY_TOKEN=aural-diplomas

# Textos del diploma (opcionales)
DIPLOMA_TITULO=DIPLOMA
DIPLOMA_SUBTITULO=Aural Centros Auditivos otorga el presente reconocimiento a
DIPLOMA_MOTIVO=Por su participación en el Diplomado Audiología Estratégica
DIPLOMA_CIUDAD=Colombia
DIPLOMA_FIRMA_NOMBRE=Juan Pablo Peláez
DIPLOMA_FIRMA_CARGO=Gerente General
```

## Ejecutar
```
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```
Para probar en local, exponlo con `ngrok http 8000`.

## Conectar en Meta
1. developers.facebook.com → tu app → WhatsApp → Configuración.
2. Webhook: URL `https://TU-DOMINIO/webhook`, token de verificación igual a `WEBHOOK_VERIFY_TOKEN`.
3. Suscríbete al campo **messages**.

⚠️ Un número solo puede tener un webhook. Si usas el mismo número de Amanda, este bot reemplaza a Amanda. Para el diplomado, lo ideal es un número aparte (se agrega en la misma WABA) o meter este flujo dentro de Amanda cuando el mensaje diga "diploma".

## Notas
- El estado de cada conversación se guarda en memoria: si el servidor se reinicia, la persona solo tiene que volver a escribir. Para varios workers, pásalo a Redis o Supabase.
- Para que el bot inicie la conversación (por ejemplo, avisar a todos los del diplomado), Meta exige una plantilla aprobada. Si la persona escribe primero, no hace falta.
