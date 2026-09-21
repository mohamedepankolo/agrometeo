"""Envoi des codes de vérification (SMS / e-mail).

Deux implémentations : `console` (développement et tests : le message est journalisé
et conservé dans OUTBOX) et `smtp` (e-mail réel). L'envoi de SMS par l'API Orange reste
à brancher : il suffit d'ajouter une classe respectant `send(to, message)` et de
l'enregistrer dans `_SMS_BACKENDS` — le reste du code n'a pas à changer.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from .config import get_settings

log = logging.getLogger("auth.notifications")

OUTBOX: list[dict] = []  # messages « envoyés » par le backend console (tests)


class Sender(Protocol):
    def send(self, to: str, message: str) -> None: ...


class ConsoleSender:
    def __init__(self, channel: str) -> None:
        self.channel = channel

    def send(self, to: str, message: str) -> None:
        OUTBOX.append({"channel": self.channel, "to": to, "message": message})
        log.warning("[%s -> %s] %s", self.channel, to, message)


class SmtpEmailSender:
    def send(self, to: str, message: str) -> None:
        s = get_settings()
        msg = EmailMessage()
        msg["Subject"] = "ANAM - code de vérification"
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg.set_content(message)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)


def get_sender(channel: str) -> Sender:
    s = get_settings()
    if channel == "sms":
        if s.sms_backend == "console":
            return ConsoleSender("sms")
        raise RuntimeError(f"SMS_BACKEND '{s.sms_backend}' non implémenté (API Orange à brancher).")
    if channel == "email":
        if s.email_backend == "console":
            return ConsoleSender("email")
        if s.email_backend == "smtp":
            return SmtpEmailSender()
        raise RuntimeError(f"EMAIL_BACKEND '{s.email_backend}' inconnu.")
    raise ValueError(channel)


def send_verification_code(channel: str, to: str, code: str, minutes: int) -> None:
    get_sender(channel).send(to, f"ANAM : votre code de vérification est {code}. Il expire dans {minutes} minutes.")
