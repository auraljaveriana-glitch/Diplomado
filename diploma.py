"""Generación del diploma en PDF.

Dos modos:
1. Si existe PLANTILLA (imagen PNG/JPG horizontal hecha en Canva/Illustrator),
   se usa como fondo y solo se escribe el nombre encima.
2. Si no hay plantilla, se dibuja un diploma completo con los colores de Aural.
"""
import os
import unicodedata
from datetime import date
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

BASE = Path(__file__).parent

# ---------- Configuración (se puede sobrescribir con variables de entorno) ----------
TITULO = os.getenv("DIPLOMA_TITULO", "DIPLOMA")
SUBTITULO = os.getenv("DIPLOMA_SUBTITULO", "Aural Centros Auditivos otorga el presente reconocimiento a")
MOTIVO = os.getenv(
    "DIPLOMA_MOTIVO",
    "Por su participación en el Diplomado Audiología Estratégica",
)
CIUDAD = os.getenv("DIPLOMA_CIUDAD", "Colombia")
FIRMA_NOMBRE = os.getenv("DIPLOMA_FIRMA_NOMBRE", "Juan Pablo Peláez")
FIRMA_CARGO = os.getenv("DIPLOMA_FIRMA_CARGO", "Gerente General")
PLANTILLA = BASE / os.getenv("DIPLOMA_PLANTILLA", "assets/plantilla.png")
LOGO = BASE / os.getenv("DIPLOMA_LOGO", "assets/logo.png")
# Posición vertical del nombre cuando se usa plantilla (0 = abajo, 1 = arriba)
NOMBRE_Y_REL = float(os.getenv("DIPLOMA_NOMBRE_Y", "0.50"))
NOMBRE_COLOR = os.getenv("DIPLOMA_NOMBRE_COLOR", "#041E42")

NAVY = HexColor("#041E42")
GRIS = HexColor("#706F6F")
TEAL = HexColor("#10616F")
BEIGE = HexColor("#CAC1B0")

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _registrar_fuentes():
    """Usa Gotham si está en assets/fonts; si no, una sans disponible."""
    fuentes = BASE / "assets" / "fonts"
    candidatos = {
        "Titulo": ["Gotham-Bold.ttf", "Gotham-Bold.otf"],
        "Texto": ["Gotham-Book.ttf", "Gotham-Book.otf"],
        "Light": ["Gotham-Light.ttf", "Gotham-Light.otf"],
    }
    respaldo = {
        "Titulo": str(BASE / "assets/fonts" / "DejaVuSans-Bold.ttf"),
        "Texto": str(BASE / "assets/fonts" / "DejaVuSans.ttf"),
        "Light": str(BASE / "assets/fonts" / "DejaVuSans-ExtraLight.ttf"),
    }
    for nombre, archivos in candidatos.items():
        ruta = next((fuentes / a for a in archivos if (fuentes / a).exists()), None)
        if ruta is None and Path(respaldo[nombre]).exists():
            ruta = Path(respaldo[nombre])
        if ruta is not None:
            pdfmetrics.registerFont(TTFont(nombre, str(ruta)))
        else:  # último recurso: fuentes base de PDF
            base = {"Titulo": "Helvetica-Bold", "Texto": "Helvetica", "Light": "Helvetica"}[nombre]
            pdfmetrics.registerFont(pdfmetrics.getFont(base))
            globals()[f"_F_{nombre}"] = base
    return {k: globals().get(f"_F_{k}", k) for k in candidatos}


F = _registrar_fuentes()


def limpiar_nombre(texto: str) -> str:
    """Quita espacios extra y pone mayúscula inicial en cada palabra."""
    partes = texto.strip().split()
    menores = {"de", "del", "la", "las", "los", "y"}
    out = []
    for i, p in enumerate(partes):
        p = p.lower()
        out.append(p if (i > 0 and p in menores) else p.capitalize())
    return " ".join(out)


def nombre_archivo(nombre: str) -> str:
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    plano = "".join(c if c.isalnum() else "_" for c in plano).strip("_")
    return f"Diploma_{plano or 'Aural'}.pdf"


def _ajustar_tamano(c, texto, fuente, maximo, ancho_max):
    tam = maximo
    while tam > 14 and c.stringWidth(texto, fuente, tam) > ancho_max:
        tam -= 1
    return tam


def _fecha_hoy():
    h = date.today()
    return f"{CIUDAD}, {h.day} de {MESES[h.month - 1]} de {h.year}"


def generar_diploma(nombre: str, salida: Path) -> Path:
    nombre = limpiar_nombre(nombre)
    ancho, alto = landscape(letter)
    c = canvas.Canvas(str(salida), pagesize=(ancho, alto))
    c.setTitle(f"Diploma - {nombre}")

    if PLANTILLA.exists():
        c.drawImage(str(PLANTILLA), 0, 0, width=ancho, height=alto)
        tam = _ajustar_tamano(c, nombre, F["Titulo"], 44, ancho * 0.75)
        c.setFillColor(HexColor(NOMBRE_COLOR))
        c.setFont(F["Titulo"], tam)
        c.drawCentredString(ancho / 2, alto * NOMBRE_Y_REL, nombre)
        c.save()
        return salida

    # --- Diseño propio con la marca Aural ---
    m = 28
    c.setStrokeColor(NAVY)
    c.setLineWidth(2.5)
    c.rect(m, m, ancho - 2 * m, alto - 2 * m)
    c.setStrokeColor(BEIGE)
    c.setLineWidth(0.8)
    c.rect(m + 8, m + 8, ancho - 2 * (m + 8), alto - 2 * (m + 8))

    # Ondas de puntos decorativas en esquinas (motivo de la marca)
    import math
    c.setFillColor(BEIGE)
    for (cx, cy, inicio) in [(m + 8, alto - m - 8, 270), (ancho - m - 8, m + 8, 90)]:
        for r in range(30, 160, 18):
            for k in range(0, 91, 6):
                ang = math.radians(inicio + k)
                x = cx + r * math.cos(ang)
                y = cy + r * math.sin(ang)
                if m + 10 < x < ancho - m - 10 and m + 10 < y < alto - m - 10:
                    c.circle(x, y, 1.3, stroke=0, fill=1)

    y = alto - 105
    if LOGO.exists():
        c.drawImage(str(LOGO), ancho / 2 - 70, y - 10, width=140, height=50,
                    preserveAspectRatio=True, mask="auto")
    else:
        c.setFillColor(NAVY)
        c.setFont(F["Titulo"], 22)
        c.drawCentredString(ancho / 2, y + 10, "aural")
        c.setFillColor(GRIS)
        c.setFont(F["Texto"], 8)
        c.drawCentredString(ancho / 2, y - 4, "CENTROS AUDITIVOS")

    c.setFillColor(NAVY)
    c.setFont(F["Titulo"], 44)
    c.drawCentredString(ancho / 2, alto - 175, TITULO)
    c.setStrokeColor(TEAL)
    c.setLineWidth(2)
    c.line(ancho / 2 - 30, alto - 190, ancho / 2 + 30, alto - 190)

    c.setFillColor(GRIS)
    c.setFont(F["Texto"], 14)
    c.drawCentredString(ancho / 2, alto - 225, SUBTITULO)

    tam = _ajustar_tamano(c, nombre, F["Titulo"], 38, ancho * 0.75)
    c.setFillColor(NAVY)
    c.setFont(F["Titulo"], tam)
    c.drawCentredString(ancho / 2, alto - 285, nombre)
    c.setStrokeColor(GRIS)
    c.setLineWidth(0.6)
    c.line(ancho * 0.2, alto - 300, ancho * 0.8, alto - 300)

    c.setFillColor(GRIS)
    c.setFont(F["Texto"], 14)
    c.drawCentredString(ancho / 2, alto - 335, MOTIVO)
    c.setFont(F["Light"], 11)
    c.drawCentredString(ancho / 2, alto - 360, _fecha_hoy())

    # Firma
    fy = 105
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.8)
    c.line(ancho / 2 - 110, fy, ancho / 2 + 110, fy)
    c.setFillColor(NAVY)
    c.setFont(F["Titulo"], 12)
    c.drawCentredString(ancho / 2, fy - 18, FIRMA_NOMBRE)
    c.setFillColor(GRIS)
    c.setFont(F["Texto"], 10)
    c.drawCentredString(ancho / 2, fy - 33, FIRMA_CARGO)

    c.save()
    return salida


if __name__ == "__main__":
    import sys
    n = " ".join(sys.argv[1:]) or "maría fernanda de la torre"
    out = BASE / nombre_archivo(limpiar_nombre(n))
    print(generar_diploma(n, out))
