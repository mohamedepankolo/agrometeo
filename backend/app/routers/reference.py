"""Données de référence : zones, carte des alertes, types d'alerte, messages de prévention."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import module1_bridge as bridge
from ..content_views import alert_is_active
from ..db import get_db
from ..models import User, utcnow
from ..models_content import (
    LEVEL_ORDER,
    Alert,
    AlertType,
    AlertZone,
    ContentStatus,
    PreventionMessage,
    Zone,
)
from ..rbac import require_permission
from ..schemas_content import (
    AlertMap,
    AlertTypeOut,
    AlertTypeUpdate,
    AlertTypeWrite,
    MapAlertSummary,
    MapZone,
    PreventionOut,
    PreventionUpdate,
    PreventionWrite,
    TranslateRequest,
    ZoneDetail,
    ZoneOut,
    ZoneUpdate,
    ZoneWrite,
)
from .common import get_or_404

router = APIRouter(tags=["Zones, carte et référentiels"])


# ============================================================== zones
@router.get("/zones", response_model=list[ZoneOut])
def list_zones(pilot_only: bool = Query(default=False, description="Seulement les 5 communes pilotes"),
               db: Session = Depends(get_db)):
    """Zones (communes pilotes et régions) utilisables pour les alertes et la carte. Public."""
    stmt = select(Zone).order_by(Zone.name)
    if pilot_only:
        stmt = stmt.where(Zone.is_pilot.is_(True))
    return db.scalars(stmt).all()


@router.get("/zones/{zone_id}", response_model=ZoneDetail)
def get_zone(zone_id: str, db: Session = Depends(get_db)):
    """Détail d'une zone, avec son contour GeoJSON s'il est renseigné. Public."""
    return get_or_404(db, Zone, zone_id, "Zone")


@router.post("/zones", response_model=ZoneDetail, status_code=status.HTTP_201_CREATED)
def create_zone(body: ZoneWrite, _: User = Depends(require_permission("config:manage")), db: Session = Depends(get_db)):
    zone = Zone(**body.model_dump())
    db.add(zone)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Une zone porte déjà ce nom.") from None
    return zone


@router.patch("/zones/{zone_id}", response_model=ZoneDetail)
def update_zone(zone_id: str, body: ZoneUpdate, _: User = Depends(require_permission("config:manage")),
                db: Session = Depends(get_db)):
    """Modifie une zone (ex. renseigner ses coordonnées ou son contour GeoJSON fournis par l'ANAM)."""
    zone = get_or_404(db, Zone, zone_id, "Zone")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(zone, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Une zone porte déjà ce nom.") from None
    return zone


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(zone_id: str, _: User = Depends(require_permission("config:manage")), db: Session = Depends(get_db)):
    zone = get_or_404(db, Zone, zone_id, "Zone")
    db.delete(zone)
    db.commit()


# ============================================================== carte des alertes
@router.get("/map/alerts", response_model=AlertMap)
def alert_map(db: Session = Depends(get_db)):
    """Niveau d'alerte de chaque zone (vert / jaune / orange / rouge) d'après les alertes publiées et non
    expirées ; en cas de plusieurs alertes sur une zone, le niveau le plus élevé l'emporte. Public."""
    now = utcnow()
    active = [a for a in db.scalars(select(Alert).where(Alert.status == ContentStatus.published)) if alert_is_active(a, now)]
    types = {t.id: t.code for t in db.scalars(select(AlertType))}
    links = db.execute(select(AlertZone.alert_id, AlertZone.zone_id)).all()
    zones_of: dict[str, set[str]] = {}
    for alert_id, zone_id in links:
        zones_of.setdefault(alert_id, set()).add(zone_id)

    def summary(a: Alert) -> MapAlertSummary:
        return MapAlertSummary(id=a.id, title=a.title, level=a.level, type_code=types.get(a.alert_type_id, ""),
                               valid_until=a.valid_until)

    result = []
    for zone in db.scalars(select(Zone).order_by(Zone.name)):
        here = [a for a in active if zone.id in zones_of.get(a.id, set())]
        level = max((a.level.value for a in here), key=LEVEL_ORDER.get, default="vert")
        result.append(MapZone(zone=ZoneDetail.model_validate(zone), level=level, alerts=[summary(a) for a in here]))
    national = [summary(a) for a in active if a.id not in zones_of]
    return AlertMap(zones=result, national_alerts=national)


# ============================================================== types d'alerte
@router.get("/alert-types", response_model=list[AlertTypeOut])
def list_alert_types(include_inactive: bool = False, db: Session = Depends(get_db)):
    """Types d'alerte (orages, fortes pluies, inondations, vents violents, poussière, chaleur, sécheresse…). Public."""
    stmt = select(AlertType).order_by(AlertType.label_fr)
    if not include_inactive:
        stmt = stmt.where(AlertType.active.is_(True))
    return db.scalars(stmt).all()


@router.post("/alert-types", response_model=AlertTypeOut, status_code=status.HTTP_201_CREATED)
def create_alert_type(body: AlertTypeWrite, _: User = Depends(require_permission("content:manage")),
                      db: Session = Depends(get_db)):
    t = AlertType(**body.model_dump())
    db.add(t)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce code de type existe déjà.") from None
    return t


@router.patch("/alert-types/{type_id}", response_model=AlertTypeOut)
def update_alert_type(type_id: str, body: AlertTypeUpdate, _: User = Depends(require_permission("content:manage")),
                      db: Session = Depends(get_db)):
    """Modifie les libellés d'un type ; `active=false` le retire des choix sans casser les alertes existantes."""
    t = get_or_404(db, AlertType, type_id, "Type d'alerte")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(t, field, value)
    db.commit()
    return t


# ============================================================== messages de prévention (F8.1)
@router.get("/prevention-messages", response_model=list[PreventionOut])
def list_prevention(alert_type_id: str | None = None, alert_type_code: str | None = None, db: Session = Depends(get_db)):
    """Messages de prévention par type d'alerte. Public."""
    stmt = select(PreventionMessage).where(PreventionMessage.active.is_(True))
    if alert_type_id:
        stmt = stmt.where(PreventionMessage.alert_type_id == alert_type_id)
    if alert_type_code:
        stmt = stmt.join(AlertType, AlertType.id == PreventionMessage.alert_type_id).where(AlertType.code == alert_type_code)
    return db.scalars(stmt).all()


@router.post("/prevention-messages", response_model=PreventionOut, status_code=status.HTTP_201_CREATED)
def create_prevention(body: PreventionWrite, _: User = Depends(require_permission("content:manage")),
                      db: Session = Depends(get_db)):
    get_or_404(db, AlertType, body.alert_type_id, "Type d'alerte")
    m = PreventionMessage(**body.model_dump())
    db.add(m)
    db.commit()
    return m


@router.patch("/prevention-messages/{message_id}", response_model=PreventionOut)
def update_prevention(message_id: str, body: PreventionUpdate, _: User = Depends(require_permission("content:manage")),
                      db: Session = Depends(get_db)):
    m = get_or_404(db, PreventionMessage, message_id, "Message de prévention")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    db.commit()
    return m


@router.delete("/prevention-messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prevention(message_id: str, _: User = Depends(require_permission("content:manage")),
                      db: Session = Depends(get_db)):
    db.delete(get_or_404(db, PreventionMessage, message_id, "Message de prévention"))
    db.commit()


@router.post("/prevention-messages/{message_id}/translate", response_model=PreventionOut)
def translate_prevention(message_id: str, body: TranslateRequest, _: User = Depends(require_permission("content:manage")),
                         db: Session = Depends(get_db)):
    """Propose une traduction automatique (anglais : MyMemory, mooré : CITADEL/NLLB) à partir du texte français.
    Résultat à relire avant diffusion. Les traductions déjà saisies ne sont pas écrasées sauf `overwrite=true`."""
    m = get_or_404(db, PreventionMessage, message_id, "Message de prévention")
    try:
        for lang in body.langs:
            field = f"text_{lang}"
            if body.overwrite or not getattr(m, field):
                setattr(m, field, bridge.translate(m.text_fr, lang))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Service de traduction indisponible : {exc}") from None
    db.commit()
    return m

