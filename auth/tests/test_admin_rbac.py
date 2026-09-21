from app.models import Role
from conftest import PASSWORD


def test_public_user_cannot_access_admin(client, make_user, session):
    make_user(email="a@anam.bf")
    h = session.headers("a@anam.bf")
    assert client.get("/admin/users", headers=h).status_code == 403
    assert client.get("/admin/stats/communes", headers=h).status_code == 403


def test_agent_can_read_but_not_manage(client, make_user, session):
    make_user(Role.agent_anam, email="agent@anam.bf")
    make_user(email="a@anam.bf")
    h = session.headers("agent@anam.bf")
    assert client.get("/admin/users", headers=h).status_code == 200
    assert client.get("/admin/stats/communes", headers=h).status_code == 200
    assert client.post("/admin/users", headers=h, json={"email": "x@anam.bf", "password": PASSWORD, "role": "agent_anam"}).status_code == 403


def test_admin_creates_internal_account(client, make_user, session):
    make_user(Role.administrateur, email="admin@anam.bf")
    h = session.headers("admin@anam.bf")
    r = client.post("/admin/users", headers=h, json={"email": "agent@anam.bf", "password": "MdpInitial123",
                                                      "role": "agent_anam", "full_name": "Agent Kaya", "commune": "Kaya"})
    assert r.status_code == 201
    assert r.json()["role"] == "agent_anam" and r.json()["must_change_password"] is True
    assert client.post("/admin/users", headers=h, json={"email": "agent@anam.bf", "password": "MdpInitial123",
                                                         "role": "agent_anam"}).status_code == 409

    # le nouvel agent doit configurer la 2FA (rôle qui l'exige) ; le drapeau de changement de mot de passe est transmis
    tokens = session.login("agent@anam.bf", "MdpInitial123")
    assert tokens["must_change_password"] is True


def test_admin_role_changes_and_self_protection(client, make_user, session):
    admin = make_user(Role.administrateur, email="admin@anam.bf")
    other = make_user(email="a@anam.bf")
    h = session.headers("admin@anam.bf")

    r = client.patch(f"/admin/users/{other.id}/role", headers=h, json={"role": "responsable_communal"})
    assert r.status_code == 200 and r.json()["role"] == "responsable_communal"
    assert client.patch(f"/admin/users/{admin.id}/role", headers=h, json={"role": "grand_public"}).status_code == 400
    assert client.post(f"/admin/users/{admin.id}/disable", headers=h).status_code == 400
    assert client.patch("/admin/users/inexistant/role", headers=h, json={"role": "agent_anam"}).status_code == 404


def test_disable_user_revokes_sessions(client, make_user, session):
    make_user(Role.administrateur, email="admin@anam.bf")
    victim = make_user(email="a@anam.bf")
    tokens = client.post("/auth/login", json={"identifier": "a@anam.bf", "password": PASSWORD}).json()["tokens"]
    h = session.headers("admin@anam.bf")

    assert client.post(f"/admin/users/{victim.id}/disable", headers=h).json()["status"] == "disabled"
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/auth/login", json={"identifier": "a@anam.bf", "password": PASSWORD}).status_code == 403


def test_reset_two_factor(client, make_user, session):
    make_user(Role.administrateur, email="admin@anam.bf")
    agent = make_user(Role.agent_anam, email="agent@anam.bf")
    session.login("agent@anam.bf")  # configure la 2FA
    assert client.post("/auth/login", json={"identifier": "agent@anam.bf", "password": PASSWORD}).json()["requires_2fa"]

    h = session.headers("admin@anam.bf")
    assert client.post(f"/admin/users/{agent.id}/reset-2fa", headers=h).status_code == 200
    assert client.post("/auth/login", json={"identifier": "agent@anam.bf", "password": PASSWORD}).json()["requires_2fa_setup"]


def test_user_list_filters_and_commune_stats(client, make_user, session):
    make_user(Role.administrateur, email="admin@anam.bf")
    make_user(email="k1@anam.bf", commune="Kaya")
    make_user(email="k2@anam.bf", commune="Kaya")
    make_user(email="z1@anam.bf", commune="Ziniaré")
    make_user(email="n1@anam.bf")
    h = session.headers("admin@anam.bf")

    assert client.get("/admin/users?commune=Kaya", headers=h).json()["total"] == 2
    assert client.get("/admin/users?role=administrateur", headers=h).json()["total"] == 1
    assert client.get("/admin/users?q=z1", headers=h).json()["items"][0]["email"] == "z1@anam.bf"
    assert client.get("/admin/users?limit=2", headers=h).json()["total"] == 5

    stats = {s["commune"]: s["users"] for s in client.get("/admin/stats/communes", headers=h).json()}
    assert stats["Kaya"] == 2 and stats["Ziniaré"] == 1 and stats["Non renseignée"] == 2  # admin + n1
