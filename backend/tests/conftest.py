import os
import shutil
import tempfile
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="anam_auth_test_")
os.environ.update(
    ENV="test",
    JWT_SECRET="test-secret-" + "x" * 40,
    DATABASE_URL=f"sqlite:///{Path(_TMP, 'test.db').as_posix()}",
    LOGIN_MAX_FAILURES="3",
    VERIFICATION_RESEND_SECONDS="0",
    VERIFICATION_MAX_ATTEMPTS="3",
    STORAGE_DIR=str(Path(_TMP, "storage")),
)

import pyotp  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbmod  # noqa: E402
from app import notifications, security  # noqa: E402
from app.main import app  # noqa: E402
from app import module1_bridge  # noqa: E402
from app.models import Language, Role, User, UserStatus  # noqa: E402
from app.seed import seed_reference_data  # noqa: E402

PASSWORD = "MotDePasse1"


class Clock:
    """Horloge contrôlée pour la 2FA (un code TOTP ne peut servir qu'une fois par pas de 30 s)."""

    def __init__(self):
        self.t = 1_800_000_000.0

    def advance(self, seconds: float = 30):
        self.t += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(security, "time", types.SimpleNamespace(time=lambda: c.t))
    return c


@pytest.fixture(autouse=True)
def fresh_db():
    dbmod.Base.metadata.drop_all(dbmod.get_engine())
    dbmod.init_db()
    seeder = dbmod.new_session()
    seed_reference_data(seeder)
    seeder.close()
    shutil.rmtree(Path(_TMP, "storage"), ignore_errors=True)
    notifications.OUTBOX.clear()


def _fake_media(out_dir, stem):
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for lang in ("fr", "en", "mos"):
        audio, video = out_dir / f"{stem}_{lang}.mp3", out_dir / f"{stem}_{lang}.mp4"
        audio.write_bytes(b"AUDIO-" + lang.encode())
        video.write_bytes(b"VIDEO-" + lang.encode())
        files[lang] = {"audio": audio, "video": video}
    return {"texts": {"fr": "Texte français lu.", "en": "English text read.", "mos": "Texte moore lu."}, "files": files}


@pytest.fixture(autouse=True)
def no_external_services(monkeypatch):
    """Aucun test n'appelle CITADEL, MyMemory, Edge TTS ou ffmpeg : la génération de médias est simulée."""
    monkeypatch.setattr(module1_bridge, "generate_alert_media", lambda image, text, out: _fake_media(out, "alerte"))
    monkeypatch.setattr(module1_bridge, "generate_bulletin_media", lambda pdf, out: _fake_media(out, "bulletin"))
    monkeypatch.setattr(module1_bridge, "translate", lambda text, lang: f"[{lang}] {text}")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = next(dbmod.get_db())
    yield session
    session.close()


@pytest.fixture
def make_user(db):
    def _make(role=Role.grand_public, *, email=None, phone=None, username=None, status=UserStatus.active,
              commune=None, password=PASSWORD, channels=("push",), language=Language.fr):
        user = User(email=email, phone=phone, username=username, password_hash=security.hash_password(password),
                    role=role, status=status, commune=commune, notification_channels=list(channels), language=language)
        db.add(user)
        db.commit()
        return user

    return _make


class Session:
    """Connexion complète d'un compte (gère la 2FA), avec l'en-tête d'autorisation prêt à l'emploi."""

    def __init__(self, client, clock):
        self.client, self.clock = client, clock
        self.secrets = {}

    def login(self, identifier, password=PASSWORD):
        r = self.client.post("/auth/login", json={"identifier": identifier, "password": password})
        assert r.status_code == 200, r.text
        body = r.json()
        if body["requires_2fa_setup"]:
            hdr = {"Authorization": f"Bearer {body['setup_token']}"}
            secret = self.client.post("/auth/2fa/setup", headers=hdr).json()["secret"]
            self.secrets[identifier] = secret
            self.clock.advance()
            r = self.client.post("/auth/2fa/enable", headers=hdr, json={"code": pyotp.TOTP(secret).at(self.clock.t)})
            assert r.status_code == 200, r.text
            return r.json()
        if body["requires_2fa"]:
            self.clock.advance()
            code = pyotp.TOTP(self.secrets[identifier]).at(self.clock.t)
            r = self.client.post("/auth/2fa/verify", json={"challenge_token": body["challenge_token"], "code": code})
            assert r.status_code == 200, r.text
            return r.json()
        return body["tokens"]

    def headers(self, identifier, password=PASSWORD):
        return {"Authorization": f"Bearer {self.login(identifier, password)['access_token']}"}


@pytest.fixture
def session(client, clock):
    return Session(client, clock)


ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "module1" / "samples"


@pytest.fixture
def staff(make_user, session):
    """Renvoie les en-têtes d'autorisation d'un compte du rôle demandé (2FA comprise), créé à la demande."""
    cache = {}

    def _staff(role=Role.agent_anam):
        if role not in cache:
            email = f"{role.value}@anam.bf"
            make_user(role, email=email)
            cache[role] = session.headers(email)
        return cache[role]

    return _staff
