# Vertical Agirc-Arrco — pourquoi il précède la CNAV dans la file

Statut : **draft** (squelette de config uniquement, aucun pipeline construit).

## Pourquoi ce vertical passe avant la reprise de pension_cnav

1. **Calcul par points, structurellement plus simple.** La complémentaire
   Agirc-Arrco se vérifie par une multiplication : points acquis × valeur du
   point, corrigée de coefficients (majorations familiales, minorations
   d'anticipation). C'est un calcul fermé, rejouable, qui passe la barre de
   vérifiabilité beaucoup plus facilement que le régime général.
2. **Pas de reconstitution de carrière complète.** Le vertical pension_cnav
   exige de reconstituer le SAM sur les 25 meilleures années (relevés
   incomplets, coefficients de revalorisation annuels, trimestres assimilés...).
   Côté Agirc-Arrco, la vérification porte sur la cohérence points reportés ↔
   cotisations connues, année par année : chaque année est vérifiable
   indépendamment, sans dépendre de la reconstitution de toute la carrière.
3. **Sources de vérité centralisées.** Valeur du point et salaire de référence
   sont publiés chaque année par l'Agirc-Arrco (un seul organisme), là où le
   régime général mélange Cnav/Carsat et des paramètres dispersés.
4. **Même public, même documents que pension_cnav.** Les leads captés par le
   vertical retraite (relevés, bulletins) sont directement réutilisables :
   coût d'acquisition marginal faible.

## Conditions de promotion (draft → pipeline)

- Sourcer tous les paramètres de `config.yaml` (texte officiel + date) —
  aujourd'hui tout est à `null` / `source: null` / `validated_by_lawyer: false`.
- Valider le vertical avec l'avocat (barre de vérifiabilité complète).
- Écrire `calc_plugin.py` (points × valeur du point × coefficients) + tests.
- Décider explicitement la promotion (décision tracée), comme pour tout vertical.
