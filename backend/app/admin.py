"""Back-office de supervision par exception.

L'humain OBSERVE le flux ; il n'intervient que sur la file d'exceptions
(et la file d'escalade avocat). Les envois AUTO sont journalisés au même
titre que les actions humaines.

RBAC (MVP) : rôle porté par le header `X-Role`, identité par `X-Acteur`.
C'est un STUB à remplacer par une vraie authentification avant toute mise
en production — le contrôle d'accès par rôle et le moindre privilège sont
en place, seul le mécanisme d'identification est simulé. Tant qu'aucune
authentification réelle n'existe, quiconque atteint l'API peut s'auto-
déclarer `X-Role: admin` ; définir `ADMIN_API_TOKEN` (variable d'env.) exige
en plus un jeton partagé (`X-Admin-Token`) pour toute route `/admin/*`,
ce qui ferme l'accès à un attaquant qui n'aurait que le rôle en clair.
Ne remplace pas une vraie authentification (jeton unique, pas par acteur).

Rôles : operateur < juridique < dpo / admin (moindre privilège par endpoint).
"""

from __future__ import annotations

import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from core.schemas import ModeVertical, StatutVertical, Verdict

from . import models
from .services import config_ou_404, dossier_ou_404, executer_envoi

router = APIRouter(prefix="/admin", tags=["back-office"])

ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN")

ROLES_VALIDES = {"operateur", "juridique", "dpo", "admin"}

# Durée de conservation MVP pour la vue conformité (registre des traitements
# à compléter ; valeur opérationnelle, pas juridique).
DUREE_CONSERVATION_JOURS = 730


class Habilitation(BaseModel):
    acteur: str
    role: str


def _identite(
    x_role: str = Header(..., alias="X-Role"),
    x_acteur: str = Header("inconnu", alias="X-Acteur"),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> Habilitation:
    if ADMIN_API_TOKEN and not (x_admin_token and hmac.compare_digest(x_admin_token, ADMIN_API_TOKEN)):
        raise HTTPException(403, "Jeton d'administration manquant ou invalide.")
    if x_role not in ROLES_VALIDES:
        raise HTTPException(403, f"Rôle inconnu : {x_role}")
    return Habilitation(acteur=x_acteur, role=x_role)


def _exiger(habilitation: Habilitation, *roles_autorises: str) -> None:
    if habilitation.role not in roles_autorises:
        raise HTTPException(
            403, f"Rôle '{habilitation.role}' non habilité (requis : {', '.join(roles_autorises)})"
        )


# ─────────────────────────── Vue flux ───────────────────────────


@router.get("/flux")
def vue_flux(habilitation: Habilitation = Depends(_identite)) -> dict:
    """Tous les dossiers et leur état — observation seule, rien à valider."""
    _exiger(habilitation, "operateur", "juridique", "dpo", "admin")
    dossiers = models.lister_dossiers()
    return {
        "dossiers": [
            {
                "dossier_id": d["id"],
                "vertical": d["vertical_slug"],
                "statut": d["statut"],
                "verdict": d["verdict"],
                "montant_estime": d["montant_estime"],
                "statut_envoi": d["statut_envoi"],
                "escalade_avocat": bool(d["escalade_avocat"]),
                "traite_par": d["traite_par"],
            }
            for d in dossiers
        ]
    }


# ─────────────────────────── File d'exceptions ───────────────────────────


@router.get("/exceptions")
def file_exceptions(habilitation: Habilitation = Depends(_identite)) -> dict:
    """Uniquement les dossiers EXCEPTION non traités, avec le motif du flag,
    les anomalies, le calcul et le projet de courrier."""
    _exiger(habilitation, "operateur", "juridique", "admin")
    dossiers = models.lister_dossiers(verdict=Verdict.EXCEPTION.value)
    return {
        "exceptions": [
            {
                "dossier_id": d["id"],
                "vertical": d["vertical_slug"],
                "motifs": json.loads(d["motifs_exception"] or "[]"),
                "rapport_anomalies": d["rapport_anomalies"],
                "montant_estime": d["montant_estime"],
                "confiance": d["confiance"],
                "score_recouvrabilite": d["score_recouvrabilite"],
                "projet_courrier": d["projet_courrier"],
                "escalade_avocat": bool(d["escalade_avocat"]),
            }
            for d in dossiers
            if d["traite_par"] is None and d["statut_envoi"] is None
        ]
    }


class Traitement(BaseModel):
    action: str  # approuver_envoi | corriger | rejeter
    commentaire: str = ""
    courrier_corrige: Optional[str] = None


@router.post("/dossiers/{dossier_id}/traiter")
def traiter_exception(
    dossier_id: int, payload: Traitement, habilitation: Habilitation = Depends(_identite)
) -> dict:
    """Traitement humain d'un dossier EXCEPTION : la SEULE porte de sortie
    d'une exception. Un dossier verrouillé en escalade avocat n'est pas
    traitable tant que l'escalade n'est pas levée par un rôle juridique."""
    _exiger(habilitation, "operateur", "juridique", "admin")
    dossier = dossier_ou_404(dossier_id)

    if dossier["escalade_avocat"] and habilitation.role == "operateur":
        raise HTTPException(
            423, "Dossier verrouillé en escalade avocat : traitement réservé au rôle juridique."
        )

    if payload.action == "corriger":
        if not payload.courrier_corrige:
            raise HTTPException(422, "courrier_corrige requis pour l'action 'corriger'")
        models.maj_dossier(dossier_id, projet_courrier=payload.courrier_corrige)
        resultat: dict = {"action": "corrige"}
    elif payload.action == "approuver_envoi":
        resultat = {"action": "envoye", "envoi": executer_envoi(dossier_id, habilitation.acteur, habilitation.role)}
    elif payload.action == "rejeter":
        models.upsert_outcome(
            dossier_id,
            {
                "vertical_slug": dossier["vertical_slug"],
                "verdict_initial": dossier["verdict"] or "EXCEPTION",
                "montant_reclame": dossier["montant_estime"] or 0.0,
                "statut": "abandonne",
                "profil_debiteur_type": dossier["type_debiteur"] or "particulier",
                "timestamps": {},
            },
        )
        resultat = {"action": "rejete"}
    else:
        raise HTTPException(422, "action doit être approuver_envoi, corriger ou rejeter")

    if payload.action != "corriger":
        models.maj_dossier(dossier_id, traite_par=habilitation.acteur)
    models.journaliser(
        habilitation.acteur, habilitation.role, f"exception_{payload.action}",
        dossier_id, dossier["vertical_slug"], {"commentaire": payload.commentaire},
    )
    return {"dossier_id": dossier_id, **resultat}


# ─────────────────────────── Escalade avocat ───────────────────────────


@router.post("/dossiers/{dossier_id}/escalader")
def escalader(dossier_id: int, habilitation: Habilitation = Depends(_identite)) -> dict:
    _exiger(habilitation, "operateur", "juridique", "admin")
    dossier = dossier_ou_404(dossier_id)
    models.maj_dossier(dossier_id, escalade_avocat=1)
    models.journaliser(
        habilitation.acteur, habilitation.role, "escalade_avocat", dossier_id, dossier["vertical_slug"]
    )
    return {"dossier_id": dossier_id, "escalade_avocat": True}


@router.post("/dossiers/{dossier_id}/lever-escalade")
def lever_escalade(dossier_id: int, habilitation: Habilitation = Depends(_identite)) -> dict:
    _exiger(habilitation, "juridique", "admin")
    dossier = dossier_ou_404(dossier_id)
    models.maj_dossier(dossier_id, escalade_avocat=0)
    models.journaliser(
        habilitation.acteur, habilitation.role, "escalade_levee", dossier_id, dossier["vertical_slug"]
    )
    return {"dossier_id": dossier_id, "escalade_avocat": False}


# ─────────────────────────── Kill switch par vertical ───────────────────────────


class ChangementEtat(BaseModel):
    mode: Optional[str] = None    # smoke_test | supervise_lancement | auto | suspendu
    status: Optional[str] = None  # active | paused | draft


@router.post("/verticals/{slug}/mode")
def changer_mode_vertical(
    slug: str, payload: ChangementEtat, habilitation: Habilitation = Depends(_identite)
) -> dict:
    """Kill switch : repasser un vertical en supervise_lancement/suspendu (ou
    le mettre en pause) en un appel. Bascule vers `auto` = décision explicite
    tracée dans l'audit."""
    _exiger(habilitation, "admin")
    config = config_ou_404(slug)

    if payload.mode is not None and payload.mode not in {m.value for m in ModeVertical}:
        raise HTTPException(422, f"mode invalide : {payload.mode}")
    if payload.status is not None and payload.status not in {s.value for s in StatutVertical}:
        raise HTTPException(422, f"status invalide : {payload.status}")
    if payload.mode is None and payload.status is None:
        raise HTTPException(422, "mode ou status requis")

    etat_precedent = models.resoudre_mode_et_status(slug, config)
    models.set_etat_vertical(slug, payload.mode, payload.status, habilitation.acteur)
    mode_effectif, status_effectif = models.resoudre_mode_et_status(slug, config)

    models.journaliser(
        habilitation.acteur, habilitation.role, "vertical_mode_change", None, slug,
        {
            "avant": {"mode": etat_precedent[0], "status": etat_precedent[1]},
            "apres": {"mode": mode_effectif, "status": status_effectif},
        },
    )
    return {"slug": slug, "mode": mode_effectif, "status": status_effectif}


# ─────────────────────────── Audit & conformité ───────────────────────────


@router.get("/audit")
def journal_audit(habilitation: Habilitation = Depends(_identite), limite: int = 200) -> dict:
    _exiger(habilitation, "juridique", "dpo", "admin")
    return {"audit": [dict(r) for r in models.lire_audit(limite)]}


@router.get("/conformite")
def vue_conformite(habilitation: Habilitation = Depends(_identite)) -> dict:
    """Vue DPO : dossiers ayant atteint la durée de conservation (à purger),
    incidents (placeholder MVP)."""
    _exiger(habilitation, "dpo", "admin")
    seuil = datetime.now(timezone.utc) - timedelta(days=DUREE_CONSERVATION_JOURS)
    a_purger = [
        {"dossier_id": d["id"], "vertical": d["vertical_slug"], "cree_le": d["cree_le"]}
        for d in models.lister_dossiers()
        if datetime.fromisoformat(d["cree_le"]) < seuil
    ]
    return {
        "duree_conservation_jours": DUREE_CONSERVATION_JOURS,
        "dossiers_a_purger": a_purger,
        "incidents": [],
    }


# ─────────────────────────── Partenaires (attribution) ───────────────────────────


class CreationPartenaire(BaseModel):
    code: str
    nom: str
    type: str = "autre"  # adil | association | agence | autre


@router.post("/partenaires", status_code=201)
def creer_partenaire(
    payload: CreationPartenaire, habilitation: Habilitation = Depends(_identite)
) -> dict:
    _exiger(habilitation, "admin")
    if models.get_partenaire(payload.code):
        raise HTTPException(409, f"Code partenaire déjà existant : {payload.code}")
    models.creer_partenaire(payload.code, payload.nom, payload.type)
    models.journaliser(
        habilitation.acteur, habilitation.role, "partenaire_cree", None, None,
        {"code": payload.code, "nom": payload.nom},
    )
    return {"code": payload.code, "lien": f"?ref={payload.code}"}


@router.get("/partenaires/{code}/rapport")
def rapport_partenaire(code: str, habilitation: Habilitation = Depends(_identite)) -> dict:
    _exiger(habilitation, "operateur", "juridique", "admin")
    if not models.get_partenaire(code):
        raise HTTPException(404, f"Partenaire inconnu : {code}")
    return models.rapport_partenaire(code)
