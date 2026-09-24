"""Outils de développement — JAMAIS actifs en production (ENV=prod) : messages « envoyés » en simulation,
état de la configuration, explorateur de base de données en lecture seule."""

from __future__ import annotations

import re
import shutil

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import notifications, services
from ..config import get_settings
from ..db import Base, get_db

router = APIRouter(prefix="/dev", tags=["Développement (désactivé en production)"])

_REDACTED = {"password_hash", "totp_secret_enc", "code_hash", "token_hash", "token"}


@router.get("/status", response_model=dict)
def dev_status():
    """État de la configuration : backends d'envoi actifs, dépendances externes, stockage."""
    s = get_settings()
    return {
        "env": s.env,
        "database": s.database_url.split("@")[-1] if "@" in s.database_url else s.database_url,
        "backends": {"sms": s.sms_backend, "email": s.email_backend, "push": s.push_backend, "whatsapp": s.whatsapp_backend},
        "ffmpeg_installed": shutil.which("ffmpeg") is not None,
        "citadel_translation_configured": bool(s.citadel_api_email and s.citadel_api_password),
        "citadel_speech_configured": bool(s.moore_api_base_url and s.moore_api_token),
        "moore_model_type": s.moore_model_type,
        "storage_dir": s.storage_dir,
        "public_base_url": s.public_base_url or "(vide : URLs relatives)",
    }


@router.get("/outbox", response_model=list)
def outbox(limit: int = Query(default=30, ge=1, le=200)):
    """Derniers messages « envoyés » par les backends `console` (SMS, e-mail, push, WhatsApp simulés)."""
    return list(reversed(notifications.OUTBOX[-limit:]))


@router.get("/verification-code", response_model=dict)
def last_verification_code(identifier: str):
    """Dernier code de vérification simulé envoyé à ce numéro / e-mail (pour tester l'inscription sans SMS réel)."""
    from ..identifiers import classify_identifier

    ident = classify_identifier(identifier)
    if not ident:
        raise HTTPException(422, "Identifiant invalide.")
    for msg in reversed(notifications.OUTBOX):
        if msg["to"] == ident[1] and "code de vérification" in msg["message"]:
            m = re.search(r"est (\d{6})", msg["message"])
            if m:
                return {"identifier": ident[1], "code": m.group(1), "channel": msg["channel"]}
    raise HTTPException(404, "Aucun code envoyé à cet identifiant.")


@router.post("/reset-2fa", response_model=dict)
def reset_2fa_for_tests(identifier: str, db: Session = Depends(get_db)):
    """Réinitialise la 2FA d'un compte SANS authentification (utile en test : la reconfiguration ne redonne
    jamais le secret d'origine une fois la page/session fermée — cf. `/admin/.../reset-2fa` pour l'équivalent
    protégé, réservé aux administrateurs, à utiliser en production)."""
    user = services.find_user(db, identifier)
    if user is None:
        raise HTTPException(404, "Compte introuvable.")
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_last_step = 0
    services.revoke_all_sessions(db, user.id)
    db.commit()
    return {"message": f"2FA réinitialisée pour {identifier} : reconnectez-vous pour la reconfigurer."}


@router.get("/db", response_model=dict)
def db_tables(db: Session = Depends(get_db)):
    """Tables de la base et nombre de lignes."""
    from .. import models, models_content  # noqa: F401

    return {name: db.scalar(select(func.count()).select_from(table)) for name, table in sorted(Base.metadata.tables.items())}


@router.get("/db/{table}", response_model=dict)
def db_rows(table: str, limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
            db: Session = Depends(get_db)):
    """Contenu d'une table en lecture seule. Mots de passe hachés, secrets 2FA, codes et jetons masqués."""
    t = Base.metadata.tables.get(table)
    if t is None:
        raise HTTPException(404, "Table inconnue.")
    rows = db.execute(select(t).limit(limit).offset(offset)).mappings().all()
    clean = [{k: ("***" if k in _REDACTED and v else v) for k, v in dict(r).items()} for r in rows]
    return {"table": table, "total": db.scalar(select(func.count()).select_from(t)), "columns": list(t.columns.keys()),
            "rows": jsonable_encoder(clean)}
