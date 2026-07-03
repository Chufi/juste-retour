"""Enregistrement d'issue structuré produit par chaque dossier.

C'est la matière première de la boucle de résultats : les outcomes
historiques alimentent le scoring de recouvrabilité (`scoring.py`) qui, à
son tour, filtre l'admission des nouveaux dossiers (double filtre juridique
+ économique dans `core/review_agent.py`).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class StatutOutcome(str, Enum):
    ENVOYE = "envoye"
    REPONSE_RECUE = "reponse_recue"
    PAYE_TOTAL = "paye_total"
    PAYE_PARTIEL = "paye_partiel"
    REFUS = "refus"
    SANS_REPONSE = "sans_reponse"
    ESCALADE = "escalade"
    ABANDONNE = "abandonne"


# Statuts terminaux : seuls ceux-ci nourrissent le calcul empirique du taux
# de recouvrement (un dossier "envoye" n'a pas encore d'issue).
STATUTS_TERMINAUX = {
    StatutOutcome.PAYE_TOTAL,
    StatutOutcome.PAYE_PARTIEL,
    StatutOutcome.REFUS,
    StatutOutcome.SANS_REPONSE,
    StatutOutcome.ABANDONNE,
}

STATUTS_RECOUVRES = {StatutOutcome.PAYE_TOTAL, StatutOutcome.PAYE_PARTIEL}


class TypeDebiteur(str, Enum):
    PARTICULIER = "particulier"
    PRO = "pro"
    ADMINISTRATION = "administration"


class CanalResolution(str, Enum):
    COURRIER_SEUL = "courrier_seul"
    RELANCE = "relance"
    MISE_EN_DEMEURE = "mise_en_demeure"
    ESCALADE_EXTERNE = "escalade_externe"


class ProfilDebiteur(BaseModel):
    type: TypeDebiteur
    features: dict = Field(default_factory=dict)


class Outcome(BaseModel):
    dossier_id: str
    vertical: str
    verdict_initial: str  # AUTO | EXCEPTION
    montant_reclame: float
    montant_recouvre: Optional[float] = None
    statut: StatutOutcome
    delai_reponse_jours: Optional[int] = None
    delai_paiement_jours: Optional[int] = None
    profil_debiteur: ProfilDebiteur
    canal_resolution: CanalResolution = CanalResolution.COURRIER_SEUL
    timestamps: dict = Field(default_factory=dict)
