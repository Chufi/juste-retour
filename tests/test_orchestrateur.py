"""Respect du cycle de vie des verticaux par l'orchestrateur
(core/calc_engine.py) et la génération de courrier (core/letter_engine.py)."""

import pytest

from core import calc_engine, letter_engine
from core.config_loader import charger_config


def test_vertical_smoke_test_refuse_le_calcul():
    with pytest.raises(calc_engine.VerticalSansPipeline):
        calc_engine.calculer("frais_bancaires", {})


def test_vertical_draft_sans_plugin_refuse_le_calcul():
    with pytest.raises(calc_engine.VerticalSansPipeline):
        calc_engine.calculer("agirc_arrco", {})


def test_vertical_inconnu_leve_une_erreur():
    from core.config_loader import VerticalInconnu

    with pytest.raises(VerticalInconnu):
        calc_engine.calculer("inexistant", {})


def test_depot_garantie_pipeline_complet_calcule():
    config = charger_config("depot_garantie")
    donnees = {
        "declaration": {
            "loyer_hc_mensuel": 700.0,
            "depot_verse": 700.0,
            "montant_restitue": 0.0,
            "edl_sortie_conforme": True,
            "nouvelle_adresse_transmise": True,
            "date_remise_cles": "2026-01-10",
            "date_reference": "2026-03-15",
        },
        "pieces_fournies": list(config["pieces"]),
    }
    resultat = calc_engine.calculer("depot_garantie", donnees)
    assert resultat["montant_estime"] > 0


def test_pension_cnav_paused_mais_pipeline_toujours_calculable():
    """`paused` gèle le développement et interdit AUTO/envoi (review_agent),
    mais le pipeline existant reste exécutable — rien n'est supprimé."""
    donnees = {
        "annees_carriere": [{"annee": 2020, "salaire_reporte": 20000.0, "trimestres": 4}],
        "pension_notifiee": {},
    }
    resultat = calc_engine.calculer("pension_cnav", donnees)
    assert resultat["details"]["sam_recalcule"] > 0


def test_courrier_depot_garantie_est_genere_et_chiffre():
    config = charger_config("depot_garantie")
    contexte = {
        "nom": "Jeanne Martin",
        "montant_estime": 1120.0,
        "anomalies": [],
        "details": {
            "delai_applique_jours": 30,
            "date_limite_restitution": "2026-02-09",
            "nb_mois_retard_commences": 4,
            "principal_restant_du": 800.0,
            "majoration_legale": 320.0,
            "majoration_taux_applique": 0.10,
        },
        "declaration": {
            "depot_verse": 800.0,
            "montant_restitue": 0.0,
            "date_remise_cles": "2026-01-10",
        },
        "pieces": config["pieces"],
        "base_legale": config["juridique"]["base_legale"],
        "voie_recours": config["juridique"]["voie_recours"],
    }
    courrier = letter_engine.generer_courrier("depot_garantie", contexte)
    assert "1120.00" in courrier
    assert "Mise en demeure" in courrier
    assert config["juridique"]["base_legale"] in courrier
    # Le gabarit reste factuel : la balise de commentaire Jinja ne fuit pas.
    assert "TODO_LAWYER" not in courrier
