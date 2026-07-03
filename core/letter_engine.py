"""Génération déterministe du courrier de réclamation.

Le courrier est rendu depuis `verticals/<slug>/gabarit_courrier.md` (Jinja2)
et le résultat du `calc_engine` : aucun appel LLM ici. C'est ce qui rend le
courrier prévisible et donc automatisable (cf. `core/review_agent.py`) — le
gabarit doit rester **purement factuel** (constat chiffré + pièces jointes),
sans argumentation juridique, pour rester dans le périmètre "mandataire de
réclamation administrative" (hors consultation juridique, loi de 1971).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from jinja2 import Environment, StrictUndefined

from core.config_loader import charger_texte

GABARIT_NOM = "gabarit_courrier.md"


def generer_courrier(slug: str, contexte: dict[str, Any]) -> str:
    gabarit = charger_texte(slug, GABARIT_NOM)
    environnement = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    modele = environnement.from_string(gabarit)

    contexte_complet = {"date_jour": date.today().strftime("%d/%m/%Y"), **contexte}
    return modele.render(**contexte_complet).strip() + "\n"
