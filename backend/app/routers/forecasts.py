"""Prévisions (Module 3) : ingestion des fichiers WRF déposés par l'ANAM et consultation des
résumés journaliers par zone (température, précipitations, vent, humidité)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import forecast_jobs
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..models_content import ForecastRun, MediaStatus, Zone, ZoneForecast
from ..rbac import require_permission
from ..schemas_content import ForecastIngestRequest, ForecastRunOut, ZoneForecastOut
from .common import get_or_404

router = APIRouter(prefix="/forecasts", tags=["Prévisions (Module 3)"])


def _zone_forecast_out(zf: ZoneForecast, zone_name: str) -> ZoneForecastOut:
    return ZoneForecastOut(
        id=zf.id, run_id=zf.run_id, zone_id=zf.zone_id, zone_name=zone_name,
        forecast_date=zf.forecast_date, distance_km=zf.distance_km,
        temp_min_c=zf.temp_min_c, temp_max_c=zf.temp_max_c, temp_mean_c=zf.temp_mean_c,
        precip_total_mm=zf.precip_total_mm, wind_speed_mean_ms=zf.wind_speed_mean_ms,
        wind_speed_max_ms=zf.wind_speed_max_ms, humidity_mean_pct=zf.humidity_mean_pct,
    )


@router.get("/incoming", response_model=list[str])
def list_incoming_files(_: User = Depends(require_permission("content:manage"))):
    """Fichiers wrfout présents dans le dossier d'arrivée (`wrf_incoming_dir`), pas encore forcément
    ingérés. Utile pour choisir le `filename` à passer à `POST /forecasts/ingest`."""
    d = Path(get_settings().wrf_incoming_dir)
    if not d.is_absolute():
        d = (Path(__file__).resolve().parents[3] / d).resolve()
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file())


@router.post("/ingest", response_model=ForecastRunOut, status_code=status.HTTP_202_ACCEPTED)
def ingest_forecast(body: ForecastIngestRequest, background: BackgroundTasks,
                    user: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    """Lance l'extraction des prévisions par zone à partir d'un fichier wrfout du dossier d'arrivée.
    Réponse immédiate (`status=processing`) ; relire `GET /forecasts/runs/{id}` jusqu'à `ready`/`failed`.
    Domaine déduit du nom de fichier (`wrfout_d02_...` -> `d02`)."""
    parts = body.filename.split("_")
    domain = parts[1] if len(parts) > 1 and parts[1].startswith("d") else "?"
    run = ForecastRun(source_file=body.filename, domain=domain, created_by=user.id, status=MediaStatus.processing)
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce fichier a déjà été ingéré.") from None
    background.add_task(forecast_jobs.run_forecast_ingest, run.id)
    return run


@router.get("/runs", response_model=list[ForecastRunOut])
def list_runs(limit: int = Query(default=20, ge=1, le=100),
             _: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    """Historique des ingestions, de la plus récente à la plus ancienne."""
    return db.scalars(select(ForecastRun).order_by(ForecastRun.created_at.desc()).limit(limit)).all()


@router.get("/runs/{run_id}", response_model=ForecastRunOut)
def get_run(run_id: str, _: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    return get_or_404(db, ForecastRun, run_id, "Ingestion")


@router.get("", response_model=list[ZoneForecastOut])
def list_forecasts(
    zone_id: str | None = Query(default=None, description="Identifiant exact d'une zone (voir GET /zones)"),
    zone_name: str | None = Query(default=None, description="Nom exact d'une commune/région (ex. \"Kaya\"), insensible à la casse -- alternative à zone_id quand on ne le connaît pas"),
    pilot_only: bool = Query(default=False, description="Seulement les 5 communes pilotes, comme GET /zones?pilot_only"),
    forecast_date: str | None = Query(default=None, description="AAAA-MM-JJ"),
    db: Session = Depends(get_db),
):
    """Résumés journaliers par zone (température, précipitations, vent, humidité). Public, comme les
    autres contenus de référence.

    Trois façons de choisir les zones, combinables avec `forecast_date` :
    - rien -> toutes les zones qui ont une prévision enregistrée (jusqu'à 351 communes si tout le
      pays a été ingéré, voir `module3/README.md`) ;
    - `pilot_only=true` -> seulement les 5 communes pilotes ;
    - `zone_id=...` (identifiant obtenu via `GET /zones`) ou `zone_name=...` (nom exact, ex. "Kaya")
      -> une seule zone. `zone_name` évite d'avoir à connaître l'identifiant à l'avance.

    Sans `forecast_date`, renvoie TOUTES les prévisions enregistrées (pas seulement les plus
    récentes) : si plusieurs fichiers ont été ingérés pour des jours différents, filtrer par date
    ou trier côté client."""
    stmt = select(ZoneForecast, Zone.name).join(Zone, Zone.id == ZoneForecast.zone_id)
    if zone_id:
        stmt = stmt.where(ZoneForecast.zone_id == zone_id)
    if zone_name:
        stmt = stmt.where(func.lower(Zone.name) == zone_name.lower())
    if pilot_only:
        stmt = stmt.where(Zone.is_pilot.is_(True))
    if forecast_date:
        stmt = stmt.where(ZoneForecast.forecast_date == forecast_date)
    stmt = stmt.order_by(ZoneForecast.forecast_date.desc(), Zone.name)
    rows = db.execute(stmt).all()
    return [_zone_forecast_out(zf, name) for zf, name in rows]
