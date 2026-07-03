"""Orchestrateur générique de calcul.

Charge la config du vertical et son `calc_plugin`, puis délègue le calcul au
plugin. Le moteur lui-même ne contient AUCUNE règle métier : toute règle de
calcul vit dans `verticals/<slug>/calc_plugin.py` (code déterministe, testé
unitairement), jamais ici et jamais dans un appel LLM.

Cycle de vie (`status`, champ unique de la config) :
- `draft` / `smoke_test` : aucun pipeline — le calcul est refusé ;
- `paused`  : pipeline gelé mais exécutable (tests, relecture d'anciens
  dossiers) ; le verdict AUTO et l'envoi restent bloqués en aval ;
- `active`  : régime nominal.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

from core.config_loader import charger_config

_PLUGIN_CACHE: dict[str, ModuleType] = {}

STATUS_AVEC_PIPELINE = ("active", "paused")


class VerticalSansPipeline(RuntimeError):
    """Levée quand on tente de calculer pour un vertical sans pipeline
    (`draft` ou `smoke_test` : seul le lead capture est disponible)."""


def _charger_plugin(slug: str) -> ModuleType:
    if slug not in _PLUGIN_CACHE:
        try:
            module = importlib.import_module(f"verticals.{slug}.calc_plugin")
        except ModuleNotFoundError as exc:
            raise VerticalSansPipeline(
                f"Le vertical '{slug}' n'a pas de calc_plugin."
            ) from exc
        _PLUGIN_CACHE[slug] = module
    return _PLUGIN_CACHE[slug]


def calculer(slug: str, donnees: dict[str, Any]) -> dict[str, Any]:
    """Calcule le résultat déterministe pour un dossier du vertical `slug`.

    Retourne le contrat générique `ResultatCalcul` (cf. docstring des plugins) :
    ``{"montant_estime", "confiance", "anomalies", "champs_manquants", "details"}``.
    """
    config = charger_config(slug)
    status = config.get("status", "draft")
    if status not in STATUS_AVEC_PIPELINE:
        raise VerticalSansPipeline(
            f"Le vertical '{slug}' est en status '{status}' : aucun pipeline "
            "de calcul n'est construit pour lui (leads uniquement)."
        )

    plugin = _charger_plugin(slug)
    return plugin.calculer(donnees, config)
