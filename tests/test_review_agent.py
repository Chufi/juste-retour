"""Tests du Directeur Juridique (core/review_agent.py) : double filtre
juridique + économique, respect du cycle de vie des verticaux."""

from core.review_agent import MOTIF_LOW_RECOVERABILITY, REGLES_VERSION, evaluer

CONFIG_AUTO_OK = {
    "status": "active",
    "juridique": {"statut_validation_avocat": "valide"},
    "seuils_auto": {"confiance_min": 0.8, "montant_plafond_auto": 2000.0, "recouvrabilite_min": 0.5},
}

CALCUL_OK = {"montant_estime": 1000.0, "confiance": 0.9, "anomalies": [], "champs_manquants": []}
SCORE_OK = {"probabilite": 0.7, "delai_estime_jours": 45, "version": "bayes-v2", "base": "prior_heuristique", "n_echantillon": 0}


def evaluer_type(**surcharges):
    params = dict(
        config=CONFIG_AUTO_OK,
        resultat_calcul=CALCUL_OK,
        fiabilite_ocr_toutes_hautes=True,
        mandat_signe=True,
        mode_effectif="auto",
        status_effectif="active",
        score_recouvrabilite=SCORE_OK,
    )
    params.update(surcharges)
    return evaluer(**params)


def test_toutes_conditions_reunies_verdict_auto():
    verdict = evaluer_type()
    assert verdict["decision"] == "AUTO"
    assert verdict["motifs"] == []
    assert verdict["regles_version"] == REGLES_VERSION
    assert verdict["scoring_version"] == "bayes-v2"


def test_vertical_paused_jamais_auto():
    verdict = evaluer_type(status_effectif="paused")
    assert verdict["decision"] == "EXCEPTION"
    assert any("paused" in m for m in verdict["motifs"])


def test_vertical_draft_jamais_auto():
    verdict = evaluer_type(status_effectif="draft")
    assert verdict["decision"] == "EXCEPTION"


def test_low_recoverability_part_en_exception_avec_motif():
    verdict = evaluer_type(score_recouvrabilite={**SCORE_OK, "probabilite": 0.3})
    assert verdict["decision"] == "EXCEPTION"
    assert any(m.startswith(MOTIF_LOW_RECOVERABILITY) for m in verdict["motifs"])


def test_score_absent_bloque_le_verdict_auto():
    verdict = evaluer_type(score_recouvrabilite=None)
    assert verdict["decision"] == "EXCEPTION"


def test_validation_avocat_manquante_bloque():
    config = {**CONFIG_AUTO_OK, "juridique": {"statut_validation_avocat": "en_attente"}}
    verdict = evaluer_type(config=config)
    assert verdict["decision"] == "EXCEPTION"
    assert any("avocat" in m for m in verdict["motifs"])


def test_regime_recouvrement_non_valide_bloque():
    config = {**CONFIG_AUTO_OK, "regime_recouvrement": {"applicable": "a_confirmer"}}
    verdict = evaluer_type(config=config)
    assert verdict["decision"] == "EXCEPTION"


def test_mandat_absent_bloque():
    verdict = evaluer_type(mandat_signe=False)
    assert verdict["decision"] == "EXCEPTION"
    assert any("mandat" in m for m in verdict["motifs"])


def test_montant_au_dela_du_plafond_bloque():
    verdict = evaluer_type(resultat_calcul={**CALCUL_OK, "montant_estime": 5000.0})
    assert verdict["decision"] == "EXCEPTION"


def test_plafond_null_bloque_toujours():
    config = {
        **CONFIG_AUTO_OK,
        "seuils_auto": {**CONFIG_AUTO_OK["seuils_auto"], "montant_plafond_auto": None},
    }
    verdict = evaluer_type(config=config)
    assert verdict["decision"] == "EXCEPTION"


def test_mode_supervise_lancement_route_en_exception():
    verdict = evaluer_type(mode_effectif="supervise_lancement")
    assert verdict["decision"] == "EXCEPTION"
