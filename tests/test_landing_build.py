"""Garde-fous du système de landing pages (landing/build.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "landing"))

from build import CHAMPS_OBLIGATOIRES, construire, filtrer_stats  # noqa: E402


def test_stat_sans_source_non_rendue():
    stats = [
        {"valeur": "1 mois", "libelle": "délai", "source": "Art. 22 loi 89-462"},
        {"valeur": "99 %", "libelle": "chiffre inventé sans source"},
        {"valeur": "42", "libelle": "source vide", "source": "  "},
    ]
    filtrees = filtrer_stats(stats)
    assert len(filtrees) == 1
    assert filtrees[0]["valeur"] == "1 mois"


def test_stats_absentes_ne_cassent_pas_le_build():
    assert filtrer_stats(None) == []


def test_build_depot_garantie_contient_les_elements_obligatoires(tmp_path):
    chemin = construire("depot_garantie")
    html = chemin.read_text(encoding="utf-8")
    assert "caution" in html.lower()
    assert "loi n° 71-1130" in html  # mention légale loi de 1971
    assert "48 h" in html  # message de confirmation honnête
    assert 'VERTICAL = "depot_garantie"' in html
    assert "utm_" in html  # capture d'attribution
    assert "/leads" in html


def test_build_ne_publie_aucune_stat_non_sourcee():
    chemin = construire("frais_bancaires")
    html = chemin.read_text(encoding="utf-8")
    # frais_bancaires n'a qu'une stat sourcée (modèle au succès interne).
    assert html.count('class="stat-item"') == 1


def test_champs_obligatoires_manquants_refuses(monkeypatch):
    import build as build_module

    def config_incomplete(slug, forcer_rechargement=False):
        return {"slug": slug, "nom_public": "Test"}  # hook, etapes... absents

    monkeypatch.setattr(build_module, "charger_config", config_incomplete)
    with pytest.raises(ValueError, match="champs de landing manquants"):
        construire("depot_garantie")
    assert "hook" in CHAMPS_OBLIGATOIRES
