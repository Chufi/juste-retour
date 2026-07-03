from verticals.pension_cnav.rappel import calculer_pension_base_mensuelle, calculer_rappel


def test_pension_de_base_proratisee_par_trimestres():
    pension = calculer_pension_base_mensuelle(
        sam=20000.0, taux_pourcentage=50.0, trimestres_valides=84, trimestres_requis=168
    )
    assert pension == round(20000.0 * 0.5 * 0.5 / 12, 2)


def test_pension_plafonnee_a_taux_plein_meme_si_trimestres_excedentaires():
    pension_a_taux_plein = calculer_pension_base_mensuelle(
        sam=20000.0, taux_pourcentage=50.0, trimestres_valides=168, trimestres_requis=168
    )
    pension_avec_exces = calculer_pension_base_mensuelle(
        sam=20000.0, taux_pourcentage=50.0, trimestres_valides=180, trimestres_requis=168
    )
    assert pension_avec_exces == pension_a_taux_plein


def test_rappel_plafonne_par_le_delai_de_prescription_parametre():
    """Le délai de prescription est un PARAMÈTRE (jamais en dur, cf. brief) :
    on vérifie ici que faire varier ce seul paramètre change proportionnellement
    le rappel estimé, sans toucher au code."""
    resultat_court = calculer_rappel(
        sam_recalcule=20000.0,
        taux_pourcentage=50.0,
        trimestres_valides=168,
        trimestres_requis=168,
        pension_base_notifiee_mensuelle=700.0,
        delai_prescription_annees=2,
    )
    resultat_long = calculer_rappel(
        sam_recalcule=20000.0,
        taux_pourcentage=50.0,
        trimestres_valides=168,
        trimestres_requis=168,
        pension_base_notifiee_mensuelle=700.0,
        delai_prescription_annees=5,
    )
    assert resultat_court["nombre_mois_plafonne"] == 24
    assert resultat_long["nombre_mois_plafonne"] == 60
    assert resultat_long["rappel_estime"] == round(resultat_court["rappel_estime"] * 5 / 2, 2)


def test_pas_de_rappel_negatif_si_pension_notifiee_deja_superieure():
    resultat = calculer_rappel(
        sam_recalcule=10000.0,
        taux_pourcentage=50.0,
        trimestres_valides=168,
        trimestres_requis=168,
        pension_base_notifiee_mensuelle=5000.0,
        delai_prescription_annees=5,
    )
    assert resultat["majoration_mensuelle"] == 0.0
    assert resultat["rappel_estime"] == 0.0


def test_salaire_a_zero_ne_genere_aucun_rappel():
    resultat = calculer_rappel(
        sam_recalcule=0.0,
        taux_pourcentage=50.0,
        trimestres_valides=168,
        trimestres_requis=168,
        pension_base_notifiee_mensuelle=0.0,
        delai_prescription_annees=5,
    )
    assert resultat["pension_base_recalculee_mensuelle"] == 0.0
    assert resultat["rappel_estime"] == 0.0


def test_trimestres_requis_nul_ne_leve_pas_de_division_par_zero():
    pension = calculer_pension_base_mensuelle(
        sam=20000.0, taux_pourcentage=50.0, trimestres_valides=0, trimestres_requis=0
    )
    assert pension == 0.0
