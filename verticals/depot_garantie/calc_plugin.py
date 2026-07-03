"""Plugin de calcul du vertical depot_garantie (caution locative non restituée).

Calcul 100% déterministe de la somme réclamable au bailleur :

    principal restant dû  = dépôt versé − montant restitué − retenues admises
    majoration légale     = taux (config) × loyer mensuel HC × nb de mois de
                            retard COMMENCÉS depuis l'expiration du délai légal

Le taux (10%), les délais (30/60 jours selon conformité de l'état des lieux)
et l'exception de majoration (nouvelle adresse non transmise) viennent de
`config.yaml` (art. 22 loi n° 89-462, sourcé) — jamais codés en dur ici.

Un "mois commencé" est une période mensuelle calendaire entamée à compter de
la date limite de restitution : 1 jour de retard = 1 mois ; exactement 1 mois
de retard = 1 mois ; 1 mois + 1 jour = 2 mois (cf. tests/test_caution.py).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, TypedDict

from core.confiance import estimer_confiance

# Champs de déclaration sans lesquels aucun calcul n'est possible.
CHAMPS_REQUIS = (
    "loyer_hc_mensuel",
    "depot_verse",
    "montant_restitue",
    "date_remise_cles",
    "edl_sortie_conforme",
    "nouvelle_adresse_transmise",
)

# Gravité par type d'anomalie (cf. core/confiance.py). Un litige factuel
# écrase la confiance (arbitrage humain requis) ; une exception mécanique et
# certaine ne remet pas en cause la fiabilité du calcul.
GRAVITES = {
    "retenues_contestees": 0.50,        # litige sur les dégradations : à trancher par un humain
    "delai_legal_non_expire": 0.60,     # rien n'est encore exigible
    "aucun_principal_restant_du": 0.40, # plus rien à réclamer, dossier douteux
    "retenues_malgre_edl_conforme": 0.20,  # position ferme mais contestation probable
    "exception_majoration": 0.05,       # règle mécanique, le principal reste fiable
}


class ResultatCalcul(TypedDict):
    montant_estime: float
    confiance: float
    anomalies: list[dict]
    champs_manquants: list[str]
    details: dict[str, Any]


def _ajouter_mois(d: date, n: int) -> date:
    mois_total = d.month - 1 + n
    annee = d.year + mois_total // 12
    mois = mois_total % 12 + 1
    jour = min(d.day, calendar.monthrange(annee, mois)[1])
    return date(annee, mois, jour)


def mois_commences(date_limite: date, date_fin: date) -> int:
    """Nombre de périodes mensuelles commencées entre `date_limite`
    (exclue) et `date_fin` (incluse)."""
    if date_fin <= date_limite:
        return 0
    n = 1
    while _ajouter_mois(date_limite, n) < date_fin:
        n += 1
    return n


def _parser_date(valeur: Any) -> date:
    if isinstance(valeur, date):
        return valeur
    return date.fromisoformat(str(valeur))


def calculer(donnees: dict[str, Any], config: dict[str, Any]) -> ResultatCalcul:
    juridique = config["juridique"]
    declaration = donnees.get("declaration") or {}
    pieces_fournies = set(donnees.get("pieces_fournies") or [])

    champs_manquants = [c for c in CHAMPS_REQUIS if declaration.get(c) is None]
    champs_manquants += [
        f"pièce : {piece}" for piece in config.get("pieces", []) if piece not in pieces_fournies
    ]
    if champs_manquants:
        return {
            "montant_estime": 0.0,
            "confiance": 0.0,
            "anomalies": [{"type": "declaration_incomplete", "champs": champs_manquants}],
            "champs_manquants": champs_manquants,
            "details": {},
        }

    anomalies: list[dict] = []

    loyer_hc = float(declaration["loyer_hc_mensuel"])
    depot_verse = float(declaration["depot_verse"])
    montant_restitue = float(declaration["montant_restitue"])
    retenues = float(declaration.get("retenues_bailleur") or 0.0)
    retenues_contestees = bool(declaration.get("retenues_contestees", False))
    edl_conforme = bool(declaration["edl_sortie_conforme"])
    adresse_transmise = bool(declaration["nouvelle_adresse_transmise"])
    date_remise_cles = _parser_date(declaration["date_remise_cles"])
    date_reference = _parser_date(declaration.get("date_reference") or date.today())

    if edl_conforme:
        delai_jours = juridique["delai_restitution_conforme_jours"]
        # EDL conforme : aucune retenue pour dégradation n'est opposable ;
        # une retenue annoncée est précisément ce que la réclamation conteste.
        retenues_admises = 0.0
        if retenues > 0:
            anomalies.append(
                {"type": "retenues_malgre_edl_conforme", "montant": retenues}
            )
    else:
        delai_jours = juridique["delai_restitution_non_conforme_jours"]
        if retenues_contestees:
            # Litige factuel sur les dégradations : le moteur ne tranche pas,
            # il réclame hors retenues et signale l'anomalie (→ EXCEPTION).
            retenues_admises = retenues
            anomalies.append({"type": "retenues_contestees", "montant": retenues})
        else:
            retenues_admises = retenues

    date_limite = date_remise_cles + timedelta(days=delai_jours)
    delai_depasse = date_reference > date_limite
    if not delai_depasse:
        anomalies.append(
            {"type": "delai_legal_non_expire", "date_limite": date_limite.isoformat()}
        )

    principal_restant = max(0.0, round(depot_verse - montant_restitue - retenues_admises, 2))
    if principal_restant == 0.0 and delai_depasse:
        anomalies.append({"type": "aucun_principal_restant_du"})

    nb_mois = mois_commences(date_limite, date_reference) if delai_depasse else 0
    if adresse_transmise:
        majoration = round(juridique["majoration_taux"] * loyer_hc * nb_mois, 2)
    else:
        majoration = 0.0
        anomalies.append(
            {"type": "exception_majoration", "motif": juridique["exception_majoration"]}
        )

    montant_estime = round(principal_restant + majoration, 2) if delai_depasse else 0.0

    return {
        "montant_estime": montant_estime,
        "confiance": estimer_confiance(anomalies, GRAVITES),
        "anomalies": anomalies,
        "champs_manquants": [],
        "details": {
            "delai_applique_jours": delai_jours,
            "date_limite_restitution": date_limite.isoformat(),
            "delai_depasse": delai_depasse,
            "nb_mois_retard_commences": nb_mois,
            "principal_restant_du": principal_restant,
            "retenues_admises": retenues_admises,
            "majoration_legale": majoration,
            "majoration_taux_applique": juridique["majoration_taux"],
            "assiette_majoration": juridique["majoration_assiette"],
            "loyer_hc_mensuel": loyer_hc,
        },
    }
