"""Accès SQLite du backend Juste Retour (multi-verticaux).

Tables :
- dossiers            : dossiers de réclamation (tous verticaux pipeline)
- documents           : pièces uploadées
- annees_carriere     : données extraites du vertical pension_cnav (gelé)
- leads               : capture de leads des landings (tous verticaux)
- evenements          : analytics (visite / clic / soumission, UTM)
- outcomes            : boucle de résultats (issue de chaque dossier)
- partenaires         : codes prescripteurs (attribution)
- audit_log           : journal d'audit (RGPD art. 5.2 + qualité)
- verticals_etat      : overrides runtime mode/status par vertical (kill switch)

Les schémas Pydantic communs vivent dans `core/schemas.py` ; les schémas
spécifiques à un vertical dans `verticals/<slug>/calc_plugin.py`.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from core.schemas import Fiabilite, StatutDossier, TypeDocument

DB_PATH = Path(__file__).resolve().parent.parent / "juste_retour.db"


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS dossiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vertical_slug TEXT NOT NULL,
                nom TEXT NOT NULL,
                email TEXT NOT NULL,
                statut TEXT NOT NULL DEFAULT 'cree',
                cree_le TEXT NOT NULL,
                mandat_signe INTEGER NOT NULL DEFAULT 0,
                declaration TEXT,                -- JSON : faits déclarés (depot_garantie...)
                type_debiteur TEXT,              -- particulier | pro | administration
                rapport_anomalies TEXT,
                projet_courrier TEXT,
                verdict TEXT,                    -- AUTO | EXCEPTION
                motifs_exception TEXT,           -- JSON list
                confiance REAL,
                montant_estime REAL,
                score_recouvrabilite REAL,
                score_version TEXT,
                regles_version TEXT,
                escalade_avocat INTEGER NOT NULL DEFAULT 0,
                traite_par TEXT,                 -- opérateur ayant traité l'exception
                id_envoi TEXT,
                canal_envoi TEXT,
                statut_envoi TEXT,
                preuves_envoi TEXT,              -- JSON
                acquisition_canal TEXT NOT NULL DEFAULT 'organique',
                acquisition_source_id TEXT NOT NULL DEFAULT '',
                acquisition_utm TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dossier_id INTEGER NOT NULL REFERENCES dossiers(id),
                fichier TEXT NOT NULL,
                type TEXT NOT NULL,
                pages INTEGER NOT NULL DEFAULT 0,
                fiabilite_ocr TEXT NOT NULL,
                chemin_stockage TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS annees_carriere (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dossier_id INTEGER NOT NULL REFERENCES dossiers(id),
                annee INTEGER NOT NULL,
                salaire_reporte REAL,
                trimestres INTEGER NOT NULL DEFAULT 0,
                origine TEXT NOT NULL,
                source TEXT NOT NULL,
                fiabilite TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vertical_slug TEXT NOT NULL,
                nom TEXT NOT NULL,
                email TEXT NOT NULL,
                cree_le TEXT NOT NULL,
                acquisition_canal TEXT NOT NULL DEFAULT 'organique',
                acquisition_source_id TEXT NOT NULL DEFAULT '',
                acquisition_utm TEXT NOT NULL DEFAULT '{}',
                pieces_declarees TEXT
            );

            CREATE TABLE IF NOT EXISTS evenements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,              -- visite | clic | soumission
                vertical_slug TEXT NOT NULL,
                horodatage TEXT NOT NULL,
                acquisition_source_id TEXT NOT NULL DEFAULT '',
                acquisition_utm TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS outcomes (
                dossier_id INTEGER PRIMARY KEY REFERENCES dossiers(id),
                vertical_slug TEXT NOT NULL,
                verdict_initial TEXT NOT NULL,
                montant_reclame REAL NOT NULL,
                montant_recouvre REAL,
                statut TEXT NOT NULL,
                delai_reponse_jours INTEGER,
                delai_paiement_jours INTEGER,
                profil_debiteur_type TEXT NOT NULL,
                profil_debiteur_features TEXT NOT NULL DEFAULT '{}',
                canal_resolution TEXT NOT NULL DEFAULT 'courrier_seul',
                timestamps TEXT NOT NULL DEFAULT '{}',
                maj_le TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS partenaires (
                code TEXT PRIMARY KEY,
                nom TEXT NOT NULL,
                type TEXT NOT NULL,              -- adil | association | agence | autre
                cree_le TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                horodatage TEXT NOT NULL,
                acteur TEXT NOT NULL,            -- 'systeme' ou identifiant humain
                role TEXT NOT NULL,
                action TEXT NOT NULL,
                dossier_id INTEGER,
                vertical_slug TEXT,
                details TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS verticals_etat (
                slug TEXT PRIMARY KEY,
                mode_override TEXT,
                status_override TEXT,
                maj_le TEXT NOT NULL,
                maj_par TEXT NOT NULL
            );
            """
        )


# --- Audit -----------------------------------------------------------------


def journaliser(
    acteur: str,
    role: str,
    action: str,
    dossier_id: Optional[int] = None,
    vertical_slug: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO audit_log (horodatage, acteur, role, action, dossier_id, vertical_slug, details)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                _maintenant(),
                acteur,
                role,
                action,
                dossier_id,
                vertical_slug,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )


def lire_audit(limite: int = 200) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()


# --- État runtime des verticaux (kill switch) --------------------------------


def get_etat_vertical(slug: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM verticals_etat WHERE slug = ?", (slug,)
        ).fetchone()


def set_etat_vertical(
    slug: str,
    mode_override: Optional[str],
    status_override: Optional[str],
    par: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO verticals_etat (slug, mode_override, status_override, maj_le, maj_par)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(slug) DO UPDATE SET
                 mode_override = excluded.mode_override,
                 status_override = excluded.status_override,
                 maj_le = excluded.maj_le,
                 maj_par = excluded.maj_par""",
            (slug, mode_override, status_override, _maintenant(), par),
        )


def resoudre_mode_et_status(slug: str, config: dict[str, Any]) -> tuple[str, str]:
    """Mode et status effectifs = override runtime (kill switch) s'il existe,
    sinon la valeur de la config versionnée."""
    etat = get_etat_vertical(slug)
    mode = (etat["mode_override"] if etat and etat["mode_override"] else None) or config.get(
        "mode", "smoke_test"
    )
    status = (etat["status_override"] if etat and etat["status_override"] else None) or config.get(
        "status", "draft"
    )
    return mode, status


# --- Dossiers ----------------------------------------------------------------


def creer_dossier(
    nom: str,
    email: str,
    vertical_slug: str,
    acquisition_canal: str = "organique",
    acquisition_source_id: str = "",
    acquisition_utm: Optional[dict] = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO dossiers
               (vertical_slug, nom, email, statut, cree_le,
                acquisition_canal, acquisition_source_id, acquisition_utm)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                vertical_slug,
                nom,
                email,
                StatutDossier.CREE.value,
                _maintenant(),
                acquisition_canal,
                acquisition_source_id,
                json.dumps(acquisition_utm or {}, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def get_dossier(dossier_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM dossiers WHERE id = ?", (dossier_id,)).fetchone()


def maj_dossier(dossier_id: int, **champs: Any) -> None:
    """Mise à jour partielle d'un dossier ; les dicts/lists sont sérialisés en JSON."""
    if not champs:
        return
    colonnes, valeurs = [], []
    for cle, valeur in champs.items():
        if isinstance(valeur, (dict, list)):
            valeur = json.dumps(valeur, ensure_ascii=False)
        colonnes.append(f"{cle} = ?")
        valeurs.append(valeur)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE dossiers SET {', '.join(colonnes)} WHERE id = ?",
            (*valeurs, dossier_id),
        )


def lister_dossiers(
    verdict: Optional[str] = None, escalade_avocat: Optional[bool] = None
) -> list[sqlite3.Row]:
    requete = "SELECT * FROM dossiers"
    conditions, params = [], []
    if verdict is not None:
        conditions.append("verdict = ?")
        params.append(verdict)
    if escalade_avocat is not None:
        conditions.append("escalade_avocat = ?")
        params.append(int(escalade_avocat))
    if conditions:
        requete += " WHERE " + " AND ".join(conditions)
    requete += " ORDER BY id DESC"
    with get_connection() as conn:
        return conn.execute(requete, params).fetchall()


# --- Documents / données extraites -------------------------------------------


def ajouter_document(
    dossier_id: int,
    fichier: str,
    type_document: TypeDocument,
    pages: int,
    fiabilite_ocr: Fiabilite,
    chemin_stockage: str,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO documents
               (dossier_id, fichier, type, pages, fiabilite_ocr, chemin_stockage)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (dossier_id, fichier, type_document.value, pages, fiabilite_ocr.value, chemin_stockage),
        )
        return int(cur.lastrowid)


def get_documents(dossier_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM documents WHERE dossier_id = ?", (dossier_id,)
        ).fetchall()


def ajouter_annee_carriere(
    dossier_id: int,
    annee: int,
    salaire_reporte: Optional[float],
    trimestres: int,
    origine: str,
    source: str,
    fiabilite: Fiabilite,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO annees_carriere
               (dossier_id, annee, salaire_reporte, trimestres, origine, source, fiabilite)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (dossier_id, annee, salaire_reporte, trimestres, origine, source, fiabilite.value),
        )
        return int(cur.lastrowid)


def get_annees_carriere(dossier_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM annees_carriere WHERE dossier_id = ? ORDER BY annee",
            (dossier_id,),
        ).fetchall()


# --- Leads & analytics ---------------------------------------------------------


def creer_lead(
    vertical_slug: str,
    nom: str,
    email: str,
    acquisition_canal: str = "organique",
    acquisition_source_id: str = "",
    acquisition_utm: Optional[dict] = None,
    pieces_declarees: Optional[list[str]] = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO leads
               (vertical_slug, nom, email, cree_le,
                acquisition_canal, acquisition_source_id, acquisition_utm, pieces_declarees)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                vertical_slug,
                nom,
                email,
                _maintenant(),
                acquisition_canal,
                acquisition_source_id,
                json.dumps(acquisition_utm or {}, ensure_ascii=False),
                json.dumps(pieces_declarees or [], ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def enregistrer_evenement(
    type_evenement: str,
    vertical_slug: str,
    acquisition_source_id: str = "",
    acquisition_utm: Optional[dict] = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO evenements (type, vertical_slug, horodatage, acquisition_source_id, acquisition_utm)
               VALUES (?, ?, ?, ?, ?)""",
            (
                type_evenement,
                vertical_slug,
                _maintenant(),
                acquisition_source_id,
                json.dumps(acquisition_utm or {}, ensure_ascii=False),
            ),
        )


def stats_leads() -> list[dict]:
    """Visites, leads et taux de conversion, par vertical et par campagne
    (utm_campaign ou code partenaire)."""
    with get_connection() as conn:
        visites = conn.execute(
            """SELECT vertical_slug, acquisition_source_id, COUNT(*) AS n
               FROM evenements WHERE type = 'visite'
               GROUP BY vertical_slug, acquisition_source_id"""
        ).fetchall()
        leads = conn.execute(
            """SELECT vertical_slug, acquisition_source_id, COUNT(*) AS n
               FROM leads GROUP BY vertical_slug, acquisition_source_id"""
        ).fetchall()

    par_cle: dict[tuple[str, str], dict] = {}
    for row in visites:
        cle = (row["vertical_slug"], row["acquisition_source_id"])
        par_cle.setdefault(
            cle, {"vertical": cle[0], "source": cle[1], "visites": 0, "leads": 0}
        )["visites"] = row["n"]
    for row in leads:
        cle = (row["vertical_slug"], row["acquisition_source_id"])
        par_cle.setdefault(
            cle, {"vertical": cle[0], "source": cle[1], "visites": 0, "leads": 0}
        )["leads"] = row["n"]

    resultats = []
    for stats in par_cle.values():
        stats["taux_conversion"] = (
            round(stats["leads"] / stats["visites"], 3) if stats["visites"] else None
        )
        resultats.append(stats)
    return sorted(resultats, key=lambda s: (s["vertical"], s["source"]))


# --- Outcomes -------------------------------------------------------------------


def upsert_outcome(dossier_id: int, champs: dict[str, Any]) -> None:
    serialise = {
        cle: json.dumps(valeur, ensure_ascii=False) if isinstance(valeur, (dict, list)) else valeur
        for cle, valeur in champs.items()
    }
    serialise["maj_le"] = _maintenant()
    colonnes = ", ".join(["dossier_id", *serialise.keys()])
    placeholders = ", ".join(["?"] * (len(serialise) + 1))
    maj = ", ".join(f"{c} = excluded.{c}" for c in serialise)
    with get_connection() as conn:
        conn.execute(
            f"""INSERT INTO outcomes ({colonnes}) VALUES ({placeholders})
                ON CONFLICT(dossier_id) DO UPDATE SET {maj}""",
            (dossier_id, *serialise.values()),
        )


def get_outcome(dossier_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM outcomes WHERE dossier_id = ?", (dossier_id,)
        ).fetchone()


def lister_outcomes(vertical_slug: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM outcomes WHERE vertical_slug = ?", (vertical_slug,)
        ).fetchall()
    return [dict(r) for r in rows]


# --- Partenaires ------------------------------------------------------------------


def creer_partenaire(code: str, nom: str, type_partenaire: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO partenaires (code, nom, type, cree_le) VALUES (?, ?, ?, ?)",
            (code, nom, type_partenaire, _maintenant()),
        )


def get_partenaire(code: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM partenaires WHERE code = ?", (code,)).fetchone()


def rapport_partenaire(code: str) -> dict:
    """Volume, taux d'éligibilité, taux de recouvrement, montant moyen —
    la donnée qui permet de comparer le CAC ads vs prescription."""
    with get_connection() as conn:
        nb_leads = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE acquisition_source_id = ?", (code,)
        ).fetchone()["n"]
        dossiers = conn.execute(
            "SELECT * FROM dossiers WHERE acquisition_source_id = ?", (code,)
        ).fetchall()
        outcomes = conn.execute(
            """SELECT o.* FROM outcomes o
               JOIN dossiers d ON d.id = o.dossier_id
               WHERE d.acquisition_source_id = ?""",
            (code,),
        ).fetchall()

    nb_dossiers = len(dossiers)
    evalues = [d for d in dossiers if d["verdict"] is not None]
    eligibles = [d for d in evalues if d["verdict"] == "AUTO"]
    termines = [o for o in outcomes if o["statut"] in ("paye_total", "paye_partiel", "refus", "sans_reponse", "abandonne")]
    recouvres = [o for o in termines if o["statut"] in ("paye_total", "paye_partiel")]
    montants = [o["montant_recouvre"] for o in recouvres if o["montant_recouvre"] is not None]

    return {
        "code": code,
        "volume_leads": nb_leads,
        "volume_dossiers": nb_dossiers,
        "taux_eligibilite": round(len(eligibles) / len(evalues), 3) if evalues else None,
        "taux_recouvrement": round(len(recouvres) / len(termines), 3) if termines else None,
        "montant_moyen_recouvre": round(sum(montants) / len(montants), 2) if montants else None,
    }
