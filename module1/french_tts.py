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
from pathlib import Path

import edge_tts

from moore_client import _split_safe

DEFAULT_VOICE_FR = "fr-FR-DeniseNeural"
DEFAULT_VOICE_EN = "en-US-JennyNeural"


def translate_long_fr_to_english(text_fr: str) -> str:
    """Traduction FR -> anglais, phrase par phrase (MyMemory limite les requêtes
    à 500 caractères ; on réutilise le découpage <=200 caractères déjà validé
    pour le mooré, qui offre une marge suffisante)."""
    from deep_translator import MyMemoryTranslator

    translator = MyMemoryTranslator(source="fr-FR", target="en-GB")
    chunks = _split_safe(text_fr)
    return " ".join(translator.translate(c) for c in chunks)


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
