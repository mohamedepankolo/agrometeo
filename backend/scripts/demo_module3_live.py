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


def show(title, obj):
    import json

    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    print(json.dumps(obj, indent=2, ensure_ascii=False))


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

    r = client.get("/forecasts/incoming", headers=headers)
    show("GET /forecasts/incoming", r.json())

    r = client.post("/forecasts/ingest", json={"filename": filename}, headers=headers)
    show(f'POST /forecasts/ingest {{"filename": "{filename}"}}', r.json())
    run_id = r.json()["id"]

    r = client.get(f"/forecasts/runs/{run_id}", headers=headers)
    show(f"GET /forecasts/runs/{run_id}", r.json())

    r = client.get("/forecasts", params={"pilot_only": True})
    show("GET /forecasts?pilot_only=true  (core, 5 communes pilotes)", r.json())

    r = client.get("/forecasts", params={"zone_name": "Kaya", "fields": "extended"})
    show("GET /forecasts?zone_name=Kaya&fields=extended", r.json())

    r = client.get("/forecasts/variables", headers=headers)
    rows = r.json()
    show(f"GET /forecasts/variables  (catalogue complet, {len(rows)} variables -- 8 premières)", rows[:8])

    r = client.get("/forecasts/raw", headers=headers,
                   params={"run_id": run_id, "zone_name": "Kaya", "variable": "SWDOWN"})
    show("GET /forecasts/raw?...&zone_name=Kaya&variable=SWDOWN", r.json())

    r = client.get("/forecasts/raw", headers=headers,
                   params={"run_id": run_id, "zone_name": "Kaya", "variable": ["T2", "U10", "V10"]})
    show("GET /forecasts/raw?...&variable=T2&variable=U10&variable=V10", r.json())

    import time
    t0 = time.time()
    r = client.get("/forecasts/raw", headers=headers,
                   params={"run_id": run_id, "zone_name": "Kaya", "variable": "all"})
    elapsed = time.time() - t0
    body = r.json()
    print(f"\n{'=' * 78}\nGET /forecasts/raw?...&variable=all  ({elapsed:.1f}s)\n{'=' * 78}")
    print(f"{len(body['results'])} variables résolues, {len(body['errors'])} en erreur "
          f"(profils verticaux sans niveau, champs statiques...)")
    print("5 premières résolues :", list(body["results"])[:5])
    print("5 premières en erreur :", list(body["errors"])[:5])


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
