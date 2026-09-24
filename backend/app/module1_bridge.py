"""Pont vers la chaîne audio/vidéo du Module 1 (dossier `module1/`).

Le Module 1 est un ensemble de scripts « à plat » (imports du type `from moore_client import ...`) :
on ajoute son dossier au chemin d'import au premier usage, après avoir exporté vers l'environnement
les identifiants CITADEL, que `moore_client` lit au moment de son import.
Les fonctions de génération sont lentes (réseau + ffmpeg) : à appeler depuis une tâche de fond.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from .config import get_settings

LANGS = ("fr", "en", "mos")


def _load() -> None:
    s = get_settings()
    module_dir = Path(s.module1_dir)
    if not module_dir.is_absolute():
        module_dir = (Path(__file__).resolve().parents[1] / module_dir).resolve()
    if not module_dir.is_dir():
        raise RuntimeError(f"Dossier du Module 1 introuvable : {module_dir}")
    if str(module_dir) not in sys.path:
        sys.path.append(str(module_dir))
    for env_name, value in {
        "CITADEL_TRANSLATE_URL": s.citadel_translate_url,
        "CITADEL_API_EMAIL": s.citadel_api_email,
        "CITADEL_API_PASSWORD": s.citadel_api_password,
        "MOORE_API_BASE_URL": s.moore_api_base_url,
        "MOORE_API_TOKEN": s.moore_api_token,
        "MOORE_MODEL_TYPE": s.moore_model_type,
    }.items():
        if value:
            os.environ.setdefault(env_name, value)


def parse_alert(raw_text: str) -> dict:
    """Structure le texte d'une alerte (rapide, aucun appel réseau)."""
    _load()
    from alert_parser import parse_alert_text

    a = parse_alert_text(raw_text)
    return {"date_text": a.date_text, "situation": a.situation, "evolution": a.evolution,
            "risques": a.risques, "conseils_intro": a.conseils_intro, "conseils": a.conseils}


def parse_bulletin_pdf(pdf_path: Path) -> dict:
    """Extrait les sections d'un bulletin PDF (rapide, aucun appel réseau)."""
    _load()
    from bulletin_parser import parse_bulletin

    b = parse_bulletin(pdf_path)
    return {"date_text": b.date_text, "observed": b.observed, "forecast": b.forecast,
            "advice_intro": b.advice_intro, "advice": b.advice}


def _collect(result: dict) -> dict:
    """Normalise le résultat du Module 1. Une langue peut manquer (ex. anglais si le service gratuit de
    traduction a atteint son quota) : elle est alors absente de `texts`/`files` et listée dans `skipped`."""
    done = [lang for lang in LANGS if f"audio_{lang}" in result]
    return {
        "texts": {lang: result[f"text_{lang}"] for lang in done},
        "files": {lang: {"audio": Path(result[f"audio_{lang}"]), "video": Path(result[f"video_{lang}"])} for lang in done},
        "skipped": result.get("skipped", {}),
    }


def generate_alert_media(image_path: Path, raw_text: str, out_dir: Path) -> dict:
    """Image + texte d'alerte -> 3 audios et 3 vidéos dans `out_dir`.
    Renvoie {"texts": {fr,en,mos}, "files": {lang: {"audio": Path, "video": Path}}}."""
    _load()
    from generate_alert_all import generate_alert_all

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        text_path = Path(tmp) / "alerte.txt"
        text_path.write_text(raw_text, encoding="utf-8")
        return _collect(generate_alert_all(str(image_path), str(text_path), str(out_dir), stem="alerte"))


def generate_bulletin_media(pdf_path: Path, out_dir: Path) -> dict:
    """Bulletin PDF -> 3 audios et 3 vidéos (cartes + logo, synchronisées par section)."""
    _load()
    from generate_bulletin_all import generate_bulletin_all

    out_dir.mkdir(parents=True, exist_ok=True)
    return _collect(generate_bulletin_all(str(pdf_path), str(out_dir)))


def translate(text_fr: str, lang: str) -> str:
    """Traduit un texte français vers 'en' (MyMemory) ou 'mos' (CITADEL/NLLB). Résultat à faire relire."""
    _load()
    if lang == "en":
        from french_tts import translate_long_fr_to_english

        return translate_long_fr_to_english(text_fr)
    if lang == "mos":
        from moore_client import translate_long_fr_to_moore

        return translate_long_fr_to_moore(text_fr)
    raise ValueError(lang)
