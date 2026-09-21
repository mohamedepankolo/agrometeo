from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..models import User
from ..rbac import get_current_user
from ..schemas import MessageResponse, PasswordChange, ProfileUpdate, UserOut
from ..security import hash_password, verify_password

router = APIRouter(prefix="/me", tags=["Profil"])


@router.get("", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.patch("", response_model=UserOut)
def update_me(body: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Met à jour la commune, la langue préférée et le mode de réception des alertes."""
    data = body.model_dump(exclude_unset=True)
    channels = data.get("notification_channels")
    if channels is not None:
        values = {c.value if hasattr(c, "value") else c for c in channels}
        if "sms" in values and not user.phone:
            raise HTTPException(422, "Le canal SMS nécessite un numéro de téléphone sur le compte.")
        if "email" in values and not user.email:
            raise HTTPException(422, "Le canal e-mail nécessite une adresse e-mail sur le compte.")
        data["notification_channels"] = sorted(values)
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    return user


@router.post("/password", response_model=MessageResponse)
def change_password(body: PasswordChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Change le mot de passe et ferme toutes les sessions (reconnexion nécessaire)."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mot de passe actuel incorrect.")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    services.revoke_all_sessions(db, user.id)
    db.commit()
    return MessageResponse(message="Mot de passe modifié. Reconnectez-vous.")
