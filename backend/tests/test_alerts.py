from sqlalchemy import select

from app import notifications
from app.models import Language, Role
from app.models_content import DeviceToken, Zone
from conftest import SAMPLES

ALERT_TEXT = (SAMPLES / "alerte1.txt").read_text(encoding="utf-8")


def _ids(client, db):
    zones = {z["name"]: z["id"] for z in client.get("/zones").json()}
    types = {t["code"]: t["id"] for t in client.get("/alert-types").json()}
    return zones, types


def _new_alert(client, staff, zone_names=("Kaya",), level="orange", type_code="orages", **extra):
    zones, types = _ids(client, None)
    body = {"alert_type_id": types[type_code], "level": level, "raw_text": ALERT_TEXT,
            "zone_ids": [zones[n] for n in zone_names], **extra}
    r = client.post("/alerts", headers=staff(), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _with_image(client, staff, alert_id):
    img = (SAMPLES / "alerte1.jpg").read_bytes()
    return client.put(f"/alerts/{alert_id}/image", headers=staff(), files={"file": ("a.jpg", img, "image/jpeg")})


def _subscriber(make_user, db, email, commune, *, phone=None, channels=("push", "email"), token=None):
    u = make_user(email=email, phone=phone, commune=commune, channels=channels)
    if token:
        db.add(DeviceToken(user_id=u.id, token=token))
        db.commit()
    return u


# ------------------------------------------------------------ référentiels
def test_seeded_reference_data(client):
    zones = client.get("/zones").json()
    assert {z["name"] for z in zones if z["is_pilot"]} == {"Kaya", "Ziniaré", "Zitenga", "Absouya", "Korsimoro"}
    assert len(client.get("/alert-types").json()) == 7
    assert len(client.get("/prevention-messages", params={"alert_type_code": "orages"}).json()) == 2
    cfg = client.get("/config").json()
    assert [lvl["code"] for lvl in cfg["alert_levels"]] == ["vert", "jaune", "orange", "rouge"]
    assert cfg["communes"] == ["Kaya", "Ziniaré", "Zitenga", "Absouya", "Korsimoro"]


# ------------------------------------------------------------ cycle de vie complet
def test_alert_full_lifecycle(client, staff, make_user, db):
    _subscriber(make_user, db, "kaya@x.bf", "Kaya", phone="+22670000001", channels=("push", "sms", "email"), token="fcm-token-kaya-1")
    _subscriber(make_user, db, "zini@x.bf", "Ziniaré", phone="+22670000002", channels=("push", "sms", "email"), token="fcm-token-zini-1")

    alert = _new_alert(client, staff)
    aid = alert["id"]
    assert alert["status"] == "draft" and alert["media"]["status"] == "none"
    assert alert["parsed"]["situation"].startswith("Des formations pluvio-orageuses")
    assert alert["title"] == "Alerte orange - Orages"

    # invisible du public tant que ce n'est pas publié
    assert client.get(f"/alerts/{aid}").status_code == 404
    assert client.get("/alerts").json()["total"] == 0
    assert client.get("/alerts", params={"status": "draft"}).status_code == 403

    # génération impossible sans image, puis réussie
    assert client.post(f"/alerts/{aid}/media", headers=staff()).status_code == 409
    assert _with_image(client, staff, aid).status_code == 200
    r = client.post(f"/alerts/{aid}/media", headers=staff())
    assert r.status_code == 202
    ready = client.get(f"/alerts/{aid}", headers=staff()).json()
    assert ready["media"]["status"] == "ready"
    assert set(ready["media"]["files"]) == {"fr", "en", "mos"}
    assert ready["texts"]["mos"] == "Texte moore lu."

    # média de brouillon : refusé au public, accepté pour le personnel (en-tête ou ?token=)
    video = ready["media"]["files"]["fr"]["video"]
    assert client.get(video).status_code == 404
    assert client.get(video, headers=staff()).content == b"VIDEO-fr"
    token = staff()["Authorization"].split()[1]
    assert client.get(video, params={"token": token}).status_code == 200

    # publication + diffusion automatique
    r = client.post(f"/alerts/{aid}/publish", headers=staff())
    assert r.status_code == 200 and r.json()["status"] == "published" and r.json()["valid_until"]
    sent = [(m["channel"], m["to"]) for m in notifications.OUTBOX]
    assert ("sms", "+22670000001") in sent and ("email", "kaya@x.bf") in sent and ("push", "fcm-token-kaya-1") in sent
    assert not any("zini" in m["to"] or m["to"] == "+22670000002" for m in notifications.OUTBOX)  # autre commune
    sms = next(m for m in notifications.OUTBOX if m["channel"] == "sms")
    assert sms["message"].startswith("ANAM ALERTE ORANGE") and len(sms["message"]) <= 320

    # le public voit l'alerte, ses médias, le message de prévention
    pub = client.get(f"/alerts/{aid}").json()
    assert pub["is_active"] and pub["raw_text"] is None and len(pub["prevention"]) == 2
    assert pub["source"].startswith("Source : ANAM")
    assert client.get(video).content == b"VIDEO-fr"
    assert client.get(pub["image_url"]).status_code == 200
    assert client.get("/alerts", params={"active_only": True}).json()["total"] == 1

    # suivi de la diffusion
    b = client.get("/backoffice/broadcasts", headers=staff()).json()["items"][0]
    detail = client.get(f"/backoffice/broadcasts/{b['id']}", headers=staff()).json()
    assert b["status"] == "done" and b["trigger"] == "auto" and b["target_count"] == 3
    assert detail["by_channel"] == {"sms": {"simulated": 1}, "email": {"simulated": 1}, "push": {"simulated": 1}}

    # carte : Kaya passe à l'orange, les autres restent vertes
    levels = {z["zone"]["name"]: z["level"] for z in client.get("/map/alerts").json()["zones"]}
    assert levels["Kaya"] == "orange" and levels["Ziniaré"] == "vert"

    # annulation : la carte revient au vert et l'alerte disparaît du public
    assert client.post(f"/alerts/{aid}/cancel", headers=staff()).json()["status"] == "cancelled"
    assert {z["zone"]["name"]: z["level"] for z in client.get("/map/alerts").json()["zones"]}["Kaya"] == "vert"
    assert client.get(f"/alerts/{aid}").status_code == 404
    assert client.get(video).status_code == 404


def test_map_takes_highest_level_and_national_alerts(client, staff):
    a1 = _new_alert(client, staff, ("Kaya",), level="jaune")
    a2 = _new_alert(client, staff, ("Kaya", "Ziniaré"), level="rouge")
    national = _new_alert(client, staff, (), level="jaune", type_code="chaleur")
    for a in (a1, a2, national):
        assert client.post(f"/alerts/{a['id']}/publish", headers=staff(), params={"broadcast": False}).status_code == 200
    m = client.get("/map/alerts").json()
    levels = {z["zone"]["name"]: z["level"] for z in m["zones"]}
    assert levels["Kaya"] == "rouge" and levels["Ziniaré"] == "rouge" and levels["Zitenga"] == "vert"
    assert len(next(z for z in m["zones"] if z["zone"]["name"] == "Kaya")["alerts"]) == 2
    assert [n["type_code"] for n in m["national_alerts"]] == ["chaleur"]


def test_expired_alert_leaves_the_map(client, staff, db):
    a = _new_alert(client, staff, ("Kaya",), level="rouge", valid_until="2000-01-01T00:00:00")
    client.post(f"/alerts/{a['id']}/publish", headers=staff(), params={"broadcast": False})
    assert client.get(f"/alerts/{a['id']}").json()["is_active"] is False
    assert {z["zone"]["name"]: z["level"] for z in client.get("/map/alerts").json()["zones"]}["Kaya"] == "vert"
    assert client.get("/alerts", params={"active_only": True}).json()["total"] == 0


# ------------------------------------------------------------ règles et permissions
def test_permissions_on_alert_management(client, staff, make_user, session):
    zones, types = _ids(client, None)
    body = {"alert_type_id": types["orages"], "level": "jaune", "raw_text": ALERT_TEXT}
    assert client.post("/alerts", json=body).status_code == 401
    make_user(email="citoyen@x.bf")
    assert client.post("/alerts", json=body, headers=session.headers("citoyen@x.bf")).status_code == 403

    # l'observateur peut consulter mais pas créer ; l'agent crée et publie ; l'admin aussi
    assert client.post("/alerts", json=body, headers=staff(Role.observateur)).status_code == 403
    aid = client.post("/alerts", json=body, headers=staff(Role.agent_anam)).json()["id"]
    assert client.post(f"/alerts/{aid}/publish", headers=staff(Role.responsable_communal)).status_code == 403
    assert client.post(f"/alerts/{aid}/publish", headers=staff(Role.administrateur), params={"broadcast": False}).status_code == 200


def test_editing_rules(client, staff):
    a = _new_alert(client, staff)
    ok = client.patch(f"/alerts/{a['id']}", headers=staff(), json={"level": "rouge", "raw_text": ALERT_TEXT + " Nouveau."})
    assert ok.status_code == 200 and ok.json()["level"] == "rouge"
    client.post(f"/alerts/{a['id']}/publish", headers=staff(), params={"broadcast": False})
    # publiée : le texte et les zones sont figés, mais le niveau et la validité restent ajustables
    assert client.patch(f"/alerts/{a['id']}", headers=staff(), json={"raw_text": "x" * 20}).status_code == 409
    assert client.patch(f"/alerts/{a['id']}", headers=staff(), json={"level": "jaune"}).status_code == 200
    assert client.delete(f"/alerts/{a['id']}", headers=staff()).status_code == 409
    client.post(f"/alerts/{a['id']}/cancel", headers=staff())
    assert client.patch(f"/alerts/{a['id']}", headers=staff(), json={"level": "rouge"}).status_code == 409
    assert client.delete(f"/alerts/{a['id']}", headers=staff()).status_code == 204


def test_alert_validation_and_uploads(client, staff):
    zones, types = _ids(client, None)
    base = {"alert_type_id": types["orages"], "level": "jaune", "raw_text": ALERT_TEXT}
    assert client.post("/alerts", headers=staff(), json={**base, "level": "violet"}).status_code == 422
    assert client.post("/alerts", headers=staff(), json={**base, "alert_type_id": "inconnu"}).status_code == 404
    assert client.post("/alerts", headers=staff(), json={**base, "zone_ids": ["inconnue"]}).status_code == 422
    a = _new_alert(client, staff)
    bad = client.put(f"/alerts/{a['id']}/image", headers=staff(), files={"file": ("a.jpg", b"pas une image", "image/jpeg")})
    assert bad.status_code == 415
    assert client.put(f"/alerts/{a['id']}/image", headers=staff(),
                      files={"file": ("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png")}).status_code == 200


def test_media_endpoint_blocks_path_tricks(client):
    for path in ("alerts/x/../../../etc/passwd", "secrets/a/b", "alerts/inconnu/media/x.mp3", "alerts"):
        assert client.get(f"/media/{path}").status_code == 404


def test_failed_generation_is_reported(client, staff, monkeypatch):
    from app import module1_bridge

    def boom(*_):
        raise RuntimeError("service CITADEL indisponible")

    monkeypatch.setattr(module1_bridge, "generate_alert_media", boom)
    a = _new_alert(client, staff)
    _with_image(client, staff, a["id"])
    client.post(f"/alerts/{a['id']}/media", headers=staff())
    media = client.get(f"/alerts/{a['id']}", headers=staff()).json()["media"]
    assert media["status"] == "failed" and "CITADEL" in media["error"]
    # on peut publier une alerte sans média (diffusion texte) et relancer plus tard
    assert client.post(f"/alerts/{a['id']}/publish", headers=staff(), params={"broadcast": False}).status_code == 200


# ------------------------------------------------------------ diffusion
def test_channels_and_targeting(client, staff, make_user, db):
    _subscriber(make_user, db, "a@x.bf", "Kaya", channels=("email",), token="fcm-token-a-0001")  # n'a choisi que l'e-mail
    _subscriber(make_user, db, "b@x.bf", "Kaya", phone="+22670000003", channels=("sms",))
    _subscriber(make_user, db, "c@x.bf", None, channels=("email",))  # sans commune : exclu d'une alerte ciblée
    a = _new_alert(client, staff, ("Kaya",))
    client.post(f"/alerts/{a['id']}/publish", headers=staff())
    sent = {(m["channel"], m["to"]) for m in notifications.OUTBOX}
    assert sent == {("email", "a@x.bf"), ("sms", "+22670000003")}


def test_alert_without_zone_reaches_everyone_and_language_is_respected(client, staff, make_user, db):
    _subscriber(make_user, db, "fr@x.bf", "Kaya", channels=("email",))
    en = make_user(email="en@x.bf", channels=("email",), language=Language.en)
    a = _new_alert(client, staff, ())
    _with_image(client, staff, a["id"])
    client.post(f"/alerts/{a['id']}/media", headers=staff())
    client.post(f"/alerts/{a['id']}/publish", headers=staff())
    by_to = {m["to"]: m["message"] for m in notifications.OUTBOX if m["channel"] == "email"}
    assert "Texte français lu." in by_to["fr@x.bf"] and "English text read." in by_to[en.email]
    assert "/media/alerts/" in by_to["fr@x.bf"] and "ANAM" in by_to["fr@x.bf"]


def test_sms_can_be_disabled_in_settings(client, staff, make_user, db):
    _subscriber(make_user, db, "b@x.bf", "Kaya", phone="+22670000003", channels=("sms", "email"))
    settings = client.get("/backoffice/settings", headers=staff(Role.administrateur)).json()
    channels = {**settings["diffusion.channels"], "alert": ["email"]}
    assert client.put("/backoffice/settings", headers=staff(Role.administrateur), json={"values": {"diffusion.channels": channels}}).status_code == 200
    a = _new_alert(client, staff, ("Kaya",))
    client.post(f"/alerts/{a['id']}/publish", headers=staff())
    assert {m["channel"] for m in notifications.OUTBOX} == {"email"}


def test_failed_and_invalid_deliveries_are_traced(client, staff, make_user, db, monkeypatch):
    _subscriber(make_user, db, "a@x.bf", "Kaya", channels=("email", "push"), token="fcm-token-dead-1")

    class Failing:
        simulated = False

        def send(self, to, message, title=None, data=None):
            raise notifications.InvalidRecipient(to) if to.startswith("fcm") else RuntimeError("SMTP en panne")

    monkeypatch.setitem(notifications._CACHE, "email:console", Failing())
    monkeypatch.setitem(notifications._CACHE, "push:console", Failing())
    a = _new_alert(client, staff, ("Kaya",))
    client.post(f"/alerts/{a['id']}/publish", headers=staff())
    b = client.get("/backoffice/broadcasts", headers=staff()).json()["items"][0]
    assert b["status"] == "done" and b["failed_count"] == 2 and b["sent_count"] == 0
    errors = [d["error"] for d in client.get(f"/backoffice/broadcasts/{b['id']}", headers=staff()).json()["deliveries"]]
    assert any("SMTP en panne" in e for e in errors) and any("jeton supprimé" in e for e in errors)
    assert db.scalars(select(DeviceToken)).all() == []  # le jeton mort est nettoyé


def test_manual_rebroadcast_and_share_kit(client, staff, make_user, db):
    _subscriber(make_user, db, "a@x.bf", "Kaya", channels=("email",))
    a = _new_alert(client, staff, ("Kaya",))
    assert client.post(f"/alerts/{a['id']}/broadcast", headers=staff()).status_code == 409  # pas encore publiée
    client.post(f"/alerts/{a['id']}/publish", headers=staff(), params={"broadcast": False})
    assert notifications.OUTBOX == []
    r = client.post(f"/alerts/{a['id']}/broadcast", headers=staff())
    assert r.status_code == 202 and len(notifications.OUTBOX) == 1

    kit = client.get(f"/alerts/{a['id']}/share-kit", headers=staff()).json()
    fr = kit["text"]["fr"]
    assert "*ALERTE MÉTÉO - NIVEAU ORANGE*" in fr and "📍 *Zones concernées :* Kaya" in fr
    assert "⛈️ *Situation actuelle*" in fr and "• Évitez de vous abriter sous les arbres" in fr
    assert fr.rstrip().endswith("_Source : ANAM - Agence Nationale de la Météorologie du Burkina Faso_")
    assert set(kit["text"]) == {"fr", "en", "mos"}
    assert client.get(f"/alerts/{a['id']}/share-kit").status_code == 401


def test_whatsapp_recipients_from_settings(client, staff, monkeypatch):
    admin = staff(Role.administrateur)
    r = client.put("/backoffice/settings", headers=admin, json={"values": {"diffusion.whatsapp_recipients": ["+22670000009"]}})
    assert r.status_code == 200
    a = _new_alert(client, staff, ("Kaya",))
    client.post(f"/alerts/{a['id']}/publish", headers=staff())
    wa = [m for m in notifications.OUTBOX if m["channel"] == "whatsapp"]
    assert [m["to"] for m in wa] == ["+22670000009"] and "*ALERTE MÉTÉO" in wa[0]["message"]


def test_zone_deletion_cascades(client, staff, db):
    a = _new_alert(client, staff, ("Kaya",))
    zone = db.scalar(select(Zone).where(Zone.name == "Kaya"))
    assert client.delete(f"/zones/{zone.id}", headers=staff(Role.agent_anam)).status_code == 403
    assert client.delete(f"/zones/{zone.id}", headers=staff(Role.administrateur)).status_code == 204
    assert client.get(f"/alerts/{a['id']}", headers=staff()).json()["zones"] == []
