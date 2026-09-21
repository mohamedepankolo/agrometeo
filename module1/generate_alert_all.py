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
                       stem: str | None = None) -> dict[str, Path]:
    image_path = Path(image_path)
    text_path = Path(text_path)
    out_dir = Path(out_dir) if out_dir else image_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or image_path.stem

    alert = parse_alert_text(text_path.read_text(encoding="utf-8"))

    text_fr = alert_narration_fr(alert)
    text_en = alert_narration_en(alert)
    text_mos = alert_narration_moore(alert)

    result: dict[str, Path] = {"text_fr": text_fr, "text_en": text_en, "text_mos": text_mos}

    fr_audio = out_dir / f"{stem}_fr.mp3"
    tts_french(text_fr, out_path=str(fr_audio))
    en_audio = out_dir / f"{stem}_en.mp3"
    tts_english(text_en, out_path=str(en_audio))
    mos_audio = out_dir / f"{stem}_mos.wav"
    tts_moore_long(text_mos, out_path=str(mos_audio))

    audio_by_lang = {"fr": fr_audio, "en": en_audio, "mos": mos_audio}
    result["audio_fr"], result["audio_en"], result["audio_mos"] = fr_audio, en_audio, mos_audio

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
    print("EN :", result["text_en"])
    print()
    print("MOS:", result["text_mos"])
    print()
    for key in ("audio_fr", "audio_en", "audio_mos", "video_fr", "video_en", "video_mos"):
        print(f"{key:10s} -> {result[key]}")
