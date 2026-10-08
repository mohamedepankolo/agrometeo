# Module 3 — prévisions (fichiers WRF / NetCDF)

Lecture des fichiers de sortie du modèle **WRF** (Weather Research and Forecasting) fournis par
l'ANAM, et extraction d'un résumé journalier (température, précipitations, vent, humidité) pour
chaque zone (commune/région). Contrairement au Module 1, ce module ne fait aucun appel réseau :
lecture locale d'un fichier NetCDF, intégrée au backend via `backend/app/module3_bridge.py` (même
principe que `module1_bridge.py`).

## Ce qu'on a reçu

Trois fichiers (23, 24, 25 mai 2022), nommés `wrfout_d02_<AAAA-MM-JJ>_<HH:MM:SS>` — la convention
de nommage standard de WRF. Chacun :

- couvre **24 échéances horaires** (une journée complète) ;
- une grille de **400 × 300 points à 3 km de résolution** (domaine imbriqué `d02`), centrée sur
  12,68° N / -1,64° O (région de Ouagadougou, Burkina Faso) ;
- **242 variables** au total. Celles utilisées pour le résumé journalier par point :
  `T2` (température à 2 m), `Q2` (humidité spécifique à 2 m), `PSFC` (pression de surface),
  `U10`/`V10` (vent à 10 m), `RAINC`+`RAINNC` (précipitations cumulées depuis le début de la
  simulation — la pluie du jour est la différence entre la dernière et la première échéance du
  fichier) ;
- ~5 Go chacun. L'équipe en a reçu une trentaine au total (tous les fichiers n'ont pas pu être
  transférés en une fois, faute d'espace disque) — un répertoire `wrf_incoming/` à la racine du
  dépôt (jamais versionné, voir `.gitignore`) reçoit ceux à traiter.

## ⚠️ Piège Windows : les ':' dans le nom de fichier

La convention WRF met des `:` dans le nom (`..._01:00:00`). **Windows (NTFS/Win32) refuse ce
caractère**, à la création comme à l'ouverture d'un fichier — ce n'est pas propre à une clé USB :
même constat sur le disque système. Un fichier déposé par un outil Linux (ex. `ntfs-3g`) peut
exister sur le disque avec ces `:` et rester *listable*, mais aucune API Windows normale
(Python, PowerShell, `cmd`, `robocopy`...) ne peut l'ouvrir ; seul un outil lisant le volume en
brut (ex. `7z l/x \\.\<lettre>:`) y parvient.

**Avant de placer un fichier wrfout dans `wrf_incoming_dir` sur un serveur Windows**, renommez-le
en remplaçant les `:` par des `-` (ex. `wrfout_d02_2022-05-23_01-00-00`). Un serveur Linux n'a pas
cette contrainte (ext4 et la plupart des systèmes de fichiers Linux acceptent les `:`).

## `wrf_reader.py`

Fonctions pures (pas de base de données, pas d'API) :

- `open_wrf(path)` — ouvre le fichier (import de `netCDF4` différé : pas besoin de l'installer
  si le Module 3 n'est pas utilisé).
- `run_date(ds)` — jour couvert (lu dans la variable `Times`, pas dans le nom du fichier).
- `daily_summary_at_point(ds, lat, lon)` — résumé journalier au point de grille le plus proche
  de `(lat, lon)` : min/max/moyenne de température, pluie du jour, vent moyen/max, humidité
  relative moyenne. La distance réelle au point de grille utilisé (`distance_km`) est renvoyée :
  une valeur élevée signale un point hors du domaine couvert par le fichier (grille à 3 km :
  `backend` ignore une zone au-delà de `wrf_max_distance_km`, 15 km par défaut).
- `daily_summaries(path, points)` — plusieurs points en un seul passage sur le fichier
  (`{clé: (lat, lon)}` -> `{clé: résumé}`).

L'humidité relative est calculée à partir de `T2`/`Q2`/`PSFC` par la formule de Magnus (approche
standard en post-traitement WRF, ex. NCL/wrf-python) — WRF ne fournit pas directement l'humidité
relative à 2 m dans cette sortie.

## Intégration backend

- `backend/app/module3_bridge.py` — pont (ajoute ce dossier à `sys.path`, pattern identique à
  `module1_bridge.py`).
- `backend/app/forecast_jobs.py` — tâche de fond : ouvre un fichier, extrait le résumé pour
  chaque zone qui a des coordonnées, enregistre les résultats.
- `backend/app/routers/forecasts.py` — API : `GET /forecasts/incoming` (fichiers en attente),
  `POST /forecasts/ingest` (lance l'extraction), `GET /forecasts/runs[/{id}]` (suivi),
  `GET /forecasts` (résultats par zone, public).
- Modèles `ForecastRun` (une ingestion = un fichier) et `ZoneForecast` (un résumé = une zone pour
  un jour donné) dans `backend/app/models_content.py`.

## Limites connues / à faire

- **Extraction par point, pas par polygone.** Les zones n'ont pour l'instant que des coordonnées
  ponctuelles (voir `backend/app/seed.py`, `COMMUNE_COORDS` — approximatives, domaine public, en
  attendant les coordonnées précises de l'ANAM). Une fois les contours GeoJSON des zones fournis
  (`Zone.geometry`), une moyenne sur tous les points de grille à l'intérieur du polygone serait
  plus représentative qu'un point unique — nécessiterait `shapely` (pas encore une dépendance).
- **Un fichier = un jour, ingestion manuelle.** Pas encore d'automatisation pour traiter en bloc
  la trentaine de fichiers reçus (une simple boucle sur `POST /forecasts/ingest` suffirait, mais
  n'a pas été scriptée — l'équipe n'a pour l'instant que 3 fichiers de test en local).
- Variables non exploitées : les 242 du fichier n'ont pas toutes un intérêt pour un bulletin
  (profils verticaux, variables de microphysique...) ; T2/Q2/PSFC/U10/V10/RAINC/RAINNC couvrent
  l'essentiel d'un résumé journalier grand public.
