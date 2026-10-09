"""Démonstration en conditions réelles du Module 3, contre un vrai fichier WRF (pas le fichier
synthétique des tests automatisés) : authentification, ingestion, puis les 3 niveaux d'accès
(core / extended / variable au choix). Utilise le même moteur que le serveur (TestClient sur
l'app FastAPI réelle), avec une base SQLite jetable -- pas besoin de lancer uvicorn pour ça.

Usage : python scripts/demo_module3_live.py <chemin_vers_le_fichier_wrfout>
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="anam_demo_")
os.environ.update(
    ENV="dev",
    JWT_SECRET="demo-secret-" + "x" * 40,
    DATABASE_URL=f"sqlite:///{Path(_TMP, 'demo.db').as_posix()}",
    STORAGE_DIR=str(Path(_TMP, "storage")),
    WRF_INCOMING_DIR=str(Path(sys.argv[1]).resolve().parent),
)

import pyotp  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbmod  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User, UserStatus  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.seed import seed_reference_data  # noqa: E402

PASSWORD = "DemoLive1234!"


def main():
    if len(sys.argv) < 2:
        print("Usage : python scripts/demo_module3_live.py <chemin_vers_le_fichier_wrfout>")
        sys.exit(1)
    filename = Path(sys.argv[1]).name

    dbmod.init_db()
    session = dbmod.new_session()
    seed_reference_data(session)
    user = User(email="demo-agent@anam.bf", password_hash=hash_password(PASSWORD),
               role=Role.agent_anam, status=UserStatus.active)
    session.add(user)
    session.commit()
    session.close()

    client = TestClient(app)
    r = client.post("/auth/login", json={"identifier": "demo-agent@anam.bf", "password": PASSWORD})
    body = r.json()
    setup_hdr = {"Authorization": f"Bearer {body['setup_token']}"}
    secret = client.post("/auth/2fa/setup", headers=setup_hdr).json()["secret"]
    r = client.post("/auth/2fa/enable", headers=setup_hdr, json={"code": pyotp.TOTP(secret).now()})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    print("Authentifié comme agent_anam.\n")

    print(f"=== POST /forecasts/ingest ({filename}) ===")
    r = client.post("/forecasts/ingest", json={"filename": filename}, headers=headers)
    run = r.json()
    print(f"status={r.status_code} run_status={run['status']} zones_done={run['zones_done']} "
          f"zones_skipped={run['zones_skipped']} forecast_date={run['forecast_date']}\n")
    run_id = run["id"]

    print("=== GET /forecasts?zone_name=Kaya (core, par défaut) ===")
    r = client.get("/forecasts", params={"zone_name": "Kaya"})
    print(r.json()[0], "\n")

    print("=== GET /forecasts?zone_name=Kaya&fields=extended ===")
    r = client.get("/forecasts", params={"zone_name": "Kaya", "fields": "extended"})
    print(r.json()[0]["extended"], "\n")

    print("=== GET /forecasts/variables (catalogue, 5 premières lignes) ===")
    r = client.get("/forecasts/variables", headers=headers)
    for row in r.json()[:5]:
        print(" ", row)
    print(f"  ... {len(r.json())} variables au total\n")

    print("=== GET /forecasts/raw (SWDOWN, zone_name=Kaya) ===")
    r = client.get("/forecasts/raw", headers=headers,
                   params={"run_id": run_id, "zone_name": "Kaya", "variable": "SWDOWN"})
    print(r.json(), "\n")

    print("=== GET /forecasts/raw (variable=all, zone_name=Kaya) : temps + nombre de resultats ===")
    import time
    t0 = time.time()
    r = client.get("/forecasts/raw", headers=headers,
                   params={"run_id": run_id, "zone_name": "Kaya", "variable": "all"})
    body = r.json()
    print(f"{time.time()-t0:.1f}s -- {len(body['results'])} variables resolues, "
          f"{len(body['errors'])} en erreur (profils verticaux sans niveau, champs statiques...)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
