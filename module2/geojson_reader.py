"""Lecture des exports GeoJSON de stations météo de l'ANAM (Module 2).

Fonctions pures (pas de base de données, pas d'API), même esprit que `module3/wrf_reader.py` :
une seule responsabilité, lire un fichier et renvoyer des données normalisées. Contrairement au
Module 3 (fichiers WRF modélisés, ~5 Go), ce sont de petits exports GeoJSON (~15-20 Ko) de
relevés RÉELS de stations météo physiques -- une mesure, pas une prévision.

Format reçu (un fichier par variable, un jour par fichier) : `FeatureCollection` de `Point`,
chaque `Feature.properties` portant `stations` (nom), `date` (AAAA-MM-JJ), et les valeurs
propres à la variable :
- température : `tmin`, `tmax` (°C)
- pluviométrie : `value` (mm, cumul du jour)
- humidité relative : `umin`, `umax` (%)

La variable est déduite des clés présentes dans `properties` (voir `detect_kind`), pas du nom de
fichier -- les noms reçus (`exporttemp.geojson`, `exportrr.geojson`, `exportrelhum.geojson`) ne
sont qu'une convention de celui qui exporte, pas un format garanti.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

Kind = Literal["temperature", "pluviometrie", "humidite"]

_KIND_KEYS: dict[Kind, tuple[str, ...]] = {
    "temperature": ("tmin", "tmax"),
    "pluviometrie": ("value",),
    "humidite": ("umin", "umax"),
}


def detect_kind(properties: dict) -> Kind:
    for kind, keys in _KIND_KEYS.items():
        if all(k in properties for k in keys):
            return kind
    raise ValueError(f"Variable non reconnue dans les propriétés : {sorted(properties.keys())}")


def read_export(path: Path) -> dict:
    """Lit un export GeoJSON de stations. Renvoie `{"kind", "date", "records"}` où `records` est
    une liste de `{"station", "latitude", "longitude", ...valeurs}` (un par station).

    Toutes les features doivent porter la même date et la même variable (un fichier = un jour =
    une variable) ; une incohérence lève `ValueError` plutôt que de mélanger silencieusement deux
    jours ou deux variables dans le même import."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    if not features:
        raise ValueError("Export vide (aucune feature).")

    kind = detect_kind(features[0]["properties"])
    date = features[0]["properties"].get("date")

    records = []
    for feat in features:
        props = feat["properties"]
        if detect_kind(props) != kind:
            raise ValueError(f"Variable incohérente dans le même fichier (station {props.get('stations')!r}).")
        if props.get("date") != date:
            raise ValueError(f"Date incohérente dans le même fichier (station {props.get('stations')!r}).")
        lon, lat = feat["geometry"]["coordinates"]
        record = {"station": props["stations"], "latitude": lat, "longitude": lon}
        for key in _KIND_KEYS[kind]:
            record[key] = props[key]
        records.append(record)

    return {"kind": kind, "date": date, "records": records}
