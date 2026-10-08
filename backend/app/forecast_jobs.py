"""Tâche de fond : extraction des prévisions par zone à partir d'un fichier WRF (Module 3).

Contrairement au Module 1 (réseau + ffmpeg, 1 à 3 minutes), l'extraction WRF est une lecture
locale rapide (moins d'une seconde par zone) : passer par une tâche de fond évite surtout de
bloquer la requête HTTP le temps d'itérer sur toutes les zones.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from . import module3_bridge as bridge
from .config import get_settings
from .db import new_session
from .models import utcnow
from .models_content import ForecastRun, MediaStatus, Zone, ZoneForecast

log = logging.getLogger("backend.forecasts")


def run_forecast_ingest(run_id: str) -> None:
    db = new_session()
    try:
        run = db.get(ForecastRun, run_id)
        if run is None:
            return
        try:
            _ingest(db, run)
            run.status = MediaStatus.ready
        except Exception as exc:  # noqa: BLE001 — l'erreur est rapportée au client, pas perdue
            log.exception("ingestion WRF échouée (run %s, fichier %s)", run.id, run.source_file)
            run.status = MediaStatus.failed
            run.error = f"{type(exc).__name__}: {exc}"[:500]
        run.finished_at = utcnow()
        db.commit()
    finally:
        db.close()


def _ingest(db, run: ForecastRun) -> None:
    settings = get_settings()
    path = Path(settings.wrf_incoming_dir) / run.source_file
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[2] / path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Fichier introuvable dans wrf_incoming_dir : {run.source_file}")

    zones = [z for z in db.scalars(select(Zone)) if z.latitude is not None and z.longitude is not None]
    if not zones:
        run.zones_skipped = 0
        run.forecast_date = bridge.run_date(path)
        return

    points = {z.id: (z.latitude, z.longitude) for z in zones}
    summaries = bridge.daily_summaries(path, points)
    by_id = {z.id: z for z in zones}

    done = skipped = 0
    forecast_date = None
    for zone_id, summary in summaries.items():
        forecast_date = summary["forecast_date"]
        if summary["distance_km"] > settings.wrf_max_distance_km:
            skipped += 1
            continue
        existing = db.scalar(select(ZoneForecast).where(ZoneForecast.run_id == run.id, ZoneForecast.zone_id == zone_id))
        row = existing or ZoneForecast(run_id=run.id, zone_id=zone_id)
        row.forecast_date = summary["forecast_date"]
        row.distance_km = summary["distance_km"]
        row.temp_min_c = summary["temp_min_c"]
        row.temp_max_c = summary["temp_max_c"]
        row.temp_mean_c = summary["temp_mean_c"]
        row.precip_total_mm = summary["precip_total_mm"]
        row.wind_speed_mean_ms = summary["wind_speed_mean_ms"]
        row.wind_speed_max_ms = summary["wind_speed_max_ms"]
        row.humidity_mean_pct = summary["humidity_mean_pct"]
        if existing is None:
            db.add(row)
        done += 1

    run.zones_done, run.zones_skipped, run.forecast_date = done, skipped, forecast_date
