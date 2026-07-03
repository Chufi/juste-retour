"""Génère les landing pages statiques depuis les configs de verticaux.

Une seule template (`landing/template/index.html.jinja2`), N pages :

    python landing/build.py                    # tous les verticaux
    python landing/build.py depot_garantie     # un vertical précis

Garde-fous appliqués au build (pas seulement à la template) :
- une stat sans champ `source` (ou avec une source vide) n'est PAS rendue ;
- un vertical sans les champs obligatoires (hook, etapes, mentions_legales)
  est refusé avec une erreur explicite plutôt que publié incomplet.
"""

from __future__ import annotations

import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from core.config_loader import charger_config, lister_verticals  # noqa: E402

TEMPLATE_DIR = Path(__file__).resolve().parent / "template"
SORTIE_DIR = Path(__file__).resolve().parent

CHAMPS_OBLIGATOIRES = ("slug", "nom_public", "hook", "sous_titre", "etapes", "mentions_legales")


def filtrer_stats(stats: list[dict] | None) -> list[dict]:
    """Aucune stat non sourcée sur une page publique (garde-fou)."""
    return [s for s in (stats or []) if s.get("source") and str(s["source"]).strip()]


def construire(slug: str) -> Path:
    config = charger_config(slug, forcer_rechargement=True)

    manquants = [c for c in CHAMPS_OBLIGATOIRES if not config.get(c)]
    if manquants:
        raise ValueError(f"Vertical '{slug}' : champs de landing manquants : {', '.join(manquants)}")

    environnement = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR), undefined=StrictUndefined, autoescape=True
    )
    template = environnement.get_template("index.html.jinja2")

    html = template.render(
        slug=config["slug"],
        nom_public=config["nom_public"],
        hook=config["hook"],
        sous_titre=config["sous_titre"],
        etapes=config["etapes"],
        stats=filtrer_stats(config.get("stats")),
        pieces=config.get("pieces", []),
        mentions_legales=config["mentions_legales"],
        app_url=config.get("app_url"),
    )

    sortie = SORTIE_DIR / slug / "index.html"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(html, encoding="utf-8")
    return sortie


def main(arguments: list[str]) -> None:
    if arguments:
        slugs = arguments  # slug explicite : build forcé, même en draft (prévisualisation)
    else:
        # Un vertical `draft` n'est pas publié : exclu du build par défaut.
        slugs = [
            slug
            for slug in lister_verticals()
            if charger_config(slug, forcer_rechargement=True).get("status") != "draft"
        ]
    for slug in slugs:
        chemin = construire(slug)
        print(f"Générée : {chemin.relative_to(RACINE)}")


if __name__ == "__main__":
    main(sys.argv[1:])
