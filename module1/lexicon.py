"""lexicon.py — accès au lexique météo FR->mooré (ANAM Kaya + BRACED/Internews 2016).

Exigence F1.7 du cahier des charges : exploiter le lexique météorologique
Mooré-Français fourni pour alimenter la traduction, plutôt que de tout laisser
au modèle NLLB générique.

Le fichier lexicons/lexicon_fr_moore.json est produit par lexicons/build_lexicon.py
à partir des deux PDF sources (voir ce script pour la provenance).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_LEXICON_PATH = Path(__file__).parent / "lexicons" / "lexicon_fr_moore.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    """Charge le lexique en dict {terme FR normalisé -> entrée}.
    Les entrées Kaya (vocabulaire de bulletin ANAM) priment sur BRACED en cas de doublon."""
    entries = json.loads(_LEXICON_PATH.read_text(encoding="utf-8"))
    by_term: dict[str, dict] = {}
    for e in entries:
        key = _normalize(e["fr"])
        if key not in by_term or (e["source"] == "kaya" and by_term[key]["source"] != "kaya"):
            by_term[key] = e
    return by_term


def _normalize(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip().lower())


def lookup(term_fr: str) -> str | None:
    """Traduction mooré exacte d'un terme/expression FR du lexique, si présente."""
    return _load().get(_normalize(term_fr), {}).get("moore")


def entries() -> list[dict]:
    """Toutes les entrées du lexique (fr, moore, explication, source)."""
    return list(_load().values())


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    for term in sys.argv[1:] or ["nuageux", "orageux", "les dernières 24h", "bulletin météo"]:
        print(f"{term!r} -> {lookup(term)!r}")
