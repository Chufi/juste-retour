# Architecture — moteur de réclamation multi-verticaux

Un seul moteur (extraction → calcul déterministe → courrier factuel →
contrôle → envoi), où **un vertical = un fichier de config + d'éventuels
plugins de calcul**. Le contrôle humain se déplace du dossier vers
l'admission du vertical : on valide le vertical une fois à l'entrée, ensuite
les dossiers se traitent automatiquement, sauf exception.

```
juste-retour/
  core/                      générique — ne connaît aucun vertical
    extraction/              OCR (ocrmypdf/pytesseract) + tables (pdfplumber) + normalisation
    calc_engine.py           orchestre : config du vertical → calc_plugin (DÉTERMINISTE)
    letter_engine.py         courrier factuel depuis gabarit Jinja2 (PAS de LLM)
    review_agent.py          Directeur Juridique : verdict AUTO/EXCEPTION (règles, PAS de LLM)
    llm_client.py            rapport d'anomalies qualitatif (seule utilisation du LLM)
    outcomes/                boucle de résultats : schéma d'issue + scoring de recouvrabilité
    envoi/                   interface EnvoiRecommande + mock sandbox
    schemas.py               modèles Pydantic communs
    config_loader.py         seul point d'accès aux config.yaml
  verticals/
    depot_garantie/          PRIMAIRE (status: active — pipeline complet, envoi auto)
    pension_cnav/            GELÉ (status: paused — rien supprimé, pipeline exécutable)
    agirc_arrco/             status: draft (config squelette + README, candidat n°2)
    frais_bancaires/         status: smoke_test (landing + leads uniquement)
  landing/
    template/                UNE template Jinja2, N pages
    build.py                 config.yaml → landing/<slug>/index.html
    <slug>/index.html        pages générées (commitées)
  backend/app/
    main.py                  API publique (dossiers, analyse, envoi, leads, outcomes)
    admin.py                 back-office de supervision par exception (RBAC)
    services.py              exécution d'envoi partagée main/admin
    models.py                SQLite (dossiers, leads, outcomes, audit, partenaires…)
  tests/                     unitaires + intégration API
```

## Cycle de vie d'un vertical : un seul champ, `status`

- **`draft`** : squelette de config, rien de publié (pas de landing générée
  par défaut), pas de pipeline.
- **`smoke_test`** : landing + capture de leads publiées, pas de pipeline —
  sert uniquement à mesurer la demande.
- **`paused`** : pipeline construit mais gelé — pas de nouveaux dossiers, pas
  de verdict `AUTO`, pas d'envoi (même à la demande d'un humain) ; rien n'est
  supprimé et le pipeline reste exécutable en test.
- **`active`** : régime nominal, seul status qui autorise verdict `AUTO` et
  envoi.

S'y ajoute **`mode`** (kill switch d'envoi) : `auto` (défaut d'un vertical
actif) | `supervise_lancement` (tout en revue humaine, temporaire) |
`suspendu`. Overrides runtime dans la table `verticals_etat`
(`POST /admin/verticals/{slug}/mode`, sans redéploiement) ; la valeur runtime
prime sur la config versionnée.

## Automatisation par défaut

La vérification humaine se fait **une fois, à l'entrée du vertical** : l'avocat
valide les paramètres sourcés (`statut_validation_avocat: valide`, et
`regime_recouvrement.applicable: valide` pour les créances privées). Ensuite,
**tout est automatique** : dès qu'un dossier est complet (déclaration/données
+ pièces + mandat), l'analyse se déclenche seule à l'ingestion
(`_auto_analyser_si_pret`), et sur verdict `AUTO` le courrier part seul.
Seuls les blocages réels (données illisibles, litige → confiance basse,
montant hors plafond, mauvais score de recouvrabilité, mandat absent) routent
le dossier vers la file d'exceptions du back-office.

## Barre de vérifiabilité (le seul verrou avant l'automatisation totale)

Un vertical n'auto-envoie que si TOUT est vrai : règles de calcul 100%
déterministes et codées ; paramètres légaux sourcés (texte officiel + date)
et chargés depuis la config ; gabarit de courrier purement factuel ; voie de
recours standardisée ; validation avocat unique du vertical
(`statut_validation_avocat: valide`) — plus, pour les verticaux de
recouvrement de créance privée, `regime_recouvrement.applicable: valide`.
Basculer ces champs dans la config suffit : aucun changement de code n'est
nécessaire pour passer un vertical en automatisation totale (testé de bout
en bout dans `tests/test_api.py::test_automatisation_totale_apres_validation_avocat`).

## Décision par dossier : double filtre (core/review_agent.py)

Après extraction + calcul + génération du courrier, le Directeur Juridique
(déterministe, versionné `regles_version`) rend un verdict :

1. **Filtre juridique** : validation avocat du vertical, régime de
   recouvrement, fiabilité OCR haute partout, aucun champ critique manquant,
   confiance ≥ `confiance_min`, montant ≤ `montant_plafond_auto`, mandat
   signé présent. La confiance est pondérée par la gravité des anomalies
   (`core/confiance.py` + table `GRAVITES` de chaque plugin) : un litige
   factuel écrase la confiance, une exception mécanique certaine non.
2. **Filtre économique** : score de recouvrabilité
   (`core/outcomes/scoring.py`, versionné) ≥ `recouvrabilite_min`. Un dossier
   juridiquement valide mais économiquement mauvais part en `EXCEPTION` avec
   le motif `low_recoverability` — jamais de rejet silencieux.

`AUTO` → envoi automatique immédiat. `EXCEPTION` → file d'exceptions du
back-office, motifs journalisés. L'audit trace la version des règles et du
scoring de chaque verdict.

## Boucle de résultats (core/outcomes/)

Chaque dossier produit un enregistrement d'issue (statut envoye →
paye_total/partiel/refus/sans_reponse/escalade/abandonne, montants, délais,
profil débiteur, canal de résolution, timestamps) via
`POST /dossiers/{id}/outcome`. Le scoring (v2, bayésien) part d'un prior par
type de débiteur (administration 0.80 > pro 0.70 > particulier 0.55) pesant
`PRIOR_STRENGTH` issues équivalentes, et chaque issue terminale réelle
déplace continûment l'estimation vers le taux empirique — pas de bascule
brutale : quelques refus précoces suffisent à faire tomber un profil sous le
seuil (`low_recoverability`), quelques paiements le consolident, et le prior
s'efface à mesure que l'historique grossit. L'architecture (fonction pure
sur l'historique) permet de brancher un modèle prédictif sans toucher au
backend ni au review_agent.

## Attribution par canal d'acquisition

Dossiers et leads portent `acquisition {canal: ads|partenaire|organique|
referral, source_id, utm}`. Les landings capturent UTM et code partenaire
(`?ref=CODE`) depuis l'URL, sans friction utilisateur. Codes partenaires
(ADIL, associations, agences) : `POST /admin/partenaires`, rapport par
partenaire (`GET /admin/partenaires/{code}/rapport` : volume, taux
d'éligibilité, taux de recouvrement, montant moyen) — la donnée qui permet
de comparer le CAC ads vs prescription. `GET /leads/stats` donne visites /
leads / conversion par vertical et campagne.

## Envoi recommandé (core/envoi/)

Interface `EnvoiRecommande` (`envoyer`, `recuperer_preuves`) ; le code métier
ne dépend d'aucun prestataire. Choix du canal par type de destinataire, en
config :

- **hybride** (défaut) : dépôt API → distribution papier. Aucun consentement
  requis — obligatoire vers les administrations (Carsat/Cnav) et les
  particuliers (bailleurs).
- **lre_electronique** : réservé aux professionnels ayant consenti.

Preuves (dépôt, distribution) archivées au dossier + journal d'audit. Un
mock/sandbox sert tant qu'aucun compte prestataire qualifié eIDAS n'est
ouvert ; le prestataire réel se branche derrière le flag
`prestataire_envoi` du vertical.

## Back-office (supervision par exception)

L'humain observe le flux (`GET /admin/flux`) et n'agit que sur la file
d'exceptions (`GET /admin/exceptions`, `POST /admin/dossiers/{id}/traiter` :
approuver l'envoi / corriger le courrier / rejeter). File d'escalade avocat
verrouillée (`/escalader`, `/lever-escalade` — seul un rôle `juridique` peut
lever). Journal d'audit (`GET /admin/audit`), vue conformité DPO
(`GET /admin/conformite`), kill switch (`POST /admin/verticals/{slug}/mode`).
RBAC par rôles `operateur / juridique / dpo / admin` (headers `X-Role` /
`X-Acteur` — stub MVP à remplacer par une vraie authentification).

## Règles non négociables

- Le calcul (SAM, majorations, rappels) n'est **jamais** délégué au LLM ; le
  LLM ne produit que le rapport d'anomalies en langage clair, optionnel.
- Aucune valeur juridique en dur : tout vient des `config.yaml`, `null` tant
  que non validé avocat, jamais affiché tant que `null`
  (cf. LEGAL_OPEN_POINTS.md).
- Aucune stat non sourcée sur une page publique (filtrage au build).
- Courriers factuels et chiffrés, sans argumentation juridique — posture de
  mandataire de réclamation, jamais de consultation juridique (loi 1971).
- Jamais d'encaissement des fonds pour les verticaux de créance privée.
