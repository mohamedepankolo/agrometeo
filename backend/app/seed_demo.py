"""Crée un compte de démonstration par rôle, pour tester l'API et l'interface de test.

    python -m app.seed_demo

Mot de passe commun : Demo1234!  — À N'UTILISER QU'EN DÉVELOPPEMENT : refuse de s'exécuter si ENV=prod.
Les comptes administrateur et agent demanderont de configurer la 2FA à leur première connexion.
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from . import db as dbmod
from .config import get_settings
from .models import Language, Role, User, UserStatus
from .security import hash_password
from .seed import seed_reference_data

PASSWORD = "Demo1234!"
DEMO = [
    ("admin@demo.test", Role.administrateur, "Administrateur démo", "Kaya", None),
    ("agent@demo.test", Role.agent_anam, "Agent ANAM démo", "Ziniaré", None),
    ("commune@demo.test", Role.responsable_communal, "Responsable communal démo", "Kaya", None),
    ("observateur@demo.test", Role.observateur, "Observateur démo", "Korsimoro", None),
    ("citoyen@demo.test", Role.grand_public, "Citoyen démo", "Kaya", "+22670000001"),
]


def main() -> int:
    if get_settings().is_prod:
        print("Refusé : comptes de démonstration interdits en production.", file=sys.stderr)
        return 1
    dbmod.init_db()
    db = dbmod.new_session()
    seed_reference_data(db)
    for email, role, name, commune, phone in DEMO:
        if db.scalar(select(User.id).where(User.email == email)):
            print(f"  existe déjà : {email}")
            continue
        db.add(User(email=email, phone=phone, password_hash=hash_password(PASSWORD), full_name=name, role=role,
                    status=UserStatus.active, email_verified=True, phone_verified=bool(phone), commune=commune,
                    language=Language.fr, notification_channels=["push", "email"] + (["sms"] if phone else [])))
        print(f"  créé        : {email}  ({role.value})")
    db.commit()
    print(f"Mot de passe de tous les comptes : {PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
