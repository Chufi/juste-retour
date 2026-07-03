# LEGAL_OPEN_POINTS — points juridiques ouverts (note de cadrage avocat)

Ce fichier recense toutes les valeurs et questions juridiques **non tranchées**
du moteur. Règle du repo : aucune valeur juridique en dur dans le code ; dans
les configs, une valeur non sourcée/non validée reste à `null` (marquée
`TODO_LAWYER`) et n'est jamais affichée ni utilisée pour un envoi automatique.

## Bloquants pour le passage en `auto` du vertical depot_garantie (primaire)

1. **Régime du recouvrement amiable pour compte d'autrui** — décret
   n° 96-1112 du 18/12/1996 (art. R.124-1 et s. CPCE). Le vertical récupère
   une créance due par un tiers privé (bailleur) : confirmer l'applicabilité,
   les mentions imposées dans la mise en demeure, et valider la règle interne
   "ne jamais encaisser les fonds — restitution directe bailleur → client".
   → `verticals/depot_garantie/config.yaml`, bloc `regime_recouvrement`
   (`applicable: a_confirmer`).
2. **Mentions imposées du courrier de mise en demeure** — le gabarit
   (`verticals/depot_garantie/gabarit_courrier.md`) est factuel ; les mentions
   obligatoires du décret 96-1112 (si applicable) doivent y être ajoutées
   après validation.
3. **Délai de prescription de l'action en restitution** — a priori 3 ans
   (art. 7-1 loi 89-462), à confirmer. → `juridique.delai_prescription: null`.
4. **Validation globale du vertical** (barre de vérifiabilité) →
   `juridique.statut_validation_avocat: en_attente`. C'est LE verrou de
   l'automatisation totale : dès que ce champ et `regime_recouvrement`
   passent à `valide`, les dossiers sans blocage partent automatiquement
   (aucun changement de code requis).
5. **Plafond d'envoi automatique** — fixé à 5 000 € (seuil business : dépôt
   ≤ 2 mois de loyer + majoration tiennent très en dessous). À confirmer en
   revue avocat, ajustable dans `seuils_auto.montant_plafond_auto`.

## Vertical pension_cnav (gelé — les points restent ouverts)

6. **Délai opposable au rappel d'arriérés d'un assuré sous-payé** (régime
   général) — non tranché en droit. → `juridique.delai_prescription: null`.
7. **`minimum_contributif_mensuel: 733.03`** — valeur 2024 indicative, sans
   source formelle datée. Non utilisée par le calcul actuel (référencée par le
   prompt d'analyse seulement) ; à sourcer (arrêté de revalorisation) ou à
   passer à `null` avant toute reprise du vertical. `TODO_LAWYER`.
8. **`trimestres_requis_taux_plein_defaut: 172`** — simplification MVP : la
   durée requise varie selon l'année de naissance (loi Touraine / réforme
   2023). À remplacer par un barème par génération sourcé. `TODO_LAWYER`.
9. **Coefficients de revalorisation** (`coefficients_2026.json`) — valeurs
   d'exemple de développement, à remplacer par la table officielle Cnav de
   l'année de liquidation.

## Vertical agirc_arrco (draft)

10. Tous les paramètres (`valeur_du_point`, coefficients, taux, prescription,
    voie de recours) sont à `null` / `source: null` /
    `validated_by_lawyer: false`. À sourcer intégralement avant toute
    construction du pipeline.

## Vertical frais_bancaires (draft, smoke test)

11. Plafonds des commissions d'intervention et frais d'incident : à sourcer
    (Code monétaire et financier + décrets) avant tout affichage chiffré.
12. Même question de régime de recouvrement pour compte d'autrui que
    depot_garantie (créance sur un tiers privé).

## Transverse

13. **Canal d'envoi** : la doctrine retenue (LRE 100% électronique interdite
    sans consentement vers particuliers et administrations, hybride par
    défaut, art. L.100 CPCE) est à faire confirmer, notamment la
    qualification "administration" des caisses (Carsat/Cnav) et GPS.
14. **RGPD** : registre des traitements à compléter pour la finalité
    "prospection / test de demande" (leads) ; durée de conservation
    opérationnelle du back-office (730 jours, `backend/app/admin.py`) à
    valider avec le DPO.
