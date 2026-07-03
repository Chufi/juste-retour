"""Interface d'envoi de courrier recommandé.

Le code métier ne dépend jamais d'un prestataire particulier : il appelle
cette interface. Une implémentation réelle (La Poste/Docaposte-Maileva, AR24...)
peut être branchée derrière un flag sans toucher à `core/` ni à `backend/`.

## Choix du canal (piège juridique à respecter dans toute implémentation)
- `hybride` : dépôt via API, La Poste imprime et distribue en PAPIER. Valeur
  légale d'une LRAR classique, AUCUN consentement du destinataire requis.
  Canal par défaut pour toute administration (Carsat/Cnav, etc.) — la LRE
  électronique est bloquée vers un destinataire administratif sans son
  consentement (art. L.100 CPCE).
- `lre_electronique` : LRE 100% électronique, valeur légale d'une LRAR
  (eIDAS qualifiée). Réservée aux destinataires professionnels ayant
  explicitement consenti (ex. banque, assureur, bailleur pro).
Le canal effectif est toujours lu depuis `verticals/<slug>/config.yaml`
(`canal_envoi`), jamais décidé en dur dans une implémentation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


class ResultatEnvoi(TypedDict):
    id_envoi: str
    canal: str
    statut: str  # depose | distribue | echec
    horodatage: str


class PreuvesEnvoi(TypedDict):
    id_envoi: str
    preuve_depot: str
    preuve_distribution: str | None
    statut: str
    horodatage_maj: str


class EnvoiRecommande(ABC):
    """Interface qu'implémente chaque prestataire d'envoi recommandé."""

    @abstractmethod
    def envoyer(self, dossier: dict[str, Any], canal: str, contenu: str) -> ResultatEnvoi:
        """Dépose le courrier `contenu` pour envoi recommandé au destinataire
        du `dossier`, sur le `canal` demandé (`hybride` | `lre_electronique`)."""

    @abstractmethod
    def recuperer_preuves(self, id_envoi: str) -> PreuvesEnvoi:
        """Récupère les preuves d'envoi (dépôt, distribution, refus, négligence)
        associées à un envoi déjà déposé, pour archivage dans le dossier et le
        journal d'audit."""
