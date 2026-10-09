"""Module 3 (prévisions WRF) : ingestion d'un fichier wrfout et consultation des résumés par zone.

Un vrai fichier wrfout fait plusieurs Go : les tests en fabriquent un minuscule mais structurellement
identique (mêmes variables/dimensions que les fichiers réels) via netCDF4, pour exercer la vraie
logique d'extraction (module3/wrf_reader.py) plutôt qu'une version simulée."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.config import get_settings
from app.models import Role

# Point au centre de la mini-grille de test ; loin de tout point -> hors domaine.
IN_DOMAIN = (12.70, -1.30)
OUT_OF_DOMAIN = (48.8566, 2.3522)  # Paris


def _write_fake_wrfout(path: Path) -> None:
    import netCDF4

    n_time, ny, nx = 3, 4, 5
    ds = netCDF4.Dataset(path, "w", format="NETCDF4")
    try:
        ds.createDimension("Time", n_time)
        ds.createDimension("DateStrLen", 19)
        ds.createDimension("south_north", ny)
        ds.createDimension("west_east", nx)
        ds.createDimension("soil_layers_stag", 4)

        times = ds.createVariable("Times", "S1", ("Time", "DateStrLen"))
        labels = ["2022-05-23_00:00:00", "2022-05-23_12:00:00", "2022-05-23_23:00:00"]
        for t, label in enumerate(labels):
            times[t, :] = np.array(list(label), dtype="S1")

        lat0, lon0, step = 12.5, -1.6, 0.1
        lat2d = np.array([[lat0 + j * step for _ in range(nx)] for j in range(ny)])
        lon2d = np.array([[lon0 + i * step for i in range(nx)] for _ in range(ny)])
        xlat = ds.createVariable("XLAT", "f4", ("Time", "south_north", "west_east"))
        xlong = ds.createVariable("XLONG", "f4", ("Time", "south_north", "west_east"))
        for t in range(n_time):
            xlat[t] = lat2d
            xlong[t] = lon2d

        def surf(name, fill):
            var = ds.createVariable(name, "f4", ("Time", "south_north", "west_east"))
            var[:] = fill
            return var

        # T2 varie avec le temps pour donner un min/max/mean distincts (301.15K=28C .. 308.15K=35C)
        t2 = ds.createVariable("T2", "f4", ("Time", "south_north", "west_east"))
        for t, val in enumerate([301.15, 308.15, 303.15]):
            t2[t] = val
        surf("Q2", 0.012)
        surf("PSFC", 97000.0)
        surf("U10", 2.0)
        surf("V10", 1.0)
        # RAINC/RAINNC : cumuls croissants -> 5 mm de pluie dans la journée
        rainc = ds.createVariable("RAINC", "f4", ("Time", "south_north", "west_east"))
        rainnc = ds.createVariable("RAINNC", "f4", ("Time", "south_north", "west_east"))
        for t, val in enumerate([0.0, 2.0, 3.0]):
            rainc[t] = val
            rainnc[t] = val * 0.5

        # Variables etendues (module3.wrf_reader.EXTENDED_VARIABLES)
        surf("CLDFRAC2D", 0.6)
        surf("SWDOWN", 250.0)
        surf("GLW", 400.0)
        surf("PBLH", 900.0)
        soil = ds.createVariable("SMOIS", "f4", ("Time", "soil_layers_stag", "south_north", "west_east"))
        soil[:] = 0.15  # m3/m3 (-> 15 % une fois mis a l'echelle)
        tslb = ds.createVariable("TSLB", "f4", ("Time", "soil_layers_stag", "south_north", "west_east"))
        tslb[:] = 303.15  # K (-> 30 C)
    finally:
        ds.close()


@pytest.fixture
def wrf_file(tmp_path, monkeypatch):
    incoming = tmp_path / "wrf_incoming"
    incoming.mkdir()
    # Note Windows : la convention WRF ("wrfout_d02_2022-05-23_01:00:00") met des ':' dans le nom.
    # NTFS/Win32 les refuse à la création ET à l'ouverture (CreateFile), que ce soit un disque USB
    # ou le disque système -- ce n'est pas un détail du périphérique, c'est l'API Windows qui bloque
    # ces noms. Un fichier déposé par un outil Linux (ntfs-3g) peut exister avec ces ':' et rester
    # lisible via un outil bas niveau (7-Zip sur le volume brut), mais pas via les API normales -- un
    # fichier WRF reçu doit donc être renommé (':' -> '-') avant d'être placé dans wrf_incoming_dir
    # sur un serveur Windows. Un serveur Linux n'a pas cette contrainte. Voir module3/README.md.
    filename = "wrfout_d02_2022-05-23_01-00-00"
    _write_fake_wrfout(incoming / filename)
    monkeypatch.setattr(get_settings(), "wrf_incoming_dir", str(incoming))
    return filename


@pytest.fixture
def no_preexisting_zones(db):
    """Les communes pilotes seedées par défaut ont de vraies coordonnées (Module 3) qui tombent
    parfois près de la minuscule grille synthétique de ces tests : on repart d'une table vide
    pour que les tests contrôlent entièrement les zones en présence."""
    from app.models_content import Zone

    db.query(Zone).delete()
    db.commit()


@pytest.fixture
def pilot_zone(db, no_preexisting_zones):
    from app.models_content import Zone, ZoneKind

    zone = Zone(name="Kaya-test", kind=ZoneKind.commune, is_pilot=True, commune_names=["Kaya-test"],
                latitude=IN_DOMAIN[0], longitude=IN_DOMAIN[1])
    db.add(zone)
    db.commit()
    return zone


@pytest.fixture
def far_zone(db, no_preexisting_zones):
    from app.models_content import Zone, ZoneKind

    zone = Zone(name="Paris-test", kind=ZoneKind.commune, is_pilot=False, commune_names=[],
                latitude=OUT_OF_DOMAIN[0], longitude=OUT_OF_DOMAIN[1])
    db.add(zone)
    db.commit()
    return zone


@pytest.fixture
def other_zone(db, no_preexisting_zones):
    """Une commune non pilote mais dans le domaine (contrairement a far_zone) : pour distinguer
    pilot_only=true (qui doit l'exclure) d'un simple hors-domaine (qui l'exclurait de toute facon)."""
    from app.models_content import Zone, ZoneKind

    zone = Zone(name="Ziniare-test", kind=ZoneKind.commune, is_pilot=False, commune_names=["Ziniare-test"],
                latitude=IN_DOMAIN[0] + 0.05, longitude=IN_DOMAIN[1] + 0.05)
    db.add(zone)
    db.commit()
    return zone


def test_wrf_reader_extracts_plausible_daily_summary(wrf_file, tmp_path):
    """Logique pure (module3/wrf_reader.py), sans passer par l'API."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "module3"))
    import wrf_reader

    path = Path(get_settings().wrf_incoming_dir) / wrf_file
    summary = wrf_reader.daily_summary_at_point(wrf_reader.open_wrf(path), *IN_DOMAIN)
    assert summary.forecast_date == "2022-05-23"
    assert summary.distance_km < 1.0  # point demandé == point de grille généré
    assert summary.temp_min_c == pytest.approx(28.0, abs=0.1)
    assert summary.temp_max_c == pytest.approx(35.0, abs=0.1)
    assert summary.precip_total_mm == pytest.approx(4.5, abs=0.1)  # (3+1.5) - (0+0)
    assert summary.wind_speed_mean_ms == pytest.approx((2.0**2 + 1.0**2) ** 0.5, abs=0.01)
    assert 0 < summary.humidity_mean_pct <= 100


def test_ingest_requires_content_manage_permission(client, wrf_file):
    r = client.post("/forecasts/ingest", json={"filename": wrf_file})
    assert r.status_code == 401

    r = client.post("/forecasts/ingest", json={"filename": wrf_file}, headers={"Authorization": "Bearer invalid"})
    assert r.status_code == 401


def test_ingest_missing_file_marks_run_failed(client, staff):
    r = client.post("/forecasts/ingest", json={"filename": "wrfout_d02_2099-01-01_00:00:00"},
                    headers=staff(Role.agent_anam))
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]

    r = client.get(f"/forecasts/runs/{run_id}", headers=staff(Role.agent_anam))
    body = r.json()
    assert body["status"] == "failed"
    assert "introuvable" in body["error"]


def test_ingest_then_list_forecasts(client, staff, wrf_file, pilot_zone, far_zone):
    headers = staff(Role.agent_anam)
    r = client.post("/forecasts/ingest", json={"filename": wrf_file}, headers=headers)
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    assert r.json()["status"] == "processing"  # état au moment de la réponse, avant la tâche de fond

    # la tâche de fond a déjà tourné (TestClient l'exécute de façon synchrone) : un second appel
    # relit l'état final en base, comme le ferait un vrai client qui "repolle" GET /forecasts/runs/{id}.
    run = client.get(f"/forecasts/runs/{run_id}", headers=headers).json()
    assert run["status"] == "ready"
    assert run["forecast_date"] == "2022-05-23"
    assert run["zones_done"] == 1  # pilot_zone seulement : far_zone est hors domaine
    assert run["zones_skipped"] == 1

    # liste publique, sans authentification
    r = client.get("/forecasts")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    item = items[0]
    assert item["zone_name"] == "Kaya-test"
    assert item["forecast_date"] == "2022-05-23"
    assert item["temp_max_c"] == pytest.approx(35.0, abs=0.1)
    assert item["precip_total_mm"] == pytest.approx(4.5, abs=0.1)

    r = client.get("/forecasts", params={"zone_id": pilot_zone.id})
    assert len(r.json()) == 1

    r = client.get("/forecasts", params={"forecast_date": "2099-12-31"})
    assert r.json() == []


def test_list_forecasts_pilot_only_and_zone_name(client, staff, wrf_file, pilot_zone, other_zone):
    """pilot_zone (is_pilot=True) et other_zone (is_pilot=False, mais dans le domaine) : de quoi
    distinguer pilot_only=true d'un simple filtre géographique."""
    r = client.post("/forecasts/ingest", json={"filename": wrf_file}, headers=staff(Role.agent_anam))
    assert r.status_code == 202, r.text

    r = client.get("/forecasts")
    assert {item["zone_name"] for item in r.json()} == {"Kaya-test", "Ziniare-test"}

    r = client.get("/forecasts", params={"pilot_only": True})
    items = r.json()
    assert len(items) == 1 and items[0]["zone_name"] == "Kaya-test"

    # zone_name : exact, insensible a la casse -- alternative a zone_id quand on ne le connait pas
    r = client.get("/forecasts", params={"zone_name": "kaya-TEST"})
    assert len(r.json()) == 1 and r.json()[0]["zone_name"] == "Kaya-test"

    r = client.get("/forecasts", params={"zone_name": "Commune-Inexistante"})
    assert r.json() == []


def test_ingest_same_file_twice_conflicts(client, staff, wrf_file):
    headers = staff(Role.agent_anam)
    r1 = client.post("/forecasts/ingest", json={"filename": wrf_file}, headers=headers)
    assert r1.status_code == 202
    r2 = client.post("/forecasts/ingest", json={"filename": wrf_file}, headers=headers)
    assert r2.status_code == 409


def test_list_incoming_files(client, staff, wrf_file):
    r = client.get("/forecasts/incoming", headers=staff(Role.agent_anam))
    assert r.status_code == 200
    assert wrf_file in r.json()


def test_list_variables_catalog(client, staff):
    r = client.get("/forecasts/variables", headers=staff(Role.agent_anam))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 242
    by_name = {v["name"]: v for v in rows}
    assert by_name["T2"]["in_core"] is True and by_name["T2"]["in_extended"] is False
    assert by_name["SWDOWN"]["in_core"] is False and by_name["SWDOWN"]["in_extended"] is True
    assert by_name["HGT"]["in_core"] is False and by_name["HGT"]["in_extended"] is False


def test_list_forecasts_fields_core_vs_extended(client, staff, wrf_file, pilot_zone):
    client.post("/forecasts/ingest", json={"filename": wrf_file}, headers=staff(Role.agent_anam))

    core = client.get("/forecasts").json()[0]
    assert core["extended"] is None

    ext = client.get("/forecasts", params={"fields": "extended"}).json()[0]
    assert ext["extended"]["nebulosite_pct"] == pytest.approx(60.0, abs=0.1)
    assert ext["extended"]["temperature_sol_c"] == pytest.approx(30.0, abs=0.1)


def test_raw_variable_single_and_all(client, staff, wrf_file, pilot_zone):
    headers = staff(Role.agent_anam)
    r = client.post("/forecasts/ingest", json={"filename": wrf_file}, headers=headers)
    run_id = r.json()["id"]

    # une seule variable, par zone_name
    r = client.get("/forecasts/raw", headers=headers,
                   params={"run_id": run_id, "zone_name": "Kaya-test", "variable": "SWDOWN"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["zone_name"] == "Kaya-test"
    assert body["results"]["SWDOWN"]["mean"] == pytest.approx(250.0, abs=0.1)
    assert len(body["results"]["SWDOWN"]["hourly_values"]) == 3  # 3 echeances dans le fichier de test

    # variable a 4 dimensions sans level -> erreur rapportee, pas une exception serveur
    r = client.get("/forecasts/raw", headers=headers,
                   params={"run_id": run_id, "zone_id": pilot_zone.id, "variable": "SMOIS"})
    assert r.status_code == 200
    assert "SMOIS" in r.json()["errors"]

    # avec level
    r = client.get("/forecasts/raw", headers=headers,
                   params={"run_id": run_id, "zone_id": pilot_zone.id, "variable": "SMOIS", "level": 0})
    assert r.json()["results"]["SMOIS"]["mean"] == pytest.approx(0.15, abs=0.001)

    # plusieurs variables d'un coup
    r = client.get("/forecasts/raw", headers=headers, params={
        "run_id": run_id, "zone_id": pilot_zone.id, "variable": ["T2", "U10"],
    })
    assert set(r.json()["results"]) == {"T2", "U10"}

    # "all" -> les 242 (dont beaucoup en erreur : statiques, profils verticaux sans level...)
    r = client.get("/forecasts/raw", headers=headers,
                   params={"run_id": run_id, "zone_id": pilot_zone.id, "variable": "all"})
    assert r.status_code == 200
    body = r.json()
    assert "T2" in body["results"] and "SWDOWN" in body["results"]


def test_raw_variable_requires_source_file_still_present(client, staff, wrf_file, pilot_zone):
    headers = staff(Role.agent_anam)
    r = client.post("/forecasts/ingest", json={"filename": wrf_file}, headers=headers)
    run_id = r.json()["id"]

    import os
    os.remove(Path(get_settings().wrf_incoming_dir) / wrf_file)

    r = client.get("/forecasts/raw", headers=headers,
                   params={"run_id": run_id, "zone_id": pilot_zone.id, "variable": "T2"})
    assert r.status_code == 409
