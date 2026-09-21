"""alert_parser.py — extrait le contenu d'une alerte météo ANAM (F1.6).

Contrairement aux bulletins (Module IA), une alerte n'est pas un PDF structuré
mais un texte WhatsApp libre (avec emojis, puces, liens) accompagné d'une seule
image (radar/satellite) — pas de logo ni de cartes ANAM à extraire, l'image est
déjà fournie telle quelle.

Format observé (2 échantillons réels, cf. samples/alerte1.txt, alerte2.txt) :

    🚨 ALERTE MÉTÉO DU <date> À <heure>

    ⛈️ SITUATION ACTUELLE / Situation météorologique
    <texte>

    ➡️ ÉVOLUTION ATTENDUE / Évolution attendue
    <texte>

    ⚠️ RISQUES ATTENDUS               (optionnelle)
    <puces>

    ⚠️ CONSEILS DE PRUDENCE / Conseils de sécurité
    <puces>

    📲🌐📱 liens et rappel "suivez nos publications"   (retiré : redondant avec
    notre propre formule de clôture, et les liens ne se lisent pas à l'oral)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Emojis / pictogrammes à retirer du texte avant narration (aucune information
# utile à l'oral). Couvre les blocs Unicode emoji usuels + le sélecteur FE0F.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002300-\U000023FF"
    "\U00002600-\U000027BF"
    "\U00002B00-\U00002BFF"
    "\U0001F1E6-\U0001F1FF"
    "️"
    "]+",
    flags=re.UNICODE,
)

_HEADER_RE = re.compile(
    r"ALERTE\s+M[ÉE]T[ÉE]O\s+DU?\s+(\d{1,2}\s+\S+\s+\d{4})\s+[ÀA]\s+(\d{1,2}\s*[hH]\s*\d{0,2})",
    re.IGNORECASE,
)

_SECTION_ORDER = ["situation", "evolution", "risques", "conseils"]
_SECTION_HEADERS = {
    "situation": re.compile(r"situation(?:\s+actuelle|\s+m[ée]t[ée]orologique)?\s*:?\s*$", re.IGNORECASE),
    "evolution": re.compile(r"[ée]volution(?:\s+attendue)?\s*:?\s*$", re.IGNORECASE),
    "risques": re.compile(r"risques?(?:\s+attendus)?\s*:?\s*$", re.IGNORECASE),
    "conseils": re.compile(r"conseils?\s+de\s+(?:prudence|s[ée]curit[ée])\s*:?\s*$", re.IGNORECASE),
}

_SKIP_LINE_RE = re.compile(r"https?://|www\.|whatsapp\.com|\bsuivez\b", re.IGNORECASE)


@dataclass
class Alert:
    date_text: str | None
    situation: str = ""
    evolution: str = ""
    conseils: list[str] = field(default_factory=list)
    conseils_intro: str | None = None
    risques: list[str] = field(default_factory=list)
    source_text: str = ""

    @property
    def has_risques(self) -> bool:
        return bool(self.risques)


def _clean_line(line: str) -> str:
    return _EMOJI_RE.sub("", line).strip(" \t>-•")


def parse_alert_text(raw_text: str) -> Alert:
    """Parse le texte brut d'une alerte (tel que collé depuis WhatsApp)."""
    date_text = None
    buckets: dict[str, list[str]] = {k: [] for k in _SECTION_ORDER}
    current: str | None = None

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _HEADER_RE.search(line)
        if m:
            date_text = f"{m.group(1)} à {m.group(2)}".lower()
            continue

        cleaned = _clean_line(line)
        if not cleaned:
            continue
        if _SKIP_LINE_RE.search(cleaned):
            continue

        matched = next((k for k in _SECTION_ORDER
                        if len(cleaned) < 60 and _SECTION_HEADERS[k].match(cleaned)), None)
        if matched:
            current = matched
            continue

        if current is None:
            current = "situation"
        buckets[current].append(cleaned)

    situation = " ".join(buckets["situation"])
    evolution = " ".join(buckets["evolution"])
    risques = list(buckets["risques"])

    conseils_lines = buckets["conseils"]
    conseils_intro = None
    conseils = conseils_lines
    # Si la 1re ligne de la section conseils est une phrase longue (pas une puce
    # courte), on la traite comme phrase d'introduction plutôt que comme conseil.
    if conseils_lines and len(conseils_lines[0]) > 80 and len(conseils_lines) > 1:
        conseils_intro, conseils = conseils_lines[0], conseils_lines[1:]

    return Alert(
        date_text=date_text,
        situation=situation,
        evolution=evolution,
        risques=risques,
        conseils_intro=conseils_intro,
        conseils=conseils,
        source_text=raw_text,
    )


def _strip_end(item: str) -> str:
    return item.rstrip(" .;!")


def _join_items(items: list[str]) -> str:
    return " ; ".join(_strip_end(i) for i in items) + "."


def alert_narration_fr(alert: Alert) -> str:
    """Construit le texte FR à traduire/synthétiser à partir de l'alerte extraite."""
    parts = []
    if alert.date_text:
        parts.append(f"Alerte météo du {alert.date_text}.")
    if alert.situation:
        parts.append(f"Situation actuelle : {alert.situation}")
    if alert.evolution:
        parts.append(f"Évolution attendue : {alert.evolution}")
    if alert.has_risques:
        parts.append("Risques attendus : " + _join_items(alert.risques))
    if alert.conseils:
        intro = f"{alert.conseils_intro} " if alert.conseils_intro else ""
        parts.append("Conseils de prudence : " + intro + _join_items(alert.conseils))
    return " ".join(parts)


def alert_narration_en(alert: Alert) -> str:
    """Version anglaise : intitulés fixes (MyMemory les traduit mal hors contexte,
    ex. "Évolution attendue" -> "Prospects for the IOC"), contenu traduit à la volée."""
    from french_tts import translate_long_fr_to_english as tr

    parts = []
    if alert.date_text:
        parts.append(f"Weather alert of {tr(alert.date_text)}.")
    if alert.situation:
        parts.append(f"Current situation: {tr(alert.situation)}")
    if alert.evolution:
        parts.append(f"Expected evolution: {tr(alert.evolution)}")
    if alert.has_risques:
        parts.append("Expected risks: " + _join_items([tr(r) for r in alert.risques]))
    if alert.conseils:
        intro = f"{tr(alert.conseils_intro)} " if alert.conseils_intro else ""
        parts.append("Safety advice: " + intro + _join_items([tr(c) for c in alert.conseils]))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Salutation d'ouverture et clôture spécifiques aux alertes (registre plus
# urgent/impératif que la formule de bienvenue des bulletins, cf.
# bulletin_parser.MOORE_INTRO/MOORE_OUTRO) — traductions NLLB, À FAIRE VALIDER
# PAR CITADEL/ANAM avant mise en production.
MOORE_ALERT_INTRO = "Gũus-y tɩ yaa nasaar tʋʋm-noor ning sẽn geta sa-gãongã yelle."
MOORE_ALERT_OUTRO = (
    "Kell-y n gũus-y la y tũ tõnd kibay nins sẽn watã sẽn na yɩl n paam kibay sẽn kẽed "
    "ne yellã. Gũus-y y mens neere."
)


def alert_narration_moore(alert: Alert, tclient=None) -> str:
    """Construit la narration mooré : formule d'ouverture/clôture "alerte" fixes
    + contenu variable traduit à la volée, phrase par phrase (même pipeline
    robuste que pour les bulletins, cf. moore_client.translate_long_fr_to_moore)."""
    from moore_client import TranslationClient, translate_long_fr_to_moore

    tclient = tclient or TranslationClient()
    parts = [MOORE_ALERT_INTRO]

    # La date n'est volontairement pas narrée : NLLB la traduit en charabia
    # ("Alerte météo du 09 septembre..." -> phrase incohérente), et l'ouverture
    # fixe annonce déjà qu'il s'agit d'une alerte.
    if alert.situation:
        parts.append(translate_long_fr_to_moore(alert.situation, tclient))
    if alert.evolution:
        parts.append(translate_long_fr_to_moore(alert.evolution, tclient))
    if alert.has_risques:
        risques_moore = [translate_long_fr_to_moore(r, tclient).rstrip(".") for r in alert.risques]
        parts.append(" ; ".join(risques_moore) + ".")
    if alert.conseils:
        if alert.conseils_intro:
            parts.append(translate_long_fr_to_moore(alert.conseils_intro, tclient))
        conseils_moore = [translate_long_fr_to_moore(c, tclient).rstrip(".") for c in alert.conseils]
        parts.append(" ; ".join(conseils_moore) + ".")

    parts.append(MOORE_ALERT_OUTRO)
    return " ".join(p for p in parts if p)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage : python alert_parser.py <alerte.txt>")
        sys.exit(1)

    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    alert = parse_alert_text(text)
    print("Date      :", alert.date_text)
    print("Situation :", alert.situation)
    print("Évolution :", alert.evolution)
    print("Risques   :", alert.risques if alert.has_risques else "(absents)")
    print("Conseils  :", alert.conseils_intro)
    for item in alert.conseils:
        print("            -", item)
    print()
    print("--- Narration FR ---")
    print(alert_narration_fr(alert))
