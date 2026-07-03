from pathlib import Path

import pytest

from core.extraction import normalize, ocr, tables

FIXTURES = Path(__file__).parent / "fixtures"
RELEVE_CARRIERE = FIXTURES / "releve_carriere_exemple.pdf"
BULLETIN_IMAGE = FIXTURES / "bulletin_paie_1999.png"


# --- normalize.py -----------------------------------------------------


def test_nettoyer_texte_ocr_remplace_espaces_insecables():
    assert normalize.nettoyer_texte_ocr("18 340,00 €") == "18 340,00 €"


def test_parser_montant_fr_avec_separateur_de_milliers():
    assert normalize.parser_montant_fr("18 340,00") == 18340.00


def test_parser_montant_fr_avec_symbole_euro():
    assert normalize.parser_montant_fr("1 200,00 €") == 1200.00


def test_parser_montant_fr_retourne_none_si_illisible():
    assert normalize.parser_montant_fr("???") is None


def test_est_illisible_detecte_les_fragments_vides_ou_places_holders():
    assert normalize.est_illisible("") is True
    assert normalize.est_illisible("???") is True
    assert normalize.est_illisible("18 340,00 €") is False


# --- tables.py (relevé de carrière, PDF texte tabulaire) --------------


def test_extraction_releve_carriere_lignes_lisibles():
    lignes = tables.extraire_lignes_carriere(RELEVE_CARRIERE)
    par_annee = {ligne["annee"]: ligne for ligne in lignes}

    assert par_annee[2015]["salaire_reporte"] == 18000.0
    assert par_annee[2015]["trimestres"] == 4
    assert par_annee[2015]["lisible"] is True


def test_extraction_releve_carriere_signale_le_champ_illisible():
    lignes = tables.extraire_lignes_carriere(RELEVE_CARRIERE)
    par_annee = {ligne["annee"]: ligne for ligne in lignes}

    assert par_annee[2018]["salaire_reporte"] is None
    assert par_annee[2018]["lisible"] is False


def test_extraction_releve_carriere_annee_blanche():
    lignes = tables.extraire_lignes_carriere(RELEVE_CARRIERE)
    par_annee = {ligne["annee"]: ligne for ligne in lignes}

    assert par_annee[2017]["salaire_reporte"] == 0.0
    assert par_annee[2017]["trimestres"] == 0


def test_extraction_releve_carriere_annee_manquante_non_generee():
    lignes = tables.extraire_lignes_carriere(RELEVE_CARRIERE)
    annees_presentes = {ligne["annee"] for ligne in lignes}
    assert 2020 not in annees_presentes


# --- ocr.py -------------------------------------------------------------


def test_est_pdf_scanne_faux_pour_un_pdf_a_couche_texte():
    assert ocr.est_pdf_scanne(RELEVE_CARRIERE) is False


def test_extraire_salaire_brut_mensuel_depuis_texte_ocr():
    texte = "Salaire brut mensuel : 1 200,00 €\nNet à payer : 950,00 €"
    assert ocr.extraire_salaire_brut_mensuel(texte) == 1200.00


def test_extraire_salaire_brut_mensuel_absent_retourne_none():
    assert ocr.extraire_salaire_brut_mensuel("Aucune ligne pertinente ici.") is None


@pytest.mark.skipif(not ocr.outils_disponibles(), reason="tesseract/ocrmypdf non installés")
def test_ocr_image_reconnait_le_bulletin_de_paie():
    texte = ocr.ocr_image(BULLETIN_IMAGE)
    assert "1" in texte and "200" in texte
