"""generate_bulletin_audio.py — pour un bulletin PDF donné, génère l'audio dans
les 3 langues (français, anglais, mooré) prévues par le cahier des charges
(F1.3/ENF5), à côté du PDF (ou dans un dossier de sortie donné), en reprenant
le nom du bulletin : <nom>_fr.mp3, <nom>_en.mp3, <nom>_mos.wav.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bulletin_parser import bulletin_narration_fr, bulletin_narration_moore, parse_bulletin
from french_tts import translate_long_fr_to_english, tts_english, tts_french
from moore_client import tts_moore_long


def generate_bulletin_audio(pdf_path: str, out_dir: str | None = None) -> dict:
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir) if out_dir else pdf_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    bulletin = parse_bulletin(pdf_path)
    text_fr = bulletin_narration_fr(bulletin)
    text_en = translate_long_fr_to_english(text_fr)
    text_mos = bulletin_narration_moore(bulletin)

    fr_path = tts_french(text_fr, out_path=str(out_dir / f"{stem}_fr.mp3"))
    en_path = tts_english(text_en, out_path=str(out_dir / f"{stem}_en.mp3"))
    mos_path = tts_moore_long(text_mos, out_path=str(out_dir / f"{stem}_mos.wav"))

    return {
        "fr": fr_path, "en": en_path, "mos": mos_path,
        "text_fr": text_fr, "text_en": text_en, "text_mos": text_mos,
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage : python generate_bulletin_audio.py <bulletin.pdf> [dossier_sortie]")
        sys.exit(1)

    out_dir_arg = sys.argv[2] if len(sys.argv) > 2 else None
    result = generate_bulletin_audio(sys.argv[1], out_dir_arg)

    print("FR  :", result["text_fr"])
    print()
    print("EN  :", result["text_en"])
    print()
    print("MOS :", result["text_mos"])
    print()
    print("Audio FR  ->", result["fr"])
    print("Audio EN  ->", result["en"])
    print("Audio MOS ->", result["mos"])
