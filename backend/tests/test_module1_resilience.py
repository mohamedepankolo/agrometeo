"""Robustesse de la chaîne de traduction anglaise (service gratuit à quota) et livraison partielle."""

import json

import pytest

from app import module1_bridge
from conftest import SAMPLES, _fake_media

ALERT_TEXT = (SAMPLES / "alerte1.txt").read_text(encoding="utf-8")


class FakeMyMemory:
    calls: list[str] = []
    quota_left = 10**6

    def __init__(self, source, target, email=None, **kw):
        type(self).email = email

    def translate(self, text):
        if len(type(self).calls) >= type(self).quota_left:
            return "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY."
        type(self).calls.append(text)
        return f"EN<{text}>"


@pytest.fixture
def french_tts(tmp_path, monkeypatch):
    module1_bridge._load()
    import deep_translator
    import french_tts as ft

    FakeMyMemory.calls, FakeMyMemory.quota_left = [], 10**6
    monkeypatch.setenv("TRANSLATION_BACKEND", "mymemory")  # ces tests visent MyMemory, pas le modèle local
    monkeypatch.setattr(deep_translator, "MyMemoryTranslator", FakeMyMemory)
    monkeypatch.setattr(ft, "_CACHE_PATH", tmp_path / ".cache" / "translations_en.json")
    return ft


def test_translations_are_cached_and_never_repeated(french_tts):
    text = "Il pleut sur Kaya. Le vent souffle fort demain."
    first = french_tts.translate_long_fr_to_english(text)
    n_calls = len(FakeMyMemory.calls)
    assert n_calls == 2 and first == "EN<Il pleut sur Kaya.> EN<Le vent souffle fort demain.>"
    assert french_tts.translate_long_fr_to_english(text) == first
    assert len(FakeMyMemory.calls) == n_calls  # deuxième passage : zéro appel, donc zéro quota consommé
    assert "Il pleut sur Kaya." in json.loads(french_tts._CACHE_PATH.read_text(encoding="utf-8"))


def test_quota_message_is_refused_and_never_cached(french_tts):
    FakeMyMemory.quota_left = 1
    with pytest.raises(RuntimeError, match="quota"):
        french_tts.translate_long_fr_to_english("Première phrase. Deuxième phrase.")
    cache = json.loads(french_tts._CACHE_PATH.read_text(encoding="utf-8"))
    assert list(cache) == ["Première phrase."]  # le progrès est conservé, l'avertissement de quota jamais
    assert not any("WARNING" in v for v in cache.values())


def test_mymemory_email_is_used_when_configured(french_tts, monkeypatch):
    monkeypatch.setenv("MYMEMORY_EMAIL", "moi@exemple.org")
    french_tts.translate_long_fr_to_english("Une phrase.")
    assert FakeMyMemory.email == "moi@exemple.org"
    monkeypatch.delenv("MYMEMORY_EMAIL")
    french_tts.translate_long_fr_to_english("Une autre phrase.")
    assert FakeMyMemory.email is None


def test_bridge_normalizes_a_result_without_english(tmp_path):
    fake = _fake_media(tmp_path, "alerte")
    raw = {"skipped": {"en": "TooManyRequests: quota"}}
    for lang in ("fr", "mos"):
        raw[f"text_{lang}"] = fake["texts"][lang]
        raw[f"audio_{lang}"], raw[f"video_{lang}"] = fake["files"][lang]["audio"], fake["files"][lang]["video"]
    out = module1_bridge._collect(raw)
    assert set(out["files"]) == set(out["texts"]) == {"fr", "mos"} and out["skipped"] == {"en": "TooManyRequests: quota"}


def test_alert_is_delivered_without_english_when_translation_quota_is_exhausted(client, staff, monkeypatch):
    def without_english(image, text, out_dir):
        fake = _fake_media(out_dir, "alerte")
        return {"texts": {k: v for k, v in fake["texts"].items() if k != "en"},
                "files": {k: v for k, v in fake["files"].items() if k != "en"},
                "skipped": {"en": "TooManyRequests: quota MyMemory"}}

    monkeypatch.setattr(module1_bridge, "generate_alert_media", without_english)
    zones = {z["name"]: z["id"] for z in client.get("/zones").json()}
    types = {t["code"]: t["id"] for t in client.get("/alert-types").json()}
    a = client.post("/alerts", headers=staff(), json={"alert_type_id": types["orages"], "level": "jaune",
                                                      "raw_text": ALERT_TEXT, "zone_ids": [zones["Kaya"]]}).json()
    img = (SAMPLES / "alerte1.jpg").read_bytes()
    client.put(f"/alerts/{a['id']}/image", headers=staff(), files={"file": ("a.jpg", img, "image/jpeg")})
    client.post(f"/alerts/{a['id']}/media", headers=staff())

    media = client.get(f"/alerts/{a['id']}", headers=staff()).json()["media"]
    assert media["status"] == "ready" and set(media["files"]) == {"fr", "mos"}
    assert "en" in media["error"] and "quota" in media["error"]
    # le contenu reste publiable, diffusable et partageable sans l'anglais
    assert client.post(f"/alerts/{a['id']}/publish", headers=staff()).status_code == 200
    kit = client.get(f"/alerts/{a['id']}/share-kit", headers=staff()).json()
    assert set(kit["text"]) == {"fr", "en", "mos"} and "🎬" not in kit["text"]["en"]


# ------------------------------------------------------------ modèle local (hors ligne)
def test_local_model_is_preferred_and_mymemory_is_not_called(french_tts, monkeypatch):
    monkeypatch.setenv("TRANSLATION_BACKEND", "auto")
    monkeypatch.setattr(french_tts, "_local_model", lambda: object())
    monkeypatch.setattr(french_tts, "_translate_local", lambda chunks: [f"LOCAL<{c}>" for c in chunks])
    assert french_tts.translate_long_fr_to_english("Il pleut. Il vente.") == "LOCAL<Il pleut.> LOCAL<Il vente.>"
    assert FakeMyMemory.calls == []
    # le résultat local est mis en cache comme les autres
    assert french_tts.translate_long_fr_to_english("Il pleut. Il vente.") == "LOCAL<Il pleut.> LOCAL<Il vente.>"


def test_falls_back_to_mymemory_when_local_model_is_absent_or_crashes(french_tts, monkeypatch):
    monkeypatch.setenv("TRANSLATION_BACKEND", "auto")
    monkeypatch.setattr(french_tts, "_local_model", lambda: None)
    assert french_tts.translate_long_fr_to_english("Première.") == "EN<Première.>"

    def crash(chunks):
        raise MemoryError("plus de mémoire")

    monkeypatch.setattr(french_tts, "_local_model", lambda: object())
    monkeypatch.setattr(french_tts, "_translate_local", crash)
    assert french_tts.translate_long_fr_to_english("Seconde.") == "EN<Seconde.>"


def test_local_only_mode_refuses_to_fall_back(french_tts, monkeypatch):
    monkeypatch.setenv("TRANSLATION_BACKEND", "local")
    monkeypatch.setattr(french_tts, "_local_model", lambda: None)
    with pytest.raises(RuntimeError, match="local"):
        french_tts.translate_long_fr_to_english("Rien.")
    assert FakeMyMemory.calls == []


@pytest.mark.slow
def test_real_local_model_translates_a_bulletin_sentence(french_tts, monkeypatch):
    """Utilise le vrai modèle (téléchargé une fois) ; ignoré s'il n'est pas installé."""
    monkeypatch.setenv("TRANSLATION_BACKEND", "local")
    if french_tts._local_model() is None:
        pytest.skip("modèle local non installé")
    en = french_tts.translate_long_fr_to_english("Évitez de traverser les zones inondées ou les cours d'eau en crue.")
    assert "flood" in en.lower() and "avoid" in en.lower()
    assert FakeMyMemory.calls == []
