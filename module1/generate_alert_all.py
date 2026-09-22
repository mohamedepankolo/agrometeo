"""generate_alert_all.py — pour une alerte météo (une image + un texte), génère
les 3 audios (FR/EN/mooré) et les 3 vidéos correspondantes (F1.6 : réutilisation
de la chaîne audio du Module 1 pour les alertes).

Contrairement aux bulletins, l'image est fournie telle quelle (radar/satellite,
pas de logo ni de cartes ANAM à extraire) et reste affichée du début à la fin de
chaque vidéo — pas de découpage en segments par section.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from alert_parser import alert_narration_en, alert_narration_fr, alert_narration_moore, parse_alert_text
from french_tts import tts_english, tts_french
from moore_client import tts_moore_long

_TARGET_WIDTH = 1280


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _make_video(image_path: Path, audio_path: Path, out_path: Path) -> None:
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(image_path), "-i", str(audio_path),
        "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p", "-vf", f"scale={_TARGET_WIDTH}:-2", "-shortest", str(out_path),
    ])


def generate_alert_all(image_path: str, text_path: str, out_dir: str | None = None,
                       stem: str | None = None) -> dict:
    image_path = Path(image_path)
    text_path = Path(text_path)
    out_dir = Path(out_dir) if out_dir else image_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or image_path.stem

    alert = parse_alert_text(text_path.read_text(encoding="utf-8"))

    text_fr = alert_narration_fr(alert)
    text_mos = alert_narration_moore(alert)
    result: dict = {"text_fr": text_fr, "text_mos": text_mos}

    # L'anglais repose sur un service gratuit à quota (MyMemory) : s'il refuse, on livre quand même le
    # français et le mooré, et on signale l'anglais manquant dans result["skipped"].
    try:
        result["text_en"] = alert_narration_en(alert)
    except Exception as exc:  # noqa: BLE001
        result["skipped"] = {"en": f"{type(exc).__name__}: {exc}"[:300]}

    audio_by_lang = {}
    tts = {"fr": tts_french, "en": tts_english, "mos": tts_moore_long}
    for lang, path in (("fr", out_dir / f"{stem}_fr.mp3"), ("en", out_dir / f"{stem}_en.mp3"), ("mos", out_dir / f"{stem}_mos.wav")):
        if f"text_{lang}" not in result:
            continue
        tts[lang](result[f"text_{lang}"], out_path=str(path))
        audio_by_lang[lang] = path
        result[f"audio_{lang}"] = path

    for lang, audio in audio_by_lang.items():
        video_path = out_dir / f"{stem}_{lang}.mp4"
        _make_video(image_path, audio, video_path)
        result[f"video_{lang}"] = video_path

    return result


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 3:
        print("Usage : python generate_alert_all.py <image.jpg> <texte.txt> [dossier_sortie]")
        sys.exit(1)

    out_dir_arg = sys.argv[3] if len(sys.argv) > 3 else None
    result = generate_alert_all(sys.argv[1], sys.argv[2], out_dir_arg)

    print("FR :", result["text_fr"])
    print()
    print("EN :", result.get("text_en", "(indisponible)"))
    print()
    print("MOS:", result["text_mos"])
    print()
    for key in ("audio_fr", "audio_en", "audio_mos", "video_fr", "video_en", "video_mos"):
        if key in result:
            print(f"{key:10s} -> {result[key]}")
    if "skipped" in result:
        print("Non générés :", result["skipped"])
