from __future__ import annotations

import re

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
_E164_RE = re.compile(r"^\+\d{8,15}$")


def normalize_phone(raw: str) -> str | None:
    """Numéro au format E.164, ou None s'il n'en a pas l'allure.
    8 chiffres seuls = numéro burkinabè (+226) ; un numéro étranger doit commencer par + ou 00."""
    s = re.sub(r"[\s().-]", "", raw.strip())
    if s.startswith("00"):
        s = "+" + s[2:]
    if re.fullmatch(r"\d{8}", s):
        s = "+226" + s
    elif re.fullmatch(r"226\d{8}", s):
        s = "+" + s
    return s if _E164_RE.fullmatch(s) else None


def is_valid_username(value: str) -> bool:
    # au moins une lettre : évite qu'un identifiant se confonde avec un numéro de téléphone
    return bool(_USERNAME_RE.fullmatch(value)) and any(c.isalpha() for c in value)


def classify_identifier(raw: str) -> tuple[str, str] | None:
    """('email'|'phone'|'username', valeur normalisée) à partir de ce que l'utilisateur a saisi."""
    raw = raw.strip()
    if "@" in raw:
        return "email", raw.lower()
    phone = normalize_phone(raw)
    if phone:
        return "phone", phone
    if is_valid_username(raw):
        return "username", raw.lower()
    return None
