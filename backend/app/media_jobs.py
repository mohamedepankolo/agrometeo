"""Tâches de fond : génération des audios/vidéos d'une alerte ou d'un bulletin.

Une génération dure 1 à 3 minutes : l'API répond tout de suite (`media_status = processing`) et le
client interroge le contenu jusqu'à `ready` ou `failed`. Deux générations au plus en parallèle
(ffmpeg + services de traduction/synthèse externes).
"""

from __future__ import annotations

import logging
import shutil
import threading

from . import module1_bridge as bridge
from . import storage
from .db import new_session
from .models_content import Alert, Bulletin, MediaStatus

log = logging.getLogger("backend.media")
_SLOTS = threading.Semaphore(2)


def _store_result(row, result: dict) -> None:
    row.texts = result["texts"]
    row.media = {lang: {"audio": storage.rel(f["audio"]), "video": storage.rel(f["video"])}
                 for lang, f in result["files"].items()}
    row.media_status = MediaStatus.ready
    # `ready` peut s'accompagner d'un avertissement : une langue n'a pas pu être générée
    skipped = result.get("skipped") or {}
    row.media_error = ("Langues non générées : " + " ; ".join(f"{lang} ({why})" for lang, why in skipped.items()))[:500] if skipped else None


def _run(model, content_id: str, generate) -> None:
    db = new_session()
    try:
        row = db.get(model, content_id)
        if row is None:
            return
        try:
            with _SLOTS:
                result = generate(row)
            _store_result(row, result)
        except Exception as exc:  # noqa: BLE001 — l'erreur est rapportée au client, pas perdue
            log.exception("génération des médias échouée (%s %s)", model.__tablename__, content_id)
            row.media_status = MediaStatus.failed
            row.media_error = f"{type(exc).__name__}: {exc}"[:500]
        db.commit()
    finally:
        db.close()


def run_alert_media(alert_id: str) -> None:
    def generate(alert: Alert):
        image = storage.absolute(alert.image_path)
        out_dir = storage.content_dir("alerts", alert.id) / "media"
        shutil.rmtree(out_dir, ignore_errors=True)
        return bridge.generate_alert_media(image, alert.raw_text, out_dir)

    _run(Alert, alert_id, generate)


def run_bulletin_media(bulletin_id: str) -> None:
    def generate(bulletin: Bulletin):
        pdf = storage.absolute(bulletin.pdf_path)
        out_dir = storage.content_dir("bulletins", bulletin.id) / "media"
        shutil.rmtree(out_dir, ignore_errors=True)
        return bridge.generate_bulletin_media(pdf, out_dir)

    _run(Bulletin, bulletin_id, generate)
