"""wrf_reader.py — lecture des fichiers de sortie du modèle WRF (Weather Research and Forecasting)
fournis par l'ANAM pour le Module 3 (prévisions).

Format des fichiers : NetCDF4/HDF5, nommés `wrfout_d<domaine>_<AAAA-MM-JJ>_<HH:MM:SS>` (convention
WRF standard — le ':' dans le nom pose problème sous Windows, voir la note dans module3/README.md).
Un fichier couvre 24 échéances horaires (une journée) sur toute la grille du domaine.

Constaté sur les 3 premiers fichiers reçus (23-25 mai 2022, domaine d02) :
  - grille 400 x 300 points, résolution 3 km (DX=DY=3000 m), projection Mercator (MAP_PROJ=3)
  - va de 8.10N/-7.85 a 17.18N/4.58 -- tout le Burkina Faso, avec de la marge
  - 242 variables au total (catalogue complet : wrf_variables.json, extrait une fois pour toutes
    d'un fichier réel -- pas besoin d'en ouvrir un juste pour savoir ce qui existe).

Trois niveaux d'accès, du plus simple au plus complet :
  - CORE_FIELDS : le résumé journalier (temperature/pluie/vent/humidite) utilisé partout ailleurs
    dans le Module 3, calculé à partir de 7 variables brutes (T2, Q2, PSFC, U10, V10, RAINC, RAINNC).
  - EXTENDED_VARIABLES : quelques variables de surface supplémentaires, simples à résumer sur la
    journée (nébulosité, rayonnement solaire, hauteur de couche limite, humidité/température du sol).
  - N'IMPORTE QUELLE variable du catalogue, à la demande, via `variable_summary_at_point` /
    `raw_hourly_at_point` -- toutes ne sont pas pré-calculées/stockées (242 x 351 communes x chaque
    jour serait énorme et presque tout inutile : beaucoup sont des champs statiques de grille/modèle,
    pas des prévisions). Nécessite le fichier source encore présent (voir module3/README.md).

Ce module ne connaît ni la base de données ni l'API : extraction pure à partir d'un fichier et de
coordonnées. L'intégration backend est dans backend/app/module3_bridge.py.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Rayon moyen de la Terre (m), pour la distance au point de grille le plus proche.
_EARTH_RADIUS_M = 6_371_000.0

_VARIABLES_CATALOG_PATH = Path(__file__).parent / "wrf_variables.json"

CORE_FIELDS = ["temp_min_c", "temp_max_c", "temp_mean_c", "precip_total_mm",
               "wind_speed_mean_ms", "wind_speed_max_ms", "humidity_mean_pct"]

# Variables de surface simples (Time, south_north, west_east ou + un niveau de sol) : faciles a
# resumer sur la journee (min/max/moyenne), contrairement aux profils verticaux complets (44
# niveaux) ou aux champs statiques (geometrie de grille, categories de sol...).
# soil_level : index dans soil_layers_stag (4 niveaux) pour SMOIS/TSLB -- 0 = couche la plus proche
# de la surface (environ 0-10 cm).
EXTENDED_VARIABLES: dict[str, dict] = {
    "nebulosite_pct": {"source": "CLDFRAC2D", "agg": "mean", "label": "Nébulosité moyenne", "unit": "%", "scale": 100.0},
    "rayonnement_solaire_wm2": {"source": "SWDOWN", "agg": "mean", "label": "Rayonnement solaire moyen", "unit": "W/m2"},
    "rayonnement_infrarouge_wm2": {"source": "GLW", "agg": "mean", "label": "Rayonnement infrarouge descendant moyen", "unit": "W/m2"},
    "hauteur_couche_limite_m": {"source": "PBLH", "agg": "mean", "label": "Hauteur moyenne de la couche limite atmosphérique", "unit": "m"},
    "humidite_sol_pct": {"source": "SMOIS", "agg": "mean", "soil_level": 0, "label": "Humidité du sol en surface (0-10 cm)", "unit": "%", "scale": 100.0},
    "temperature_sol_c": {"source": "TSLB", "agg": "mean", "soil_level": 0, "label": "Température du sol en surface (0-10 cm)", "unit": "°C", "kelvin": True},
}


@dataclass
class DailySummary:
    forecast_date: str  # AAAA-MM-JJ (jour couvert par le fichier)
    lat_used: float  # latitude du point de grille réellement utilisé (le plus proche du point demandé)
    lon_used: float
    distance_km: float  # distance entre le point demandé et le point de grille utilisé
    temp_min_c: float
    temp_max_c: float
    temp_mean_c: float
    precip_total_mm: float
    wind_speed_mean_ms: float
    wind_speed_max_ms: float
    humidity_mean_pct: float
    extended: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "forecast_date": self.forecast_date,
            "lat_used": round(self.lat_used, 4),
            "lon_used": round(self.lon_used, 4),
            "distance_km": round(self.distance_km, 2),
            "temp_min_c": round(self.temp_min_c, 1),
            "temp_max_c": round(self.temp_max_c, 1),
            "temp_mean_c": round(self.temp_mean_c, 1),
            "precip_total_mm": round(self.precip_total_mm, 1),
            "wind_speed_mean_ms": round(self.wind_speed_mean_ms, 1),
            "wind_speed_max_ms": round(self.wind_speed_max_ms, 1),
            "humidity_mean_pct": round(self.humidity_mean_pct, 1),
            "extended": {k: round(v, 2) for k, v in self.extended.items()},
        }


def open_wrf(path: str | Path):
    """Ouvre un fichier wrfout. Importé ici (pas en tête de module) pour que le reste du projet
    n'ait pas besoin de netCDF4 installé si le Module 3 n'est pas utilisé."""
    import netCDF4

    return netCDF4.Dataset(str(path))


def run_date(ds) -> str:
    """Jour couvert par le fichier (AAAA-MM-JJ), lu dans la variable Times plutôt que dans le nom
    du fichier (plus fiable, et le nom contient des ':' illisibles sous Windows)."""
    times = ds.variables["Times"][:]
    first = b"".join(times[0]).decode("utf-8")  # "2022-05-23_01:00:00"
    return first.split("_")[0]


def list_variables() -> list[dict]:
    """Catalogue des 242 variables du format WRF (nom, description, unité, dimensions), lu depuis
    un fichier figé une fois pour toutes (pas besoin d'ouvrir un fichier de plusieurs Go juste pour
    savoir ce qui existe -- le schéma de sortie WRF ne change pas d'un fichier à l'autre). Chaque
    entrée est annotée `in_core` / `in_extended` pour savoir à quel niveau d'accès elle appartient."""
    catalog = json.loads(_VARIABLES_CATALOG_PATH.read_text(encoding="utf-8"))
    extended_sources = {v["source"] for v in EXTENDED_VARIABLES.values()}
    core_sources = {"T2", "Q2", "PSFC", "U10", "V10", "RAINC", "RAINNC"}
    for row in catalog:
        row["in_core"] = row["name"] in core_sources
        row["in_extended"] = row["name"] in extended_sources
    return catalog


def _nearest_index(ds, lat: float, lon: float) -> tuple[int, int, float]:
    """Point de grille le plus proche de (lat, lon), par distance euclidienne en degrés (grille de
    3 km : largement suffisant, pas besoin d'une vraie projection pour choisir le point le plus proche).
    Renvoie (indice_sud_nord, indice_ouest_est, distance_km réelle au point choisi)."""
    xlat = ds.variables["XLAT"][0, :, :]
    xlong = ds.variables["XLONG"][0, :, :]
    d2 = (xlat - lat) ** 2 + (xlong - lon) ** 2
    iy, ix = np.unravel_index(np.argmin(d2), d2.shape)
    found_lat, found_lon = float(xlat[iy, ix]), float(xlong[iy, ix])
    distance_km = _haversine_km(lat, lon, found_lat, found_lon)
    return int(iy), int(ix), distance_km


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a)) / 1000


def _relative_humidity_pct(t2_k: np.ndarray, q2: np.ndarray, psfc_pa: np.ndarray) -> np.ndarray:
    """Humidité relative (%) à partir de la température, de l'humidité spécifique et de la pression
    de surface, par la formule de Magnus — approche standard en post-traitement WRF (ex. NCL/wrf-python).
    e  = pression de vapeur réelle (hPa) ; es = pression de vapeur saturante (hPa)."""
    t_c = t2_k - 273.15
    psfc_hpa = psfc_pa / 100.0
    es = 6.112 * np.exp(17.67 * t_c / (t_c + 243.5))
    e = psfc_hpa * q2 / (0.622 + 0.378 * q2)
    return np.clip(100.0 * e / es, 0.0, 100.0)


def _extended_summary(ds, iy: int, ix: int) -> dict[str, float]:
    out = {}
    for key, spec in EXTENDED_VARIABLES.items():
        var = ds.variables.get(spec["source"])
        if var is None:
            continue
        if "soil_level" in spec:
            series = np.asarray(var[:, spec["soil_level"], iy, ix])
        else:
            series = np.asarray(var[:, iy, ix])
        if spec.get("kelvin"):
            series = series - 273.15
        if spec.get("scale"):
            series = series * spec["scale"]
        out[key] = float(series.mean()) if spec["agg"] == "mean" else float(series.max())
    return out


def daily_summary_at_point(ds, lat: float, lon: float) -> DailySummary:
    """Résumé journalier CORE + EXTENDED (une valeur par variable, sur les 24 échéances) au point
    de grille le plus proche de (lat, lon). Lève KeyError si une variable CORE attendue est absente
    du fichier (les variables EXTENDED absentes sont silencieusement ignorées, plus permissif)."""
    iy, ix, distance_km = _nearest_index(ds, lat, lon)

    t2 = np.asarray(ds.variables["T2"][:, iy, ix])  # K, (Time,)
    q2 = np.asarray(ds.variables["Q2"][:, iy, ix])
    psfc = np.asarray(ds.variables["PSFC"][:, iy, ix])
    u10 = np.asarray(ds.variables["U10"][:, iy, ix])
    v10 = np.asarray(ds.variables["V10"][:, iy, ix])
    rainc = np.asarray(ds.variables["RAINC"][:, iy, ix])
    rainnc = np.asarray(ds.variables["RAINNC"][:, iy, ix])

    wind_speed = np.sqrt(u10**2 + v10**2)
    rh = _relative_humidity_pct(t2, q2, psfc)
    # RAINC/RAINNC sont des cumuls depuis le début de la simulation : la pluie DU JOUR couvert par
    # ce fichier est la différence entre la dernière et la première échéance.
    precip_total = float((rainc[-1] + rainnc[-1]) - (rainc[0] + rainnc[0]))

    t2_c = t2 - 273.15
    lat_used = float(ds.variables["XLAT"][0, iy, ix])
    lon_used = float(ds.variables["XLONG"][0, iy, ix])

    return DailySummary(
        forecast_date=run_date(ds),
        lat_used=lat_used,
        lon_used=lon_used,
        distance_km=distance_km,
        temp_min_c=float(t2_c.min()),
        temp_max_c=float(t2_c.max()),
        temp_mean_c=float(t2_c.mean()),
        precip_total_mm=max(precip_total, 0.0),
        wind_speed_mean_ms=float(wind_speed.mean()),
        wind_speed_max_ms=float(wind_speed.max()),
        humidity_mean_pct=float(rh.mean()),
        extended=_extended_summary(ds, iy, ix),
    )


def daily_summaries(path: str | Path, points: dict[str, tuple[float, float]]) -> dict[str, dict]:
    """Résumé journalier pour plusieurs points en un seul passage sur le fichier.
    `points` : {cle: (lat, lon)}. Renvoie {cle: DailySummary.as_dict()} ; une clé est absente du
    résultat si l'extraction a échoué pour ce point (pas d'exception globale pour un point isolé)."""
    ds = open_wrf(path)
    try:
        out: dict[str, dict] = {}
        for key, (lat, lon) in points.items():
            out[key] = daily_summary_at_point(ds, lat, lon).as_dict()
        return out
    finally:
        ds.close()


def raw_variable_at_point(ds, lat: float, lon: float, variable: str, level: int | None = None) -> dict:
    """Valeurs des 24 échéances d'UNE variable quelconque du catalogue au point le plus proche de
    (lat, lon), plus min/max/moyenne sur la journée -- pour accéder à une variable qui n'est ni
    dans CORE_FIELDS ni dans EXTENDED_VARIABLES (ex. SWDOWN brut, ou n'importe laquelle des 242).

    `level` : index de niveau pour une variable à 4 dimensions (profil vertical `bottom_top`,
    niveau de sol `soil_layers_stag`) -- obligatoire dans ce cas, sinon ValueError explicite plutôt
    qu'une erreur numpy confuse. Ignoré (doit être omis) pour une variable de surface simple."""
    if variable not in ds.variables:
        raise KeyError(f"Variable inconnue dans ce fichier : {variable!r}")
    var = ds.variables[variable]
    dims = var.dimensions
    if not dims or dims[0] != "Time" or "south_north" not in dims or "west_east" not in dims:
        raise ValueError(f"{variable!r} n'est pas une variable de surface variable dans le temps "
                         f"(dimensions : {dims}) -- extraction par point non applicable.")
    iy, ix, distance_km = _nearest_index(ds, lat, lon)
    extra_dims = [d for d in dims if d not in ("Time", "south_north", "west_east")]
    if extra_dims and level is None:
        raise ValueError(f"{variable!r} a une dimension supplémentaire ({extra_dims[0]}) : "
                         f"préciser `level` (index entier).")
    if extra_dims:
        series = np.asarray(var[:, level, iy, ix])
    else:
        series = np.asarray(var[:, iy, ix])
    series = series.astype(float)
    return {
        "variable": variable,
        "level": level,
        "distance_km": round(distance_km, 2),
        "hourly_values": [round(v, 4) for v in series.tolist()],
        "min": round(float(series.min()), 4),
        "max": round(float(series.max()), 4),
        "mean": round(float(series.mean()), 4),
    }


def raw_variables_at_point(path: str | Path, lat: float, lon: float, variables: list[str],
                           level: int | None = None) -> dict[str, dict]:
    """Comme `raw_variable_at_point`, pour plusieurs variables en un seul passage sur le fichier.
    Une variable en échec (absente, mauvaise dimension) est rapportée dans `errors`, pas levée."""
    ds = open_wrf(path)
    try:
        out: dict[str, dict] = {}
        errors: dict[str, str] = {}
        for variable in variables:
            try:
                out[variable] = raw_variable_at_point(ds, lat, lon, variable, level)
            except (KeyError, ValueError) as exc:
                errors[variable] = str(exc)
        if errors:
            out["_errors"] = errors
        return out
    finally:
        ds.close()
