"""Client Anthropic générique.

Utilisé pour UNE seule chose dans ce moteur : produire le rapport d'anomalies
qualitatif à partir du résultat déjà calculé par le `calc_plugin` du
vertical (repérage de trimestres manquants, incohérences, niveau de
confiance en langage clair...). Le LLM ne recalcule jamais un montant, et ne
rédige plus le courrier de réclamation (cf. `core/letter_engine.py`, qui
génère un texte déterministe à partir d'un gabarit — pas d'appel LLM).

Le system prompt est toujours chargé depuis `verticals/<slug>/prompt_analyse.md`,
jamais dupliqué en dur dans le code Python.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import anthropic

from core.config_loader import charger_texte

MODEL = "claude-sonnet-4-6"


def analyser_dossier(
    slug: str,
    donnees_normalisees: dict[str, Any],
    nom_prompt: str = "prompt_analyse.md",
    client: Optional[anthropic.Anthropic] = None,
) -> str:
    """Retourne le rapport d'anomalies en texte (markdown) produit par Claude."""
    client = client or anthropic.Anthropic()
    system_prompt = charger_texte(slug, nom_prompt)

    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": json.dumps(donnees_normalisees, ensure_ascii=False, indent=2),
            }
        ],
    )

    return "".join(bloc.text for bloc in message.content if bloc.type == "text")
