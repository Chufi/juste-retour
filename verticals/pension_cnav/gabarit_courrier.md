{{ date_jour }}

Objet : Réclamation relative au calcul de ma pension de retraite — demande de régularisation

Madame, Monsieur,

Je vous informe avoir fait vérifier le calcul de ma pension de retraite. Cette vérification fait apparaître les éléments factuels suivants :

{% for anomalie in anomalies -%}
- Année {{ anomalie.annee }} : {{ anomalie.type }}
{% endfor %}
Salaire annuel moyen recalculé : {{ "%.2f"|format(details.sam_recalcule) }} €
Écart avec le salaire annuel moyen retenu lors de la liquidation : {{ "%.2f"|format(details.ecart_sam) }} €
Nombre de trimestres validés pris en compte dans ce recalcul : {{ details.trimestres_valides }}
Majoration mensuelle de pension résultant de cette correction : {{ "%.2f"|format(details.majoration_mensuelle_future) }} €
Montant du rappel estimé : {{ "%.2f"|format(montant_estime) }} €

Références : {{ base_legale }}.

Je vous demande de bien vouloir procéder à la vérification de ces éléments et, le cas échéant, à la régularisation de ma pension ainsi qu'au versement du rappel correspondant.

Vous trouverez ci-joint les pièces suivantes à l'appui de cette demande :
{% for piece in pieces -%}
{{ loop.index }}. {{ piece }}
{% endfor %}
Je reste à votre disposition pour tout complément d'information.

{{ nom }}
