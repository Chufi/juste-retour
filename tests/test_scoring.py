"""Tests du scoring de recouvrabilité v2 (core/outcomes/scoring.py) :
rétrécissement bayésien continu, sans bascule brutale."""

from core.outcomes.scoring import PRIOR_STRENGTH, SCORING_VERSION, calculer_score


def outcome(statut: str, type_debiteur: str = "particulier", delai: int = 30) -> dict:
    return {
        "statut": statut,
        "profil_debiteur_type": type_debiteur,
        "delai_paiement_jours": delai if statut in ("paye_total", "paye_partiel") else None,
    }


def test_demarrage_a_froid_priors_par_type_de_debiteur():
    score_admin = calculer_score("administration", [])
    score_particulier = calculer_score("particulier", [])
    assert score_admin["base"] == "prior_heuristique"
    assert score_admin["n_echantillon"] == 0
    assert score_admin["probabilite"] == 0.80  # prior exact à froid
    assert score_admin["probabilite"] > score_particulier["probabilite"]
    assert score_admin["version"] == SCORING_VERSION


def test_type_inconnu_retombe_sur_le_prior_particulier():
    assert calculer_score("ovni", [])["probabilite"] == calculer_score("particulier", [])["probabilite"]


def test_des_la_premiere_issue_le_score_bouge():
    """Plus de bascule à N=20 : une seule issue déplace déjà l'estimation."""
    succes = calculer_score("pro", [outcome("paye_total", "pro")])
    echec = calculer_score("pro", [outcome("refus", "pro")])
    prior = calculer_score("pro", [])["probabilite"]
    assert succes["base"] == "bayes_profil"
    assert succes["probabilite"] > prior
    assert echec["probabilite"] < prior


def test_shrinkage_valeur_exacte():
    # 24 recouvrées / 30 terminales, prior pro 0.70, S=15 :
    # (15×0.70 + 24) / (15 + 30) = 34.5/45 ≈ 0.77
    historiques = [outcome("paye_total", "pro") for _ in range(24)]
    historiques += [outcome("refus", "pro") for _ in range(6)]
    score = calculer_score("pro", historiques)
    assert score["probabilite"] == round((PRIOR_STRENGTH * 0.70 + 24) / (PRIOR_STRENGTH + 30), 2)
    assert score["n_echantillon"] == 30


def test_mauvaises_issues_precoces_font_passer_sous_le_seuil():
    """Quelques refus précoces suffisent à déclencher low_recoverability
    (seuil 0.5) sans attendre 20 issues."""
    historiques = [outcome("refus", "particulier") for _ in range(10)]
    score = calculer_score("particulier", historiques)
    # (15×0.55 + 0) / 25 = 0.33
    assert score["probabilite"] < 0.5


def test_le_prior_s_efface_avec_l_historique():
    peu = calculer_score("particulier", [outcome("paye_total", "particulier")] * 5)
    beaucoup = calculer_score("particulier", [outcome("paye_total", "particulier")] * 100)
    assert peu["probabilite"] < beaucoup["probabilite"] <= 1.0


def test_statuts_non_terminaux_ignores():
    historiques = [outcome("envoye", "pro") for _ in range(50)]
    score = calculer_score("pro", historiques)
    assert score["base"] == "prior_heuristique"
    assert score["probabilite"] == 0.70


def test_repli_sur_l_historique_du_vertical_tous_profils():
    # Aucune issue pour le profil demandé, mais des issues sur le vertical :
    # on rétrécit le prior du profil demandé vers l'empirique du vertical.
    historiques = [outcome("paye_total", "pro") for _ in range(15)]
    historiques += [outcome("sans_reponse", "particulier") for _ in range(10)]
    score = calculer_score("administration", historiques)
    assert score["base"] == "bayes_vertical"
    assert score["n_echantillon"] == 25
    # (15×0.80 + 15) / (15 + 25) = 27/40 = 0.68
    assert score["probabilite"] == 0.68


def test_delai_estime_blende_prior_et_median_observe():
    # 30 paiements à 30 j, prior pro 45 j : (15×45 + 30×30)/45 = 35 j.
    historiques = [outcome("paye_total", "pro", delai=30) for _ in range(30)]
    score = calculer_score("pro", historiques)
    assert score["delai_estime_jours"] == 35
