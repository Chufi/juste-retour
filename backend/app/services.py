"""Services partagés entre l'API publique (`main.py`) et le back-office
(`admin.py`) — principalement l'exécution de l'envoi recommandé, dernière
étape du pipeline."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from core.config_loader import VerticalInconnu, charger_config
from core.envoi import determiner_canal, obtenir_prestataire

from . import models


def config_ou_404(slug: str) -> dict[str, Any]:
    try:
        return charger_config(slug)
    except VerticalInconnu:
        raise HTTPException(404, f"Vertical inconnu : {slug}")


def dossier_ou_404(dossier_id: int):
    dossier = models.get_dossier(dossier_id)
    if dossier is None:
        raise HTTPException(404, "Dossier introuvable")
    return dossier


def executer_envoi(dossier_id: int, acteur: str, role: str) -> dict:
    """Dépose le courrier en recommandé via le prestataire configuré.

    Appelée automatiquement sur verdict AUTO, ou par un humain habilité
    depuis la file d'exceptions du back-office. Dans les deux cas, un
    vertical non `active` ne peut JAMAIS émettre d'envoi (v3), et le mandat
    signé est requis.
    """
    dossier = dossier_ou_404(dossier_id)
    slug = dossier["vertical_slug"]
    config = config_ou_404(slug)

    _, status_effectif = models.resoudre_mode_et_status(slug, config)
    if status_effectif != "active":
        raise HTTPException(
            409, f"Vertical '{slug}' en status '{status_effectif}' : envoi interdit."
        )
    if not dossier["mandat_signe"]:
        raise HTTPException(409, "Mandat signé absent : envoi impossible.")
    if not dossier["projet_courrier"]:
        raise HTTPException(409, "Aucun courrier généré pour ce dossier.")
    if dossier["id_envoi"]:
        raise HTTPException(409, f"Courrier déjà envoyé (id {dossier['id_envoi']}).")

    canal = determiner_canal(config)
    prestataire = obtenir_prestataire(config)
    resultat_envoi = prestataire.envoyer(
        {"dossier_id": dossier_id, "nom": dossier["nom"]}, canal, dossier["projet_courrier"]
    )
    preuves = prestataire.recuperer_preuves(resultat_envoi["id_envoi"])

    models.maj_dossier(
        dossier_id,
        id_envoi=resultat_envoi["id_envoi"],
        canal_envoi=canal,
        statut_envoi=resultat_envoi["statut"],
        preuves_envoi=dict(preuves),
    )
    models.upsert_outcome(
        dossier_id,
        {
            "vertical_slug": slug,
            "verdict_initial": dossier["verdict"] or "",
            "montant_reclame": dossier["montant_estime"] or 0.0,
            "statut": "envoye",
            "profil_debiteur_type": dossier["type_debiteur"] or "particulier",
            "timestamps": {"envoye_le": resultat_envoi["horodatage"]},
        },
    )
    models.journaliser(
        acteur, role, "courrier_envoye", dossier_id, slug,
        {"id_envoi": resultat_envoi["id_envoi"], "canal": canal},
    )
    return {"id_envoi": resultat_envoi["id_envoi"], "canal": canal, "preuves": preuves}
