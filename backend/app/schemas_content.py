from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models_content import AdvisoryKind, AlertLevel, ContentStatus, MediaStatus, ZoneKind

Lang = Literal["fr", "en", "mos"]


# ------------------------------------------------------------------ zones
def _check_geometry(v):
    if v is not None and v.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("La géométrie doit être un GeoJSON Polygon ou MultiPolygon.")
    return v


class ZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    kind: ZoneKind
    is_pilot: bool
    commune_names: list[str]
    latitude: float | None
    longitude: float | None


class ZoneDetail(ZoneOut):
    geometry: dict | None


class ZoneWrite(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: ZoneKind = ZoneKind.commune
    is_pilot: bool = False
    commune_names: list[str] = []
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geometry: dict | None = Field(default=None, description="GeoJSON Polygon ou MultiPolygon")

    _geometry = field_validator("geometry")(_check_geometry)


class ZoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    kind: ZoneKind | None = None
    is_pilot: bool | None = None
    commune_names: list[str] | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geometry: dict | None = None

    _geometry = field_validator("geometry")(_check_geometry)


# ------------------------------------------------------------------ types d'alerte et prévention
class AlertTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    label_fr: str
    label_en: str | None
    label_mos: str | None
    active: bool


class AlertTypeWrite(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    label_fr: str = Field(min_length=2, max_length=80)
    label_en: str | None = None
    label_mos: str | None = None
    active: bool = True


class AlertTypeUpdate(BaseModel):
    label_fr: str | None = Field(default=None, min_length=2, max_length=80)
    label_en: str | None = None
    label_mos: str | None = None
    active: bool | None = None


class PreventionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alert_type_id: str
    text_fr: str
    text_en: str | None
    text_mos: str | None
    active: bool


class PreventionWrite(BaseModel):
    alert_type_id: str
    text_fr: str = Field(min_length=3)
    text_en: str | None = None
    text_mos: str | None = None
    active: bool = True


class PreventionUpdate(BaseModel):
    text_fr: str | None = Field(default=None, min_length=3)
    text_en: str | None = None
    text_mos: str | None = None
    active: bool | None = None


class TranslateRequest(BaseModel):
    langs: list[Literal["en", "mos"]] = ["en", "mos"]
    overwrite: bool = False


# ------------------------------------------------------------------ médias
class MediaFiles(BaseModel):
    audio: str | None = None
    video: str | None = None


class MediaInfo(BaseModel):
    status: MediaStatus
    error: str | None = Field(
        default=None,
        description="Si `failed` : la cause de l'échec. Si `ready` : avertissement éventuel "
                    "(ex. une langue n'a pas pu être générée ; elle est alors absente de `files`).")
    files: dict[Lang, MediaFiles] = {}


# ------------------------------------------------------------------ alertes
class AlertCreate(BaseModel):
    alert_type_id: str
    level: AlertLevel
    raw_text: str = Field(min_length=10, description="Texte de l'alerte, tel que rédigé (format WhatsApp accepté)")
    title: str | None = Field(default=None, max_length=200)
    zone_ids: list[str] = []
    valid_until: datetime | None = Field(default=None, description="UTC ; par défaut : maintenant + durée de validité configurée")


class AlertUpdate(BaseModel):
    alert_type_id: str | None = None
    level: AlertLevel | None = None
    raw_text: str | None = Field(default=None, min_length=10)
    title: str | None = Field(default=None, max_length=200)
    zone_ids: list[str] | None = None
    valid_until: datetime | None = None


class AlertPreviewRequest(BaseModel):
    raw_text: str


class AlertOut(BaseModel):
    id: str
    type: AlertTypeOut
    level: AlertLevel
    title: str
    status: ContentStatus
    is_active: bool = Field(description="Publiée et non expirée")
    zones: list[ZoneOut]
    parsed: dict | None
    texts: dict[Lang, str] | None = Field(description="Texte lu, par langue (disponible quand les médias sont prêts)")
    prevention: list[PreventionOut]
    image_url: str | None
    media: MediaInfo
    valid_until: datetime | None
    created_at: datetime
    published_at: datetime | None
    source: str
    raw_text: str | None = Field(default=None, description="Réservé au personnel")


class AlertList(BaseModel):
    total: int
    items: list[AlertOut]


# ------------------------------------------------------------------ bulletins
class BulletinOut(BaseModel):
    id: str
    title: str
    date_text: str | None
    issued_at: datetime | None
    status: ContentStatus
    parsed: dict | None
    texts: dict[Lang, str] | None
    pdf_url: str | None
    media: MediaInfo
    created_at: datetime
    published_at: datetime | None
    source: str


class BulletinList(BaseModel):
    total: int
    items: list[BulletinOut]


class BulletinUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


# ------------------------------------------------------------------ avis
class AdvisoryWrite(BaseModel):
    kind: AdvisoryKind
    title_fr: str = Field(min_length=2, max_length=200)
    body_fr: str = Field(min_length=3)
    title_en: str | None = None
    title_mos: str | None = None
    body_en: str | None = None
    body_mos: str | None = None


class AdvisoryUpdate(BaseModel):
    title_fr: str | None = Field(default=None, min_length=2, max_length=200)
    body_fr: str | None = Field(default=None, min_length=3)
    title_en: str | None = None
    title_mos: str | None = None
    body_en: str | None = None
    body_mos: str | None = None


class AdvisoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: AdvisoryKind
    title_fr: str
    title_en: str | None
    title_mos: str | None
    body_fr: str
    body_en: str | None
    body_mos: str | None
    status: ContentStatus
    created_at: datetime
    published_at: datetime | None


class AdvisoryList(BaseModel):
    total: int
    items: list[AdvisoryOut]


# ------------------------------------------------------------------ carte
class MapAlertSummary(BaseModel):
    id: str
    title: str
    level: AlertLevel
    type_code: str
    valid_until: datetime | None


class MapZone(BaseModel):
    zone: ZoneDetail
    level: Literal["vert", "jaune", "orange", "rouge"]
    alerts: list[MapAlertSummary]


class AlertMap(BaseModel):
    zones: list[MapZone]
    national_alerts: list[MapAlertSummary] = Field(description="Alertes actives sans zone précise (tout le territoire)")


# ------------------------------------------------------------------ diffusion
class BroadcastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content_type: str
    content_id: str
    status: str
    trigger: str
    created_at: datetime
    finished_at: datetime | None
    target_count: int
    sent_count: int
    failed_count: int
    note: str | None


class BroadcastList(BaseModel):
    total: int
    items: list[BroadcastOut]


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    recipient: str
    status: str
    error: str | None
    sent_at: datetime | None


class BroadcastDetail(BroadcastOut):
    by_channel: dict[str, dict[str, int]] = Field(description="Décompte des envois par canal et par statut")
    deliveries: list[DeliveryOut]


class ShareKit(BaseModel):
    """Contenu prêt à publier manuellement (WhatsApp, réseaux sociaux) : texte formaté et liens médias."""

    text: dict[Lang, str]
    media: dict[Lang, MediaFiles]
    image_url: str | None = None
    note: str


# ------------------------------------------------------------------ appareils, événements
class DeviceRegister(BaseModel):
    token: str = Field(min_length=10, max_length=512, description="Jeton Firebase (FCM) de l'appareil")
    platform: Literal["android", "ios", "web"] = "android"


class UsageEventIn(BaseModel):
    content_type: Literal["alert", "bulletin", "advisory"]
    content_id: str
    kind: Literal["view", "play_audio", "play_video", "share"] = "view"
    language: Lang | None = None


class SettingsUpdate(BaseModel):
    values: dict[str, Any] = Field(description="Paramètres à modifier : {clé: valeur}")


# ------------------------------------------------------------------ configuration, rôles, aperçu
class LanguageInfo(BaseModel):
    code: Lang
    label: str


class AlertLevelInfo(BaseModel):
    code: Literal["vert", "jaune", "orange", "rouge"]
    label: str
    color: str = Field(description="Couleur à utiliser (hexadécimal)")


class ConfigOut(BaseModel):
    platform_name: str
    default_language: Lang
    languages: list[LanguageInfo]
    communes: list[str]
    alert_levels: list[AlertLevelInfo]
    notification_channels: list[Literal["push", "sms", "email"]]
    source_citation: str = Field(description="Mention de source à afficher sur les contenus")


class RoleInfo(BaseModel):
    role: str
    label: str
    permissions: list[str]
    requires_2fa: bool


class RolesOut(BaseModel):
    roles: list[RoleInfo]
    permissions: dict[str, str] = Field(description="Code de permission -> description")


class AlertPreview(BaseModel):
    date_text: str | None = None
    situation: str = ""
    evolution: str = ""
    risques: list[str] = []
    conseils_intro: str | None = None
    conseils: list[str] = []


# ------------------------------------------------------------------ back-office
class CommuneCount(BaseModel):
    commune: str
    users: int


class DashboardUsers(BaseModel):
    total: int
    by_status: dict[str, int]
    by_role: dict[str, int]
    active_by_commune: list[CommuneCount]


class DashboardContent(BaseModel):
    bulletins_published: int
    bulletins_draft: int
    alerts_published: int
    alerts_active: int
    alerts_draft: int
    advisories_published: int
    media_failed: int = Field(description="Bulletins/alertes dont la génération audio-vidéo a échoué")


class DashboardDiffusion(BaseModel):
    deliveries_by_channel: dict[str, dict[str, int]] = Field(description="canal -> statut -> nombre d'envois")
    recent_broadcasts: list[BroadcastOut]


class DashboardOut(BaseModel):
    users: DashboardUsers
    content: DashboardContent
    diffusion: DashboardDiffusion
    usage_last_7_days: dict[str, int] = Field(description="type d'événement -> nombre")


class TopContent(BaseModel):
    content_type: str
    content_id: str
    events: int


class UsageOut(BaseModel):
    days: int
    by_day: dict[str, dict[str, int]] = Field(description="date -> type d'événement -> nombre")
    by_language: dict[str, int]
    top_content: list[TopContent]


class SmsPilotOut(BaseModel):
    target_users: int
    users_opted_in_sms: int = Field(description="Comptes actifs ayant choisi le SMS")
    distinct_recipients_reached: int
    deliveries_by_status: dict[str, int]
    progress: float | None = Field(description="Avancement vers l'objectif, entre 0 et 1")
