"""Crée le premier administrateur (les suivants se créent via l'API /admin/users).

    python -m app.create_admin --email admin@anam.bf
    python -m app.create_admin --username admin_anam

Le mot de passe est demandé de façon interactive (jamais en argument de ligne de commande).
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from . import db as dbmod
from .identifiers import is_valid_username
from .models import Role, User, UserStatus
from .security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email")
    parser.add_argument("--username")
    args = parser.parse_args()
    if bool(args.email) == bool(args.username):
        parser.error("Fournir exactement un des deux : --email ou --username.")
    if args.username and not is_valid_username(args.username):
        parser.error("Identifiant invalide (3 à 32 caractères, avec au moins une lettre).")

    password = getpass.getpass("Mot de passe (8 caractères minimum) : ")
    if len(password) < 8 or password != getpass.getpass("Confirmer : "):
        print("Mot de passe trop court ou différent de la confirmation.", file=sys.stderr)
        return 1

    dbmod.init_db()
    session = next(dbmod.get_db())
    email = args.email.lower() if args.email else None
    username = args.username.lower() if args.username else None
    exists = session.scalar(select(User.id).where((User.email == email) if email else (User.username == username)))
    if exists:
        print("Un compte existe déjà avec cet identifiant.", file=sys.stderr)
        return 1
    session.add(User(email=email, username=username, password_hash=hash_password(password), role=Role.administrateur,
                     status=UserStatus.active, email_verified=bool(email), notification_channels=["push"]))
    session.commit()
    print("Administrateur créé. La 2FA sera à configurer à la première connexion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
