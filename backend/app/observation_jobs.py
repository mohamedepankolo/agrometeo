"""Ingestion d'un export GeoJSON de stations météo (Module 2).

Contrairement au Module 3 (fichier WRF de plusieurs Go, tâche de fond), un export fait ~20 Ko :
l'ingestion est synchrone, directement dans la requête HTTP.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import module2_bridge as bridge
from .models_content import Station, StationObservation

_FIELD_BY_KIND = {
    "temperature": {"tmin": "temp_min_c", "tmax": "temp_max_c"},
    "pluviometrie": {"value": "rainfall_mm"},
    "humidite": {"umin": "humidity_min_pct", "umax": "humidity_max_pct"},
}


def ingest_file(db: Session, path: Path) -> dict:
    """Ingère un export : crée les stations inconnues, met à jour (ou crée) l'observation du
    jour pour chacune. Renvoie `{"kind", "observed_date", "stations_created", "stations_updated"}`."""
    export = bridge.read_export(path)
    kind, date, records = export["kind"], export["date"], export["records"]
    fields = _FIELD_BY_KIND[kind]

    created = updated = 0
    for record in records:
        station = db.scalar(select(Station).where(Station.name == record["station"]))
        if station is None:
            station = Station(name=record["station"], latitude=record["latitude"], longitude=record["longitude"])
            db.add(station)
            db.flush()  # obtenir station.id avant de créer l'observation qui y pointe

        obs = db.scalar(select(StationObservation).where(
            StationObservation.station_id == station.id, StationObservation.observed_date == date))
        if obs is None:
            obs = StationObservation(station_id=station.id, observed_date=date)
            db.add(obs)
            created += 1
        else:
            updated += 1
        for source_key, column in fields.items():
            setattr(obs, column, record[source_key])

    db.commit()
    return {"kind": kind, "observed_date": date, "stations_created": created, "stations_updated": updated}
