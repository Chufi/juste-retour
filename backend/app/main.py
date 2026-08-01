"""FastAPI — Juste Retour, moteur de réclamation multi-verticaux.

Pipeline par dossier (verticaux `status: active` uniquement) :
documents/déclaration → extraction → calcul déterministe (calc_plugin du
vertical) → scoring de recouvrabilité → verdict AUTO/EXCEPTION (Directeur
Juridique, `core/review_agent.py`) → courrier factuel (gabarit) → envoi
recommandé (interface `core/envoi`, mock tant que pas de compte prestataire).

Les verticaux `smoke_test` n'alimentent que la table des leads (`POST /leads`).
Le calcul n'est JAMAIS délégué au LLM (règle non négociable) ; l'appel LLM
optionnel ne produit que le rapport d'anomalies en langage clair.

Lancement local (depuis la racine du repo) :
    uvicorn backend.app.main:app --reload --port 8000
"""

from __future__ import annotations

import hmac
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Optional

import pdfplumber
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

from core import calc_engine, letter_engine, review_agent
from core.config_loader import lister_verticals
from core.extraction import ocr, tables
from core.outcomes import calculer_score
from core.outcomes.schema import Outcome
from core.schemas import Acquisition, CreationDossier, Fiabilite, StatutDossier, TypeDocument, Verdict

from . import models
from .admin import router as admin_router
from .services import config_ou_404 as _config_ou_404
from .services import dossier_ou_404 as _dossier_ou_404
from .services import executer_envoi as _executer_envoi

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
RACINE_PROJET = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = RACINE_PROJET / "frontend"
LANDING_DIR = RACINE_PROJET / "landing"
ANNEE_RE = re.compile(r"(19|20)\d{2}")

app = FastAPI(title="Juste Retour — API multi-verticaux")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router)


@app.on_event("startup")
def _startup() -> None:
    models.init_db()
    UPLOADS_DIR.mkdir(exist_ok=True)


# ─────────────────────────── Front (app client + landings) ───────────────────────────


@app.get("/", include_in_schema=False)
def racine() -> RedirectResponse:
    return RedirectResponse("/app/")


@app.get("/verticals/{slug}")
def infos_vertical(slug: str) -> dict:
    """Sous-ensemble PUBLIC de la config d'un vertical, consommé par la front
    page client (liste des pièces, mentions). Ne jamais exposer les seuils,
    paramètres juridiques internes ou statuts de validation."""
    config = _config_ou_404(slug)
    _, status_effectif = models.resoudre_mode_et_status(slug, config)
    return {
        "slug": config["slug"],
        "nom_public": config.get("nom_public", ""),
        "status": status_effectif,
        "pieces": config.get("pieces", []),
        "mentions_legales": config.get("mentions_legales", ""),
    }


# ─────────────────────────── Dossiers ───────────────────────────


def _dossier_avec_token(dossier_id: int, x_dossier_token: Optional[str]) -> Any:
    """Vérifie que l'appelant détient le jeton du dossier avant de l'exposer.

    `dossier_id` est un entier séquentiel : sans ce contrôle, n'importe qui
    pourrait énumérer /dossiers/1, /2, ... et lire les données personnelles
    (nom, e-mail, déclaration, pièces) de tous les dossiers. On répond 404
    plutôt que 403 pour ne pas confirmer l'existence du dossier à qui n'a
    pas le jeton."""
    dossier = _dossier_ou_404(dossier_id)
    if not hmac.compare_digest(dossier["token"] or "", x_dossier_token or ""):
        raise HTTPException(404, "Dossier introuvable")
    return dossier


@app.post("/dossiers", status_code=201)
def creer_dossier(payload: CreationDossier) -> dict:
    config = _config_ou_404(payload.vertical)
    _, status_effectif = models.resoudre_mode_et_status(payload.vertical, config)
    if status_effectif != "active":
        raise HTTPException(
            409,
            f"Le vertical '{payload.vertical}' est en status '{status_effectif}' : "
            "aucun nouveau dossier n'est accepté (capture de leads uniquement, POST /leads).",
        )
    dossier_id, token = models.creer_dossier(
        nom=payload.nom,
        email=payload.email,
        vertical_slug=payload.vertical,
        acquisition_canal=payload.acquisition.canal.value,
        acquisition_source_id=payload.acquisition.source_id,
        acquisition_utm=payload.acquisition.utm,
    )
    models.journaliser("systeme", "systeme", "dossier_cree", dossier_id, payload.vertical)
    return {"dossier_id": dossier_id, "token": token}


class Declaration(BaseModel):
    """Faits déclarés par le client (vertical depot_garantie). Les documents
    uploadés servent de pièces justificatives ; le calcul est déterministe
    sur ces faits."""

    champs: dict[str, Any]
    type_debiteur: str = "particulier"  # particulier | pro | administration
    pieces_fournies: list[str] = Field(default_factory=list)


@app.post("/dossiers/{dossier_id}/declaration")
def enregistrer_declaration(
    dossier_id: int, payload: Declaration, x_dossier_token: str = Header(..., alias="X-Dossier-Token")
) -> dict:
    _dossier_avec_token(dossier_id, x_dossier_token)
    models.maj_dossier(
        dossier_id,
        declaration=json.dumps(
            {"champs": payload.champs, "pieces_fournies": payload.pieces_fournies},
            ensure_ascii=False,
        ),
        type_debiteur=payload.type_debiteur,
        statut=StatutDossier.DOCUMENTS_RECUS.value,
    )
    models.journaliser("systeme", "systeme", "declaration_enregistree", dossier_id)
    reponse = {"dossier_id": dossier_id, "declaration": payload.champs}
    analyse = _auto_analyser_si_pret(dossier_id)
    if analyse is not None:
        reponse["analyse_automatique"] = analyse
    return reponse


@app.post("/dossiers/{dossier_id}/mandat")
def enregistrer_mandat(
    dossier_id: int, x_dossier_token: str = Header(..., alias="X-Dossier-Token")
) -> dict:
    """MVP : enregistre la présence d'un mandat signé (l'e-signature réelle
    n'est pas construite ce sprint). Sans mandat, aucun envoi possible."""
    _dossier_avec_token(dossier_id, x_dossier_token)
    models.maj_dossier(dossier_id, mandat_signe=1)
    models.journaliser("systeme", "systeme", "mandat_enregistre", dossier_id)
    reponse = {"dossier_id": dossier_id, "mandat_signe": True}
    analyse = _auto_analyser_si_pret(dossier_id)
    if analyse is not None:
        reponse["analyse_automatique"] = analyse
    return reponse


# ─────────────────────────── Documents & extraction ───────────────────────────


def _fiabilite_ocr(texte: str) -> Fiabilite:
    longueur = len(texte.strip())
    if longueur < 20:
        return Fiabilite.BASSE
    if longueur < 200:
        return Fiabilite.MOYENNE
    return Fiabilite.HAUTE


def _traiter_releve_carriere(path: Path, dossier_id: int) -> list[str]:
    champs_illisibles = []
    for ligne in tables.extraire_lignes_carriere(path):
        fiabilite = Fiabilite.HAUTE if ligne["lisible"] else Fiabilite.BASSE
        if not ligne["lisible"]:
            champs_illisibles.append(f"salaire_reporte {ligne['annee']}")
        models.ajouter_annee_carriere(
            dossier_id=dossier_id,
            annee=ligne["annee"],
            salaire_reporte=ligne["salaire_reporte"],
            trimestres=ligne["trimestres"],
            origine="carriere",
            source=f"relevé de carrière — année {ligne['annee']}",
            fiabilite=fiabilite,
        )
    return champs_illisibles


def _traiter_bulletin(path: Path, filename: str, dossier_id: int) -> list[str]:
    if not ocr.outils_disponibles():
        return [f"salaire_brut {filename} (OCR indisponible)"]

    texte = ocr.ocr_pdf_scanne(path) if path.suffix.lower() == ".pdf" else ocr.ocr_image(path)
    annee_match = ANNEE_RE.search(filename)
    annee = int(annee_match.group()) if annee_match else None
    montant_mensuel = ocr.extraire_salaire_brut_mensuel(texte) if texte else None

    champs_illisibles: list[str] = []
    if annee is None:
        return [f"annee_bulletin {filename}"]
    if montant_mensuel is None:
        champs_illisibles.append(f"salaire_brut {filename}")

    models.ajouter_annee_carriere(
        dossier_id=dossier_id,
        annee=annee,
        salaire_reporte=montant_mensuel * 12 if montant_mensuel else None,
        trimestres=4,
        origine="bulletin",
        source=f"bulletin de paie — {filename}",
        fiabilite=_fiabilite_ocr(texte),
    )
    return champs_illisibles


@app.post("/dossiers/{dossier_id}/documents")
def uploader_documents(
    dossier_id: int,
    fichiers: list[UploadFile] = File(...),
    x_dossier_token: str = Header(..., alias="X-Dossier-Token"),
) -> dict:
    dossier = _dossier_avec_token(dossier_id, x_dossier_token)
    slug = dossier["vertical_slug"]

    dossier_uploads = UPLOADS_DIR / str(dossier_id)
    dossier_uploads.mkdir(parents=True, exist_ok=True)

    champs_illisibles: list[str] = []
    documents_traites: list[dict] = []

    for fichier in fichiers:
        # `.name` élimine tout séparateur de chemin ("/", "..") ainsi que les
        # chemins absolus fournis par le client — sans ça, un nom de fichier
        # tel que "../../frontend/index.html" écrirait hors de uploads/.
        nom_fichier = Path(fichier.filename or "").name
        if not nom_fichier or nom_fichier in (".", ".."):
            raise HTTPException(400, "Nom de fichier invalide.")
        chemin = dossier_uploads / nom_fichier
        with chemin.open("wb") as f:
            shutil.copyfileobj(fichier.file, f)

        est_pdf_texte = chemin.suffix.lower() == ".pdf" and not ocr.est_pdf_scanne(chemin)

        if slug == "pension_cnav":
            if est_pdf_texte:
                type_document, fiabilite = TypeDocument.RELEVE_CARRIERE, Fiabilite.HAUTE
                champs_illisibles += _traiter_releve_carriere(chemin, dossier_id)
            else:
                type_document, fiabilite = TypeDocument.BULLETIN_PAIE, Fiabilite.MOYENNE
                champs_illisibles += _traiter_bulletin(chemin, nom_fichier, dossier_id)
        else:
            # Verticaux déclaratifs (depot_garantie) : les pièces sont
            # archivées comme justificatifs ; le calcul se fait sur la
            # déclaration structurée (POST /dossiers/{id}/declaration).
            type_document = TypeDocument.AUTRE
            fiabilite = Fiabilite.HAUTE if est_pdf_texte else Fiabilite.MOYENNE

        pages = 1
        if chemin.suffix.lower() == ".pdf":
            with pdfplumber.open(chemin) as pdf:
                pages = len(pdf.pages)

        doc_id = models.ajouter_document(
            dossier_id, nom_fichier, type_document, pages, fiabilite, str(chemin)
        )
        documents_traites.append(
            {"document_id": doc_id, "fichier": nom_fichier, "type": type_document.value}
        )

    statut = StatutDossier.CHAMPS_MANQUANTS if champs_illisibles else StatutDossier.DOCUMENTS_RECUS
    models.maj_dossier(dossier_id, statut=statut.value)
    models.journaliser(
        "systeme", "systeme", "documents_recus", dossier_id, slug,
        {"nb": len(documents_traites), "champs_illisibles": champs_illisibles},
    )

    reponse = {"documents": documents_traites, "champs_illisibles_ou_manquants": champs_illisibles}
    if not champs_illisibles:
        analyse = _auto_analyser_si_pret(dossier_id)
        if analyse is not None:
            reponse["analyse_automatique"] = analyse
    return reponse


# ─────────────────────────── Analyse (calcul + verdict + courrier) ───────────────────────────


def _donnees_pour_calcul(dossier, slug: str) -> dict[str, Any]:
    if slug == "pension_cnav":
        annees = [
            {
                "annee": row["annee"],
                "salaire_reporte": row["salaire_reporte"],
                "trimestres": row["trimestres"],
            }
            for row in models.get_annees_carriere(dossier["id"])
        ]
        return {"annees_carriere": annees, "pension_notifiee": {}}

    declaration_brute = json.loads(dossier["declaration"] or "{}")
    return {
        "declaration": declaration_brute.get("champs", {}),
        "pieces_fournies": declaration_brute.get("pieces_fournies", []),
    }


def _rapport_llm_si_disponible(slug: str, donnees: dict[str, Any]) -> Optional[str]:
    """Rapport qualitatif optionnel : uniquement si le vertical fournit un
    prompt d'analyse ET qu'une clé API est configurée. Jamais bloquant."""
    from core.config_loader import repertoire_vertical

    if not (repertoire_vertical(slug) / "prompt_analyse.md").exists():
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    from core import llm_client

    try:
        return llm_client.analyser_dossier(slug, donnees)
    except Exception:  # l'analyse LLM ne doit jamais faire échouer le pipeline
        return None


def _executer_analyse(dossier_id: int) -> dict:
    """Cœur du pipeline : calcul déterministe → scoring → verdict → courrier,
    et envoi immédiat sur verdict AUTO. Appelé automatiquement dès que le
    dossier est complet (_auto_analyser_si_pret) ou explicitement via
    POST /dossiers/{id}/analyser."""
    dossier = _dossier_ou_404(dossier_id)
    slug = dossier["vertical_slug"]
    config = _config_ou_404(slug)

    donnees = _donnees_pour_calcul(dossier, slug)

    try:
        resultat = calc_engine.calculer(slug, donnees)
    except calc_engine.VerticalSansPipeline as exc:
        raise HTTPException(409, str(exc))

    if resultat["champs_manquants"]:
        models.maj_dossier(dossier_id, statut=StatutDossier.CHAMPS_MANQUANTS.value)
        raise HTTPException(
            409,
            detail={
                "message": "Champs illisibles ou manquants : impossible de lancer l'analyse.",
                "champs": resultat["champs_manquants"],
            },
        )

    # Filtre économique : scoring de recouvrabilité sur l'historique du vertical.
    type_debiteur = dossier["type_debiteur"] or (
        "administration" if slug == "pension_cnav" else "particulier"
    )
    score = calculer_score(type_debiteur, models.lister_outcomes(slug))

    documents = models.get_documents(dossier_id)
    fiabilite_toutes_hautes = bool(documents) and all(
        d["fiabilite_ocr"] == Fiabilite.HAUTE.value for d in documents
    )

    mode_effectif, status_effectif = models.resoudre_mode_et_status(slug, config)
    verdict = review_agent.evaluer(
        config=config,
        resultat_calcul=resultat,
        fiabilite_ocr_toutes_hautes=fiabilite_toutes_hautes,
        mandat_signe=bool(dossier["mandat_signe"]),
        mode_effectif=mode_effectif,
        status_effectif=status_effectif,
        score_recouvrabilite=score,
    )

    contexte_courrier = {
        "nom": dossier["nom"],
        "montant_estime": resultat["montant_estime"],
        "anomalies": resultat["anomalies"],
        "details": resultat["details"],
        "declaration": donnees.get("declaration", {}),
        "pieces": config.get("pieces", []),
        "base_legale": config.get("juridique", {}).get("base_legale") or "",
        "voie_recours": config.get("juridique", {}).get("voie_recours") or "",
    }
    courrier = letter_engine.generer_courrier(slug, contexte_courrier)

    rapport = _rapport_llm_si_disponible(slug, {**donnees, "calcul_moteur": resultat})

    models.maj_dossier(
        dossier_id,
        statut=StatutDossier.ANALYSE_TERMINEE.value,
        verdict=verdict["decision"],
        motifs_exception=verdict["motifs"],
        confiance=resultat["confiance"],
        montant_estime=resultat["montant_estime"],
        score_recouvrabilite=score["probabilite"],
        score_version=score["version"],
        regles_version=verdict["regles_version"],
        projet_courrier=courrier,
        rapport_anomalies=rapport or json.dumps(resultat["anomalies"], ensure_ascii=False),
    )
    models.journaliser(
        "systeme", "systeme", "verdict_rendu", dossier_id, slug,
        {
            "verdict": verdict["decision"],
            "motifs": verdict["motifs"],
            "regles_version": verdict["regles_version"],
            "scoring_version": score["version"],
            "scoring_base": score["base"],
        },
    )

    reponse: dict[str, Any] = {
        "calcul_moteur": resultat,
        "score_recouvrabilite": score,
        "verdict": verdict,
        "projet_courrier": courrier,
    }
    if rapport:
        reponse["rapport_anomalies"] = rapport

    # Envoi automatique : uniquement sur verdict AUTO (le review_agent a déjà
    # vérifié status/mode/mandat/validation avocat — défense en profondeur ici).
    if (
        verdict["decision"] == Verdict.AUTO.value
        and status_effectif == "active"
        and not dossier["id_envoi"]
    ):
        reponse["envoi"] = _executer_envoi(dossier_id, "systeme", "systeme")

    return reponse


def _auto_analyser_si_pret(dossier_id: int) -> Optional[dict]:
    """Automatisation par défaut : dès que le dossier est complet
    (déclaration/données + pièces + mandat), l'analyse se lance seule et,
    sur verdict AUTO, le courrier part seul. Un dossier incomplet reste
    simplement en attente — jamais d'erreur remontée à l'ingestion."""
    dossier = models.get_dossier(dossier_id)
    if dossier is None or dossier["id_envoi"]:
        return None
    slug = dossier["vertical_slug"]
    config = _config_ou_404(slug)
    _, status_effectif = models.resoudre_mode_et_status(slug, config)
    if status_effectif != "active":
        return None

    if not dossier["mandat_signe"] or not models.get_documents(dossier_id):
        return None
    if slug == "pension_cnav":
        if not models.get_annees_carriere(dossier_id):
            return None
    elif not dossier["declaration"]:
        return None

    try:
        return _executer_analyse(dossier_id)
    except HTTPException:
        # Champs manquants/illisibles : le statut du dossier est déjà passé à
        # champs_manquants ; l'ingestion suivante retentera l'analyse.
        return None


@app.post("/dossiers/{dossier_id}/analyser")
def analyser(dossier_id: int, x_dossier_token: str = Header(..., alias="X-Dossier-Token")) -> dict:
    """Relance explicite de l'analyse (l'analyse se déclenche normalement
    toute seule dès que le dossier est complet)."""
    _dossier_avec_token(dossier_id, x_dossier_token)
    return _executer_analyse(dossier_id)


@app.post("/dossiers/{dossier_id}/envoyer")
def envoyer(dossier_id: int, x_dossier_token: str = Header(..., alias="X-Dossier-Token")) -> dict:
    """Déclenchement système de l'envoi — réservé aux dossiers en verdict AUTO.
    Un dossier EXCEPTION ne part que via le back-office (revue humaine)."""
    dossier = _dossier_avec_token(dossier_id, x_dossier_token)
    if dossier["verdict"] != Verdict.AUTO.value:
        raise HTTPException(
            409,
            "Envoi automatique refusé : verdict non AUTO. Passez par la file "
            "d'exceptions du back-office (POST /admin/dossiers/{id}/traiter).",
        )
    return _executer_envoi(dossier_id, "systeme", "systeme")


@app.get("/dossiers/{dossier_id}")
def get_dossier(dossier_id: int, x_dossier_token: str = Header(..., alias="X-Dossier-Token")) -> dict:
    dossier = _dossier_avec_token(dossier_id, x_dossier_token)
    outcome = models.get_outcome(dossier_id)
    return {
        **{k: dossier[k] for k in dossier.keys() if k != "token"},
        "documents": [dict(d) for d in models.get_documents(dossier_id)],
        "annees_carriere": [dict(a) for a in models.get_annees_carriere(dossier_id)],
        "outcome": dict(outcome) if outcome else None,
    }


# ─────────────────────────── Outcomes (boucle de résultats) ───────────────────────────


class MajOutcome(BaseModel):
    statut: str
    montant_recouvre: Optional[float] = None
    delai_reponse_jours: Optional[int] = None
    delai_paiement_jours: Optional[int] = None
    canal_resolution: str = "courrier_seul"
    timestamps: dict = Field(default_factory=dict)


@app.post("/dossiers/{dossier_id}/outcome")
def maj_outcome(
    dossier_id: int, payload: MajOutcome, x_dossier_token: str = Header(..., alias="X-Dossier-Token")
) -> dict:
    dossier = _dossier_avec_token(dossier_id, x_dossier_token)
    # Validation du contrat via le schéma core (statuts, canaux d'issue).
    try:
        Outcome(
            dossier_id=str(dossier_id),
            vertical=dossier["vertical_slug"],
            verdict_initial=dossier["verdict"] or "EXCEPTION",
            montant_reclame=dossier["montant_estime"] or 0.0,
            montant_recouvre=payload.montant_recouvre,
            statut=payload.statut,
            delai_reponse_jours=payload.delai_reponse_jours,
            delai_paiement_jours=payload.delai_paiement_jours,
            profil_debiteur={"type": dossier["type_debiteur"] or "particulier"},
            canal_resolution=payload.canal_resolution,
            timestamps=payload.timestamps,
        )
    except ValueError as exc:
        raise HTTPException(422, f"Outcome invalide : {exc}")
    models.upsert_outcome(
        dossier_id,
        {
            "vertical_slug": dossier["vertical_slug"],
            "verdict_initial": dossier["verdict"] or "EXCEPTION",
            "montant_reclame": dossier["montant_estime"] or 0.0,
            "montant_recouvre": payload.montant_recouvre,
            "statut": payload.statut,
            "delai_reponse_jours": payload.delai_reponse_jours,
            "delai_paiement_jours": payload.delai_paiement_jours,
            "profil_debiteur_type": dossier["type_debiteur"] or "particulier",
            "canal_resolution": payload.canal_resolution,
            "timestamps": payload.timestamps,
        },
    )
    models.journaliser(
        "systeme", "systeme", "outcome_maj", dossier_id, dossier["vertical_slug"],
        {"statut": payload.statut, "montant_recouvre": payload.montant_recouvre},
    )
    return {"dossier_id": dossier_id, "statut": payload.statut}


# ─────────────────────────── Leads & analytics (smoke tests) ───────────────────────────


class CreationLead(BaseModel):
    nom: str
    email: EmailStr
    vertical: str
    acquisition: Acquisition = Field(default_factory=Acquisition)
    pieces_declarees: list[str] = Field(default_factory=list)


@app.post("/leads", status_code=201)
def creer_lead(payload: CreationLead) -> dict:
    _config_ou_404(payload.vertical)
    lead_id = models.creer_lead(
        vertical_slug=payload.vertical,
        nom=payload.nom,
        email=payload.email,
        acquisition_canal=payload.acquisition.canal.value,
        acquisition_source_id=payload.acquisition.source_id,
        acquisition_utm=payload.acquisition.utm,
        pieces_declarees=payload.pieces_declarees,
    )
    models.enregistrer_evenement(
        "soumission", payload.vertical, payload.acquisition.source_id, payload.acquisition.utm
    )
    return {"lead_id": lead_id}


class Evenement(BaseModel):
    type: str  # visite | clic
    vertical: str
    source_id: str = ""
    utm: dict = Field(default_factory=dict)


@app.post("/evenements", status_code=201)
def enregistrer_evenement(payload: Evenement) -> dict:
    if payload.type not in ("visite", "clic"):
        raise HTTPException(422, "type doit être 'visite' ou 'clic'")
    _config_ou_404(payload.vertical)
    models.enregistrer_evenement(payload.type, payload.vertical, payload.source_id, payload.utm)
    return {"ok": True}


@app.get("/leads/stats")
def leads_stats() -> dict:
    return {"stats": models.stats_leads(), "verticals": lister_verticals()}


# ─────────────────────────── Fichiers statiques ───────────────────────────
# Montés en dernier : les routes API déclarées ci-dessus restent prioritaires.
# /app     → front page client (parcours de dossier, frontend/index.html)
# /landing → landing pages générées par landing/build.py

if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="app")
if LANDING_DIR.exists():
    app.mount("/landing", StaticFiles(directory=LANDING_DIR, html=True), name="landing")
