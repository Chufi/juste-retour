"""Tests du moteur de majoration caution (verticals/depot_garantie/calc_plugin.py).

Cas limites exigés par le brief v3 : mois entamé, restitution partielle,
montants nuls — plus l'exception d'adresse non transmise et le litige sur
retenues.
"""

from datetime import date

from core.config_loader import charger_config
from verticals.depot_garantie.calc_plugin import CHAMPS_REQUIS, calculer, mois_commences

CONFIG = charger_config("depot_garantie")


def declaration_type(**surcharges):
    base = {
        "loyer_hc_mensuel": 800.0,
        "depot_verse": 800.0,
        "montant_restitue": 0.0,
        "retenues_bailleur": 0.0,
        "retenues_contestees": False,
        "edl_sortie_conforme": True,
        "nouvelle_adresse_transmise": True,
        "date_remise_cles": "2026-01-15",
        "date_reference": "2026-05-20",
    }
    base.update(surcharges)
    return base


def calculer_type(**surcharges):
    return calculer(
        {
            "declaration": declaration_type(**surcharges),
            "pieces_fournies": list(CONFIG["pieces"]),
        },
        CONFIG,
    )


# --- mois commencés (règle "par période mensuelle commencée") ---------------


def test_un_jour_de_retard_egale_un_mois_commence():
    assert mois_commences(date(2026, 2, 14), date(2026, 2, 15)) == 1


def test_exactement_un_mois_de_retard_egale_un_mois():
    assert mois_commences(date(2026, 2, 14), date(2026, 3, 14)) == 1


def test_un_mois_et_un_jour_egale_deux_mois_commences():
    assert mois_commences(date(2026, 2, 14), date(2026, 3, 15)) == 2


def test_aucun_retard_egale_zero_mois():
    assert mois_commences(date(2026, 2, 14), date(2026, 2, 14)) == 0
    assert mois_commences(date(2026, 2, 14), date(2026, 2, 1)) == 0


def test_fin_de_mois_31_vers_fevrier():
    # Période partant d'un 31 : l'échéance suivante tombe au dernier jour de février.
    assert mois_commences(date(2026, 1, 31), date(2026, 2, 28)) == 1
    assert mois_commences(date(2026, 1, 31), date(2026, 3, 1)) == 2


# --- calcul complet -----------------------------------------------------------


def test_cas_nominal_edl_conforme():
    # Remise des clés 15/01, délai 30 j → limite 14/02 ; au 20/05 : 4 mois commencés.
    resultat = calculer_type()
    assert resultat["details"]["delai_applique_jours"] == 30
    assert resultat["details"]["nb_mois_retard_commences"] == 4
    assert resultat["details"]["principal_restant_du"] == 800.0
    assert resultat["details"]["majoration_legale"] == 0.10 * 800.0 * 4
    assert resultat["montant_estime"] == 800.0 + 320.0


def test_edl_non_conforme_delai_60_jours_et_retenues_deduites():
    resultat = calculer_type(
        edl_sortie_conforme=False, retenues_bailleur=200.0, date_reference="2026-04-20"
    )
    # Limite = 16/03 (60 j) ; au 20/04 : 2 mois commencés.
    assert resultat["details"]["delai_applique_jours"] == 60
    assert resultat["details"]["nb_mois_retard_commences"] == 2
    assert resultat["details"]["principal_restant_du"] == 600.0
    assert resultat["details"]["retenues_admises"] == 200.0


def test_restitution_partielle():
    resultat = calculer_type(montant_restitue=500.0)
    assert resultat["details"]["principal_restant_du"] == 300.0
    # La majoration reste assise sur le loyer, pas sur le solde.
    assert resultat["details"]["majoration_legale"] == 0.10 * 800.0 * 4


def test_montants_nuls():
    resultat = calculer_type(loyer_hc_mensuel=0.0, depot_verse=0.0)
    assert resultat["details"]["principal_restant_du"] == 0.0
    assert resultat["details"]["majoration_legale"] == 0.0
    assert resultat["montant_estime"] == 0.0
    assert any(a["type"] == "aucun_principal_restant_du" for a in resultat["anomalies"])


def test_restitution_totale_ne_reclame_pas_de_principal_negatif():
    resultat = calculer_type(montant_restitue=800.0)
    assert resultat["details"]["principal_restant_du"] == 0.0


def test_delai_legal_non_expire_aucun_montant():
    resultat = calculer_type(date_reference="2026-02-01")
    assert resultat["montant_estime"] == 0.0
    assert any(a["type"] == "delai_legal_non_expire" for a in resultat["anomalies"])


def test_exception_majoration_si_adresse_non_transmise():
    resultat = calculer_type(nouvelle_adresse_transmise=False)
    assert resultat["details"]["majoration_legale"] == 0.0
    assert resultat["montant_estime"] == 800.0  # le principal reste dû
    assert any(a["type"] == "exception_majoration" for a in resultat["anomalies"])
    # Exception mécanique et certaine : la confiance reste au-dessus du seuil
    # auto (0.85) — le montant calculé est fiable.
    assert resultat["confiance"] == 0.95


def test_retenues_contestees_signalees_comme_anomalie():
    resultat = calculer_type(
        edl_sortie_conforme=False, retenues_bailleur=300.0, retenues_contestees=True
    )
    assert any(a["type"] == "retenues_contestees" for a in resultat["anomalies"])
    # Litige factuel : la confiance s'effondre sous le seuil auto → EXCEPTION.
    assert resultat["confiance"] == 0.5


def test_retenues_malgre_edl_conforme_reclamees_en_totalite():
    resultat = calculer_type(retenues_bailleur=250.0)
    assert resultat["details"]["retenues_admises"] == 0.0
    assert resultat["details"]["principal_restant_du"] == 800.0
    assert any(a["type"] == "retenues_malgre_edl_conforme" for a in resultat["anomalies"])


def test_declaration_incomplete_liste_les_champs_manquants():
    donnees = {"declaration": {"loyer_hc_mensuel": 800.0}, "pieces_fournies": []}
    resultat = calculer(donnees, CONFIG)
    assert resultat["montant_estime"] == 0.0
    for champ in CHAMPS_REQUIS:
        if champ != "loyer_hc_mensuel":
            assert champ in resultat["champs_manquants"]
    assert any(m.startswith("pièce :") for m in resultat["champs_manquants"])


def test_taux_vient_de_la_config_jamais_en_dur():
    config_modifiee = {**CONFIG, "juridique": {**CONFIG["juridique"], "majoration_taux": 0.20}}
    resultat = calculer(
        {"declaration": declaration_type(), "pieces_fournies": list(CONFIG["pieces"])},
        config_modifiee,
    )
    assert resultat["details"]["majoration_legale"] == 0.20 * 800.0 * 4
