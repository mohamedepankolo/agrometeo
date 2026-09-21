from __future__ import annotations

import logging
import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("auth")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"  # dev | test | prod
    database_url: str = "sqlite:///./anam_dev.db"

    jwt_secret: str = ""
    data_encryption_key: str = ""  # chiffrement des secrets 2FA ; dérivé de jwt_secret si absent
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    challenge_token_minutes: int = 5

    verification_code_minutes: int = 10
    verification_max_attempts: int = 5
    verification_resend_seconds: int = 60

    login_max_failures: int = 5
    login_lockout_minutes: int = 15

    local_account_auto_activate: bool = False
    require_2fa_roles: str = "administrateur,agent_anam"

    cors_origins: str = ""  # liste séparée par des virgules

    sms_backend: str = "console"  # console | (orange : à brancher)
    email_backend: str = "console"  # console | smtp
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    totp_issuer: str = "ANAM"

    # Stockage des médias générés (PDF, images, audios, vidéos) et URL publique de l'API
    storage_dir: str = "./storage"
    public_base_url: str = ""  # ex. https://api.anam.bf ; vide = URLs relatives (/media/...)
    max_upload_mb: int = 25

    # Chaîne audio/vidéo du Module 1
    module1_dir: str = "../module1"
    citadel_translate_url: str = ""
    citadel_api_email: str = ""
    citadel_api_password: str = ""
    moore_api_base_url: str = ""
    moore_api_token: str = ""

    # Diffusion : push (FCM), SMS (Orange), WhatsApp (Cloud API). 'console' = simulation.
    push_backend: str = "console"  # console | fcm
    fcm_credentials_file: str = ""  # clé de compte de service Firebase (JSON)
    orange_client_id: str = ""
    orange_client_secret: str = ""
    orange_sender: str = ""  # ex. +22670000000 (numéro expéditeur enregistré chez Orange)
    orange_sender_name: str = "ANAM"
    whatsapp_backend: str = "console"  # console | cloud
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""

    @property
    def dev_tools(self) -> bool:
        """Outils de développement (/dev/*) : jamais en production."""
        return self.env in {"dev", "test"}

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def roles_requiring_2fa(self) -> set[str]:
        return {r.strip() for r in self.require_2fa_roles.split(",") if r.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.jwt_secret:
        if s.is_prod:
            raise RuntimeError("JWT_SECRET est obligatoire en production.")
        s.jwt_secret = secrets.token_urlsafe(48)
        log.warning("JWT_SECRET absent : secret éphémère généré (les sessions sautent au redémarrage).")
    if s.is_prod and "console" in (s.sms_backend, s.email_backend, s.push_backend, s.whatsapp_backend):
        raise RuntimeError("En production, aucun backend d'envoi ne peut être 'console' (simulation).")
    return s
