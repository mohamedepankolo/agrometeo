"""generate_bulletin_video.py — assemble une vidéo par bulletin : chaque section
(observé / prévisions / avis-conseils) est un segment "image fixe + audio de la
section", concaténés dans l'ordre. La section conseils, si présente, est affichée
sur le logo ANAM/météo Burkina (pas de 3e carte dans le PDF).

D'abord en français (tts_french) ; à étendre ensuite au mooré/anglais si le
résultat convient.

Dépendance externe : ffmpeg (déjà utilisé ailleurs dans le projet pour l'audio).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

from bulletin_parser import bulletin_narration_fr_parts, extract_bulletin_images, parse_bulletin
from french_tts import tts_french

# Résolution cible commune à tous les segments de la vidéo (déterminée à partir de
# la carte "observé"). Le logo, bien plus petit dans le PDF source (227x90 px
# natifs — vérifié, ce n'est pas un artefact de notre extraction), est affiché à
# une taille raisonnable sur fond blanc plutôt qu'étiré en plein cadre : l'étirer
# ne le rendrait pas plus net (résolution source insuffisante), juste plus flou.
_TARGET_WIDTH = 1280
_LOGO_MAX_WIDTH = 480


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _fitted_size(image_path: Path, max_w: int, max_h: int) -> tuple[int, int]:
    """Dimensions de `image_path` mises à l'échelle pour tenir dans max_w x max_h
    (sans dépasser, aspect conservé), arrondies au pixel pair (requis par le
    codec vidéo)."""
    with Image.open(image_path) as im:
        w, h = im.size
    scale = min(max_w / w, max_h / h)
    fw, fh = w * scale, h * scale
    return max(2, int(round(fw / 2) * 2)), max(2, int(round(fh / 2) * 2))


def _make_segment(image_path: Path, audio_path: Path, out_path: Path,
                  target_w: int, target_h: int, max_w: int, max_h: int) -> None:
    """Encode `image_path` (mise à l'échelle dans max_w x max_h, centrée sur un
    fond blanc de target_w x target_h) avec `audio_path` en piste son."""
    fw, fh = _fitted_size(image_path, max_w, max_h)
    x, y = (target_w - fw) // 2, (target_h - fh) // 2
    vf = f"scale={fw}:{fh},pad={target_w}:{target_h}:{x}:{y}:color=white"
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(image_path), "-i", str(audio_path),
        "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p", "-vf", vf, "-shortest", str(out_path),
    ])


def generate_bulletin_video(pdf_path: str, out_dir: str | None = None) -> Path:
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir) if out_dir else pdf_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    bulletin = parse_bulletin(pdf_path)
    text_parts = bulletin_narration_fr_parts(bulletin)
    images = extract_bulletin_images(pdf_path, out_dir=out_dir)
    image_for_part = {
        "observee": images["carte_observee"],
        "prevision": images["carte_prevision"],
        "conseils": images.get("logo"),
    }

    # Résolution cible = la carte "observé" mise à l'échelle en largeur _TARGET_WIDTH.
    target_w, target_h = _fitted_size(images["carte_observee"], _TARGET_WIDTH, 10_000)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        segment_paths = []
        for i, (name, text) in enumerate(text_parts):
            audio_path = tmp / f"{i}_{name}.mp3"
            tts_french(text, out_path=str(audio_path))
            segment_path = tmp / f"{i}_{name}.mp4"
            max_w, max_h = (_LOGO_MAX_WIDTH, target_h) if name == "conseils" else (target_w, target_h)
            _make_segment(image_for_part[name], audio_path, segment_path, target_w, target_h, max_w, max_h)
            segment_paths.append(segment_path)

        list_path = tmp / "list.txt"
        list_path.write_text("".join(f"file '{p.as_posix()}'\n" for p in segment_paths), encoding="utf-8")

        out_path = out_dir / f"{stem}_fr.mp4"
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(out_path)])

    return out_path


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage : python generate_bulletin_video.py <bulletin.pdf> [dossier_sortie]")
        sys.exit(1)

    out_dir_arg = sys.argv[2] if len(sys.argv) > 2 else None
    video_path = generate_bulletin_video(sys.argv[1], out_dir_arg)
    print("Vidéo :", video_path)
