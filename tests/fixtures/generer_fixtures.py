"""Génère les fixtures de test (documents anonymisés d'exemple).

À exécuter une fois pour régénérer les fichiers binaires versionnés dans ce
dossier : ``python tests/fixtures/generer_fixtures.py``. Ces documents sont
entièrement fictifs (aucune donnée personnelle réelle).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

FIXTURES_DIR = Path(__file__).resolve().parent


def generer_releve_carriere_pdf() -> None:
    """Relevé de carrière fictif, PDF à couche texte (tabulaire), avec :
    - une année blanche (0 €, 0 trimestre) à exclure du calcul
    - une année avec un montant illisible (OCR/scan dégradé)
    - une année à trimestres incomplets
    - une année manquante du relevé (2020, saut de 2019 à 2021)
    """
    chemin = FIXTURES_DIR / "releve_carriere_exemple.pdf"

    donnees = [
        ["Année", "Salaire porté au compte", "Trimestres"],
        ["2015", "18 000,00 €", "4"],
        ["2016", "18 500,00 €", "4"],
        ["2017", "0,00 €", "0"],
        ["2018", "??? €", "4"],
        ["2019", "19 000,00 €", "2"],
        ["2021", "20 000,00 €", "4"],
    ]

    doc = SimpleDocTemplate(str(chemin), pagesize=A4)
    table = Table(donnees, colWidths=[3 * cm, 6 * cm, 3 * cm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.75, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b2a4a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    doc.build([table])
    print(f"Écrit : {chemin}")


def generer_bulletin_paie_image() -> None:
    """Bulletin de paie fictif rendu en image (simule un scan) pour
    tester le pipeline OCR (`extraction/ocr.py`)."""
    chemin = FIXTURES_DIR / "bulletin_paie_1999.png"

    image = Image.new("RGB", (900, 500), "white")
    dessin = ImageDraw.Draw(image)
    try:
        police_titre = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
        police = ImageFont.truetype("DejaVuSans.ttf", 24)
    except OSError:
        police_titre = ImageFont.load_default()
        police = ImageFont.load_default()

    dessin.text((40, 30), "BULLETIN DE PAIE - Décembre 1999", font=police_titre, fill="black")
    dessin.text((40, 100), "Employeur : Société Fictive SARL", font=police, fill="black")
    dessin.text((40, 140), "Salarié : Jean Dupont (exemple anonymisé)", font=police, fill="black")
    dessin.text((40, 220), "Salaire brut mensuel : 1 200,00 €", font=police, fill="black")
    dessin.text((40, 260), "Net à payer : 950,00 €", font=police, fill="black")
    image.save(chemin)
    print(f"Écrit : {chemin}")


if __name__ == "__main__":
    generer_releve_carriere_pdf()
    generer_bulletin_paie_image()
