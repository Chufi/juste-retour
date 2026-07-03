"""Modèles Pydantic communs à tous les verticaux.

Les schémas spécifiques à un vertical (structure des données extraites, sortie
du calcul) vivent dans `verticals/<slug>/calc_plugin.py`, pas ici : ce module
ne connaît aucun vertical en particulier.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class Fiabilite(str, Enum):
    HAUTE = "haute"
    MOYENNE = "moyenne"
    BASSE = "basse"


class TypeDocument(str, Enum):
    RELEVE_CARRIERE = "releve_carriere"
    BULLETIN_PAIE = "bulletin_paie"
    NOTIFICATION_PENSION = "notification_pension"
    AUTRE = "autre"


class StatutDossier(str, Enum):
    CREE = "cree"
    DOCUMENTS_RECUS = "documents_recus"
    CHAMPS_MANQUANTS = "champs_manquants"
    ANALYSE_TERMINEE = "analyse_terminee"


class Verdict(str, Enum):
    """Décision du Directeur Juridique (`core/review_agent.py`)."""

    AUTO = "AUTO"
    EXCEPTION = "EXCEPTION"


class ModeVertical(str, Enum):
    """Mode d'envoi (rampe de lancement, régime nominal, kill switch)."""

    SMOKE_TEST = "smoke_test"
    SUPERVISE_LANCEMENT = "supervise_lancement"
    AUTO = "auto"
    SUSPENDU = "suspendu"


class StatutVertical(str, Enum):
    """Cycle de vie du vertical — champ unique `status` de la config.

    - `draft`      : squelette de config, rien de publié, pas de landing
    - `smoke_test` : landing + capture de leads uniquement, pas de pipeline
    - `paused`     : pipeline construit mais gelé (pas de nouveaux dossiers,
                     pas de verdict AUTO, pas d'envoi ; rien n'est supprimé)
    - `active`     : pipeline en service

    Seul `active` peut émettre un verdict AUTO et déclencher un envoi
    (core/review_agent.py + garde d'envoi)."""

    DRAFT = "draft"
    SMOKE_TEST = "smoke_test"
    PAUSED = "paused"
    ACTIVE = "active"


class CanalAcquisition(str, Enum):
    ADS = "ads"
    PARTENAIRE = "partenaire"
    ORGANIQUE = "organique"
    REFERRAL = "referral"


class DocumentInfo(BaseModel):
    fichier: str
    type: TypeDocument
    pages: int
    fiabilite_ocr: Fiabilite


class Acquisition(BaseModel):
    """Attribution du dossier/lead à son canal d'acquisition."""

    canal: CanalAcquisition = CanalAcquisition.ORGANIQUE
    source_id: str = ""  # code partenaire, id de campagne...
    utm: dict = Field(default_factory=dict)


class CreationDossier(BaseModel):
    nom: str
    email: EmailStr
    vertical: str = "depot_garantie"
    acquisition: Acquisition = Field(default_factory=Acquisition)


class DossierOut(BaseModel):
    dossier_id: int
    nom: str
    email: str
    statut: StatutDossier
    cree_le: str
