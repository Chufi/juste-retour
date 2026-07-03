"""Scoring de recouvrabilité — filtre ÉCONOMIQUE de l'admission d'un dossier.

v2 : estimation bayésienne par rétrécissement (shrinkage), sans bascule
brutale. Le prior par type de débiteur compte pour `PRIOR_STRENGTH` issues
équivalentes ; chaque issue terminale réelle déplace continûment l'estimation
du prior vers le taux empirique :

    probabilité = (S × prior + nb_recouvrés) / (S + nb_issues_terminales)

Conséquences :
- démarrage à froid (0 issue) → exactement le prior documenté ;
- dès les premières issues, le score bouge — quelques refus précoces suffisent
  à faire passer un profil sous le seuil `recouvrabilite_min` (EXCEPTION
  `low_recoverability`), quelques paiements le consolident ;
- plus l'historique grossit, plus le prior s'efface (à n = S, moitié-moitié).

Niveau le plus spécifique disponible : issues du même profil de débiteur si
le vertical en a, sinon issues tous profils du vertical, sinon prior seul.
L'architecture reste "fonction pure sur une liste d'outcomes" : un modèle
prédictif pourra remplacer `calculer_score` sans toucher au backend ni au
review_agent (contrat de sortie inchangé, versionné).
"""

from __future__ import annotations

from typing import Optional, TypedDict

from .schema import STATUTS_RECOUVRES, STATUTS_TERMINAUX, StatutOutcome, TypeDebiteur

SCORING_VERSION = "bayes-v2"

# Poids du prior, en nombre d'issues équivalentes. 15 ≈ le prior domine sur
# les ~10 premières issues puis s'efface progressivement.
PRIOR_STRENGTH = 15

# Priors par type de débiteur (heuristiques de démarrage, recalibrées en
# continu par les issues réelles via le shrinkage ci-dessus) :
# - administration : paie de façon quasi certaine une créance établie, mais
#   lentement (délais de traitement administratifs).
# - pro : solvable et joignable, sensible à la mise en demeure.
# - particulier : plus dispersé (solvabilité, contestation, silence).
_PRIORS: dict[str, dict[str, float]] = {
    TypeDebiteur.ADMINISTRATION.value: {"probabilite": 0.80, "delai_jours": 90},
    TypeDebiteur.PRO.value: {"probabilite": 0.70, "delai_jours": 45},
    TypeDebiteur.PARTICULIER.value: {"probabilite": 0.55, "delai_jours": 60},
}


class ScoreRecouvrabilite(TypedDict):
    probabilite: float
    delai_estime_jours: int
    version: str
    base: str  # "prior_heuristique" | "bayes_vertical" | "bayes_profil"
    n_echantillon: int


def _statut(outcome: dict) -> Optional[StatutOutcome]:
    try:
        return StatutOutcome(outcome.get("statut"))
    except ValueError:
        return None


def _issues_terminales(outcomes: list[dict]) -> tuple[int, int, list[int]]:
    """(nb_terminales, nb_recouvrées, délais de paiement observés)."""
    terminaux = [o for o in outcomes if _statut(o) in STATUTS_TERMINAUX]
    recouvres = [o for o in terminaux if _statut(o) in STATUTS_RECOUVRES]
    delais = sorted(
        o["delai_paiement_jours"]
        for o in recouvres
        if o.get("delai_paiement_jours") is not None
    )
    return len(terminaux), len(recouvres), delais


def _retrecir(prior: float, empirique_k: int, empirique_n: int) -> float:
    return (PRIOR_STRENGTH * prior + empirique_k) / (PRIOR_STRENGTH + empirique_n)


def calculer_score(
    type_debiteur: str, outcomes_historiques: list[dict]
) -> ScoreRecouvrabilite:
    """Score prédictif de recouvrabilité pour un nouveau dossier.

    `outcomes_historiques` : les outcomes déjà enregistrés pour le même
    vertical (fournis par l'appelant, typiquement depuis SQLite).
    """
    prior = _PRIORS.get(type_debiteur, _PRIORS[TypeDebiteur.PARTICULIER.value])

    du_meme_profil = [
        o for o in outcomes_historiques if o.get("profil_debiteur_type") == type_debiteur
    ]
    n_profil, k_profil, delais_profil = _issues_terminales(du_meme_profil)
    n_vertical, k_vertical, delais_vertical = _issues_terminales(outcomes_historiques)

    if n_profil > 0:
        n, k, delais, base = n_profil, k_profil, delais_profil, "bayes_profil"
    elif n_vertical > 0:
        n, k, delais, base = n_vertical, k_vertical, delais_vertical, "bayes_vertical"
    else:
        return {
            "probabilite": prior["probabilite"],
            "delai_estime_jours": int(prior["delai_jours"]),
            "version": SCORING_VERSION,
            "base": "prior_heuristique",
            "n_echantillon": 0,
        }

    probabilite = round(_retrecir(prior["probabilite"], k, n), 2)

    if delais:
        delai_median = delais[len(delais) // 2]
        delai = (PRIOR_STRENGTH * prior["delai_jours"] + len(delais) * delai_median) / (
            PRIOR_STRENGTH + len(delais)
        )
    else:
        delai = prior["delai_jours"]

    return {
        "probabilite": probabilite,
        "delai_estime_jours": int(round(delai)),
        "version": SCORING_VERSION,
        "base": base,
        "n_echantillon": n,
    }
