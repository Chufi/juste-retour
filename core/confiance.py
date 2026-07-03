"""Confiance d'un résultat de calcul, pondérée par la gravité des anomalies.

Remplace l'heuristique plate "−15% par anomalie" : toutes les anomalies ne se
valent pas. Un litige factuel (retenues contestées) doit plomber la confiance
— il exige un arbitrage humain — quand une exception purement mécanique et
certaine (majoration exclue faute d'adresse transmise) ne remet pas en cause
la fiabilité du montant calculé.

Chaque plugin de calcul déclare sa table `GRAVITES` (type d'anomalie → poids
dans [0, 1]) ; un type non déclaré reçoit `GRAVITE_DEFAUT`. La confiance est
1 − somme des poids, bornée à [0, 1]. Les poids restent des heuristiques
métier versionnées avec le code du plugin — à recalibrer sur les outcomes
réels (dossiers AUTO contestés a posteriori = poids trop faibles).
"""

from __future__ import annotations

GRAVITE_DEFAUT = 0.15


def estimer_confiance(
    anomalies: list[dict],
    gravites: dict[str, float],
    gravite_defaut: float = GRAVITE_DEFAUT,
) -> float:
    penalite = sum(gravites.get(a.get("type", ""), gravite_defaut) for a in anomalies)
    return round(max(0.0, min(1.0, 1.0 - penalite)), 2)
