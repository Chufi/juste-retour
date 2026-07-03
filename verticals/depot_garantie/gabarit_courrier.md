{# Gabarit FACTUEL de mise en demeure — aucune argumentation juridique.
   TODO_LAWYER : les mentions imposées par le décret n° 96-1112 du 18/12/1996
   (recouvrement amiable pour compte d'autrui) doivent être validées et, le
   cas échéant, ajoutées par un avocat AVANT tout envoi réel
   (cf. LEGAL_OPEN_POINTS.md). #}
{{ date_jour }}

Objet : Mise en demeure — restitution du dépôt de garantie et majoration légale

Madame, Monsieur,

Agissant en qualité de mandataire de {{ nom }}, votre ancien locataire, je vous adresse la présente au sujet du dépôt de garantie versé au titre du bail.

Les faits sont les suivants :

- Dépôt de garantie versé : {{ "%.2f"|format(declaration.depot_verse) }} €
- Montant restitué à ce jour : {{ "%.2f"|format(declaration.montant_restitue) }} €
- Remise des clés intervenue le : {{ declaration.date_remise_cles }}
- Délai légal de restitution applicable : {{ details.delai_applique_jours }} jours, expiré le {{ details.date_limite_restitution }}
- Nombre de périodes mensuelles de retard commencées : {{ details.nb_mois_retard_commences }}

En conséquence, les sommes suivantes restent dues :

- Solde du dépôt de garantie : {{ "%.2f"|format(details.principal_restant_du) }} €
- Majoration légale ({{ details.majoration_taux_applique * 100 }} % du loyer mensuel hors charges par mois de retard commencé) : {{ "%.2f"|format(details.majoration_legale) }} €
- Total réclamé : {{ "%.2f"|format(montant_estime) }} €

Références : {{ base_legale }}.

Je vous mets en demeure de procéder au versement de cette somme directement auprès de {{ nom }} sous quinzaine à compter de la réception de la présente.

Pièces jointes :
{% for piece in pieces -%}
{{ loop.index }}. {{ piece }}
{% endfor %}
À défaut de règlement dans ce délai, {{ nom }} conserve la possibilité de saisir {{ voie_recours }}.

Le mandataire, pour {{ nom }}
