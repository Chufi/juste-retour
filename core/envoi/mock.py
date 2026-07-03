"""Implémentation mock/sandbox d'`EnvoiRecommande`, utilisée tant qu'aucun
compte de production n'est ouvert chez un prestataire qualifié eIDAS. Ne fait
aucun appel réseau ; simule un dépôt et des preuves immédiates."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .base import EnvoiRecommande, PreuvesEnvoi, ResultatEnvoi

_ENVOIS_SIMULES: dict[str, dict[str, Any]] = {}


class EnvoiMock(EnvoiRecommande):
    def envoyer(self, dossier: dict[str, Any], canal: str, contenu: str) -> ResultatEnvoi:
        id_envoi = f"mock-{uuid.uuid4().hex[:12]}"
        horodatage = datetime.now(timezone.utc).isoformat()

        _ENVOIS_SIMULES[id_envoi] = {
            "dossier_id": dossier.get("dossier_id"),
            "canal": canal,
            "contenu": contenu,
            "horodatage_depot": horodatage,
        }

        return {
            "id_envoi": id_envoi,
            "canal": canal,
            "statut": "depose",
            "horodatage": horodatage,
        }

    def recuperer_preuves(self, id_envoi: str) -> PreuvesEnvoi:
        if id_envoi not in _ENVOIS_SIMULES:
            raise KeyError(f"Envoi inconnu (sandbox) : {id_envoi}")

        return {
            "id_envoi": id_envoi,
            "preuve_depot": f"preuve-depot-simulee://{id_envoi}",
            "preuve_distribution": f"preuve-distribution-simulee://{id_envoi}",
            "statut": "distribue",
            "horodatage_maj": datetime.now(timezone.utc).isoformat(),
        }
