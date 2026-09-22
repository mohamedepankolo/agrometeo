"""french_tts.py — synthèse vocale FR/EN via Edge TTS (voix neuronales Microsoft).

Solution de repli en attendant que CITADEL propose un TTS français/anglais natif
(cf. README.md : "TTS français / anglais : à intégrer côté service"). Contrairement
au mooré, le français et l'anglais sont des langues bien dotées en solutions TTS
"prêtes à l'emploi" — Edge TTS est gratuit, sans clé API, bonne qualité (voix
neuronales), mais repose sur un service non documenté publiquement par Microsoft :
à considérer comme solution provisoire, pas comme dépendance de production garantie.

Sortie : fichiers .mp3 (format natif du service), pas .wav comme le pipeline mooré.

Dépendance : edge-tts  ->  pip install edge-tts
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from pathlib import Path

import edge_tts

from moore_client import _split_safe

DEFAULT_VOICE_FR = "fr-FR-DeniseNeural"
DEFAULT_VOICE_EN = "en-US-JennyNeural"
DEFAULT_LOCAL_MODEL = "Helsinki-NLP/opus-mt-fr-en"


_CACHE_PATH = Path(__file__).with_name(".cache") / "translations_en.json"


def _load_cache() -> dict[str, str]:
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    _CACHE_PATH.parent.mkdir(exist_ok=True)
    tmp = _CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_CACHE_PATH)


_LOCAL = {"tokenizer": None, "model": None, "failed": False}
_LOCAL_LOCK = threading.Lock()


def _local_model():
    """Modèle de traduction FR->EN exécuté sur la machine (aucun quota, aucun envoi de texte à un tiers).
    Renvoie None si transformers/torch ne sont pas installés ou si le modèle est introuvable."""
    with _LOCAL_LOCK:
        if _LOCAL["model"] is None and not _LOCAL["failed"]:
            try:
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

                name = os.environ.get("LOCAL_TRANSLATION_MODEL", DEFAULT_LOCAL_MODEL)
                _LOCAL["tokenizer"] = AutoTokenizer.from_pretrained(name)
                _LOCAL["model"] = AutoModelForSeq2SeqLM.from_pretrained(name).eval()
            except Exception:  # noqa: BLE001 — bibliothèques absentes, modèle non téléchargeable, etc.
                _LOCAL["failed"] = True
        return _LOCAL["model"]


def _translate_local(chunks: list[str]) -> list[str]:
    import torch

    model, tok = _local_model(), _LOCAL["tokenizer"]
    results: list[str] = []
    for i in range(0, len(chunks), 8):  # lots de 8 phrases : mémoire maîtrisée
        batch = chunks[i:i + 8]
        with torch.no_grad():
            enc = tok(batch, return_tensors="pt", padding=True, truncation=True, max_length=256)
            out = model.generate(**enc, num_beams=4, max_new_tokens=256)
        results.extend(re.sub(r"([.!?])([A-Z])", r"\1 \2", t) for t in tok.batch_decode(out, skip_special_tokens=True))
    return results


def _translate_mymemory(chunks: list[str], record) -> None:
    """Traduit via MyMemory ; `record(phrase, traduction)` est appelé phrase par phrase pour que rien ne soit
    perdu si le quota tombe en cours de route."""
    from deep_translator import MyMemoryTranslator

    translator = MyMemoryTranslator(source="fr-FR", target="en-GB", email=os.environ.get("MYMEMORY_EMAIL") or None)
    for chunk in chunks:
        try:
            translated = translator.translate(chunk)
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "TooManyRequests":  # message d'origine trompeur (parle de Google)
                raise RuntimeError("quota gratuit de traduction MyMemory atteint pour aujourd'hui "
                                   "(installer le modèle local ou renseigner MYMEMORY_EMAIL)") from None
            raise
        if not translated or "MYMEMORY WARNING" in translated.upper():
            raise RuntimeError("quota de traduction MyMemory atteint : " + str(translated)[:120])
        record(chunk, translated)


def translate_long_fr_to_english(text_fr: str) -> str:
    """Traduction FR -> anglais, phrase par phrase (découpage <= 200 caractères, comme pour le mooré).

    Moteurs, dans l'ordre (variable TRANSLATION_BACKEND = auto | local | mymemory) :
      1. cache local (.cache/, non versionné) : une phrase déjà traduite n'est jamais retraduite ;
      2. modèle local opus-mt-fr-en (transformers + torch) : hors ligne, sans quota, qualité de traduction
         automatique courante — installé : `pip install torch transformers sentencepiece` ;
      3. MyMemory (gratuit, ~5 000 caractères/jour ; ~50 000 avec MYMEMORY_EMAIL) en dernier recours.
    """
    backend = os.environ.get("TRANSLATION_BACKEND", "auto")
    cache = _load_cache()
    chunks = [c.strip() for c in _split_safe(text_fr)]
    todo = list(dict.fromkeys(c for c in chunks if c not in cache))
    if todo:
        def record(chunk: str, translated: str) -> None:
            cache[chunk] = translated
            _save_cache(cache)

        done = None
        if backend in ("auto", "local") and _local_model() is not None:
            try:
                done = _translate_local(todo)
            except Exception:  # noqa: BLE001 — en mode auto, un incident du modèle local ne doit pas bloquer
                if backend == "local":
                    raise
        elif backend == "local":
            raise RuntimeError("modèle de traduction local indisponible (pip install torch transformers sentencepiece)")
        if done is not None:
            cache.update(zip(todo, done))
            _save_cache(cache)
        else:
            _translate_mymemory(todo, record)
    return " ".join(cache[c] for c in chunks)


async def _synthesize(text: str, voice: str, out_path: Path) -> Path:
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))
    return out_path


def tts_french(text: str, out_path: str = "bulletin_fr.mp3", voice: str = DEFAULT_VOICE_FR) -> Path:
    """Texte FR -> audio .mp3 via une voix neuronale Edge TTS."""
    if not text.strip():
        raise ValueError("Texte vide.")
    return asyncio.run(_synthesize(text, voice, Path(out_path)))


def tts_english(text: str, out_path: str = "bulletin_en.mp3", voice: str = DEFAULT_VOICE_EN) -> Path:
    """Texte EN -> audio .mp3 via une voix neuronale Edge TTS."""
    if not text.strip():
        raise ValueError("Texte vide.")
    return asyncio.run(_synthesize(text, voice, Path(out_path)))


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    arg = " ".join(sys.argv[1:]) or "Bonjour, ceci est un test de synthèse vocale en français."

    if arg.lower().endswith(".pdf"):
        from bulletin_parser import bulletin_narration_fr, parse_bulletin

        bulletin = parse_bulletin(arg)
        text = bulletin_narration_fr(bulletin)
        print("FR :", text)
    else:
        text = arg

    out = tts_french(text)
    print("Audio :", out)
