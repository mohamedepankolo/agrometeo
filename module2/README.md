# Module 2 — observations de stations météo (GeoJSON)

Relevés RÉELS des stations météo physiques de l'ANAM (pas une prévision modélisée comme le
Module 3, une mesure). Contrairement aux Modules 1 et 3, aucune dépendance lourde (netCDF4,
appels réseau) : les fichiers sont de petits GeoJSON (`FeatureCollection` de `Point`), lus avec
la seule bibliothèque standard (`json`).

## Ce qu'on a reçu

Trois fichiers, un par variable, reçus le 2026-10-13 pour la journée du **2026-10-08** :

| Fichier (convention de qui exporte, pas garantie) | Variable | Propriétés | Stations |
|---|---|---|---|
| `exporttemp.geojson` | Température | `tmin`, `tmax` (°C) | 88 |
| `exportrr.geojson` | Pluviométrie | `value` (mm, cumul du jour) | 96 |
| `exportrelhum.geojson` | Humidité relative | `umin`, `umax` (%) | 89 |

Chaque `Feature` : `geometry.coordinates` = `[longitude, latitude]`, `properties.stations` = nom
de la station, `properties.date` = `AAAA-MM-JJ`. La variable est déduite des clés présentes dans
`properties` (`module2.geojson_reader.detect_kind`), pas du nom de fichier.

## ⚠️ Qualité des données : à garder en tête

- **Pas les mêmes stations dans les trois fichiers.** Toutes les stations ne mesurent pas
  forcément les trois variables (88 à 96 selon le fichier) — une observation peut donc avoir
  des colonnes à `null` selon ce qui a été ingéré pour ce jour.
- **Doublons apparents avec légère variante d'orthographe/coordonnées**, probablement deux
  systèmes sources fusionnés (nom officiel accentué + coordonnées arrondies d'un côté, nom brut
  sans accent + coordonnées précises de l'autre) :
  - `Mane` *(-1.336212, 12.979133)* et `Mané` *(-1.3333, 12.9833)* dans `exportrr.geojson`
  - `Po` *(-1.1401, 11.165243)* et `Pô` *(-1.15, 11.1667)* dans `exporttemp.geojson` et
    `exportrelhum.geojson`
  - `Banfora` et `Banfora Agri` dans `exportrr.geojson` (ici sans doute deux stations
    distinctes dans la même ville, pas un doublon)

  Non fusionnés automatiquement à l'ingestion : chaque nom de station tel que fourni par l'ANAM
  devient sa propre `Station` (même principe que les communes pilotes du Module 3, qui gardent
  l'orthographe déjà en usage plutôt qu'une normalisation devinée). À signaler à l'ANAM si
  confirmé comme un doublon.
- **Même station, coordonnées légèrement différentes selon le fichier** : `Bobo-Dioulasso`
  apparaît avec deux couples de coordonnées (`-4.3, 11.1667` vs `-4.347839, 11.157519`) entre
  `exporttemp.geojson`/`exportrelhum.geojson` et ailleurs ; `Orodara` pareil dans
  `exportrr.geojson`. Sans conséquence pratique (quelques centaines de mètres d'écart) :
  l'ingestion garde les coordonnées de la **première** apparition de ce nom de station, les
  imports suivants ne les modifient pas.

## Intégration backend

- `backend/app/module2_bridge.py` — pont, même principe que `module1_bridge.py`/
  `module3_bridge.py`.
- `backend/app/observation_jobs.py` — ingestion (synchrone : un fichier fait ~20 Ko, pas besoin
  de tâche de fond comme pour les fichiers WRF du Module 3).
- `backend/app/routers/observations.py` — API : `GET /observations/incoming` (fichiers en
  attente), `POST /observations/ingest` (ingère un fichier), `GET /observations/stations`
  (référentiel des stations), `GET /observations` (relevés, public).
- Modèles `Station` (une par nom reçu de l'ANAM) et `StationObservation` (un relevé = une
  station pour un jour donné, colonnes remplies au fur et à mesure des imports) dans
  `backend/app/models_content.py`.

## Limites connues / à faire

- **Ingestion manuelle, un fichier à la fois** — même limite que le Module 3. Pas d'automatisation
  pour détecter l'arrivée d'un nouveau fichier et l'ingérer seul.
- **Pas de rattachement aux zones/communes du Module 3.** Une station météo n'est pas une
  commune (noms et nombre différents) : `Station` est un référentiel à part, pas une extension
  de `Zone`. Un futur rapprochement (station la plus proche d'une commune, par exemple pour
  comparer prévision WRF et relevé réel) resterait à faire à la demande, pas stocké.
- **Doublons de nom non résolus** (voir plus haut) : à clarifier avec l'ANAM plutôt qu'à deviner.
