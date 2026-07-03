from verticals.pension_cnav.sam import calculer_sam, detecter_trimestres_manquants


def test_annee_sans_activite_exclue_du_calcul():
    annees = [
        {"annee": 2020, "salaire_reporte": 0.0, "trimestres": 0},
        {"annee": 2021, "salaire_reporte": 20000.0, "trimestres": 4},
    ]
    resultat = calculer_sam(annees, nombre_meilleures_annees=25, coefficients={2020: 1.0, 2021: 1.0})
    assert resultat["nombre_annees_retenues"] == 1
    assert resultat["sam"] == 20000.0
    assert not any(a["annee"] == 2020 for a in resultat["anomalies"])


def test_salaire_nul_avec_trimestres_est_une_anomalie():
    annees = [{"annee": 2020, "salaire_reporte": 0.0, "trimestres": 3}]
    resultat = calculer_sam(annees, 25, {2020: 1.0})
    assert resultat["sam"] == 0.0
    assert resultat["anomalies"] == [{"annee": 2020, "type": "salaire_nul_avec_trimestres_valides"}]


def test_salaire_illisible_est_signale_et_exclu_du_calcul():
    annees = [
        {"annee": 2019, "salaire_reporte": None, "trimestres": 4},
        {"annee": 2020, "salaire_reporte": 15000.0, "trimestres": 4},
    ]
    resultat = calculer_sam(annees, 25, {2019: 1.0, 2020: 1.0})
    assert resultat["nombre_annees_retenues"] == 1
    assert {"annee": 2019, "type": "salaire_illisible_ou_manquant"} in resultat["anomalies"]


def test_moyenne_des_meilleures_annees_revalorisees():
    annees = [
        {"annee": 2018, "salaire_reporte": 10000.0, "trimestres": 4},
        {"annee": 2019, "salaire_reporte": 20000.0, "trimestres": 4},
        {"annee": 2020, "salaire_reporte": 30000.0, "trimestres": 4},
    ]
    coefficients = {2018: 1.0, 2019: 1.0, 2020: 1.0}
    resultat = calculer_sam(annees, nombre_meilleures_annees=2, coefficients=coefficients)
    assert resultat["nombre_annees_retenues"] == 2
    assert resultat["sam"] == 25000.0  # moyenne des deux meilleures : (20000 + 30000) / 2


def test_coefficient_de_revalorisation_est_applique():
    annees = [{"annee": 2000, "salaire_reporte": 10000.0, "trimestres": 4}]
    resultat = calculer_sam(annees, 25, {2000: 1.5})
    assert resultat["sam"] == 15000.0


def test_coefficient_manquant_signale_et_defaut_a_un():
    annees = [{"annee": 1950, "salaire_reporte": 10000.0, "trimestres": 4}]
    resultat = calculer_sam(annees, 25, {})
    assert resultat["sam"] == 10000.0
    assert {"annee": 1950, "type": "coefficient_revalorisation_manquant"} in resultat["anomalies"]


def test_trimestres_incomplets_signales():
    annees = [
        {"annee": 2019, "salaire_reporte": 10000.0, "trimestres": 2},
        {"annee": 2020, "salaire_reporte": 12000.0, "trimestres": 4},
    ]
    anomalies = detecter_trimestres_manquants(annees, trimestres_par_an=4)
    assert {"annee": 2019, "type": "trimestres_incomplets"} in anomalies
    assert {"annee": 2020, "type": "trimestres_incomplets"} not in anomalies


def test_annee_absente_du_releve_detectee():
    annees = [
        {"annee": 2018, "salaire_reporte": 10000.0, "trimestres": 4},
        {"annee": 2020, "salaire_reporte": 12000.0, "trimestres": 4},
    ]
    anomalies = detecter_trimestres_manquants(annees, trimestres_par_an=4)
    assert {"annee": 2019, "type": "annee_absente_du_releve"} in anomalies
