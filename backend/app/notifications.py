"""Canaux d'envoi : SMS (API Orange), push (Firebase FCM), e-mail (SMTP), WhatsApp (Cloud API).

Chaque canal a un backend `console` (simulation : le message est journalisé et conservé dans
OUTBOX, rien ne part) — c'est le mode de développement et de test. Les backends réels
(`orange`, `fcm`, `smtp`, `cloud`) s'activent par la configuration (SMS_BACKEND, PUSH_BACKEND,
EMAIL_BACKEND, WHATSAPP_BACKEND).

ATTENTION : les backends Orange, FCM et WhatsApp sont écrits d'après la documentation publique des
API mais n'ont PAS été essayés en réel (pas d'identifiants à ce jour) : à valider dès réception des accès.
"""

from __future__ import annotations

import base64
import json
import logging
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import httpx
import jwt

from .config import get_settings

log = logging.getLogger("auth.notifications")

OUTBOX: list[dict] = []  # messages « envoyés » par le backend console (tests, interface de test)


class InvalidRecipient(Exception):
    """Le destinataire n'existe plus (ex. jeton d'appareil désinstallé) : à supprimer côté base."""


class ConsoleSender:
    simulated = True

    def __init__(self, channel: str) -> None:
        self.channel = channel

    def send(self, to: str, message: str, title: str | None = None, data: dict | None = None) -> None:
        OUTBOX.append({"channel": self.channel, "to": to, "title": title, "message": message, "data": data})
        del OUTBOX[:-500]  # borne la mémoire
        log.warning("[%s -> %s] %s", self.channel, to, message)


class SmtpEmailSender:
    simulated = False

    def send(self, to: str, message: str, title: str | None = None, data: dict | None = None) -> None:
        s = get_settings()
        msg = EmailMessage()
        msg["Subject"] = title or "ANAM"
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg.set_content(message)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)


class OrangeSmsSender:
    """API « SMS » d'Orange (developer.orange.com) : jeton OAuth2 puis envoi vers tel:+numéro."""

    simulated = False
    TOKEN_URL = "https://api.orange.com/oauth/v3/token"
    API_URL = "https://api.orange.com/smsmessaging/v1/outbound/{sender}/requests"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=20)
        self._token: str | None = None
        self._expires = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._expires - 30:
            return self._token
        s = get_settings()
        basic = base64.b64encode(f"{s.orange_client_id}:{s.orange_client_secret}".encode()).decode()
        r = self.client.post(self.TOKEN_URL, data={"grant_type": "client_credentials"},
                             headers={"Authorization": f"Basic {basic}"})
        r.raise_for_status()
        body = r.json()
        self._token, self._expires = body["access_token"], time.time() + int(body.get("expires_in", 3600))
        return self._token

    def send(self, to: str, message: str, title: str | None = None, data: dict | None = None) -> None:
        s = get_settings()
        sender = f"tel:{s.orange_sender}"
        payload = {"outboundSMSMessageRequest": {
            "address": f"tel:{to}", "senderAddress": sender, "senderName": s.orange_sender_name,
            "outboundSMSTextMessage": {"message": message}}}
        r = self.client.post(self.API_URL.format(sender=quote(sender, safe="")), json=payload,
                             headers={"Authorization": f"Bearer {self._access_token()}"})
        r.raise_for_status()


class FcmPushSender:
    """Firebase Cloud Messaging, API HTTP v1 (compte de service Google)."""

    simulated = False
    SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=20)
        self._creds = json.loads(Path(get_settings().fcm_credentials_file).read_text(encoding="utf-8"))
        self._token: str | None = None
        self._expires = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._expires - 30:
            return self._token
        c = self._creds
        now = int(time.time())
        assertion = jwt.encode({"iss": c["client_email"], "scope": self.SCOPE, "aud": c["token_uri"],
                                "iat": now, "exp": now + 3600}, c["private_key"], algorithm="RS256")
        r = self.client.post(c["token_uri"], data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                                   "assertion": assertion})
        r.raise_for_status()
        body = r.json()
        self._token, self._expires = body["access_token"], time.time() + int(body.get("expires_in", 3600))
        return self._token

    def send(self, to: str, message: str, title: str | None = None, data: dict | None = None) -> None:
        url = f"https://fcm.googleapis.com/v1/projects/{self._creds['project_id']}/messages:send"
        payload = {"message": {"token": to, "notification": {"title": title or "ANAM", "body": message},
                               "data": {k: str(v) for k, v in (data or {}).items()}}}
        r = self.client.post(url, json=payload, headers={"Authorization": f"Bearer {self._access_token()}"})
        if r.status_code == 404 or (r.status_code == 400 and "UNREGISTERED" in r.text):
            raise InvalidRecipient(to)
        r.raise_for_status()


class WhatsAppCloudSender:
    """API WhatsApp Business (Cloud API de Meta) : messages texte vers des numéros.
    Hors fenêtre de 24 h après un message du destinataire, Meta exige des modèles de message approuvés."""

    simulated = False

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=20)

    def send(self, to: str, message: str, title: str | None = None, data: dict | None = None) -> None:
        s = get_settings()
        url = f"https://graph.facebook.com/v20.0/{s.whatsapp_phone_number_id}/messages"
        payload = {"messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "text",
                   "text": {"preview_url": False, "body": message}}
        r = self.client.post(url, json=payload, headers={"Authorization": f"Bearer {s.whatsapp_token}"})
        r.raise_for_status()


_CACHE: dict[str, object] = {}


def get_sender(channel: str):
    """Renvoie l'émetteur du canal ('sms' | 'push' | 'email' | 'whatsapp'), conservé entre les appels
    (jetons OAuth réutilisés)."""
    s = get_settings()
    backend = {"sms": s.sms_backend, "push": s.push_backend, "email": s.email_backend,
               "whatsapp": s.whatsapp_backend}[channel]
    key = f"{channel}:{backend}"
    if key in _CACHE:
        return _CACHE[key]
    if backend == "console":
        sender = ConsoleSender(channel)
    elif (channel, backend) == ("sms", "orange"):
        sender = OrangeSmsSender()
    elif (channel, backend) == ("push", "fcm"):
        sender = FcmPushSender()
    elif (channel, backend) == ("email", "smtp"):
        sender = SmtpEmailSender()
    elif (channel, backend) == ("whatsapp", "cloud"):
        sender = WhatsAppCloudSender()
    else:
        raise RuntimeError(f"Backend '{backend}' inconnu pour le canal '{channel}'.")
    _CACHE[key] = sender
    return sender


def send_verification_code(channel: str, to: str, code: str, minutes: int) -> None:
    get_sender(channel).send(to, f"ANAM : votre code de vérification est {code}. Il expire dans {minutes} minutes.",
                             title="ANAM - code de vérification")
