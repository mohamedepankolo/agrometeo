"""Observations (Module 2) : ingestion des exports GeoJSON de stations météo de l'ANAM et
consultation des relevés réels par station (température, pluviométrie, humidité)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import observation_jobs
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..models_content import Station, StationObservation
from ..rbac import require_permission
from ..schemas_content import (
    ObservationIngestRequest,
    ObservationIngestResult,
    StationObservationOut,
    StationOut,
)
from .common import safe_filename

router = APIRouter(prefix="/observations", tags=["Observations (Module 2)"])


def _station_observation_out(obs: StationObservation, station_name: str) -> StationObservationOut:
    return StationObservationOut(
        id=obs.id, station_id=obs.station_id, station_name=station_name, observed_date=obs.observed_date,
        temp_min_c=obs.temp_min_c, temp_max_c=obs.temp_max_c,
        humidity_min_pct=obs.humidity_min_pct, humidity_max_pct=obs.humidity_max_pct,
        rainfall_mm=obs.rainfall_mm,
    )


@router.get("/incoming", response_model=list[str])
def list_incoming_files(_: User = Depends(require_permission("content:manage"))):
    """Fichiers GeoJSON présents dans le dossier d'arrivée (`observations_incoming_dir`), pas
    encore forcément ingérés. Utile pour choisir le `filename` à passer à `POST /observations/ingest`."""
    d = Path(get_settings().observations_incoming_dir)
    if not d.is_absolute():
        d = (Path(__file__).resolve().parents[2] / d).resolve()
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file())


@router.post("/ingest", response_model=ObservationIngestResult)
def ingest_observations(body: ObservationIngestRequest,
                        _: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    """Ingère un export GeoJSON (température, pluviométrie OU humidité -- déduit du contenu, pas
    du nom de fichier) : crée les stations inconnues, met à jour les relevés du jour. Synchrone
    (fichier de quelques dizaines de Ko) : la réponse contient déjà le résultat, pas de suivi à
    relire comme pour `POST /forecasts/ingest` (Module 3)."""
    settings = get_settings()
    path = Path(settings.observations_incoming_dir) / safe_filename(body.filename)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[2] / path).resolve()
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Fichier introuvable dans observations_incoming_dir : {body.filename}")
    try:
        result = observation_jobs.ingest_file(db, path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return result


@router.get("/stations", response_model=list[StationOut])
def list_stations(db: Session = Depends(get_db)):
    """Référentiel des stations météo connues (créées au fil des imports). Public, comme les
    autres référentiels (zones, types d'alerte...)."""
    return db.scalars(select(Station).order_by(Station.name)).all()


@router.get("", response_model=list[StationObservationOut])
def list_observations(
    station_id: str | None = Query(default=None, description="Identifiant exact d'une station (voir GET /observations/stations)"),
    station_name: str | None = Query(default=None, description="Nom exact d'une station (ex. \"Kaya\"), insensible à la casse -- alternative à station_id"),
    observed_date: str | None = Query(default=None, description="AAAA-MM-JJ"),
    db: Session = Depends(get_db),
):
    """Relevés réels par station. Public, comme les autres contenus de référence.

    Sans filtre, renvoie TOUS les relevés enregistrés (pas seulement les plus récents) : si
    plusieurs jours ont été ingérés, filtrer par `observed_date` ou trier côté client. Des
    colonnes peuvent être `null` si cette station n'a pas encore reçu l'import correspondant
    pour ce jour (température, pluviométrie, humidité importées séparément -- voir
    module2/README.md)."""
    stmt = select(StationObservation, Station.name).join(Station, Station.id == StationObservation.station_id)
    if station_id:
        stmt = stmt.where(StationObservation.station_id == station_id)
    if station_name:
        stmt = stmt.where(func.lower(Station.name) == station_name.lower())
    if observed_date:
        stmt = stmt.where(StationObservation.observed_date == observed_date)
    stmt = stmt.order_by(StationObservation.observed_date.desc(), Station.name)
    rows = db.execute(stmt).all()
    return [_station_observation_out(obs, name) for obs, name in rows]
