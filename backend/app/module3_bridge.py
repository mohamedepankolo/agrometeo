"""Pont vers la lecture des fichiers WRF du Module 3 (dossier `module3/`).

Même principe que module1_bridge.py : le Module 3 est un script « à plat » (`wrf_reader.py`),
ajouté au chemin d'import au premier usage. Contrairement au Module 1, aucun service externe
n'est appelé : lecture seule d'un fichier local, pure et rapide (netCDF4 ne charge que les
tranches lues, pas tout le fichier — quelques dixièmes de seconde même pour un fichier de 5 Go).
"""

from __future__ import annotations

import sys
from pathlib import Path

from .config import get_settings


def _load():
    s = get_settings()
    module_dir = Path(s.module3_dir)
    if not module_dir.is_absolute():
        module_dir = (Path(__file__).resolve().parents[1] / module_dir).resolve()
    if not module_dir.is_dir():
        raise RuntimeError(f"Dossier du Module 3 introuvable : {module_dir}")
    if str(module_dir) not in sys.path:
        sys.path.append(str(module_dir))


def run_date(path: Path) -> str:
    """Jour couvert par un fichier wrfout (AAAA-MM-JJ), lu dans ses données (variable Times)."""
    _load()
    import wrf_reader

    ds = wrf_reader.open_wrf(path)
    try:
        return wrf_reader.run_date(ds)
    finally:
        ds.close()


def daily_summaries(path: Path, points: dict[str, tuple[float, float]]) -> dict[str, dict]:
    """Résumé journalier par zone. `points` : {zone_id: (latitude, longitude)}."""
    _load()
    import wrf_reader

    return wrf_reader.daily_summaries(path, points)


def list_variables() -> list[dict]:
    """Catalogue des 242 variables du format WRF (figé, ne lit aucun fichier)."""
    _load()
    import wrf_reader

    return wrf_reader.list_variables()


def raw_variables(path: Path, lat: float, lon: float, variables: list[str],
                  level: int | None = None) -> dict[str, dict]:
    """Valeurs horaires brutes d'une ou plusieurs variables à un point, directement depuis le
    fichier source (doit encore exister dans wrf_incoming_dir)."""
    _load()
    import wrf_reader

    return wrf_reader.raw_variables_at_point(path, lat, lon, variables, level)
