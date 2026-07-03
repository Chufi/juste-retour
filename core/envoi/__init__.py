"""Sélection du prestataire d'envoi recommandé.

Tant qu'aucun compte de production n'est ouvert chez un prestataire qualifié
eIDAS, `obtenir_prestataire` retourne toujours l'implémentation mock/sandbox,
quelle que soit la config — c'est le flag `prestataire_envoi` du vertical qui
active un prestataire réel une fois le compte ouvert (non construit dans ce
sprint, cf. non-objectifs).
"""

from __future__ import annotations

from typing import Any

from .base import EnvoiRecommande, PreuvesEnvoi, ResultatEnvoi
from .mock import EnvoiMock

_PRESTATAIRES_REELS: dict[str, type[EnvoiRecommande]] = {
    # "docaposte_maileva": DocaposteMaileva,  # à brancher quand le compte est ouvert
    # "ar24": AR24,
}


def obtenir_prestataire(config: dict[str, Any]) -> EnvoiRecommande:
    prestataire = config.get("prestataire_envoi")
    if prestataire and prestataire in _PRESTATAIRES_REELS:
        return _PRESTATAIRES_REELS[prestataire]()
    return EnvoiMock()


def determiner_canal(config: dict[str, Any]) -> str:
    """Lit le canal d'envoi depuis la config du vertical. Ne décide jamais
    en dur : `hybride` par défaut si non précisé (le plus sûr — valable pour
    tout destinataire, y compris une administration, sans consentement)."""
    return config.get("canal_envoi") or "hybride"


__all__ = [
    "EnvoiRecommande",
    "PreuvesEnvoi",
    "ResultatEnvoi",
    "EnvoiMock",
    "obtenir_prestataire",
    "determiner_canal",
]
