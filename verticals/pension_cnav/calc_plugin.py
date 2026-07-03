"""Plugin de calcul du vertical pension_cnav (erreur de pension, régime général).

Expose l'interface générique attendue par `core.calc_engine` :
`calculer(donnees: dict, config: dict) -> ResultatCalcul`. Le SAM et le
rappel restent 100% déterministes (`sam.py`, `rappel.py`) ; ce module se
contente d'orchestrer ces deux calculs et de les traduire dans le contrat
générique consommé par `core.review_agent` et `core.letter_engine`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, TypedDict

from pydantic import BaseModel, Field

from core.confiance import estimer_confiance
from core.schemas import Fiabilite

from . import rappel as rappel_module
from . import sam as sam_module

COEFFICIENTS_PATH = Path(__file__).resolve().parent / "coefficients_2026.json"


# --- Schéma de données spécifique au vertical retraite --------------------


class AnneeCarriere(BaseModel):
    annee: int
    salaire_reporte: Optional[float] = None
    trimestres: int
    source: str
    fiabilite: Fiabilite


class Bulletin(BaseModel):
    annee: int
    salaire_brut_annuel: float
    source: str
    fiabilite: Fiabilite


class PensionNotifiee(BaseModel):
    base_mensuel: float = 0.0
    complementaire_mensuel: float = 0.0
    sam_retenu: float = 0.0
    trimestres_retenus: int = 0
    taux: float = 0.0
    liquidation_provisoire: bool = False


class CalculMoteur(BaseModel):
    sam_recalcule: float = 0.0
    ecart_sam: float = 0.0
    rappel_estime: float = 0.0
    majoration_mensuelle_future: float = 0.0


class DossierNormalise(BaseModel):
    """Le JSON envoyé en message utilisateur au LLM pour l'analyse qualitative."""

    documents: list[dict] = Field(default_factory=list)
    carriere: list[AnneeCarriere] = Field(default_factory=list)
    bulletins: list[Bulletin] = Field(default_factory=list)
    pension_notifiee: PensionNotifiee = Field(default_factory=PensionNotifiee)
    champs_illisibles: list[str] = Field(default_factory=list)
    calcul_moteur: CalculMoteur = Field(default_factory=CalculMoteur)


# --- Contrat générique attendu par core.calc_engine ------------------------


class ResultatCalcul(TypedDict):
    montant_estime: float
    confiance: float
    anomalies: list[dict]
    champs_manquants: list[str]
    details: dict[str, Any]


@lru_cache(maxsize=1)
def charger_coefficients() -> dict[int, float]:
    with open(COEFFICIENTS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {int(annee): float(valeur) for annee, valeur in data["coefficients"].items()}


# Gravité par type d'anomalie (cf. core/confiance.py) : les trous de données
# sources pèsent plus lourd que les écarts que le courrier réclame justement.
GRAVITES = {
    "salaire_illisible_ou_manquant": 0.30,
    "coefficient_revalorisation_manquant": 0.25,
    "salaire_nul_avec_trimestres_valides": 0.20,
    "annee_absente_du_releve": 0.15,
    "trimestres_incomplets": 0.10,
}


def calculer(donnees: dict[str, Any], config: dict[str, Any]) -> ResultatCalcul:
    juridique = config["juridique"]
    annees_calcul = donnees.get("annees_carriere", [])
    pension_notifiee = donnees.get("pension_notifiee", {})

    coefficients = charger_coefficients()

    resultat_sam = sam_module.calculer_sam(
        annees_calcul, juridique["nombre_meilleures_annees_sam"], coefficients
    )
    anomalies_trimestres = sam_module.detecter_trimestres_manquants(
        annees_calcul, juridique["trimestres_par_an"]
    )
    anomalies = resultat_sam["anomalies"] + anomalies_trimestres

    trimestres_valides = sum(a["trimestres"] for a in annees_calcul)
    delai_prescription = juridique.get("delai_prescription")

    resultat_rappel = rappel_module.calculer_rappel(
        sam_recalcule=resultat_sam["sam"],
        taux_pourcentage=juridique["taux_plein_pourcentage"],
        trimestres_valides=trimestres_valides,
        trimestres_requis=juridique["trimestres_requis_taux_plein_defaut"],
        pension_base_notifiee_mensuelle=pension_notifiee.get("base_mensuel", 0.0),
        # Tant que le délai n'est pas validé par un avocat, on ne projette
        # aucun rappel chiffré au-delà du mois courant (delai=0) plutôt que
        # d'inventer une valeur par défaut non validée.
        delai_prescription_annees=delai_prescription if delai_prescription is not None else 0,
    )

    champs_manquants = [
        f"salaire_reporte {a['annee']}" for a in annees_calcul if a.get("salaire_reporte") is None
    ]

    confiance = 0.0 if not annees_calcul else estimer_confiance(anomalies, GRAVITES)

    return {
        "montant_estime": resultat_rappel["rappel_estime"],
        "confiance": confiance,
        "anomalies": anomalies,
        "champs_manquants": champs_manquants,
        "details": {
            "sam_recalcule": resultat_sam["sam"],
            "ecart_sam": resultat_sam["sam"] - pension_notifiee.get("sam_retenu", 0.0),
            "majoration_mensuelle_future": resultat_rappel["majoration_mensuelle"],
            "pension_base_recalculee_mensuelle": resultat_rappel["pension_base_recalculee_mensuelle"],
            "trimestres_valides": trimestres_valides,
            "delai_prescription_annees_applique": resultat_rappel["delai_prescription_annees_applique"],
            "annees_retenues": resultat_sam["annees_retenues"],
        },
    }
