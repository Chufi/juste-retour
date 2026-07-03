# Juste Retour — moteur de réclamation multi-verticaux

Un moteur réutilisable (extraction → calcul déterministe → courrier factuel →
contrôle → envoi recommandé) où un vertical = un `config.yaml` + d'éventuels
plugins de calcul. Modèle au succès : gratuit tant qu'aucune somme n'est
récupérée. Voir `ARCHITECTURE.md` pour la vue d'ensemble et
`LEGAL_OPEN_POINTS.md` pour les points juridiques ouverts.

**Philosophie : automatisation par défaut.** La vérification humaine se fait
une fois, à l'entrée du vertical (validation avocat des paramètres sourcés).
Ensuite, dès qu'un dossier est complet (déclaration + pièces + mandat),
l'analyse se lance toute seule et, sauf blocage ou mauvais score, le courrier
part tout seul. Les seuls dossiers qui attendent un humain sont ceux de la
file d'exceptions (motif journalisé).

**Verticaux (`status`, champ unique de cycle de vie) :**

| Vertical | status | Périmètre |
|---|---|---|
| `depot_garantie` | active | **primaire** — pipeline complet, envoi automatique dès validation avocat |
| `pension_cnav` | paused | pipeline complet gelé (rien supprimé) |
| `agirc_arrco` | draft | squelette de config, non publié (candidat n°2, cf. son README) |
| `frais_bancaires` | smoke_test | landing + leads uniquement |

## Installation

```bash
cd backend && pip install -r requirements.txt   # ou depuis un venv
# facultatif, pour l'OCR des scans (vertical pension_cnav) :
sudo apt-get install tesseract-ocr tesseract-ocr-fra ocrmypdf
# facultatif, pour le rapport d'anomalies LLM :
export ANTHROPIC_API_KEY=sk-ant-...
```

## Lancer le backend

```bash
# depuis la racine du repo (juste-retour/)
uvicorn backend.app.main:app --reload --port 8000
```

SQLite (`backend/juste_retour.db`) et `backend/uploads/` sont créés au
démarrage. L'envoi recommandé utilise le mock sandbox tant qu'aucun
prestataire n'est configuré (`prestataire_envoi` dans la config du vertical).

## Générer les landing pages

```bash
python3 landing/build.py                  # toutes
python3 landing/build.py depot_garantie   # une seule
```

Une template unique (`landing/template/`), une page par vertical
(`landing/<slug>/index.html`). Garde-fous au build : une stat sans `source`
n'est pas rendue ; un vertical sans hook/étapes/mentions légales est refusé.
Les pages capturent l'attribution (`?ref=CODE`, `utm_*`) sans friction et
postent les leads sur `POST /leads`.

## Flux depot_garantie de bout en bout

```bash
# 1. Dossier (avec attribution partenaire facultative)
curl -X POST localhost:8000/dossiers -H "Content-Type: application/json" -d '{
  "nom": "Jeanne Martin", "email": "jeanne@example.com",
  "vertical": "depot_garantie",
  "acquisition": {"canal": "partenaire", "source_id": "ADIL75", "utm": {}}
}'

# 2. Déclaration des faits + pièces
curl -X POST localhost:8000/dossiers/1/declaration -H "Content-Type: application/json" -d '{
  "champs": {"loyer_hc_mensuel": 800, "depot_verse": 800, "montant_restitue": 0,
             "edl_sortie_conforme": true, "nouvelle_adresse_transmise": true,
             "date_remise_cles": "2026-01-15"},
  "type_debiteur": "particulier",
  "pieces_fournies": ["contrat de bail", "état des lieux d'entrée", "état des lieux de sortie",
                      "preuve de remise des clés (LRAR ou récépissé) avec date",
                      "justificatif de transmission de la nouvelle adresse au bailleur"]
}'
curl -X POST localhost:8000/dossiers/1/documents -F "fichiers=@bail.pdf"   # pièces justificatives
curl -X POST localhost:8000/dossiers/1/mandat                              # mandat signé (MVP)
# ↑ Dès que le dossier est complet, l'analyse se lance TOUTE SEULE (la réponse
#   contient "analyse_automatique") et, sur verdict AUTO, le courrier part seul.
#   POST /dossiers/1/analyser reste disponible pour relancer explicitement.

# Aujourd'hui le verdict est EXCEPTION (vertical pas encore validé avocat) :
# l'envoi passe alors par la file d'exceptions du back-office.
curl -X POST localhost:8000/admin/dossiers/1/traiter \
  -H "X-Role: operateur" -H "X-Acteur: bob" -H "Content-Type: application/json" \
  -d '{"action": "approuver_envoi"}'

# Boucle de résultats (nourrit le scoring de recouvrabilité)
curl -X POST localhost:8000/dossiers/1/outcome -H "Content-Type: application/json" \
  -d '{"statut": "paye_total", "montant_recouvre": 1120.0, "delai_paiement_jours": 21}'
```

**Passage en automatisation totale** : quand l'avocat valide le vertical,
basculer dans `verticals/depot_garantie/config.yaml`
`juridique.statut_validation_avocat: valide` et
`regime_recouvrement.applicable: valide`. C'est tout — aucun changement de
code (testé : `tests/test_api.py::test_automatisation_totale_apres_validation_avocat`).
Les dossiers propres partent seuls ; litiges, données illisibles, montants
hors plafond et mauvais scores continuent d'aller en file d'exceptions.

## Ajouter un vertical

1. `verticals/<slug>/config.yaml` — partir de `depot_garantie` comme modèle.
   `status: draft`, toutes les valeurs juridiques à `null` + `source: null`
   tant que non sourcées (règle absolue).
2. Passer `status: smoke_test` + `python3 landing/build.py` → landing de
   mesure de demande ; les leads arrivent sur `POST /leads`, les stats sur
   `GET /leads/stats` (les drafts ne sont jamais publiés par défaut).
3. Si le smoke test est concluant : sourcer les paramètres, écrire
   `calc_plugin.py` (contrat : `calculer(donnees, config) -> ResultatCalcul`,
   avec sa table `GRAVITES` d'anomalies), `gabarit_courrier.md` (factuel),
   les tests, puis passer `status: active`.
4. Automatisation totale : franchir la **barre de vérifiabilité** (calcul
   déterministe testé, paramètres sourcés, gabarit factuel, voie de recours
   standardisée) puis faire valider le vertical par l'avocat — bascule de
   `statut_validation_avocat` (et `regime_recouvrement.applicable` pour les
   créances privées) à `valide` dans la config. Rien d'autre : les dossiers
   complets s'analysent et partent seuls ; blocages et mauvais scores vont
   en file d'exceptions. Kill switch runtime :
   `POST /admin/verticals/<slug>/mode` (rôle admin, tracé dans l'audit).

## Choix du canal d'envoi (selon le destinataire)

- **Administration** (Carsat/Cnav…) ou **particulier** (bailleur) : la LRE
  100% électronique exige leur consentement → canal `hybride` (dépôt API,
  distribution papier, valeur LRAR, aucun consentement requis).
- **Professionnel ayant consenti** (banque, bailleur pro) :
  `lre_electronique` possible.
- Toujours en config (`canal_envoi`), jamais en dur ; prestataire qualifié
  eIDAS branché derrière `prestataire_envoi` (mock sandbox en attendant).

## Back-office (supervision par exception)

Headers d'accès MVP : `X-Role: operateur|juridique|dpo|admin` + `X-Acteur`.

- `GET /admin/flux` — tous les dossiers, observation seule
- `GET /admin/exceptions` — file d'exceptions (motifs, calcul, courrier)
- `POST /admin/dossiers/{id}/traiter` — approuver l'envoi / corriger / rejeter
- `POST /admin/dossiers/{id}/escalader` / `lever-escalade` — file avocat verrouillée
- `POST /admin/verticals/{slug}/mode` — kill switch (mode et/ou status)
- `GET /admin/audit`, `GET /admin/conformite` — journaux, vue DPO
- `POST /admin/partenaires`, `GET /admin/partenaires/{code}/rapport` — attribution

## Lire les stats

- `GET /leads/stats` — visites, leads, taux de conversion par vertical × campagne.
- `GET /admin/partenaires/{code}/rapport` — volume, taux d'éligibilité, taux
  de recouvrement, montant moyen par prescripteur (CAC ads vs prescription).

## Tests

```bash
python3 -m pytest tests/ -v     # depuis la racine du repo
```

Couvre : moteur SAM/rappel (pension_cnav), majoration caution (mois entamé,
restitution partielle, montants nuls, exception d'adresse), extraction OCR,
review_agent (status paused/draft jamais AUTO, `low_recoverability`),
scoring (priors → historique), build des landings (stat non sourcée jamais
rendue), API de bout en bout (pipeline, back-office, kill switch, RBAC,
outcomes, rapport partenaire).

## Non-objectifs courants

Paiement/facturation du success fee, compte de production chez le prestataire
d'envoi (mock/sandbox + flag), pipeline pour les verticaux en smoke test,
valeurs juridiques non validées par avocat (restent `null`).
