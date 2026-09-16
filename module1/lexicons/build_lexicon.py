"""build_lexicon.py — extrait les lexiques météo FR->mooré (PDF) en JSON exploitable.

Sources :
- LEXIQUE français_moré_kaya.pdf : lexique court, vocabulaire de bulletin (ANAM Kaya).
- Lexicon of words and weather terms _IN_Burkina_2016.pdf : lexique BRACED/Internews
  (517 termes météo/climat, FR/anglais/mooré/gulimancema/fulfuldé), pages 33 à 118.

Sortie : lexicons/lexicon_fr_moore.json — liste de {"fr": ..., "moore": ..., "explication": ..., "source": ...}
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pdfplumber

HERE = Path(__file__).parent


def _clean(cell) -> str:
    if not cell:
        return ""
    return re.sub(r"\s+", " ", cell.replace("\n", " ")).strip()


def extract_kaya(path: Path) -> list[dict]:
    entries = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or len(row) < 2:
                        continue
                    fr, moore = _clean(row[0]), _clean(row[1])
                    if not fr or not moore or fr.lower() == "français":
                        continue
                    entries.append({"fr": fr, "moore": moore, "explication": "", "source": "kaya"})
    return entries


def extract_braced(path: Path) -> list[dict]:
    entries = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or len(row) < 4:
                        continue
                    fr, explication, moore = _clean(row[0]), _clean(row[2]), _clean(row[3])
                    if not fr or not moore:
                        continue
                    if fr.lower() in {"mots et", "termes météo"} or "termes météo" in fr.lower():
                        continue
                    entries.append({"fr": fr, "moore": moore, "explication": explication, "source": "braced"})
    return entries


def main() -> None:
    kaya_path = next(HERE.glob("LEXIQUE*kaya.pdf"))
    braced_path = next(HERE.glob("Lexicon*Burkina*.pdf"))

    entries = extract_kaya(kaya_path) + extract_braced(braced_path)

    out_path = HERE / "lexicon_fr_moore.json"
    out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(entries)} entrées écrites dans {out_path}")


if __name__ == "__main__":
    main()
