"""Mise en forme des messages diffusés : notification push, SMS, e-mail, et texte WhatsApp prêt à publier.

Le mooré n'a pas de résumé court fiable (la traduction automatique se relit avant diffusion) :
les messages courts (push, SMS) retombent sur le français si la version mooré n'existe pas.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import storage
from .content_views import alert_zones, prevention_for, source_citation
from .models_content import Alert, AlertType
from .seed import get_setting

_LEVEL_EMOJI = {"jaune": "🟡", "orange": "🟠", "rouge": "🔴"}
_LEVEL_LABEL = {"fr": "NIVEAU", "en": "LEVEL", "mos": "NIVEAU"}


def _label(t: AlertType, lang: str) -> str:
    return getattr(t, f"label_{lang}", None) or t.label_fr


def _prevention_text(db: Session, alert: Alert, lang: str) -> str | None:
    items = prevention_for(db, alert.alert_type_id)
    if not items:
        return None
    return getattr(items[0], f"text_{lang}", None) or items[0].text_fr


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _first_sentence(text: str, limit: int) -> str:
    """Première phrase complète (les messages courts ne doivent pas s'arrêter au milieu d'une info)."""
    text = " ".join(text.split())
    end = text.find(". ")
    first = text[: end + 1] if 0 < end < limit else text
    return _clip(first, limit)


def _media_urls(row, lang: str) -> dict:
    f = (row.media or {}).get(lang) or {}
    return {"audio": storage.media_url(f.get("audio")), "video": storage.media_url(f.get("video"))}


# ------------------------------------------------------------------ push / SMS / e-mail
def render(db: Session, content_type: str, content, lang: str, channel: str) -> tuple[str, str, dict]:
    """(titre, corps, données) du message pour un canal et une langue."""
    data = {"content_type": content_type, "content_id": content.id}
    citation = source_citation(db)

    if content_type == "alert":
        t = db.get(AlertType, content.alert_type_id)
        title = f"ALERTE {content.level.value.upper()} - {_label(t, lang)}"
        advice = _prevention_text(db, content, lang)
        if channel == "email":
            body = (content.texts or {}).get(lang) or content.raw_text
            urls = _media_urls(content, lang)
            links = "\n".join(u for u in (urls["video"], urls["audio"]) if u)
            return title, f"{title}\n\n{body}" + (f"\n\n{links}" if links else "") + f"\n\n{citation}", data
        summary = _first_sentence((content.parsed or {}).get("situation") or content.raw_text, 150)
        body = f"{summary} {advice or ''}".strip()
        if channel == "sms":
            limit = int(get_setting(db, "sms.max_length") or 320)
            return title, _clip(f"ANAM {title}. {body} - ANAM", limit), data
        return title, _clip(body, 240), data

    if content_type == "bulletin":
        when = content.date_text or ""
        title = {"fr": "Bulletin agrométéorologique", "en": "Agrometeorological bulletin"}.get(lang, "Bulletin agrométéorologique")
        if channel == "email":
            body = (content.texts or {}).get(lang) or (content.texts or {}).get("fr") or ""
            urls = _media_urls(content, lang)
            links = "\n".join(u for u in (urls["video"], urls["audio"]) if u)
            return f"{title} - {when}", f"{title} - {when}\n\n{body}" + (f"\n\n{links}" if links else "") + f"\n\n{citation}", data
        text = {"fr": f"Le bulletin du {when} est disponible.", "en": f"The bulletin of {when} is available."}
        return title, text.get(lang, text["fr"]), data

    # avis
    title = getattr(content, f"title_{lang}", None) or content.title_fr
    body = getattr(content, f"body_{lang}", None) or content.body_fr
    if channel == "email":
        return title, f"{title}\n\n{body}\n\n{citation}", data
    return title, _clip(body, 240), data


# ------------------------------------------------------------------ kit de partage (WhatsApp)
def _bullets(items: list[str]) -> str:
    return "\n".join(f"• {i.rstrip('.')}" for i in items)


def _alert_text_fr(db: Session, alert: Alert) -> str:
    t = db.get(AlertType, alert.alert_type_id)
    zones = ", ".join(z.name for z in alert_zones(db, alert.id))
    p = alert.parsed or {}
    lines = [f"🚨 *ALERTE MÉTÉO - NIVEAU {alert.level.value.upper()}* {_LEVEL_EMOJI[alert.level.value]}",
             f"*{t.label_fr}*" + (f" · valable jusqu'au {alert.valid_until:%d/%m/%Y à %Hh%M} (UTC)" if alert.valid_until else "")]
    if zones:
        lines.append(f"📍 *Zones concernées :* {zones}")
    if p.get("situation") or p.get("evolution") or p.get("risques") or p.get("conseils"):
        if p.get("situation"):
            lines += ["", "⛈️ *Situation actuelle*", p["situation"]]
        if p.get("evolution"):
            lines += ["", "➡️ *Évolution attendue*", p["evolution"]]
        if p.get("risques"):
            lines += ["", "⚠️ *Risques attendus*", _bullets(p["risques"])]
        if p.get("conseils"):
            lines += ["", "✅ *Conseils de prudence*"] + ([p["conseils_intro"]] if p.get("conseils_intro") else []) + [_bullets(p["conseils"])]
    else:
        lines += ["", alert.raw_text.strip()]
    return "\n".join(lines)


def share_kit(db: Session, content_type: str, content) -> dict:
    """Texte formaté (gras WhatsApp avec *…*) + liens médias, par langue. Sert au partage manuel de secours
    et de modèle pour la diffusion automatique."""
    citation = source_citation(db)
    texts, media = {}, {}
    for lang in ("fr", "en", "mos"):
        urls = _media_urls(content, lang) if content_type != "advisory" else {"audio": None, "video": None}
        media[lang] = urls
        if content_type == "alert":
            if lang == "fr":
                body = _alert_text_fr(db, content)
            else:
                t = db.get(AlertType, content.alert_type_id)
                narration = (content.texts or {}).get(lang) or ""
                body = (f"🚨 *{_label(t, lang).upper()} - {_LEVEL_LABEL[lang]} {content.level.value.upper()}* "
                        f"{_LEVEL_EMOJI[content.level.value]}\n\n{narration}").strip()
        elif content_type == "bulletin":
            narration = (content.texts or {}).get(lang) or (content.texts or {}).get("fr") or ""
            body = f"🌦️ *Bulletin agrométéorologique - {content.date_text or ''}*\n\n{narration}"
        else:
            title = getattr(content, f"title_{lang}", None) or content.title_fr
            body = f"📢 *{title}*\n\n{getattr(content, f'body_{lang}', None) or content.body_fr}"
        extras = []
        if urls["video"]:
            extras.append(f"🎬 Vidéo : {urls['video']}")
        if urls["audio"]:
            extras.append(f"🎧 Audio : {urls['audio']}")
        texts[lang] = body + ("\n\n" + "\n".join(extras) if extras else "") + f"\n\n_{citation}_"
    image = storage.media_url(content.image_path) if content_type == "alert" else None
    return {"text": texts, "media": media, "image_url": image,
            "note": "Copiez le texte dans le groupe ou la chaîne WhatsApp et joignez la vidéo ou l'image. "
                    "Les liens ne sont valables que si PUBLIC_BASE_URL est renseigné."}
