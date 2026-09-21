"""Routes transverses pour les applications : médias, événements d'usage, appareils, rôles, configuration publique."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..config import get_settings
from ..db import get_db
from ..models import COMMUNES, User
from ..models_content import Alert, Bulletin, ContentStatus, DeviceToken, UsageEvent
from ..rbac import (
    PERMISSION_LABELS,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    get_current_user,
    get_optional_user,
    has_permission,
    user_from_token,
)
from ..schemas_content import ConfigOut, DeviceRegister, RolesOut, UsageEventIn
from ..seed import get_setting

router = APIRouter(tags=["Plateforme"])

ALERT_LEVELS = [
    {"code": "vert", "label": "Aucune alerte", "color": "#2E7D32"},
    {"code": "jaune", "label": "Soyez attentif", "color": "#F9A825"},
    {"code": "orange", "label": "Soyez très vigilant", "color": "#EF6C00"},
    {"code": "rouge", "label": "Vigilance absolue", "color": "#C62828"},
]
LANGUAGES = [{"code": "fr", "label": "Français"}, {"code": "mos", "label": "Mooré"}, {"code": "en", "label": "English"}]


@router.get("/config", response_model=ConfigOut)
def public_config(db: Session = Depends(get_db)):
    """Configuration publique pour l'application : langues, communes, niveaux d'alerte et couleurs, source à citer."""
    return {
        "platform_name": get_setting(db, "platform.name"),
        "default_language": get_setting(db, "platform.default_language"),
        "languages": LANGUAGES,
        "communes": COMMUNES,
        "alert_levels": ALERT_LEVELS,
        "notification_channels": ["push", "sms", "email"],
        "source_citation": get_setting(db, "platform.source_citation"),
    }


@router.get("/roles", response_model=RolesOut)
def roles_and_permissions():
    """Les 5 rôles, leurs permissions, et ceux dont la connexion exige la 2FA. Public (aucune donnée sensible)."""
    need_2fa = get_settings().roles_requiring_2fa
    return {
        "roles": [{"role": r.value, "label": ROLE_LABELS[r], "permissions": sorted(perms),
                   "requires_2fa": r.value in need_2fa} for r, perms in ROLE_PERMISSIONS.items()],
        "permissions": PERMISSION_LABELS,
    }


# ============================================================== médias
@router.get("/media/{path:path}", response_class=FileResponse, tags=["Médias"])
def get_media(path: str, token: str | None = Query(default=None, description="Token d'accès, pour lire un média non publié dans une balise <video>/<audio>"),
              user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """Fichier généré (audio, vidéo, image, PDF). Les médias des contenus **publiés** sont publics ; ceux
    des brouillons ne sont lisibles que par le personnel (en-tête `Authorization`, ou `?token=`).
    Les URLs à utiliser sont fournies dans les champs `media` / `image_url` / `pdf_url` des contenus."""
    not_found = HTTPException(status.HTTP_404_NOT_FOUND, "Fichier introuvable.")
    parts = path.split("/")
    if len(parts) < 3 or parts[0] not in {"alerts", "bulletins"}:
        raise not_found
    row = db.get(Alert if parts[0] == "alerts" else Bulletin, parts[1])
    if row is None:
        raise not_found
    if row.status != ContentStatus.published:
        staff = user
        if staff is None and token:
            try:
                staff = user_from_token(db, token)
            except HTTPException:
                staff = None
        if not has_permission(staff, "content:manage"):
            raise not_found
    try:
        file = storage.absolute(path)
    except ValueError:
        raise not_found from None
    if not file.is_file():
        raise not_found
    return FileResponse(file)


# ============================================================== événements d'usage
@router.post("/events", status_code=status.HTTP_204_NO_CONTENT, tags=["Statistiques d'usage"])
def track_event(body: UsageEventIn, user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """À appeler par l'application quand un contenu est consulté (`view`), écouté (`play_audio`), regardé
    (`play_video`) ou partagé (`share`) : alimente les statistiques d'usage du back-office. Connexion facultative."""
    db.add(UsageEvent(user_id=user.id if user else None, content_type=body.content_type, content_id=body.content_id,
                      kind=body.kind, language=body.language))
    db.commit()


# ============================================================== appareils (notifications push)
@router.post("/me/devices", status_code=status.HTTP_204_NO_CONTENT, tags=["Profil"])
def register_device(body: DeviceRegister, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Enregistre le jeton Firebase (FCM) de l'appareil pour recevoir les notifications push.
    À appeler après chaque connexion et quand Firebase renouvelle le jeton."""
    existing = db.scalar(select(DeviceToken).where(DeviceToken.token == body.token))
    if existing:
        existing.user_id, existing.platform = user.id, body.platform
    else:
        db.add(DeviceToken(user_id=user.id, token=body.token, platform=body.platform))
    db.commit()


@router.delete("/me/devices", status_code=status.HTTP_204_NO_CONTENT, tags=["Profil"])
def unregister_device(token: str = Query(min_length=10), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Supprime le jeton de l'appareil (à appeler à la déconnexion)."""
    row = db.scalar(select(DeviceToken).where(DeviceToken.token == token, DeviceToken.user_id == user.id))
    if row:
        db.delete(row)
        db.commit()

