"""Diffusion multicanale d'un contenu (alerte, bulletin, avis) : ciblage, envoi, suivi de chaque envoi.

Ciblage :
  - alerte avec zones  -> utilisateurs dont la commune figure dans `commune_names` d'au moins une des zones ;
  - alerte sans zone, bulletin, avis -> tous les utilisateurs actifs ;
  - ensuite, seuls les canaux à la fois choisis par l'utilisateur (`notification_channels`) et activés
    pour ce type de contenu dans les paramètres (`diffusion.channels`) sont utilisés ;
  - WhatsApp : numéros de `diffusion.whatsapp_recipients` (pas les utilisateurs individuels).
"""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import messages, notifications
from .db import new_session
from .models import User, UserStatus, utcnow
from .models_content import Advisory, Alert, AlertZone, Broadcast, Bulletin, DeviceToken, Delivery, Zone
from .seed import get_setting

log = logging.getLogger("backend.diffusion")

_MODELS = {"alert": Alert, "bulletin": Bulletin, "advisory": Advisory}


def target_users(db: Session, content_type: str, content) -> list[User]:
    users = list(db.scalars(select(User).where(User.status == UserStatus.active)))
    if content_type != "alert":
        return users
    zones = list(db.scalars(select(Zone).join(AlertZone, AlertZone.zone_id == Zone.id).where(AlertZone.alert_id == content.id)))
    if not zones:
        return users
    communes = {c for z in zones for c in (z.commune_names or [])}
    return [u for u in users if u.commune in communes]


def create_broadcast(db: Session, content_type: str, content_id: str, user_id: str | None, trigger: str) -> Broadcast:
    b = Broadcast(content_type=content_type, content_id=content_id, created_by=user_id, trigger=trigger)
    db.add(b)
    db.commit()
    return b


def _plan(db: Session, content_type: str, content) -> list[tuple[User | None, str, str]]:
    """Liste des envois à faire : (utilisateur, canal, destinataire)."""
    enabled = set((get_setting(db, "diffusion.channels") or {}).get(content_type, []))
    plan: list[tuple[User | None, str, str]] = []
    for user in target_users(db, content_type, content):
        wanted = set(user.notification_channels or []) & enabled
        if "sms" in wanted and user.phone:
            plan.append((user, "sms", user.phone))
        if "email" in wanted and user.email:
            plan.append((user, "email", user.email))
        if "push" in wanted:
            for token in db.scalars(select(DeviceToken.token).where(DeviceToken.user_id == user.id)):
                plan.append((user, "push", token))
    if "whatsapp" in enabled:
        for number in get_setting(db, "diffusion.whatsapp_recipients") or []:
            plan.append((None, "whatsapp", number))
    return plan


def run_broadcast(broadcast_id: str) -> None:
    """Exécute la diffusion (tâche de fond, session propre). Chaque envoi est tracé dans `deliveries`."""
    db = new_session()
    try:
        b = db.get(Broadcast, broadcast_id)
        if b is None:
            return
        b.status = "running"
        db.commit()
        try:
            content = db.get(_MODELS[b.content_type], b.content_id)
            if content is None:
                raise LookupError("contenu introuvable")
            _deliver(db, b, content)
            b.status = "done"
        except Exception as exc:  # noqa: BLE001
            log.exception("diffusion %s échouée", broadcast_id)
            b.status = "failed"
            b.note = f"{type(exc).__name__}: {exc}"[:500]
        b.finished_at = utcnow()
        db.commit()
    finally:
        db.close()


def _deliver(db: Session, b: Broadcast, content) -> None:
    plan = _plan(db, b.content_type, content)
    b.target_count = len(plan)
    wa_lang = get_setting(db, "platform.default_language") or "fr"
    wa_text = None
    sent = failed = 0
    for user, channel, recipient in plan:
        lang = user.language.value if user else wa_lang
        delivery = Delivery(broadcast_id=b.id, user_id=user.id if user else None, channel=channel, recipient=recipient)
        db.add(delivery)
        try:
            sender = notifications.get_sender(channel)
            if channel == "whatsapp":
                wa_text = wa_text or messages.share_kit(db, b.content_type, content)["text"][wa_lang]
                title, body, data = None, wa_text, None
            else:
                title, body, data = messages.render(db, b.content_type, content, lang, channel)
            sender.send(recipient, body, title=title, data=data)
            delivery.status = "simulated" if sender.simulated else "sent"
            delivery.sent_at = utcnow()
            sent += 1
        except notifications.InvalidRecipient:
            db.execute(delete(DeviceToken).where(DeviceToken.token == recipient))
            delivery.status, delivery.error = "failed", "appareil introuvable (jeton supprimé)"
            failed += 1
        except Exception as exc:  # noqa: BLE001 — un échec d'envoi ne doit pas arrêter les autres
            delivery.status, delivery.error = "failed", f"{type(exc).__name__}: {exc}"[:300]
            failed += 1
        b.sent_count, b.failed_count = sent, failed
        if (sent + failed) % 50 == 0:
            db.commit()
    db.commit()


def summarize(db: Session, broadcast_id: str) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for channel, status_, n in db.execute(
        select(Delivery.channel, Delivery.status, func.count()).where(Delivery.broadcast_id == broadcast_id)
        .group_by(Delivery.channel, Delivery.status)
    ):
        out[channel][status_] = n
    return dict(out)

