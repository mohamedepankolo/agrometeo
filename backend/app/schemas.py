from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .identifiers import is_valid_username, normalize_phone
from .models import COMMUNES, Channel, Language, Role, UserStatus

Password = Field(min_length=8, max_length=128)


def _check_commune(v: str | None) -> str | None:
    if v is not None and v not in COMMUNES:
        raise ValueError(f"Commune inconnue. Valeurs possibles : {', '.join(COMMUNES)}")
    return v


class _Identity(BaseModel):
    """Champs d'identification partagés par l'inscription et la création de compte interne."""

    phone: str | None = None
    email: EmailStr | None = None
    username: str | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        if v is None:
            return v
        n = normalize_phone(v)
        if not n:
            raise ValueError("Numéro de téléphone invalide (format international ou 8 chiffres burkinabè).")
        return n

    @field_validator("username")
    @classmethod
    def _username(cls, v):
        if v is None:
            return v
        if not is_valid_username(v):
            raise ValueError("Identifiant : 3 à 32 caractères (lettres, chiffres, . _ -), avec au moins une lettre.")
        return v.lower()

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return v.lower() if v else v


class RegisterRequest(_Identity):
    method: Literal["phone", "email", "local"]
    password: str = Password
    full_name: str | None = Field(default=None, max_length=120)
    commune: str | None = None
    language: Language = Language.fr

    _commune = field_validator("commune")(_check_commune)

    @model_validator(mode="after")
    def _required_field(self):
        field = {"phone": "phone", "email": "email", "local": "username"}[self.method]
        if not getattr(self, field):
            raise ValueError(f"Le champ '{field}' est obligatoire pour une inscription par '{self.method}'.")
        return self


class VerifyRequest(BaseModel):
    identifier: str
    code: str = Field(pattern=r"^\d{6}$")


class ResendRequest(BaseModel):
    identifier: str


class LoginRequest(BaseModel):
    identifier: str
    password: str


class TwoFactorLoginRequest(BaseModel):
    challenge_token: str
    code: str = Field(pattern=r"^\d{6}$")


class TwoFactorEnableRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # secondes de validité du access_token
    must_change_password: bool = False


class LoginResponse(BaseModel):
    """Trois cas exclusifs : jetons (connexion terminée), challenge 2FA, ou configuration 2FA à faire."""

    tokens: TokenPair | None = None
    requires_2fa: bool = False
    challenge_token: str | None = None
    requires_2fa_setup: bool = False
    setup_token: str | None = None


class TwoFactorSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str  # à afficher en QR code côté application


class MessageResponse(BaseModel):
    message: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    phone: str | None
    email: str | None
    username: str | None
    full_name: str | None
    role: Role
    status: UserStatus
    commune: str | None
    language: Language
    notification_channels: list[Channel]
    totp_enabled: bool
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    commune: str | None = None
    language: Language | None = None
    notification_channels: list[Channel] | None = None

    _commune = field_validator("commune")(_check_commune)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Password


class InternalAccountCreate(_Identity):
    """Création d'un compte agent / administrateur / etc. par un administrateur."""

    password: str = Password  # mot de passe initial, à changer à la 1re connexion
    role: Role
    full_name: str | None = Field(default=None, max_length=120)
    commune: str | None = None

    _commune = field_validator("commune")(_check_commune)

    @model_validator(mode="after")
    def _one_identifier(self):
        if not (self.phone or self.email or self.username):
            raise ValueError("Fournir au moins un identifiant : phone, email ou username.")
        return self


class RoleChange(BaseModel):
    role: Role


class UserList(BaseModel):
    total: int
    items: list[UserOut]


class CommuneStat(BaseModel):
    commune: str
    users: int
