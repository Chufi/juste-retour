"""OCR des bulletins de paie scannés (images) et des PDF sans couche texte.

Dépendances système requises en production : `tesseract-ocr` (paquet
`tesseract-ocr-fra` pour le français) et `ocrmypdf`. Ce module échoue
explicitement si ces binaires sont absents plutôt que de retourner un
résultat silencieusement vide.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

LANG = "fra"


class OutilOCRManquant(RuntimeError):
    pass


def outils_disponibles() -> bool:
    return shutil.which("tesseract") is not None and shutil.which("ocrmypdf") is not None


def ocr_image(path: Path) -> str:
    """OCR direct d'un fichier image (JPEG, PNG, TIFF...) via pytesseract."""
    if shutil.which("tesseract") is None:
        raise OutilOCRManquant("tesseract n'est pas installé sur ce système")

    import pytesseract
    from PIL import Image

    with Image.open(path) as image:
        return pytesseract.image_to_string(image, lang=LANG)


def ocr_pdf_scanne(path: Path) -> str:
    """OCR d'un PDF image (sans couche texte) via ocrmypdf.

    ocrmypdf ajoute une couche texte invisible au PDF et produit un fichier
    "sidecar" en parallèle : c'est ce texte que l'on retourne, sans avoir à
    re-parser le PDF de sortie.
    """
    if shutil.which("ocrmypdf") is None:
        raise OutilOCRManquant("ocrmypdf n'est pas installé sur ce système")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pdf_ocr = tmp_dir / "ocr.pdf"
        sidecar = tmp_dir / "ocr.txt"
        subprocess.run(
            [
                "ocrmypdf",
                "--language", LANG,
                "--sidecar", str(sidecar),
                "--force-ocr",
                str(path),
                str(pdf_ocr),
            ],
            check=True,
            capture_output=True,
        )
        return sidecar.read_text(encoding="utf-8")


def extraire_salaire_brut_mensuel(texte: str) -> "float | None":
    """Cherche un montant de salaire brut dans le texte OCR d'un bulletin de
    paie (ligne "Salaire brut" ou "Brut" suivie d'un montant)."""
    import re

    from .normalize import nettoyer_texte_ocr, parser_montant_fr

    texte = nettoyer_texte_ocr(texte)
    for ligne in texte.splitlines():
        if re.search(r"\bbrut\b", ligne, re.IGNORECASE):
            montants = re.findall(r"-?\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{1,2})?", ligne)
            for montant in reversed(montants):
                valeur = parser_montant_fr(montant)
                if valeur is not None and valeur > 0:
                    return valeur
    return None


def est_pdf_scanne(path: Path) -> bool:
    """Heuristique : un PDF est considéré "scanné" si pdfplumber n'y trouve
    quasiment aucun texte extrait (couche image uniquement, sans texte)."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        texte = "".join(page.extract_text() or "" for page in pdf.pages)
    return len(texte.strip()) < 20
