"""Module 2 (observations de stations météo) : ingestion d'exports GeoJSON et consultation des
relevés réels par station.

Les fichiers reçus de l'ANAM font ~20 Ko (pas plusieurs Go comme le Module 3) : les tests
fabriquent de petits GeoJSON structurellement identiques, pas de données simulées à part."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.models import Role


def _write_geojson(path: Path, kind_props: dict, date: str, stations: dict[str, tuple[float, float]]) -> None:
    """`stations` : {nom: (lat, lon)}. `kind_props` : valeurs communes à toutes les stations pour
    ce fichier (ex. {"tmin": 20.0, "tmax": 30.0})."""
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"stations": name, "date": date, **kind_props},
        }
        for name, (lat, lon) in stations.items()
    ]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")


@pytest.fixture
def incoming(tmp_path, monkeypatch):
    d = tmp_path / "observations_incoming"
    d.mkdir()
    monkeypatch.setattr(get_settings(), "observations_incoming_dir", str(d))
    return d


STATIONS = {"Kaya-test": (13.0914, -1.0847), "Ziniare-test": (12.5833, -1.3)}


def test_geojson_reader_detects_kind_and_parses_records(incoming):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "module2"))
    import geojson_reader

    path = incoming / "exporttemp.geojson"
    _write_geojson(path, {"tmin": 22.5, "tmax": 34.0}, "2026-10-08", STATIONS)
    export = geojson_reader.read_export(path)
    assert export["kind"] == "temperature"
    assert export["date"] == "2026-10-08"
    assert {r["station"] for r in export["records"]} == set(STATIONS)
    record = next(r for r in export["records"] if r["station"] == "Kaya-test")
    assert record["tmin"] == 22.5 and record["tmax"] == 34.0
    assert record["latitude"] == pytest.approx(13.0914)
    assert record["longitude"] == pytest.approx(-1.0847)


def test_geojson_reader_rejects_mixed_dates(incoming):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "module2"))
    import geojson_reader

    path = incoming / "bad.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-1.0847, 13.0914]},
             "properties": {"stations": "Kaya-test", "date": "2026-10-08", "tmin": 20.0, "tmax": 30.0}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-1.3, 12.5833]},
             "properties": {"stations": "Ziniare-test", "date": "2026-10-09", "tmin": 21.0, "tmax": 31.0}},
        ],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="Date incohérente"):
        geojson_reader.read_export(path)


def test_ingest_requires_content_manage_permission(client, incoming):
    _write_geojson(incoming / "exporttemp.geojson", {"tmin": 20.0, "tmax": 30.0}, "2026-10-08", STATIONS)
    r = client.post("/observations/ingest", json={"filename": "exporttemp.geojson"})
    assert r.status_code == 401

    r = client.post("/observations/ingest", json={"filename": "exporttemp.geojson"},
                    headers={"Authorization": "Bearer invalid"})
    assert r.status_code == 401


def test_ingest_rejects_path_traversal_filename(client, staff, incoming, tmp_path):
    """`filename` isole son nom de base avant d'être joint à observations_incoming_dir : un nom
    avec '..' ou un chemin absolu ne doit jamais désigner un fichier hors de ce dossier."""
    outside = tmp_path / "outside.json"
    outside.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    r = client.post("/observations/ingest", json={"filename": f"../{outside.name}"}, headers=staff(Role.agent_anam))
    assert r.status_code == 404  # cherché dans observations_incoming_dir, pas trouvé (attendu)

    r = client.post("/observations/ingest", json={"filename": str(outside)}, headers=staff(Role.agent_anam))
    assert r.status_code == 404  # chemin absolu : seul le nom de fichier final est retenu


def test_ingest_missing_file_returns_404(client, staff, incoming):
    r = client.post("/observations/ingest", json={"filename": "ne-existe-pas.geojson"},
                    headers=staff(Role.agent_anam))
    assert r.status_code == 404


def test_list_incoming_files(client, staff, incoming):
    _write_geojson(incoming / "exporttemp.geojson", {"tmin": 20.0, "tmax": 30.0}, "2026-10-08", STATIONS)
    r = client.get("/observations/incoming", headers=staff(Role.agent_anam))
    assert r.status_code == 200
    assert r.json() == ["exporttemp.geojson"]


def test_ingest_creates_stations_then_merges_second_variable(client, staff, incoming):
    """Température ingérée d'abord (crée les stations), puis humidité pour le même jour : la
    même ligne d'observation se complète au lieu d'en créer une nouvelle."""
    _write_geojson(incoming / "exporttemp.geojson", {"tmin": 22.5, "tmax": 34.0}, "2026-10-08", STATIONS)
    _write_geojson(incoming / "exportrelhum.geojson", {"umin": 25.0, "umax": 60.0}, "2026-10-08", STATIONS)

    r = client.post("/observations/ingest", json={"filename": "exporttemp.geojson"}, headers=staff(Role.agent_anam))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"kind": "temperature", "observed_date": "2026-10-08", "stations_created": 2, "stations_updated": 0}

    r = client.get("/observations/stations")
    assert r.status_code == 200
    assert {s["name"] for s in r.json()} == set(STATIONS)

    r = client.post("/observations/ingest", json={"filename": "exportrelhum.geojson"}, headers=staff(Role.agent_anam))
    assert r.status_code == 200, r.text
    body = r.json()
    # Mêmes stations déjà créées à l'étape précédente : la ligne d'observation du jour existe déjà
    # (créée par l'ingestion température), donc "mise à jour", pas "créée" -- même si de nouvelles
    # colonnes (humidité) se remplissent pour la première fois.
    assert body == {"kind": "humidite", "observed_date": "2026-10-08", "stations_created": 0, "stations_updated": 2}

    r = client.get("/observations", params={"station_name": "Kaya-test"})
    assert r.status_code == 200
    [obs] = r.json()
    assert obs["observed_date"] == "2026-10-08"
    assert obs["temp_min_c"] == 22.5 and obs["temp_max_c"] == 34.0
    assert obs["humidity_min_pct"] == 25.0 and obs["humidity_max_pct"] == 60.0
    assert obs["rainfall_mm"] is None  # pas encore ingéré pour ce jour


def test_reingesting_same_station_keeps_first_coordinates(client, staff, incoming):
    """Même nom de station avec des coordonnées légèrement différentes selon le fichier (observé
    dans les vrais exports ANAM, ex. Bobo-Dioulasso) : la première ingestion fixe les coordonnées,
    les suivantes ne les modifient pas."""
    _write_geojson(incoming / "exporttemp.geojson", {"tmin": 20.0, "tmax": 30.0}, "2026-10-08",
                   {"Bobo-test": (11.1667, -4.3)})
    client.post("/observations/ingest", json={"filename": "exporttemp.geojson"}, headers=staff(Role.agent_anam))

    _write_geojson(incoming / "exportrr.geojson", {"value": 5.0}, "2026-10-08",
                   {"Bobo-test": (11.157519, -4.347839)})  # coordonnées légèrement différentes
    client.post("/observations/ingest", json={"filename": "exportrr.geojson"}, headers=staff(Role.agent_anam))

    r = client.get("/observations/stations")
    [station] = r.json()
    assert station["latitude"] == pytest.approx(11.1667)
    assert station["longitude"] == pytest.approx(-4.3)


def test_default_incoming_dir_resolves_next_to_repo_root(client, staff):
    """Régression : la résolution du chemin par défaut (`observations_incoming_dir` relatif, pas
    remplacé par la fixture `incoming`) doit pointer sur `agrometeo/observations_incoming/`, pas
    un niveau plus haut -- une erreur d'index (`parents[N]`) déjà trouvée et corrigée dans ce
    fichier ET dans `forecasts.py`/`forecast_jobs.py` (Module 3), qui partagent le même calcul."""
    root = Path(__file__).resolve().parents[2]  # backend/tests -> backend -> agrometeo
    marker = root / "observations_incoming" / "_test_marker_default_path.geojson"
    marker.parent.mkdir(exist_ok=True)
    marker.write_text("{}", encoding="utf-8")
    try:
        r = client.get("/observations/incoming", headers=staff(Role.agent_anam))
        assert r.status_code == 200
        assert "_test_marker_default_path.geojson" in r.json()
    finally:
        marker.unlink()


def test_list_observations_filters_by_date(client, staff, incoming):
    _write_geojson(incoming / "d1.geojson", {"value": 1.0}, "2026-10-07", STATIONS)
    client.post("/observations/ingest", json={"filename": "d1.geojson"}, headers=staff(Role.agent_anam))
    _write_geojson(incoming / "d2.geojson", {"value": 2.0}, "2026-10-08", STATIONS)
    client.post("/observations/ingest", json={"filename": "d2.geojson"}, headers=staff(Role.agent_anam))

    r = client.get("/observations", params={"observed_date": "2026-10-07"})
    assert {o["observed_date"] for o in r.json()} == {"2026-10-07"}
    assert len(r.json()) == 2  # deux stations ce jour-là

    r = client.get("/observations")
    assert len(r.json()) == 4  # deux jours x deux stations, sans filtre
