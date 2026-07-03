"""Calcul déterministe du rappel d'arriérés estimé.

Le délai de prescription opposable (`delai_prescription_annees`) est
TOUJOURS reçu en paramètre, chargé depuis `verticals/retraite/config.yaml`
(bloc `juridique`, cf. `core.config_loader.charger_config`). Il n'est jamais
codé en dur ici : sa valeur juridique reste à confirmer par un avocat (cf.
`statut_validation_avocat` dans la config).
"""

from __future__ import annotations

from typing import TypedDict


class ResultatRappel(TypedDict):
    pension_base_recalculee_mensuelle: float
    majoration_mensuelle: float
    delai_prescription_annees_applique: int
    nombre_mois_plafonne: int
    rappel_estime: float


def calculer_pension_base_mensuelle(
    sam: float,
    taux_pourcentage: float,
    trimestres_valides: int,
    trimestres_requis: int,
) -> float:
    if trimestres_requis <= 0:
        return 0.0
    proratisation = min(trimestres_valides / trimestres_requis, 1.0)
    return round(sam * (taux_pourcentage / 100) * proratisation / 12, 2)


def calculer_rappel(
    sam_recalcule: float,
    taux_pourcentage: float,
    trimestres_valides: int,
    trimestres_requis: int,
    pension_base_notifiee_mensuelle: float,
    delai_prescription_annees: int,
) -> ResultatRappel:
    """Compare la pension de base recalculée à partir du SAM corrigé à la
    pension notifiée, et plafonne le rappel au délai de prescription
    paramétré (jamais au-delà, jamais en dur)."""
    pension_recalculee = calculer_pension_base_mensuelle(
        sam_recalcule, taux_pourcentage, trimestres_valides, trimestres_requis
    )

    majoration_mensuelle = round(pension_recalculee - pension_base_notifiee_mensuelle, 2)
    majoration_mensuelle = max(majoration_mensuelle, 0.0)

    nombre_mois_plafonne = max(delai_prescription_annees, 0) * 12
    rappel_estime = round(majoration_mensuelle * nombre_mois_plafonne, 2)

    return {
        "pension_base_recalculee_mensuelle": pension_recalculee,
        "majoration_mensuelle": majoration_mensuelle,
        "delai_prescription_annees_applique": delai_prescription_annees,
        "nombre_mois_plafonne": nombre_mois_plafonne,
        "rappel_estime": rappel_estime,
    }
