import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import notifications
from app.config import get_settings
from app.main import app
from app.models import Role, UserStatus
from conftest import PASSWORD


# ------------------------------------------------------------ rôles, appareils, événements, back-office
def test_roles_endpoint_documents_the_permission_matrix(client):
    data = client.get("/roles").json()
    by_role = {r["role"]: r for r in data["roles"]}
    assert set(by_role) == {"grand_public", "observateur", "responsable_communal", "agent_anam", "administrateur"}
    assert by_role["administrateur"]["requires_2fa"] and by_role["agent_anam"]["requires_2fa"]
    assert not by_role["grand_public"]["requires_2fa"]
    assert set(by_role["administrateur"]["permissions"]) == set(data["permissions"])
    assert "content:publish" not in by_role["observateur"]["permissions"]


def test_device_registration(client, make_user, session, db):
    from sqlalchemy import select

    from app.models_content import DeviceToken

    make_user(email="a@x.bf")
    h = session.headers("a@x.bf")
    assert client.post("/me/devices", json={"token": "fcm-token-abcdef", "platform": "android"}).status_code == 401
    assert client.post("/me/devices", headers=h, json={"token": "fcm-token-abcdef", "platform": "android"}).status_code == 204
    assert client.post("/me/devices", headers=h, json={"token": "fcm-token-abcdef", "platform": "ios"}).status_code == 204  # idempotent
    assert client.post("/me/devices", headers=h, json={"token": "court"}).status_code == 422
    assert len(db.scalars(select(DeviceToken)).all()) == 1
    assert client.delete("/me/devices", headers=h, params={"token": "fcm-token-abcdef"}).status_code == 204
    assert db.scalars(select(DeviceToken)).all() == []


def test_usage_events_feed_the_dashboard(client, staff, make_user):
    make_user(email="k@x.bf", commune="Kaya")
    make_user(email="p@x.bf", commune="Kaya", status=UserStatus.pending)
    for kind, lang in [("view", "fr"), ("view", "mos"), ("play_audio", "mos"), ("share", None)]:
        assert client.post("/events", json={"content_type": "bulletin", "content_id": "b1", "kind": kind, "language": lang}).status_code == 204
    assert client.post("/events", json={"content_type": "autre", "content_id": "b1"}).status_code == 422

    agent = staff()
    dash = client.get("/backoffice/dashboard", headers=agent).json()
    assert dash["usage_last_7_days"] == {"view": 2, "play_audio": 1, "share": 1}
    assert dash["users"]["by_status"]["pending"] == 1 and dash["users"]["by_role"]["grand_public"] == 2
    assert {"commune": "Kaya", "users": 1} in dash["users"]["active_by_commune"]
    usage = client.get("/backoffice/usage", headers=agent).json()
    assert usage["by_language"] == {"fr": 1, "mos": 2, "inconnue": 1}
    assert usage["top_content"][0] == {"content_type": "bulletin", "content_id": "b1", "events": 4}
    assert client.get("/backoffice/dashboard").status_code == 401
    assert client.get("/backoffice/dashboard", headers=staff(Role.observateur)).status_code == 403


def test_sms_pilot_tracking(client, staff, make_user):
    make_user(email="a@x.bf", phone="+22670000001", channels=("sms",))
    make_user(email="b@x.bf", phone="+22670000002", channels=("push",))
    zones = {z["name"]: z["id"] for z in client.get("/zones").json()}
    types = {t["code"]: t["id"] for t in client.get("/alert-types").json()}
    a = client.post("/alerts", headers=staff(), json={"alert_type_id": types["orages"], "level": "jaune", "raw_text": "Texte d'alerte suffisant."}).json()
    client.post(f"/alerts/{a['id']}/publish", headers=staff())
    pilot = client.get("/backoffice/sms-pilot", headers=staff()).json()
    assert pilot["target_users"] == 500 and pilot["users_opted_in_sms"] == 1
    assert pilot["distinct_recipients_reached"] == 1 and pilot["deliveries_by_status"] == {"simulated": 1}
    assert zones  # référentiel présent


# ------------------------------------------------------------ outils de développement
def test_dev_tools_verification_code_and_db_explorer(client, make_user):
    client.post("/auth/register", json={"method": "phone", "phone": "70123456", "password": PASSWORD})
    code = client.get("/dev/verification-code", params={"identifier": "70123456"}).json()["code"]
    assert client.post("/auth/verify", json={"identifier": "70123456", "code": code}).status_code == 200
    assert client.get("/dev/verification-code", params={"identifier": "79999999"}).status_code == 404

    tables = client.get("/dev/db").json()
    assert tables["users"] == 1 and tables["zones"] == 10 and tables["alert_types"] == 7
    rows = client.get("/dev/db/users").json()
    user = rows["rows"][0]
    assert user["password_hash"] == "***" and user["phone"] == "+22670123456"
    assert client.get("/dev/db/inconnue").status_code == 404
    assert client.get("/dev/status").json()["backends"]["sms"] == "console"
    assert client.get("/dev/outbox").json()[0]["channel"] == "sms"


# ------------------------------------------------------------ documentation OpenAPI
def test_every_route_documents_its_access_rules():
    spec = app.openapi()
    missing = [f"{m.upper()} {p}" for p, ops in spec["paths"].items() for m, op in ops.items()
               if p != "/health" and "Accès :" not in op.get("description", "")]
    assert missing == []
    assert "content:publish" in spec["paths"]["/alerts/{alert_id}/publish"]["post"]["description"]
    assert len(spec["paths"]) > 60
    tags = {t for ops in spec["paths"].values() for op in ops.values() for t in op.get("tags", [])}
    assert {"Alertes", "Bulletins", "Back-office", "Authentification"} <= tags


# ------------------------------------------------------------ canaux d'envoi réels (serveurs simulés)
def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_orange_sms_request_shape(monkeypatch):
    s = get_settings()
    for k, v in {"orange_client_id": "id", "orange_client_secret": "secret", "orange_sender": "+22670000000", "orange_sender_name": "ANAM"}.items():
        monkeypatch.setattr(s, k, v)
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path == "/oauth/v3/token":
            assert request.headers["authorization"].startswith("Basic ") and b"client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(201, json={})

    sender = notifications.OrangeSmsSender(_client(handler))
    sender.send("+22671111111", "Alerte test")
    sender.send("+22672222222", "Deuxième")  # le jeton est réutilisé
    tokens = [r for r in seen if r.url.path == "/oauth/v3/token"]
    sms = [r for r in seen if "smsmessaging" in r.url.path]
    assert len(tokens) == 1 and len(sms) == 2
    assert "tel%3A%2B22670000000" in str(sms[0].url)
    body = json.loads(sms[0].content)["outboundSMSMessageRequest"]
    assert body["address"] == "tel:+22671111111" and body["outboundSMSTextMessage"]["message"] == "Alerte test"
    assert sms[0].headers["authorization"] == "Bearer tok"


def test_orange_sms_http_error_is_raised():
    sender = notifications.OrangeSmsSender(_client(lambda r: httpx.Response(401, json={"error": "x"})))
    with pytest.raises(httpx.HTTPStatusError):
        sender.send("+22671111111", "x")


def test_fcm_push_request_and_dead_token(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    creds = tmp_path / "fcm.json"
    creds.write_text(json.dumps({"project_id": "anam-test", "client_email": "svc@anam-test.iam.gserviceaccount.com",
                                 "private_key": pem, "token_uri": "https://oauth2.googleapis.com/token"}))
    monkeypatch.setattr(get_settings(), "fcm_credentials_file", str(creds))

    def handler(request: httpx.Request):
        if request.url.host == "oauth2.googleapis.com":
            assert b"jwt-bearer" in request.content
            return httpx.Response(200, json={"access_token": "gtok", "expires_in": 3600})
        assert str(request.url) == "https://fcm.googleapis.com/v1/projects/anam-test/messages:send"
        msg = json.loads(request.content)["message"]
        if msg["token"] == "mort":
            return httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})
        assert msg["notification"] == {"title": "ALERTE", "body": "Texte"} and msg["data"] == {"content_id": "42"}
        assert request.headers["authorization"] == "Bearer gtok"
        return httpx.Response(200, json={"name": "ok"})

    sender = notifications.FcmPushSender(_client(handler))
    sender.send("vivant", "Texte", title="ALERTE", data={"content_id": 42})
    with pytest.raises(notifications.InvalidRecipient):
        sender.send("mort", "Texte")


def test_whatsapp_cloud_request(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_token", "wtok")
    monkeypatch.setattr(s, "whatsapp_phone_number_id", "12345")

    def handler(request: httpx.Request):
        assert str(request.url) == "https://graph.facebook.com/v20.0/12345/messages"
        assert request.headers["authorization"] == "Bearer wtok"
        body = json.loads(request.content)
        assert body["to"] == "22671111111" and body["type"] == "text" and body["text"]["body"] == "Bonjour"
        return httpx.Response(200, json={"messages": [{"id": "w1"}]})

    notifications.WhatsAppCloudSender(_client(handler)).send("+22671111111", "Bonjour")


def test_unknown_backend_is_refused(monkeypatch):
    monkeypatch.setattr(get_settings(), "sms_backend", "inconnu")
    with pytest.raises(RuntimeError):
        notifications.get_sender("sms")


def test_production_refuses_simulated_channels(monkeypatch):
    from app import config

    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "y" * 40)
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="console"):
            config.get_settings()
    finally:
        monkeypatch.setenv("ENV", "test")
        config.get_settings.cache_clear()
