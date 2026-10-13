"""Pont vers la lecture des exports GeoJSON du Module 2 (dossier `module2/`).

Même principe que module1_bridge.py / module3_bridge.py : le Module 2 est un script « à plat »
(`geojson_reader.py`), ajouté au chemin d'import au premier usage.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .config import get_settings


def _load():
    s = get_settings()
    module_dir = Path(s.module2_dir)
    if not module_dir.is_absolute():
        module_dir = (Path(__file__).resolve().parents[1] / module_dir).resolve()
    if not module_dir.is_dir():
        raise RuntimeError(f"Dossier du Module 2 introuvable : {module_dir}")
    if str(module_dir) not in sys.path:
        sys.path.append(str(module_dir))


def read_export(path: Path) -> dict:
    """Lit un export GeoJSON de stations : `{"kind", "date", "records"}` (voir module2/README.md)."""
    _load()
    import geojson_reader

    return geojson_reader.read_export(path)
