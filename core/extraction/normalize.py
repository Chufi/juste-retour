"""Nettoyage du texte issu de l'OCR avant extraction structurée.

L'OCR sur des documents administratifs français produit des erreurs
récurrentes : confusion O/0, l/1, espaces insécables autour des montants,
espaces multiples. Ce module centralise ces corrections pour que
`extraction/tables.py` et `extraction/ocr.py` n'aient pas à les dupliquer.
"""

from __future__ import annotations

import re
from typing import Optional

# U+00A0 (NBSP) et U+202F (espace fine insécable) : séparateurs de milliers
# utilisés dans les documents français ("1 234,56 €").
_ESPACES_INSECABLES = (" ", " ")

_MONTANT_RE = re.compile(r"^-?\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{1,2})?$")


def nettoyer_texte_ocr(texte: str) -> str:
    """Corrige les artefacts OCR courants sans toucher au sens du texte."""
    for espace in _ESPACES_INSECABLES:
        texte = texte.replace(espace, " ")
    texte = re.sub(r"[ \t]+", " ", texte)
    return texte.strip()


def _corriger_confusions_chiffres(fragment: str) -> str:
    """Remplace O/o -> 0 et l/I -> 1 dans un fragment déjà identifié comme
    numérique (ne s'applique jamais à du texte libre)."""
    fragment = fragment.replace("O", "0").replace("o", "0")
    fragment = fragment.replace("l", "1").replace("I", "1")
    return fragment


def parser_montant_fr(fragment: str) -> Optional[float]:
    """Parse un montant écrit en notation française ("1 234,56", "12.345,00",
    "1234.56") en float. Retourne None si le fragment n'est pas un montant
    reconnaissable (à traiter alors comme un champ ILLISIBLE)."""
    fragment = nettoyer_texte_ocr(fragment)
    if not fragment:
        return None

    candidat = re.sub(r"(?i)\s*(€|eur)\s*$", "", fragment).strip()
    if not _MONTANT_RE.match(candidat):
        candidat = _corriger_confusions_chiffres(candidat)
        if not _MONTANT_RE.match(candidat):
            return None

    candidat = candidat.replace(" ", "")
    if "," in candidat:
        candidat = candidat.replace(".", "").replace(",", ".")
    try:
        return float(candidat)
    except ValueError:
        return None


def est_illisible(fragment: str) -> bool:
    """Un fragment est marqué ILLISIBLE si, une fois nettoyé, il ne contient
    ni montant, ni entier, ni texte exploitable (vide, "?", "___", etc.)."""
    fragment = nettoyer_texte_ocr(fragment)
    if not fragment or set(fragment) <= {"?", "_", "-", "."}:
        return True
    return False
