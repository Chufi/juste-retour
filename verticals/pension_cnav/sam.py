"""Calcul déterministe du Salaire Annuel Moyen (SAM), régime général.

Règle : moyenne des salaires revalorisés des N meilleures années de
carrière (N = 25 pour les assurés nés à partir de 1948, paramétré dans
`verticals/retraite/config.yaml`, bloc `juridique`). Ce module ne fait AUCUN
appel réseau ni LLM : le résultat doit être reproductible et testable
unitairement.
"""

from __future__ import annotations

from typing import Optional, TypedDict


class AnneeCarriereInput(TypedDict):
    annee: int
    salaire_reporte: Optional[float]
    trimestres: int


class AnomalieSAM(TypedDict):
    annee: int
    type: str


class ResultatSAM(TypedDict):
    sam: float
    annees_retenues: list[dict]
    nombre_annees_retenues: int
    anomalies: list[AnomalieSAM]


def calculer_sam(
    annees: list[AnneeCarriereInput],
    nombre_meilleures_annees: int,
    coefficients: dict[int, float],
) -> ResultatSAM:
    anomalies: list[AnomalieSAM] = []
    revalues: list[dict] = []

    for a in annees:
        annee = a["annee"]
        salaire = a["salaire_reporte"]
        trimestres = a["trimestres"]

        if salaire is None:
            anomalies.append({"annee": annee, "type": "salaire_illisible_ou_manquant"})
            continue

        if trimestres == 0 and salaire == 0:
            # Année sans activité déclarée : ni salaire ni trimestre, on
            # l'exclut du calcul (pas une anomalie en soi).
            continue

        if salaire == 0 and trimestres > 0:
            anomalies.append({"annee": annee, "type": "salaire_nul_avec_trimestres_valides"})
            continue

        coef = coefficients.get(annee)
        if coef is None:
            anomalies.append({"annee": annee, "type": "coefficient_revalorisation_manquant"})
            coef = 1.0

        revalues.append(
            {
                "annee": annee,
                "salaire_reporte": salaire,
                "coefficient": coef,
                "salaire_revalue": round(salaire * coef, 2),
            }
        )

    if not revalues:
        return {
            "sam": 0.0,
            "annees_retenues": [],
            "nombre_annees_retenues": 0,
            "anomalies": anomalies,
        }

    meilleures = sorted(revalues, key=lambda x: x["salaire_revalue"], reverse=True)[
        :nombre_meilleures_annees
    ]
    diviseur = min(nombre_meilleures_annees, len(revalues))
    sam = round(sum(x["salaire_revalue"] for x in meilleures) / diviseur, 2)

    return {
        "sam": sam,
        "annees_retenues": meilleures,
        "nombre_annees_retenues": len(meilleures),
        "anomalies": anomalies,
    }


def detecter_trimestres_manquants(
    annees: list[AnneeCarriereInput], trimestres_par_an: int = 4
) -> list[AnomalieSAM]:
    """Signale les années présentes dans le relevé avec moins de
    `trimestres_par_an` trimestres validés, et les années manquantes dans la
    plage [min(annee), max(annee)] du relevé fourni."""
    anomalies: list[AnomalieSAM] = []
    if not annees:
        return anomalies

    annees_presentes = {a["annee"] for a in annees}
    for a in annees:
        if a["trimestres"] < trimestres_par_an:
            anomalies.append({"annee": a["annee"], "type": "trimestres_incomplets"})

    debut, fin = min(annees_presentes), max(annees_presentes)
    for annee in range(debut, fin + 1):
        if annee not in annees_presentes:
            anomalies.append({"annee": annee, "type": "annee_absente_du_releve"})

    return anomalies
