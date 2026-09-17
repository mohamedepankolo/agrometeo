"""bulletin_parser.py — extrait les sections d'un bulletin PDF ANAM/RECLIM (F1.1 / F1.2).

Format des bulletins spécifiques RECLIM (cf. cahier des charges, section 6.1) :

    1. Le temps observé au cours des dernières 24 heures
    2. Prévisions valables jusqu'à demain 12 heures
    3. Avis et conseils agrométéorologiques        (optionnelle — absente sur certains bulletins)

Chaque section "temps" est accompagnée d'une carte (image) ; la légende
"Ci-contre, la carte ..." est retirée du texte car elle ne porte aucune
information utile à la restitution audio.

Dépendance : pdfplumber  ->  pip install pdfplumber
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

HEADER_OBSERVE = re.compile(r"1\.\s*Le temps observ[ée][^\n]*\n?", re.IGNORECASE)
HEADER_PREVISION = re.compile(r"2\.\s*Pr[ée]visions valables[^\n]*\n?", re.IGNORECASE)
HEADER_AVIS = re.compile(r"3\.\s*Avis et conseils agrom[ée]t[ée]orologiques[^\n]*\n?", re.IGNORECASE)

# Date réelle du bulletin (corps du document). À distinguer de la date figée
# du cartouche d'en-tête ("Date : 29 octobre 2024"), reconnaissable au fait
# qu'elle n'est jamais suivie de "à ... h".
DATE_RE = re.compile(r"Date\s*:\s*(\d{1,2}\s+\S+\s+\d{4})\s*[àa]\s*(\d{1,2})\s*h", re.IGNORECASE)

# Lignes de cartouche/pied de page répétées sur chaque page, à ignorer.
BOILERPLATE_LINE_RES = [
    re.compile(r"^BULLETIN\s+R[ée]f\s*:.*$", re.IGNORECASE),
    re.compile(r"^Date\s*:\s*\d{1,2}\s+\S+\s+\d{4}\s*$", re.IGNORECASE),
    re.compile(r"^AGROMETEOROLOGIQUE SPECIFIQUE\s+Page\s*:.*$", re.IGNORECASE),
    re.compile(r"^AGENCE NATIONALE DE LA M[ÉE]T[ÉE]OROLOGIE\s*$", re.IGNORECASE),
]
# Légende de carte ("Ci-contre, la carte ... .") : peut s'étaler sur plusieurs
# lignes une fois extraite du PDF ; on la retire après avoir rejoint les lignes.
CAPTION_RE = re.compile(r"Ci-contre[^.]*\.?", re.IGNORECASE)


@dataclass
class Bulletin:
    date_text: str | None          # ex : "13 Septembre 2026 à 12 h"
    observed: str                  # section 1, texte nettoyé
    forecast: str                  # section 2, texte nettoyé
    advice_intro: str | None = None    # phrase d'introduction de la section 3, si présente
    advice: list[str] = field(default_factory=list)   # puces de la section 3, liste vide si absente
    source_path: Path | None = None

    @property
    def has_advice(self) -> bool:
        return bool(self.advice)


def _useful_lines(text: str) -> list[str]:
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(p.match(line) for p in BOILERPLATE_LINE_RES):
            continue
        lines.append(line)
    return lines


def _clean_block(text: str) -> str:
    joined = " ".join(_useful_lines(text))
    joined = CAPTION_RE.sub("", joined)
    return re.sub(r"\s{2,}", " ", joined).strip()


def _extract_advice(text: str) -> tuple[str | None, list[str]]:
    joined = " ".join(_useful_lines(text))
    chunks = re.split(r"➢", joined)
    intro = chunks[0].strip() or None
    items = [c.strip(" ;.") for c in chunks[1:] if c.strip(" ;.")]
    return intro, items


def extract_text(pdf_path: str | Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def extract_bulletin_images(pdf_path: str | Path, out_dir: str | Path | None = None,
                            resolution: int = 200) -> dict[str, Path]:
    """F1.4 : extrait du bulletin les 2 cartes (observé + prévisions) et le logo
    ANAM/météo Burkina en 3 fichiers séparés, en rognant le rendu de la page 1
    aux coordonnées des images embarquées.

    Heuristique (constatée sur les bulletins RECLIM) : les 2 plus grandes images
    de la page sont les cartes, triées par position verticale (la plus haute =
    section "temps observé", la plus basse = section "prévisions") ; parmi les
    images restantes, nettement plus petites, la plus haute sur la page est le
    logo (cartouche en haut de page)."""
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir) if out_dir else pdf_path.parent
    stem = pdf_path.stem

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        rendered = page.to_image(resolution=resolution)
        scale = resolution / 72

        images = sorted(page.images, key=lambda im: (im["x1"] - im["x0"]) * (im["y1"] - im["y0"]), reverse=True)
        if len(images) < 2:
            raise ValueError(f"Moins de 2 images trouvées sur la page 1 de {pdf_path.name}.")
        maps = sorted(images[:2], key=lambda im: im["top"])
        others = images[2:]

        def _crop(img: dict, out_name: str) -> Path:
            box = (img["x0"] * scale, img["top"] * scale, img["x1"] * scale, img["bottom"] * scale)
            out_path = out_dir / out_name
            rendered.original.crop(box).save(out_path)
            return out_path

        result = {
            "carte_observee": _crop(maps[0], f"{stem}_carte_observee.png"),
            "carte_prevision": _crop(maps[1], f"{stem}_carte_prevision.png"),
        }
        if others:
            logo_img = min(others, key=lambda im: im["top"])
            result["logo"] = _crop(logo_img, f"{stem}_logo.png")

    return result


def parse_bulletin(pdf_path: str | Path) -> Bulletin:
    """Parse un bulletin PDF RECLIM et renvoie ses sections structurées."""
    pdf_path = Path(pdf_path)
    full_text = extract_text(pdf_path)

    date_match = DATE_RE.search(full_text)
    date_text = f"{date_match.group(1)} à {date_match.group(2)} h" if date_match else None

    m_observe = HEADER_OBSERVE.search(full_text)
    m_prevision = HEADER_PREVISION.search(full_text)
    m_avis = HEADER_AVIS.search(full_text)

    if not m_observe or not m_prevision:
        raise ValueError(f"Sections 1/2 introuvables dans {pdf_path.name} — format inattendu.")

    observed_raw = full_text[m_observe.end(): m_prevision.start()]
    if m_avis:
        forecast_raw = full_text[m_prevision.end(): m_avis.start()]
        advice_raw = full_text[m_avis.end():]
        advice_intro, advice = _extract_advice(advice_raw)
    else:
        forecast_raw = full_text[m_prevision.end():]
        advice_intro, advice = None, []

    return Bulletin(
        date_text=date_text,
        observed=_clean_block(observed_raw),
        forecast=_clean_block(forecast_raw),
        advice_intro=advice_intro,
        advice=advice,
        source_path=pdf_path,
    )


def bulletin_narration_fr_parts(bulletin: Bulletin) -> list[tuple[str, str]]:
    """Narration FR découpée par section : [("observee", texte), ("prevision", texte),
    ("conseils", texte)?]. Une image différente est associée à chaque partie pour la
    vidéo (F1.4) ; la version "audio complet" (bulletin_narration_fr) n'est que la
    concaténation de ces parties."""
    intro = f"Bulletin agrométéorologique du {bulletin.date_text}. " if bulletin.date_text else ""
    parts = [
        ("observee", f"{intro}Temps observé au cours des dernières 24 heures : {bulletin.observed}"),
        ("prevision", f"Prévisions pour les prochaines 24 heures : {bulletin.forecast}"),
    ]
    if bulletin.has_advice:
        advice_intro = f"{bulletin.advice_intro} " if bulletin.advice_intro else ""
        parts.append(("conseils", "Avis et conseils agrométéorologiques : "
                                   + advice_intro + " ; ".join(bulletin.advice) + "."))
    return parts


def bulletin_narration_fr(bulletin: Bulletin) -> str:
    """Construit le texte FR à traduire/synthétiser à partir des sections extraites."""
    return " ".join(text for _, text in bulletin_narration_fr_parts(bulletin))


def bulletin_narration_en_parts(bulletin: Bulletin) -> list[tuple[str, str]]:
    """Narration anglaise découpée par section (même structure que la FR),
    traduite phrase par phrase via MyMemory (cf. french_tts.py)."""
    from french_tts import translate_long_fr_to_english

    return [(name, translate_long_fr_to_english(text)) for name, text in bulletin_narration_fr_parts(bulletin)]


# ---------------------------------------------------------------------------
# Phrases-titres récurrentes (identiques d'un bulletin RECLIM à l'autre) :
# figées une bonne fois pour toutes plutôt que retraduites à chaque bulletin,
# pour une qualité/cohérence audio constante. Traductions initiales obtenues
# via le service NLLB — À FAIRE VALIDER PAR UN LOCUTEUR NATIF avant mise en
# production (cf. cahier des charges §8.3 : critère de qualité audio).
_KNOWN_ADVICE_INTRO_FR = (
    "Compte tenu des conditions météorologiques passées et des prévisions du temps, "
    "il est recommandé aux productrices et producteurs"
)

MOORE_LABEL_OBSERVED = "Zĩ-kãnga sẽn maan lɛɛr pisi la naas sẽn looge:"
MOORE_LABEL_FORECAST = "Wakat pissi la a naas sẽn wate:"
MOORE_LABEL_ADVICE = "Gʋlsg sẽn kẽed ne koobã la sa-gãongã wɛɛngẽ:"
MOORE_ADVICE_INTRO = "Sãn n yaa ne sa-gãonga sẽn zĩnd pĩndã, b sagenda koaadbã:"

# Salutation d'ouverture et formule de clôture. Confirmées comme quasi identiques
# sur 10 bulletins audio RECLIM réels distincts (salutation/paix, citation de la
# source ANAM, bénédiction de clôture) — cf. reference_pairs/transcripts/. Le texte
# mooré ci-dessous n'est PAS celui de ces enregistrements (trop bruité par l'ASR
# pour être fiable) mais une reconstruction FR propre traduite via le même canal
# NLLB validé que le reste — À FAIRE VALIDER PAR CITADEL/ANAM (idéalement avec leur
# texte officiel exact) avant mise en production.
MOORE_INTRO = (
    "Ne-y fãa ne y laafɩ. Ad kibay nins sẽn yi Burkĩna Faso nao-kẽndr ning sẽn geta "
    "sa-gãonga yellã sẽn yiis moore. Tõnd sũur yaa noogo, d sẽn paam yãmb rũndã wã."
)
MOORE_OUTRO = "Yaa woto la tõnd rũndã kibayã sa. Wa-y beoogo ne kibay a taaba. Bɩ laafɩ zĩnd ne yãmba."


def bulletin_narration_moore_parts(bulletin: Bulletin, tclient=None) -> list[tuple[str, str]]:
    """Narration mooré découpée par section, même principe que bulletin_narration_fr_parts
    (une image différente par partie pour la vidéo). L'intro va sur la 1re partie
    ("observee"), l'outro sur la dernière ("conseils" si présente, sinon "prevision")."""
    from moore_client import TranslationClient, translate_long_fr_to_moore

    tclient = tclient or TranslationClient()

    observed_text = MOORE_INTRO
    if bulletin.date_text:
        observed_text += " " + translate_long_fr_to_moore(f"Bulletin agrométéorologique du {bulletin.date_text}.", tclient)
    observed_text += " " + MOORE_LABEL_OBSERVED + " " + translate_long_fr_to_moore(bulletin.observed, tclient)

    forecast_text = MOORE_LABEL_FORECAST + " " + translate_long_fr_to_moore(bulletin.forecast, tclient)

    parts = [("observee", observed_text)]

    if bulletin.has_advice:
        parts.append(("prevision", forecast_text))

        advice_text = MOORE_LABEL_ADVICE
        intro_fr = (bulletin.advice_intro or "").rstrip(" :")
        if intro_fr == _KNOWN_ADVICE_INTRO_FR:
            advice_text += " " + MOORE_ADVICE_INTRO
        elif bulletin.advice_intro:
            advice_text += " " + translate_long_fr_to_moore(bulletin.advice_intro, tclient)
        items_moore = [translate_long_fr_to_moore(item, tclient).rstrip(".") for item in bulletin.advice]
        advice_text += " " + " ; ".join(items_moore) + "."
        advice_text += " " + MOORE_OUTRO
        parts.append(("conseils", advice_text))
    else:
        forecast_text += " " + MOORE_OUTRO
        parts.append(("prevision", forecast_text))

    return parts


def bulletin_narration_moore(bulletin: Bulletin, tclient=None) -> str:
    """Construit la narration mooré : phrases-titres fixes (validées une fois)
    + contenu variable du bulletin traduit à la volée, phrase par phrase.
    Évite de retraduire (et donc de risquer une dégradation de qualité sur)
    les mêmes phrases-titres à chaque bulletin."""
    return " ".join(text for _, text in bulletin_narration_moore_parts(bulletin, tclient))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage : python bulletin_parser.py <bulletin.pdf>")
        sys.exit(1)

    b = parse_bulletin(sys.argv[1])
    print("Date      :", b.date_text)
    print("Observé   :", b.observed)
    print("Prévision :", b.forecast)
    if b.has_advice:
        print("Conseils  :", b.advice_intro)
        for item in b.advice:
            print("            -", item)
    else:
        print("Conseils  : (absents de ce bulletin)")
    print()
    print("--- Narration FR ---")
    print(bulletin_narration_fr(b))
