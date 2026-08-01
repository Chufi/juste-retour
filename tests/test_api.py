"""Tests d'intégration API : pipeline depot_garantie de bout en bout,
leads/analytics, back-office, kill switch, outcomes et rapport partenaire."""

import pytest
from fastapi.testclient import TestClient

from backend.app import main, models

ADMIN = {"X-Role": "admin", "X-Acteur": "alice"}
OPERATEUR = {"X-Role": "operateur", "X-Acteur": "bob"}
DPO = {"X-Role": "dpo", "X-Acteur": "carole"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(main, "UPLOADS_DIR", tmp_path / "uploads")
    with TestClient(main.app) as c:
        yield c


def _headers(token: str) -> dict:
    return {"X-Dossier-Token": token}


def declaration_valide():
    from core.config_loader import charger_config

    config = charger_config("depot_garantie")
    return {
        "champs": {
            "loyer_hc_mensuel": 800.0,
            "depot_verse": 800.0,
            "montant_restitue": 0.0,
            "edl_sortie_conforme": True,
            "nouvelle_adresse_transmise": True,
            "date_remise_cles": "2026-01-15",
            "date_reference": "2026-05-20",
        },
        "type_debiteur": "particulier",
        "pieces_fournies": list(config["pieces"]),
    }


def creer_dossier_analyse(client) -> tuple[int, str]:
    r = client.post(
        "/dossiers",
        json={
            "nom": "Jeanne Martin",
            "email": "jeanne@example.com",
            "vertical": "depot_garantie",
            "acquisition": {"canal": "partenaire", "source_id": "ADIL75", "utm": {}},
        },
    )
    assert r.status_code == 201
    corps = r.json()
    dossier_id, token = corps["dossier_id"], corps["token"]
    assert (
        client.post(
            f"/dossiers/{dossier_id}/declaration", json=declaration_valide(), headers=_headers(token)
        ).status_code
        == 200
    )
    assert client.post(f"/dossiers/{dossier_id}/mandat", headers=_headers(token)).status_code == 200
    return dossier_id, token


# --- Front (app client + landings + infos publiques) ---------------------------


def test_racine_redirige_vers_l_app(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/app/"


def test_app_client_servie(client):
    r = client.get("/app/")
    assert r.status_code == 200
    assert "dépôt de garantie" in r.text.lower()
    assert "mandat" in r.text.lower()


def test_landing_servie(client):
    r = client.get("/landing/depot_garantie/")
    assert r.status_code == 200
    assert "caution" in r.text.lower()


def test_infos_vertical_publiques_sans_donnees_sensibles(client):
    r = client.get("/verticals/depot_garantie")
    assert r.status_code == 200
    infos = r.json()
    assert infos["slug"] == "depot_garantie"
    assert len(infos["pieces"]) == 5
    # Rien d'interne ne fuit : ni seuils, ni statut de validation avocat.
    assert "seuils_auto" not in infos
    assert "juridique" not in infos
    assert "statut_validation_avocat" not in r.text


# --- Sécurité : jeton de dossier -------------------------------------------------


def test_dossier_inaccessible_sans_le_bon_jeton(client):
    dossier_id, token = creer_dossier_analyse(client)

    # Sans jeton du tout.
    assert client.get(f"/dossiers/{dossier_id}").status_code == 422  # header requis
    # Avec un jeton erroné : 404, pas 403, pour ne pas confirmer l'existence.
    assert client.get(f"/dossiers/{dossier_id}", headers=_headers("mauvais-jeton")).status_code == 404
    # Avec le bon jeton : accès normal.
    assert client.get(f"/dossiers/{dossier_id}", headers=_headers(token)).status_code == 200
    # Le jeton d'un AUTRE dossier ne doit pas non plus fonctionner.
    _, autre_token = creer_dossier_analyse(client)
    assert client.get(f"/dossiers/{dossier_id}", headers=_headers(autre_token)).status_code == 404


def test_upload_rejette_un_nom_de_fichier_avec_traversee_de_chemin(client, tmp_path):
    dossier_id, token = creer_dossier_analyse(client)
    r = client.post(
        f"/dossiers/{dossier_id}/documents",
        files={"fichiers": ("../../../evil.txt", b"contenu", "text/plain")},
        headers=_headers(token),
    )
    assert r.status_code == 200
    # Le fichier est resté cantonné au dossier de uploads/, jamais écrit hors de son périmètre.
    fichier_attendu = tmp_path / "uploads" / str(dossier_id) / "evil.txt"
    assert fichier_attendu.exists()
    assert not (tmp_path / "evil.txt").exists()


# --- Pipeline depot_garantie ------------------------------------------------


def test_pipeline_depot_garantie_exception_sans_validation_avocat(client):
    dossier_id, token = creer_dossier_analyse(client)
    r = client.post(f"/dossiers/{dossier_id}/analyser", headers=_headers(token))
    assert r.status_code == 200
    corps = r.json()

    assert corps["calcul_moteur"]["montant_estime"] == 1120.0
    # avocat en_attente + recouvrement a_confirmer + pas de documents → EXCEPTION.
    assert corps["verdict"]["decision"] == "EXCEPTION"
    assert "envoi" not in corps  # rien ne part automatiquement
    assert "Mise en demeure" in corps["projet_courrier"]


def test_smoke_test_vertical_refuse_les_dossiers(client):
    r = client.post(
        "/dossiers",
        json={"nom": "X", "email": "x@example.com", "vertical": "frais_bancaires"},
    )
    assert r.status_code == 409
    assert "leads" in r.json()["detail"]


def test_analyser_refuse_si_declaration_incomplete(client):
    r = client.post(
        "/dossiers",
        json={"nom": "Y", "email": "y@example.com", "vertical": "depot_garantie"},
    )
    corps = r.json()
    dossier_id, token = corps["dossier_id"], corps["token"]
    r = client.post(f"/dossiers/{dossier_id}/analyser", headers=_headers(token))
    assert r.status_code == 409
    assert r.json()["detail"]["champs"]


def test_envoi_systeme_refuse_sur_exception(client):
    dossier_id, token = creer_dossier_analyse(client)
    client.post(f"/dossiers/{dossier_id}/analyser", headers=_headers(token))
    r = client.post(f"/dossiers/{dossier_id}/envoyer", headers=_headers(token))
    assert r.status_code == 409


# --- Back-office ---------------------------------------------------------------


def test_exception_visible_puis_approuvee_et_envoyee(client):
    dossier_id, token = creer_dossier_analyse(client)
    client.post(f"/dossiers/{dossier_id}/analyser", headers=_headers(token))

    exceptions = client.get("/admin/exceptions", headers=OPERATEUR).json()["exceptions"]
    assert any(e["dossier_id"] == dossier_id for e in exceptions)

    r = client.post(
        f"/admin/dossiers/{dossier_id}/traiter",
        json={"action": "approuver_envoi", "commentaire": "vérifié manuellement"},
        headers=OPERATEUR,
    )
    assert r.status_code == 200
    envoi = r.json()["envoi"]
    assert envoi["canal"] == "hybride"
    assert envoi["id_envoi"].startswith("mock-")
    assert envoi["preuves"]["statut"] == "distribue"

    # L'outcome initial "envoye" est créé, l'audit tracé.
    dossier = client.get(f"/dossiers/{dossier_id}", headers=_headers(token)).json()
    assert dossier["outcome"]["statut"] == "envoye"
    audit = client.get("/admin/audit", headers=ADMIN).json()["audit"]
    assert any(a["action"] == "courrier_envoye" and a["acteur"] == "bob" for a in audit)


def test_rbac_role_inconnu_et_moindre_privilege(client):
    assert client.get("/admin/flux", headers={"X-Role": "stagiaire"}).status_code == 403
    assert client.get("/admin/conformite", headers=OPERATEUR).status_code == 403
    assert client.get("/admin/conformite", headers=DPO).status_code == 200


def test_kill_switch_paused_bloque_l_envoi_humain(client):
    dossier_id, token = creer_dossier_analyse(client)
    client.post(f"/dossiers/{dossier_id}/analyser", headers=_headers(token))

    r = client.post(
        "/admin/verticals/depot_garantie/mode", json={"status": "paused"}, headers=ADMIN
    )
    assert r.status_code == 200 and r.json()["status"] == "paused"

    r = client.post(
        f"/admin/dossiers/{dossier_id}/traiter",
        json={"action": "approuver_envoi"},
        headers=OPERATEUR,
    )
    assert r.status_code == 409  # paused → envoi interdit, même humain

    # Retour à la normale (kill switch dans l'autre sens) + trace d'audit.
    client.post("/admin/verticals/depot_garantie/mode", json={"status": "active"}, headers=ADMIN)
    audit = client.get("/admin/audit", headers=ADMIN).json()["audit"]
    assert sum(1 for a in audit if a["action"] == "vertical_mode_change") == 2


def test_escalade_verrouille_pour_operateur(client):
    dossier_id, token = creer_dossier_analyse(client)
    client.post(f"/dossiers/{dossier_id}/analyser", headers=_headers(token))
    client.post(f"/admin/dossiers/{dossier_id}/escalader", headers=OPERATEUR)

    r = client.post(
        f"/admin/dossiers/{dossier_id}/traiter",
        json={"action": "approuver_envoi"},
        headers=OPERATEUR,
    )
    assert r.status_code == 423  # verrouillé tant que l'escalade n'est pas levée

    client.post(
        f"/admin/dossiers/{dossier_id}/lever-escalade",
        headers={"X-Role": "juridique", "X-Acteur": "maitre-durand"},
    )
    r = client.post(
        f"/admin/dossiers/{dossier_id}/traiter",
        json={"action": "approuver_envoi"},
        headers=OPERATEUR,
    )
    assert r.status_code == 200


# --- Leads, analytics, attribution ---------------------------------------------


def test_leads_et_stats_par_campagne(client):
    utm = {"utm_source": "facebook", "utm_campaign": "test-dg-1"}
    for _ in range(4):
        client.post(
            "/evenements",
            json={"type": "visite", "vertical": "frais_bancaires", "source_id": "test-dg-1", "utm": utm},
        )
    r = client.post(
        "/leads",
        json={
            "nom": "Lead Test",
            "email": "lead@example.com",
            "vertical": "frais_bancaires",
            "acquisition": {"canal": "ads", "source_id": "test-dg-1", "utm": utm},
        },
    )
    assert r.status_code == 201

    stats = client.get("/leads/stats").json()["stats"]
    ligne = next(s for s in stats if s["vertical"] == "frais_bancaires" and s["source"] == "test-dg-1")
    assert ligne["visites"] == 4
    assert ligne["leads"] == 1
    assert ligne["taux_conversion"] == 0.25


def test_outcome_et_rapport_partenaire(client):
    client.post(
        "/admin/partenaires",
        json={"code": "ADIL75", "nom": "ADIL Paris", "type": "adil"},
        headers=ADMIN,
    )

    dossier_id, token = creer_dossier_analyse(client)
    client.post(f"/dossiers/{dossier_id}/analyser", headers=_headers(token))
    client.post(
        f"/admin/dossiers/{dossier_id}/traiter",
        json={"action": "approuver_envoi"},
        headers=OPERATEUR,
    )
    r = client.post(
        f"/dossiers/{dossier_id}/outcome",
        json={"statut": "paye_total", "montant_recouvre": 1120.0, "delai_paiement_jours": 21},
        headers=_headers(token),
    )
    assert r.status_code == 200

    rapport = client.get("/admin/partenaires/ADIL75/rapport", headers=OPERATEUR).json()
    assert rapport["volume_dossiers"] == 1
    assert rapport["taux_recouvrement"] == 1.0
    assert rapport["montant_moyen_recouvre"] == 1120.0


def test_outcome_statut_invalide_refuse(client):
    dossier_id, token = creer_dossier_analyse(client)
    r = client.post(
        f"/dossiers/{dossier_id}/outcome", json={"statut": "paye_peut_etre"}, headers=_headers(token)
    )
    assert r.status_code == 422


# --- Automatisation totale (vertical validé par l'avocat) -----------------------


@pytest.fixture()
def vertical_valide_avocat():
    """Simule la validation avocat du vertical depot_garantie : les deux
    verrous juridiques basculent à 'valide', tout le reste est inchangé.
    C'est la SEULE différence avec la prod actuelle — aucune modification de
    code n'est nécessaire pour passer en automatisation totale."""
    import copy

    from core import config_loader

    config = copy.deepcopy(config_loader.charger_config("depot_garantie", forcer_rechargement=True))
    config["juridique"]["statut_validation_avocat"] = "valide"
    config["regime_recouvrement"]["applicable"] = "valide"
    config_loader._cache["depot_garantie"] = config
    yield config
    config_loader.vider_cache()


def test_automatisation_totale_apres_validation_avocat(client, vertical_valide_avocat):
    """Le flux cible : dossier complet → analyse automatique → verdict AUTO →
    courrier parti tout seul, sans aucun appel humain ni /analyser explicite."""
    r = client.post(
        "/dossiers",
        json={"nom": "Jeanne Martin", "email": "jeanne@example.com", "vertical": "depot_garantie"},
    )
    corps = r.json()
    dossier_id, token = corps["dossier_id"], corps["token"]
    client.post(
        f"/dossiers/{dossier_id}/declaration", json=declaration_valide(), headers=_headers(token)
    )

    # Pièce justificative avec couche texte → fiabilité haute.
    with open("tests/fixtures/releve_carriere_exemple.pdf", "rb") as f:
        client.post(
            f"/dossiers/{dossier_id}/documents",
            files={"fichiers": ("bail.pdf", f, "application/pdf")},
            headers=_headers(token),
        )

    # Dernière brique : le mandat. L'analyse ET l'envoi partent tout seuls.
    r = client.post(f"/dossiers/{dossier_id}/mandat", headers=_headers(token))
    analyse = r.json()["analyse_automatique"]
    assert analyse["verdict"]["decision"] == "AUTO"
    assert analyse["verdict"]["motifs"] == []
    assert analyse["envoi"]["id_envoi"].startswith("mock-")

    dossier = client.get(f"/dossiers/{dossier_id}", headers=_headers(token)).json()
    assert dossier["id_envoi"] is not None
    assert dossier["outcome"]["statut"] == "envoye"

    # Relancer l'analyse ne renvoie pas le courrier une deuxième fois.
    r = client.post(f"/dossiers/{dossier_id}/analyser", headers=_headers(token))
    assert r.status_code == 200
    assert "envoi" not in r.json()


def test_blocage_reste_bloquant_meme_vertical_valide(client, vertical_valide_avocat):
    """Litige sur les retenues → confiance sous le seuil → EXCEPTION, même
    avec le vertical entièrement validé : seuls les dossiers propres partent."""
    r = client.post(
        "/dossiers",
        json={"nom": "Cas Litigieux", "email": "l@example.com", "vertical": "depot_garantie"},
    )
    corps = r.json()
    dossier_id, token = corps["dossier_id"], corps["token"]
    declaration = declaration_valide()
    declaration["champs"]["edl_sortie_conforme"] = False
    declaration["champs"]["retenues_bailleur"] = 300.0
    declaration["champs"]["retenues_contestees"] = True
    client.post(f"/dossiers/{dossier_id}/declaration", json=declaration, headers=_headers(token))
    with open("tests/fixtures/releve_carriere_exemple.pdf", "rb") as f:
        client.post(
            f"/dossiers/{dossier_id}/documents",
            files={"fichiers": ("bail.pdf", f, "application/pdf")},
            headers=_headers(token),
        )
    r = client.post(f"/dossiers/{dossier_id}/mandat", headers=_headers(token))
    analyse = r.json()["analyse_automatique"]
    assert analyse["verdict"]["decision"] == "EXCEPTION"
    assert any("confiance" in m for m in analyse["verdict"]["motifs"])
    assert "envoi" not in analyse
