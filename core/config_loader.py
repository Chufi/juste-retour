"""Chargement des fichiers `verticals/<slug>/config.yaml`.

Ce module est le seul point d'entrée pour lire la configuration d'un
vertical : aucune valeur métier (juridique, seuils, canal d'envoi...) ne doit
être lue autrement que via `charger_config`. Le cache est invalidé
explicitement par `vider_cache` (utile pour les tests et pour un rechargement
à chaud sans redéploiement).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

VERTICALS_DIR = Path(__file__).resolve().parent.parent / "verticals"

_cache: dict[str, dict[str, Any]] = {}


class VerticalInconnu(LookupError):
    pass


def repertoire_vertical(slug: str) -> Path:
    return VERTICALS_DIR / slug


def lister_verticals() -> list[str]:
    if not VERTICALS_DIR.exists():
        return []
    return sorted(
        p.name
        for p in VERTICALS_DIR.iterdir()
        if p.is_dir() and (p / "config.yaml").exists()
    )


def charger_config(slug: str, forcer_rechargement: bool = False) -> dict[str, Any]:
    if not forcer_rechargement and slug in _cache:
        return _cache[slug]

    chemin = repertoire_vertical(slug) / "config.yaml"
    if not chemin.exists():
        raise VerticalInconnu(f"Vertical inconnu ou sans config.yaml : {slug}")

    with open(chemin, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    _cache[slug] = config
    return config


def vider_cache() -> None:
    _cache.clear()


def charger_texte(slug: str, nom_fichier: str) -> str:
    """Charge un fichier texte annexe du vertical (gabarit, prompt...)."""
    chemin = repertoire_vertical(slug) / nom_fichier
    return chemin.read_text(encoding="utf-8")
