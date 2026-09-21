import pyotp

from app import notifications
from app.models import Role, UserStatus
from conftest import PASSWORD


def _last_code():
    return notifications.OUTBOX[-1]["message"].split("est ")[1][:6]


def _register_phone(client, phone="70123456", **extra):
    return client.post("/auth/register", json={"method": "phone", "phone": phone, "password": PASSWORD, **extra})


# ------------------------------------------------------------ inscription
def test_register_by_phone_then_verify_then_login(client):
    r = _register_phone(client)
    assert r.status_code == 201
    assert r.json()["verification_channel"] == "sms" and r.json()["status"] == "pending"
    assert notifications.OUTBOX[-1]["to"] == "+22670123456"

    # pas de connexion avant activation
    r = client.post("/auth/login", json={"identifier": "70123456", "password": PASSWORD})
    assert r.status_code == 403

    r = client.post("/auth/verify", json={"identifier": "+226 70 12 34 56", "code": _last_code()})
    assert r.status_code == 200

    r = client.post("/auth/login", json={"identifier": "70123456", "password": PASSWORD})
    tokens = r.json()["tokens"]
    me = client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    assert me["phone"] == "+22670123456" and me["role"] == "grand_public" and me["status"] == "active"
    assert "password_hash" not in me and "totp_secret_enc" not in me


def test_register_by_email_then_verify(client):
    r = client.post("/auth/register", json={"method": "email", "email": "Jean@Example.com", "password": PASSWORD,
                                            "commune": "Kaya", "language": "mos"})
    assert r.status_code == 201
    assert notifications.OUTBOX[-1]["channel"] == "email" and notifications.OUTBOX[-1]["to"] == "jean@example.com"
    assert client.post("/auth/verify", json={"identifier": "jean@example.com", "code": _last_code()}).status_code == 200
    tokens = client.post("/auth/login", json={"identifier": "JEAN@example.com", "password": PASSWORD}).json()["tokens"]
    me = client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    assert me["commune"] == "Kaya" and me["language"] == "mos"
    assert set(me["notification_channels"]) == {"push", "email"}


def test_local_account_needs_admin_validation(client, make_user, session):
    r = client.post("/auth/register", json={"method": "local", "username": "Agent_Kaya", "password": PASSWORD})
    assert r.status_code == 201 and r.json()["verification_required"] is False
    assert client.post("/auth/login", json={"identifier": "agent_kaya", "password": PASSWORD}).status_code == 403

    make_user(Role.administrateur, email="admin@anam.bf")
    admin = session.headers("admin@anam.bf")
    pending = client.get("/admin/users?status=pending", headers=admin).json()
    assert pending["total"] == 1
    assert client.post(f"/admin/users/{pending['items'][0]['id']}/activate", headers=admin).status_code == 200
    assert client.post("/auth/login", json={"identifier": "agent_kaya", "password": PASSWORD}).status_code == 200


def test_duplicate_and_invalid_registration(client):
    assert _register_phone(client).status_code == 201
    assert _register_phone(client, phone="+226 70 12 34 56").status_code == 409
    assert _register_phone(client, phone="123").status_code == 422
    assert client.post("/auth/register", json={"method": "phone", "phone": "70000000", "password": "court"}).status_code == 422
    assert client.post("/auth/register", json={"method": "email", "password": PASSWORD}).status_code == 422
    assert _register_phone(client, phone="70999999", commune="Paris").status_code == 422


def test_register_cannot_choose_role(client):
    r = _register_phone(client, role="administrateur")
    assert r.status_code == 201
    client.post("/auth/verify", json={"identifier": "70123456", "code": _last_code()})
    tokens = client.post("/auth/login", json={"identifier": "70123456", "password": PASSWORD}).json()["tokens"]
    assert client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()["role"] == "grand_public"


def test_verification_attempts_are_limited(client):
    _register_phone(client)
    good = _last_code()
    bad = "000000" if good != "000000" else "111111"
    for _ in range(3):
        assert client.post("/auth/verify", json={"identifier": "70123456", "code": bad}).status_code == 400
    # le bon code ne passe plus après trop d'essais : il faut en redemander un
    assert client.post("/auth/verify", json={"identifier": "70123456", "code": good}).status_code == 400
    assert client.post("/auth/resend-code", json={"identifier": "70123456"}).status_code == 202
    assert client.post("/auth/verify", json={"identifier": "70123456", "code": _last_code()}).status_code == 200


def test_resend_code_does_not_reveal_accounts(client):
    known = _register_phone(client) and client.post("/auth/resend-code", json={"identifier": "70123456"})
    unknown = client.post("/auth/resend-code", json={"identifier": "79999999"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


# ------------------------------------------------------------ connexion / sessions
def test_wrong_password_and_lockout(client, make_user):
    make_user(email="a@anam.bf")
    for _ in range(3):
        r = client.post("/auth/login", json={"identifier": "a@anam.bf", "password": "mauvais-mot-de-passe"})
        assert r.status_code == 401
    # verrouillé : même le bon mot de passe est refusé
    assert client.post("/auth/login", json={"identifier": "a@anam.bf", "password": PASSWORD}).status_code == 429
    # identifiant inconnu : même réponse qu'un mauvais mot de passe
    r = client.post("/auth/login", json={"identifier": "inconnu@anam.bf", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == "Identifiant ou mot de passe incorrect."


def test_disabled_account_cannot_login(client, make_user):
    make_user(email="a@anam.bf", status=UserStatus.disabled)
    assert client.post("/auth/login", json={"identifier": "a@anam.bf", "password": PASSWORD}).status_code == 403


def test_refresh_rotation_and_reuse_detection(client, make_user):
    make_user(email="a@anam.bf")
    first = client.post("/auth/login", json={"identifier": "a@anam.bf", "password": PASSWORD}).json()["tokens"]
    second = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    second = second.json()
    assert second["refresh_token"] != first["refresh_token"]

    # rejouer l'ancien jeton = vol présumé : tout est révoqué, y compris le jeton légitime récent
    assert client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh_token(client, make_user):
    make_user(email="a@anam.bf")
    tokens = client.post("/auth/login", json={"identifier": "a@anam.bf", "password": PASSWORD}).json()["tokens"]
    assert client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/auth/logout", json={"refresh_token": "n-importe-quoi"}).status_code == 204


def test_protected_routes_require_valid_token(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_disabled_user_loses_access_immediately(client, make_user, session, db):
    user = make_user(email="a@anam.bf")
    headers = session.headers("a@anam.bf")
    assert client.get("/me", headers=headers).status_code == 200
    user.status = UserStatus.disabled
    db.commit()
    assert client.get("/me", headers=headers).status_code == 401


# ------------------------------------------------------------ profil
def test_profile_update(client, make_user, session):
    make_user(email="a@anam.bf")
    h = session.headers("a@anam.bf")
    r = client.patch("/me", headers=h, json={"commune": "Ziniaré", "language": "en", "notification_channels": ["push", "email"]})
    assert r.status_code == 200 and r.json()["commune"] == "Ziniaré" and r.json()["language"] == "en"
    assert client.patch("/me", headers=h, json={"commune": "Paris"}).status_code == 422
    # ce compte n'a pas de téléphone : le canal SMS est refusé
    assert client.patch("/me", headers=h, json={"notification_channels": ["sms"]}).status_code == 422


def test_profile_cannot_change_role(client, make_user, session):
    make_user(email="a@anam.bf")
    h = session.headers("a@anam.bf")
    client.patch("/me", headers=h, json={"role": "administrateur"})
    assert client.get("/me", headers=h).json()["role"] == "grand_public"


def test_change_password_revokes_sessions(client, make_user):
    make_user(email="a@anam.bf")
    tokens = client.post("/auth/login", json={"identifier": "a@anam.bf", "password": PASSWORD}).json()["tokens"]
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/me/password", headers=h, json={"current_password": "faux-mot-de-passe", "new_password": "NouveauMdp42"}).status_code == 400
    assert client.post("/me/password", headers=h, json={"current_password": PASSWORD, "new_password": "NouveauMdp42"}).status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/auth/login", json={"identifier": "a@anam.bf", "password": PASSWORD}).status_code == 401
    assert client.post("/auth/login", json={"identifier": "a@anam.bf", "password": "NouveauMdp42"}).status_code == 200


# ------------------------------------------------------------ 2FA
def test_two_factor_flow_for_admin(client, make_user, clock, session):
    make_user(Role.administrateur, email="admin@anam.bf")

    r = client.post("/auth/login", json={"identifier": "admin@anam.bf", "password": PASSWORD}).json()
    assert r["requires_2fa_setup"] and r["tokens"] is None
    setup_hdr = {"Authorization": f"Bearer {r['setup_token']}"}
    # le token de configuration ne donne accès à rien d'autre
    assert client.get("/me", headers=setup_hdr).status_code == 401

    secret = client.post("/auth/2fa/setup", headers=setup_hdr).json()["secret"]
    clock.advance()
    assert client.post("/auth/2fa/enable", headers=setup_hdr, json={"code": "000000"}).status_code == 401
    tokens = client.post("/auth/2fa/enable", headers=setup_hdr, json={"code": pyotp.TOTP(secret).at(clock.t)}).json()
    assert client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()["totp_enabled"] is True

    # connexions suivantes : challenge + code
    r = client.post("/auth/login", json={"identifier": "admin@anam.bf", "password": PASSWORD}).json()
    assert r["requires_2fa"] and r["tokens"] is None
    challenge = r["challenge_token"]
    assert client.post("/auth/2fa/verify", json={"challenge_token": challenge, "code": "123456"}).status_code == 401

    # le code déjà utilisé à l'activation ne peut pas resservir (rejeu)
    used = pyotp.TOTP(secret).at(clock.t)
    assert client.post("/auth/2fa/verify", json={"challenge_token": challenge, "code": used}).status_code == 401

    clock.advance()
    ok = client.post("/auth/2fa/verify", json={"challenge_token": challenge, "code": pyotp.TOTP(secret).at(clock.t)})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_challenge_token_cannot_be_used_as_access_token(client, make_user, clock, session):
    make_user(Role.administrateur, email="admin@anam.bf")
    session.login("admin@anam.bf")
    challenge = client.post("/auth/login", json={"identifier": "admin@anam.bf", "password": PASSWORD}).json()["challenge_token"]
    assert client.get("/me", headers={"Authorization": f"Bearer {challenge}"}).status_code == 401
