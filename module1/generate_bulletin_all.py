"""generate_bulletin_all.py — pour un bulletin PDF donné, génère en une seule
commande les 3 audios (FR/EN/mooré) ET les 3 vidéos correspondantes (F1.3/F1.4).
Les images (cartes + logo) ne sont que des artefacts intermédiaires : elles sont
utilisées pour construire les vidéos puis supprimées, pas copiées dans le dossier
de sortie. Résultat : 6 fichiers par bulletin, nommés <nom>_fr/_en/_mos.{mp3,wav,mp4}.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from bulletin_parser import (
    bulletin_narration_en_parts,
    bulletin_narration_fr_parts,
    bulletin_narration_moore_parts,
    extract_bulletin_images,
    parse_bulletin,
)
from french_tts import tts_english, tts_french
from generate_bulletin_video import _LOGO_MAX_WIDTH, _TARGET_WIDTH, _fitted_size, _make_segment, _run
from moore_client import tts_moore_long

_AUDIO_EXT = {"fr": "mp3", "en": "mp3", "mos": "wav"}


def _tts_part(lang: str, text: str, out_path: Path) -> None:
    if lang == "fr":
        tts_french(text, out_path=str(out_path))
    elif lang == "en":
        tts_english(text, out_path=str(out_path))
    else:
        tts_moore_long(text, out_path=str(out_path))


def _concat(paths: list[Path], out_path: Path) -> None:
    list_path = out_path.parent / f".{out_path.stem}_list.txt"
    list_path.write_text("".join(f"file '{p.as_posix()}'\n" for p in paths), encoding="utf-8")
    try:
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(out_path)])
    finally:
        list_path.unlink(missing_ok=True)


def generate_bulletin_all(pdf_path: str, out_dir: str | None = None) -> dict[str, Path | str]:
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir) if out_dir else pdf_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    bulletin = parse_bulletin(pdf_path)
    parts_by_lang = {
        "fr": bulletin_narration_fr_parts(bulletin),
        "en": bulletin_narration_en_parts(bulletin),
        "mos": bulletin_narration_moore_parts(bulletin),
    }

    result: dict[str, Path | str] = {
        f"text_{lang}": " ".join(text for _, text in parts) for lang, parts in parts_by_lang.items()
    }

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)

        images = extract_bulletin_images(pdf_path, out_dir=tmp)
        target_w, target_h = _fitted_size(images["carte_observee"], _TARGET_WIDTH, 10_000)
        image_for_part = {
            "observee": images["carte_observee"],
            "prevision": images["carte_prevision"],
            "conseils": images.get("logo"),
        }

        for lang, parts in parts_by_lang.items():
            ext = _AUDIO_EXT[lang]
            part_audio_paths, segment_video_paths = [], []

            for i, (name, text) in enumerate(parts):
                audio_path = tmp / f"{lang}_{i}_{name}.{ext}"
                _tts_part(lang, text, audio_path)
                part_audio_paths.append(audio_path)

                video_path = tmp / f"{lang}_{i}_{name}.mp4"
                max_w, max_h = (_LOGO_MAX_WIDTH, target_h) if name == "conseils" else (target_w, target_h)
                _make_segment(image_for_part[name], audio_path, video_path, target_w, target_h, max_w, max_h)
                segment_video_paths.append(video_path)

            audio_out = out_dir / f"{stem}_{lang}.{ext}"
            _concat(part_audio_paths, audio_out)
            result[f"audio_{lang}"] = audio_out

            video_out = out_dir / f"{stem}_{lang}.mp4"
            _concat(segment_video_paths, video_out)
            result[f"video_{lang}"] = video_out

    return result


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage : python generate_bulletin_all.py <bulletin.pdf> [dossier_sortie]")
        sys.exit(1)

    out_dir_arg = sys.argv[2] if len(sys.argv) > 2 else None
    result = generate_bulletin_all(sys.argv[1], out_dir_arg)
    for key in ("audio_fr", "audio_en", "audio_mos", "video_fr", "video_en", "video_mos"):
        print(f"{key:10s} -> {result[key]}")
