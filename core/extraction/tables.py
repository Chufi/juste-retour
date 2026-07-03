"""Extraction du relevé de carrière Cnav (PDF à couche texte, tabulaire).

Les relevés de carrière Cnav listent, par année, le régime, le salaire porté
au compte et le nombre de trimestres validés. Ils ont une couche texte native
(pas un scan) : `pdfplumber.extract_tables()` est donc prioritaire sur l'OCR
pour ce type de document (cf. brief).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .normalize import nettoyer_texte_ocr, parser_montant_fr

ANNEE_RE = re.compile(r"^(19|20)\d{2}$")
TRIMESTRES_RE = re.compile(r"^[0-4]$")


def extraire_lignes_carriere(path: Path) -> list[dict]:
    """Parcourt les tableaux d'un relevé de carrière et retourne une ligne
    par année trouvée :
    ``{"annee", "salaire_reporte", "trimestres", "lisible"}``.

    ``lisible`` est False si l'année a été identifiée mais que le salaire n'a
    pas pu être extrait ou parsé (champ à marquer ILLISIBLE en amont)."""
    lignes: list[dict] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    ligne = _parser_ligne(row)
                    if ligne is not None:
                        lignes.append(ligne)
    return lignes


def _parser_ligne(row: list[Optional[str]]) -> Optional[dict]:
    cellules = [nettoyer_texte_ocr(c) if c else "" for c in row]

    annee_str = next((c.strip() for c in cellules if ANNEE_RE.match(c.strip())), None)
    if annee_str is None:
        return None

    salaire: Optional[float] = None
    trimestres = 0
    salaire_present_mais_illisible = False

    for cellule in cellules:
        cellule = cellule.strip()
        if not cellule or cellule == annee_str:
            continue

        if TRIMESTRES_RE.match(cellule):
            trimestres = int(cellule)
            continue

        montant = parser_montant_fr(cellule)
        if montant is not None:
            salaire = montant
        elif "," in cellule or "€" in cellule:
            # Ressemble à un montant mais n'a pas pu être parsé (artefact OCR).
            salaire_present_mais_illisible = True

    lisible = salaire is not None or not salaire_present_mais_illisible
    if salaire_present_mais_illisible:
        lisible = False

    return {
        "annee": int(annee_str),
        "salaire_reporte": salaire,
        "trimestres": trimestres,
        "lisible": lisible,
    }
