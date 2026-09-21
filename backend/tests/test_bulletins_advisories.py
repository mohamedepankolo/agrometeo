from datetime import datetime

from app import notifications
from app.models import Role
from conftest import SAMPLES

PDF = (SAMPLES / "Bulletin_today.pdf").read_bytes()


def _import(client, staff, content=PDF, name="bulletin.pdf"):
    return client.post("/bulletins", headers=staff(), files={"file": (name, content, "application/pdf")})


# ------------------------------------------------------------ bulletins
def test_bulletin_import_uses_real_pdf_parsing(client, staff):
    r = _import(client, staff)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["status"] == "draft"
    assert b["date_text"] == "17 Septembre 2026 à 12 h" and b["issued_at"] == "2026-09-17T12:00:00"
    assert b["title"] == "Bulletin agrométéorologique - 17 Septembre 2026 à 12 h"
    assert b["parsed"]["observed"] and b["parsed"]["forecast"] and isinstance(b["parsed"]["advice"], list)
    assert b["pdf_url"].endswith("/bulletin.pdf")

    full = client.get(f"/bulletins/{b['id']}", headers=staff()).json()
    assert full["media"]["status"] == "ready" and set(full["media"]["files"]) == {"fr", "en", "mos"}
    assert full["texts"]["fr"] == "Texte français lu."


def test_bulletin_publish_broadcast_and_visibility(client, staff, make_user):
    make_user(email="a@x.bf", channels=("email", "push"))
    bid = _import(client, staff).json()["id"]

    assert client.get("/bulletins").json()["total"] == 0
    assert client.get(f"/bulletins/{bid}").status_code == 404
    assert client.get("/bulletins/latest").status_code == 404

    r = client.post(f"/bulletins/{bid}/publish", headers=staff())
    assert r.status_code == 200 and r.json()["status"] == "published"
    assert client.get("/bulletins/latest").json()["id"] == bid
    assert client.get(client.get(f"/bulletins/{bid}").json()["media"]["files"]["mos"]["audio"]).content == b"AUDIO-mos"
    assert client.get(f"/bulletins/{bid}").json()["pdf_url"]

    emails = [m for m in notifications.OUTBOX if m["channel"] == "email"]
    assert len(emails) == 1 and "17 Septembre 2026" in emails[0]["title"] and "Texte français lu." in emails[0]["message"]
    assert not [m for m in notifications.OUTBOX if m["channel"] == "sms"]  # pas de SMS pour les bulletins

    assert client.post(f"/bulletins/{bid}/publish", headers=staff()).status_code == 409
    assert client.post(f"/bulletins/{bid}/unpublish", headers=staff()).json()["status"] == "archived"
    assert client.get(f"/bulletins/{bid}").status_code == 404
    assert client.delete(f"/bulletins/{bid}", headers=staff()).status_code == 204


def test_bulletin_latest_is_the_most_recent_by_issue_date(client, staff):
    old = _import(client, staff).json()["id"]
    new = _import(client, staff).json()["id"]
    from app import db as dbmod
    from app.models_content import Bulletin

    s = dbmod.new_session()
    s.get(Bulletin, old).issued_at = datetime(2026, 9, 1)
    s.get(Bulletin, new).issued_at = datetime(2026, 9, 20)
    s.commit()
    s.close()
    for bid in (old, new):
        client.post(f"/bulletins/{bid}/publish", headers=staff(), params={"broadcast": False})
    assert client.get("/bulletins/latest").json()["id"] == new
    assert [b["id"] for b in client.get("/bulletins").json()["items"]] == [new, old]


def test_bulletin_rejects_bad_files(client, staff):
    assert _import(client, staff, b"ceci n'est pas un pdf").status_code == 415
    assert _import(client, staff, b"%PDF-1.4 contenu invalide").status_code == 422
    assert client.get("/bulletins", headers=staff(), params={"status": "draft"}).json()["total"] == 0  # rien de laissé en base
    assert client.post("/bulletins", files={"file": ("b.pdf", PDF, "application/pdf")}).status_code == 401
    assert client.post("/bulletins", headers=staff(Role.observateur), files={"file": ("b.pdf", PDF, "application/pdf")}).status_code == 403


def test_bulletin_regenerate_media_and_share_kit(client, staff):
    bid = _import(client, staff).json()["id"]
    assert client.post(f"/bulletins/{bid}/media", headers=staff()).status_code == 202
    kit = client.get(f"/bulletins/{bid}/share-kit", headers=staff()).json()
    assert kit["text"]["fr"].startswith("🌦️ *Bulletin agrométéorologique - 17 Septembre 2026 à 12 h*")
    assert "🎬 Vidéo : /media/bulletins/" in kit["text"]["mos"]


# ------------------------------------------------------------ avis
def test_advisory_lifecycle_and_translation(client, staff, make_user):
    make_user(email="a@x.bf", channels=("email",))
    body = {"kind": "planification", "title_fr": "Début probable de la saison", "body_fr": "Les premières pluies sont attendues mi-mai."}
    r = client.post("/advisories", headers=staff(), json=body)
    assert r.status_code == 201
    aid = r.json()["id"]
    assert client.get(f"/advisories/{aid}").status_code == 404 and client.get("/advisories").json()["total"] == 0

    t = client.post(f"/advisories/{aid}/translate", headers=staff(), json={"langs": ["en", "mos"]}).json()
    assert t["title_en"] == "[en] Début probable de la saison" and t["body_mos"].startswith("[mos] ")
    kept = client.patch(f"/advisories/{aid}", headers=staff(), json={"body_en": "Rain expected mid-May."}).json()
    again = client.post(f"/advisories/{aid}/translate", headers=staff(), json={"langs": ["en"]}).json()
    assert again["body_en"] == kept["body_en"]  # n'écrase pas une traduction saisie

    pub = client.post(f"/advisories/{aid}/publish", headers=staff())
    assert pub.status_code == 200 and notifications.OUTBOX == []  # avis : pas de diffusion automatique par défaut
    assert client.get("/advisories", params={"kind": "planification"}).json()["total"] == 1
    assert client.get("/advisories", params={"kind": "conseil"}).json()["total"] == 0
    assert client.post(f"/advisories/{aid}/broadcast", headers=staff()).status_code == 202
    assert [m["channel"] for m in notifications.OUTBOX] == ["email"]

    assert client.post(f"/advisories/{aid}/withdraw", headers=staff()).json()["status"] == "cancelled"
    assert client.get(f"/advisories/{aid}").status_code == 404


def test_advisory_validation_and_permissions(client, staff):
    assert client.post("/advisories", headers=staff(), json={"kind": "autre", "title_fr": "Titre", "body_fr": "Texte"}).status_code == 422
    assert client.post("/advisories", json={"kind": "conseil", "title_fr": "Titre", "body_fr": "Texte"}).status_code == 401
    aid = client.post("/advisories", headers=staff(), json={"kind": "conseil", "title_fr": "Titre", "body_fr": "Texte"}).json()["id"]
    assert client.post(f"/advisories/{aid}/publish", headers=staff(Role.observateur)).status_code == 403


# ------------------------------------------------------------ référentiels
def test_prevention_messages_crud_and_translation(client, staff):
    types = {t["code"]: t["id"] for t in client.get("/alert-types").json()}
    r = client.post("/prevention-messages", headers=staff(), json={"alert_type_id": types["chaleur"], "text_fr": "Restez au frais."})
    assert r.status_code == 201
    mid = r.json()["id"]
    assert len(client.get("/prevention-messages", params={"alert_type_code": "chaleur"}).json()) == 3
    assert client.post(f"/prevention-messages/{mid}/translate", headers=staff(), json={"langs": ["mos"]}).json()["text_mos"] == "[mos] Restez au frais."
    assert client.patch(f"/prevention-messages/{mid}", headers=staff(), json={"active": False}).json()["active"] is False
    assert len(client.get("/prevention-messages", params={"alert_type_code": "chaleur"}).json()) == 2
    assert client.delete(f"/prevention-messages/{mid}", headers=staff()).status_code == 204
    assert client.post("/prevention-messages", headers=staff(), json={"alert_type_id": "x", "text_fr": "abc"}).status_code == 404


def test_alert_types_management(client, staff):
    body = {"code": "grele", "label_fr": "Grêle", "label_en": "Hail"}
    assert client.post("/alert-types", headers=staff(), json=body).status_code == 201
    assert client.post("/alert-types", headers=staff(), json=body).status_code == 409
    assert client.post("/alert-types", headers=staff(), json={**body, "code": "Grêle!"}).status_code == 422
    tid = next(t["id"] for t in client.get("/alert-types").json() if t["code"] == "grele")
    client.patch(f"/alert-types/{tid}", headers=staff(), json={"label_mos": "Kɩlgr"})
    client.patch(f"/alert-types/{tid}", headers=staff(), json={"active": False})
    assert "grele" not in {t["code"] for t in client.get("/alert-types").json()}
    assert "grele" in {t["code"] for t in client.get("/alert-types", params={"include_inactive": True}).json()}
    # un type désactivé ne peut plus servir à créer une alerte
    r = client.post("/alerts", headers=staff(), json={"alert_type_id": tid, "level": "jaune", "raw_text": "Texte d'alerte suffisant."})
    assert r.status_code == 422


def test_zone_management(client, staff):
    admin, agent = staff(Role.administrateur), staff(Role.agent_anam)
    square = {"type": "Polygon", "coordinates": [[[-1.1, 13.0], [-1.0, 13.0], [-1.0, 13.1], [-1.1, 13.0]]]}
    r = client.post("/zones", headers=admin, json={"name": "Centre-Nord", "kind": "region", "commune_names": ["Kaya"], "geometry": square})
    assert r.status_code == 201
    zid = r.json()["id"]
    assert client.post("/zones", headers=agent, json={"name": "Autre"}).status_code == 403
    assert client.post("/zones", headers=admin, json={"name": "Centre-Nord"}).status_code == 409
    assert client.post("/zones", headers=admin, json={"name": "Mauvaise", "geometry": {"type": "Point", "coordinates": [0, 0]}}).status_code == 422
    assert client.post("/zones", headers=admin, json={"name": "Hors", "latitude": 120}).status_code == 422
    assert client.patch(f"/zones/{zid}", headers=admin, json={"latitude": 13.09, "longitude": -1.08}).json()["latitude"] == 13.09
    assert client.get(f"/zones/{zid}").json()["geometry"]["type"] == "Polygon"
    assert "geometry" not in client.get("/zones").json()[0]  # la liste reste légère
    assert len(client.get("/zones", params={"pilot_only": True}).json()) == 5


# ------------------------------------------------------------ paramètres
def test_settings_validation(client, staff):
    admin = staff(Role.administrateur)
    assert client.get("/backoffice/settings", headers=staff(Role.agent_anam)).status_code == 403

    def put(values):
        return client.put("/backoffice/settings", headers=admin, json={"values": values})

    assert put({"inconnu": 1}).status_code == 422
    assert put({"diffusion.channels": {"alert": ["fax"], "bulletin": [], "advisory": []}}).status_code == 422
    assert put({"diffusion.channels": {"alert": ["sms"]}}).status_code == 422
    assert put({"diffusion.whatsapp_recipients": ["0022670"]}).status_code == 422
    assert put({"platform.default_language": "de"}).status_code == 422
    assert put({"alert.default_validity_hours": 0}).status_code == 422
    assert put({"sms.max_length": True}).status_code == 422
    ok = put({"alert.default_validity_hours": 12, "platform.name": "ANAM Test"})
    assert ok.status_code == 200 and ok.json()["alert.default_validity_hours"] == 12
    assert client.get("/config").json()["platform_name"] == "ANAM Test"
