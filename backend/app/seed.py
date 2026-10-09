"""Données de référence créées au premier démarrage (uniquement si les tables sont vides).

Les messages de prévention et les libellés sont des PROPOSITIONS rédigées à partir des exemples
d'alertes de l'ANAM : à faire valider/corriger par l'ANAM (via le back-office, sans toucher au code).
Les contours GeoJSON des zones ne sont pas fournis : à charger depuis les fichiers de l'ANAM.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import COMMUNES
from .models_content import AlertType, PreventionMessage, Setting, Zone, ZoneKind

# Régions citées dans les alertes de l'ANAM (le rattachement aux communes des utilisateurs reste à renseigner)
SAMPLE_REGIONS = ["Liptako", "Goulmou", "Tapoa", "Nakambé", "Sirba"]

# Les 351 communes officielles du Burkina Faso (nom, région, province, coordonnées), source :
# OCHA/Institut Géographique du Burkina (data.humdata.org, limites administratives, admin niveau 3,
# valide au 01/08/2025) -- coordonnées réelles, pas des approximations. cf. module3/README.md pour
# le détail de la récupération. Sert à la fois à lister toutes les communes (F-à-préciser) et à
# donner au Module 3 (prévisions WRF) un point de grille pour chacune, pas seulement les 5 pilotes.
_COMMUNES_DATA_PATH = Path(__file__).parent / "data" / "burkina_communes.json"
# La source officielle orthographie différemment l'une des 5 communes pilotes : on garde
# l'orthographe déjà utilisée dans COMMUNES/models.py (users, tests...) pour ne pas la dédoubler.
_NAME_ALIASES = {"Ambsouya": "Absouya"}


def _load_all_communes() -> list[dict]:
    rows = json.loads(_COMMUNES_DATA_PATH.read_text(encoding="utf-8"))
    for row in rows:
        row["name"] = _NAME_ALIASES.get(row["name"], row["name"])
    return rows

ALERT_TYPES = [
    ("orages", "Orages", "Thunderstorms"),
    ("fortes_pluies", "Fortes pluies", "Heavy rain"),
    ("inondations", "Inondations", "Floods"),
    ("vents_violents", "Vents violents", "Strong winds"),
    ("poussiere", "Poussière", "Dust"),
    ("chaleur", "Chaleur", "Heat"),
    ("secheresse", "Sécheresse", "Drought"),
]

PREVENTION = {
    "orages": ["Évitez de vous abriter sous les arbres pendant les orages.",
               "Mettez-vous à l'abri dès les premiers coups de tonnerre."],
    "fortes_pluies": ["Évitez de traverser les routes ou les zones inondées.",
                      "Éloignez-vous des cours d'eau en crue."],
    "inondations": ["Évitez de traverser les zones inondées ou les cours d'eau en crue.",
                    "Rejoignez un endroit surélevé et suivez les consignes des autorités."],
    "vents_violents": ["Mettez-vous à l'abri dans un bâtiment solide et évitez les arbres isolés.",
                       "Rentrez ou fixez les objets susceptibles d'être emportés."],
    "poussiere": ["Limitez vos déplacements et protégez votre respiration avec un foulard ou un masque.",
                  "Fermez portes et fenêtres pendant l'épisode de poussière."],
    "chaleur": ["Buvez de l'eau régulièrement et évitez les efforts aux heures les plus chaudes.",
                "Protégez les enfants, les personnes âgées et le bétail."],
    "secheresse": ["Économisez l'eau et protégez vos réserves.",
                   "Suivez les conseils de l'ANAM pour adapter votre calendrier agricole."],
}

DEFAULT_SETTINGS: dict = {
    "platform.name": "ANAM-BF Agrométéo",
    "platform.default_language": "fr",
    "platform.source_citation": "Source : ANAM - Agence Nationale de la Météorologie du Burkina Faso",
    "alert.default_validity_hours": 24,
    # Canaux utilisés selon le type de contenu (le SMS est réservé aux alertes : il est payant)
    "diffusion.channels": {
        "alert": ["push", "sms", "email", "whatsapp"],
        "bulletin": ["push", "email", "whatsapp"],
        "advisory": ["push", "email"],
    },
    # Diffusion déclenchée automatiquement à la publication
    "diffusion.auto_broadcast": {"alert": True, "bulletin": True, "advisory": False},
    # Numéros WhatsApp (format international) qui reçoivent les diffusions via l'API WhatsApp Business
    "diffusion.whatsapp_recipients": [],
    "sms.max_length": 320,
    "sms.pilot_target": 500,  # objectif du pilote SMS (cahier des charges : 500 utilisateurs)
}


def get_setting(db: Session, key: str):
    row = db.get(Setting, key)
    return row.value if row is not None else DEFAULT_SETTINGS.get(key)


def all_settings(db: Session) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    merged.update({r.key: r.value for r in db.scalars(select(Setting))})
    return merged


def seed_reference_data(db: Session) -> None:
    if not db.scalar(select(func.count()).select_from(Zone)):
        pilot_names = set(COMMUNES)
        for row in _load_all_communes():
            db.add(Zone(name=row["name"], kind=ZoneKind.commune, is_pilot=row["name"] in pilot_names,
                       commune_names=[row["name"]], latitude=row["latitude"], longitude=row["longitude"]))
        for name in SAMPLE_REGIONS:
            db.add(Zone(name=name, kind=ZoneKind.region, is_pilot=False, commune_names=[]))
    if not db.scalar(select(func.count()).select_from(AlertType)):
        for code, fr, en in ALERT_TYPES:
            t = AlertType(code=code, label_fr=fr, label_en=en)
            db.add(t)
            db.flush()
            for text in PREVENTION[code]:
                db.add(PreventionMessage(alert_type_id=t.id, text_fr=text))
    db.commit()
