"""Directeur Juridique — filtre de risque déterministe AUTO / EXCEPTION.

Ce n'est PAS un agent LLM : la décision d'envoi automatique doit rester
vérifiable et rejouable, donc entièrement basée sur des règles explicites et
la config du vertical (cf. "barre de vérifiabilité" du brief). Toute
condition non remplie fait basculer le dossier en `EXCEPTION` avec un motif
journalisé — jamais un envoi silencieux, jamais un rejet silencieux.

L'éligibilité est un DOUBLE filtre :
- **juridique** : validation avocat du vertical, régime de recouvrement,
  fiabilité OCR, champs manquants, confiance, plafond, mandat signé ;
- **économique** : score de recouvrabilité (`core/outcomes/scoring.py`)
  >= seuil `recouvrabilite_min` du vertical. Un dossier juridiquement valide
  mais économiquement mauvais part en EXCEPTION avec le motif
  `low_recoverability` — il reste visible dans la file d'exceptions.

Philosophie : AUTOMATISATION PAR DÉFAUT. La vérification humaine se fait
UNE FOIS, à l'admission du vertical (validation avocat + sourçage des
paramètres) ; ensuite les dossiers auto-procèdent et auto-partent. Ce filtre
ne route en EXCEPTION que les blocages réels : vertical non validé, données
illisibles/manquantes, litige (confiance basse), montant hors plafond,
mauvais score économique, mandat absent.

Cycle de vie du vertical (`status`, champ unique) : seul `active` peut
recevoir un verdict AUTO — `paused`, `smoke_test` et `draft` jamais (et
l'envoi est bloqué en aval par le même champ).

Chaque verdict emporte la version des règles (`REGLES_VERSION`) et du
scoring utilisées, journalisées dans l'audit pour rejouabilité.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict

from core.schemas import Verdict

REGLES_VERSION = "regles-v3.1"

MOTIF_LOW_RECOVERABILITY = "low_recoverability"


class ResultatVerdict(TypedDict):
    decision: str  # Verdict.AUTO ou Verdict.EXCEPTION
    motifs: list[str]
    regles_version: str
    scoring_version: Optional[str]


def evaluer(
    *,
    config: dict[str, Any],
    resultat_calcul: dict[str, Any],
    fiabilite_ocr_toutes_hautes: bool,
    mandat_signe: bool,
    mode_effectif: str,
    status_effectif: str = "active",
    score_recouvrabilite: Optional[dict[str, Any]] = None,
) -> ResultatVerdict:
    motifs: list[str] = []

    juridique = config.get("juridique", {})
    seuils = config.get("seuils_auto") or {}
    regime_recouvrement = config.get("regime_recouvrement")

    # --- Cycle de vie du vertical (prime sur tout le reste) ---------------
    if status_effectif != "active":
        motifs.append(
            f"vertical en status '{status_effectif}' : verdict AUTO et envoi interdits"
        )

    if mode_effectif != "auto":
        motifs.append(f"mode vertical = '{mode_effectif}' (revue humaine requise)")

    # --- Filtre juridique --------------------------------------------------
    if juridique.get("statut_validation_avocat") != "valide":
        motifs.append("vertical non validé par un avocat (statut_validation_avocat != 'valide')")

    if regime_recouvrement is not None and regime_recouvrement.get("applicable") != "valide":
        motifs.append("régime de recouvrement pour compte d'autrui non validé (regime_recouvrement)")

    if not fiabilite_ocr_toutes_hautes:
        motifs.append("fiabilité OCR non 'haute' sur au moins un document du dossier")

    champs_manquants = resultat_calcul.get("champs_manquants") or []
    if champs_manquants:
        motifs.append(f"champs manquants ou illisibles : {', '.join(champs_manquants)}")

    confiance_min = seuils.get("confiance_min")
    confiance = resultat_calcul.get("confiance", 0.0)
    if confiance_min is None:
        motifs.append("seuil de confiance minimal non défini pour ce vertical (confiance_min)")
    elif confiance < confiance_min:
        motifs.append(f"confiance de l'analyse ({confiance}) < seuil requis ({confiance_min})")

    plafond = seuils.get("montant_plafond_auto")
    montant = resultat_calcul.get("montant_estime", 0.0)
    if plafond is None:
        motifs.append("plafond d'envoi automatique non défini pour ce vertical (montant_plafond_auto)")
    elif montant > plafond:
        motifs.append(f"montant estimé ({montant} €) au-delà du plafond auto ({plafond} €)")

    if not mandat_signe:
        motifs.append("mandat de réclamation non signé par le client")

    # --- Filtre économique (recouvrabilité) --------------------------------
    scoring_version: Optional[str] = None
    seuil_recouvrabilite = seuils.get("recouvrabilite_min")
    if score_recouvrabilite is not None:
        scoring_version = score_recouvrabilite.get("version")
        if seuil_recouvrabilite is None:
            motifs.append("seuil de recouvrabilité non défini pour ce vertical (recouvrabilite_min)")
        elif score_recouvrabilite.get("probabilite", 0.0) < seuil_recouvrabilite:
            motifs.append(
                f"{MOTIF_LOW_RECOVERABILITY} : probabilité de recouvrement "
                f"({score_recouvrabilite.get('probabilite')}) < seuil ({seuil_recouvrabilite})"
            )
    else:
        motifs.append("score de recouvrabilité absent (filtre économique non évalué)")

    decision = Verdict.EXCEPTION.value if motifs else Verdict.AUTO.value
    return {
        "decision": decision,
        "motifs": motifs,
        "regles_version": REGLES_VERSION,
        "scoring_version": scoring_version,
    }
