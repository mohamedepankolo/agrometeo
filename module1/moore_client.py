"""
moore_client.py — clients pour les services langue mooré de CITADEL.

Deux services distincts sont enveloppés :

1) TRADUCTION texte <-> texte (FR <-> mooré), plateforme "playground" CITADEL.
   - Login : POST /translation/api/auth/login  -> token Bearer
   - Usage : POST /translation/api/translate   (modèle NLLB)

2) PAROLE (TTS / ASR / S2ST) en mooré, service séparé (cf. notebook du collègue).
   - Bearer token (s2s_pat_...) fourni par les admins.

Le module 1 (audio des bulletins) enchaîne : texte FR -> [traduction] -> texte
mooré -> [TTS] -> audio.

Configuration par variables d'environnement (ne jamais coder les secrets en dur) :

    # Traduction (plateforme playground)
    CITADEL_TRANSLATE_URL   defaut https://playground.citadel.bf/translation
    CITADEL_API_EMAIL       ex: citadel.api.user@citadel.bf
    CITADEL_API_PASSWORD    ex: ********   (creds de test dans le guide CITADEL)

    # Parole (TTS/ASR/S2S)
    MOORE_API_BASE_URL      ex: https://xxxx.ngrok-free.dev  (URL STABLE en prod)
    MOORE_API_TOKEN         s2s_pat_...

Dépendance : requests  ->  pip install requests
"""

from __future__ import annotations

import base64
import mimetypes
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

DEFAULT_TIMEOUT = 60  # secondes


class MooreApiError(RuntimeError):
    """Erreur de transport HTTP ou réponse inattendue d'un service."""


_RETRY_ATTEMPTS = 4
_RETRY_BASE_DELAY_S = 2.0


def _post_with_retry(url: str, **kwargs) -> requests.Response:
    """requests.post avec retry + backoff sur les coupures réseau (connexion
    réinitialisée, timeout) — les services CITADEL/ngrok en produisent
    régulièrement. Les erreurs HTTP (4xx/5xx) ne sont pas rejouées."""
    import time

    # Un fichier ouvert (ASR/S2S) est consommé par le 1er envoi : pas de retry.
    attempts = 1 if "files" in kwargs else _RETRY_ATTEMPTS
    for attempt in range(attempts):
        try:
            return requests.post(url, **kwargs)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == attempts - 1:
                raise
            time.sleep(_RETRY_BASE_DELAY_S * (2 ** attempt))


def _first(data, keys):
    """Renvoie la 1re valeur non vide parmi `keys` dans un dict (gère {'data': {...}})."""
    if isinstance(data, dict):
        for k in keys:
            if data.get(k):
                return data[k]
        if isinstance(data.get("data"), dict):
            return _first(data["data"], keys)
    return None


# =====================================================================
#  1) TRADUCTION texte FR <-> mooré (plateforme playground CITADEL)
# =====================================================================
@dataclass
class TranslationClient:
    base_url: str = os.environ.get("CITADEL_TRANSLATE_URL", "https://playground.citadel.bf/translation")
    email: str = os.environ.get("CITADEL_API_EMAIL", "")
    password: str = os.environ.get("CITADEL_API_PASSWORD", "")
    timeout: int = 30
    _token: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.email or not self.password:
            raise ValueError("CITADEL_API_EMAIL / CITADEL_API_PASSWORD manquants (variables d'env).")

    def login(self) -> str:
        """Authentifie et met en cache le token Bearer."""
        url = f"{self.base_url}/api/auth/login"
        try:
            r = _post_with_retry(url, json={"email": self.email, "password": self.password}, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise MooreApiError(f"Échec du login {url} : {exc}") from exc
        data = r.json()
        token = _first(data, ["access_token", "token", "accessToken", "jwt"])
        if not token:
            raise MooreApiError(f"Token introuvable dans la réponse de login (clés: {list(data) if isinstance(data, dict) else type(data)}).")
        self._token = token
        return token

    def _auth(self) -> dict:
        if not self._token:
            self.login()
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def translate(self, text: str, source_lang: str = "french",
                  target_lang: str = "moore", model_type: str = "nllb",
                  _retry: bool = True) -> str:
        """Traduit `text`. Renvoie la chaîne traduite.
        Ré-authentifie automatiquement une fois sur 401 (token expiré)."""
        if not text or not text.strip():
            return ""
        url = f"{self.base_url}/api/translate"
        payload = {"text": text, "source_lang": source_lang, "target_lang": target_lang, "model_type": model_type}
        try:
            r = _post_with_retry(url, json=payload, headers=self._auth(), timeout=self.timeout)
            if r.status_code == 401 and _retry:
                self.login()
                return self.translate(text, source_lang, target_lang, model_type, _retry=False)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise MooreApiError(f"Échec de la traduction : {exc}") from exc
        data = r.json()
        out = _first(data, ["translation", "translated_text", "result", "text", "output"])
        if out is None:
            raise MooreApiError(f"Texte traduit introuvable dans la réponse (clés: {list(data) if isinstance(data, dict) else type(data)}).")
        return out

    # raccourcis
    def fr_to_moore(self, text: str) -> str:
        # MOORE_MODEL_TYPE : à basculer entre "nllb" (actuel) et "nllb2" une fois la comparaison
        # validée par un locuteur natif (les deux donnent des traductions différentes, cf. tests).
        return self.translate(text, "french", "moore", model_type=os.environ.get("MOORE_MODEL_TYPE", "nllb"))

    def moore_to_fr(self, text: str) -> str:
        return self.translate(text, "moore", "french")


# =====================================================================
#  2) PAROLE : TTS / ASR / S2ST en mooré (service séparé)
# =====================================================================
@dataclass
class MooreClient:
    base_url: str = os.environ.get("MOORE_API_BASE_URL", "")
    token: str = os.environ.get("MOORE_API_TOKEN", "")
    timeout: int = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("MOORE_API_BASE_URL manquant.")
        if not self.token:
            raise ValueError("MOORE_API_TOKEN manquant (jeton s2s_pat_...).")
        self.base_url = self.base_url.rstrip("/")

    @property
    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def _post(self, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        try:
            r = _post_with_retry(url, headers=self._auth, timeout=self.timeout, **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            raise MooreApiError(f"Échec de l'appel {url} : {exc}") from exc

    def tts_moore(self, text_moore: str, out_path="tts_output.wav") -> Path:
        """Texte DÉJÀ en mooré -> audio .wav."""
        if not text_moore.strip():
            raise ValueError("Texte vide.")
        r = self._post("/api/tts_moore", data={"text": text_moore})
        out = Path(out_path)
        out.write_bytes(r.content)
        return out

    def asr_moore(self, audio_path) -> str:
        """Audio mooré -> texte mooré."""
        p = Path(audio_path)
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        with p.open("rb") as f:
            r = self._post("/api/asr_moore", files={"audio": (p.name, f, mime)})
        return r.json().get("transcription", "")

    def s2s(self, audio_path, lang_src: str, out_path="s2s_output.wav") -> dict:
        """Traduction parole-à-parole. lang_src = 'mos' (mos->fra) ou 'fra' (fra->mos)."""
        if lang_src not in {"mos", "fra"}:
            raise ValueError("lang_src doit être 'mos' ou 'fra'.")
        p = Path(audio_path)
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        with p.open("rb") as f:
            r = self._post("/api/s2s", data={"lang_src": lang_src}, files={"audio": (p.name, f, mime)})
        data = r.json()
        out = Path(out_path)
        out.write_bytes(base64.b64decode(data["audio_b64"]))
        return {"transcript": data.get("transcript", ""), "translation": data.get("translation", ""), "audio_path": out}


# =====================================================================
#  MODULE 1 : bulletin FR -> texte mooré -> audio mooré
# =====================================================================
# Le service TTS échoue (500) au-delà d'une certaine limite qui ne dépend pas
# que du nombre de caractères : un bloc de 780 caractères (phrases complètes)
# passe, mais un bloc de 806 caractères composé de nombreux items séparés par
# " ; " échoue alors que chaque item pris seul fonctionne (testé empiriquement).
# Le nombre de segments/clauses semble aussi compter, pas seulement la longueur.
# On découpe donc à la fois sur la ponctuation forte ET sur les points-virgules,
# avec une marge de sécurité réduite, puis on recolle les .wav produits.
_TTS_MAX_CHARS = 500


def _split_for_tts(text_moore: str) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+", text_moore.strip()) if s.strip()]
    blocks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > _TTS_MAX_CHARS and current:
            blocks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        blocks.append(current)
    return blocks


def _concat_wavs(paths: list[Path], out_path: Path) -> Path:
    import wave

    with wave.open(str(paths[0]), "rb") as first:
        params = first.getparams()
        frames = [first.readframes(first.getnframes())]
    for p in paths[1:]:
        with wave.open(str(p), "rb") as w:
            frames.append(w.readframes(w.getnframes()))
    with wave.open(str(out_path), "wb") as out:
        out.setparams(params)
        for f in frames:
            out.writeframes(f)
    return out_path


def tts_moore_long(text_moore: str, out_path="tts_output.wav", sclient: MooreClient | None = None) -> Path:
    """Synthèse vocale d'un texte mooré long : découpe en blocs sous la limite du
    service TTS puis recolle les audios en un seul fichier."""
    sclient = sclient or MooreClient()
    blocks = _split_for_tts(text_moore)
    if len(blocks) <= 1:
        return sclient.tts_moore(text_moore, out_path=out_path)

    import tempfile

    tmp_paths: list[Path] = []
    try:
        for i, block in enumerate(blocks):
            tmp = Path(tempfile.gettempdir()) / f"_tts_block_{os.getpid()}_{i}.wav"
            sclient.tts_moore(block, out_path=tmp)
            tmp_paths.append(tmp)
        return _concat_wavs(tmp_paths, Path(out_path))
    finally:
        for p in tmp_paths:
            p.unlink(missing_ok=True)


def translate_fr_to_moore(text_fr: str, tclient: TranslationClient | None = None) -> str:
    """Traduction texte FR -> mooré (désormais opérationnelle)."""
    return (tclient or TranslationClient()).fr_to_moore(text_fr)


# Le service de traduction NLLB tronque sa sortie au-delà d'une longueur limite
# (~150-250 caractères mooré observés en test), quelle que soit la longueur du
# texte FR envoyé. Découper phrase par phrase avant de traduire évite ce problème —
# mais une phrase "naturelle" à virgules (plutôt que ponctuée en points-virgules)
# peut rester trop longue après ce découpage ; on la resplite alors récursivement.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;:!?])\s+")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=,)\s+")
_MAX_CHUNK_CHARS = 200


def _split_safe(text: str) -> list[str]:
    """Découpe `text` en fragments <= _MAX_CHUNK_CHARS, d'abord sur la ponctuation
    forte (. ; : ! ?), puis sur les virgules si un fragment est encore trop long."""
    chunks = [c.strip() for c in _SENTENCE_SPLIT_RE.split(text.strip()) if c.strip()]
    safe: list[str] = []
    for chunk in chunks:
        if len(chunk) <= _MAX_CHUNK_CHARS:
            safe.append(chunk)
            continue
        sub_chunks = [c.strip() for c in _CLAUSE_SPLIT_RE.split(chunk) if c.strip()]
        safe.extend(sub_chunks)
    return safe


def translate_long_fr_to_moore(text_fr: str, tclient: TranslationClient | None = None) -> str:
    """Traduction FR -> mooré d'un texte long (bulletin complet), phrase par phrase."""
    tclient = tclient or TranslationClient()
    chunks = _split_safe(text_fr)
    return " ".join(tclient.fr_to_moore(c) for c in chunks)


def bulletin_to_moore_audio(bulletin_fr: str, out_path: str = "bulletin_mos.wav",
                            tclient: TranslationClient | None = None,
                            sclient: MooreClient | None = None) -> dict:
    """Pipeline module 1 (voie mooré) : traduit (phrase par phrase) puis synthétise.
    Renvoie {'text_moore', 'audio_path'}."""
    text_moore = translate_long_fr_to_moore(bulletin_fr, tclient)
    audio = tts_moore_long(text_moore, out_path=out_path, sclient=sclient)
    return {"text_moore": text_moore, "audio_path": audio}


def bulletin_pdf_to_moore_audio(pdf_path, out_path: str = "bulletin_mos.wav",
                                tclient: TranslationClient | None = None,
                                sclient: MooreClient | None = None) -> dict:
    """Pipeline complet F1.1-F1.4 (voie mooré) : PDF ANAM/RECLIM -> extraction des
    sections (bulletin_parser) -> texte FR -> traduction mooré -> audio.
    Les phrases-titres récurrentes (titres de section, intro des conseils) utilisent
    des traductions mooré fixes (cf. bulletin_parser.MOORE_LABEL_*) plutôt que d'être
    retraduites à chaque bulletin ; seul le contenu variable passe par le traducteur.
    Renvoie {'bulletin', 'text_fr', 'text_moore', 'audio_path'}."""
    from bulletin_parser import bulletin_narration_fr, bulletin_narration_moore, parse_bulletin

    bulletin = parse_bulletin(pdf_path)
    text_fr = bulletin_narration_fr(bulletin)
    text_moore = bulletin_narration_moore(bulletin, tclient)
    audio = tts_moore_long(text_moore, out_path=out_path, sclient=sclient)
    return {"bulletin": bulletin, "text_fr": text_fr, "text_moore": text_moore, "audio_path": audio}


# ---------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    arg = " ".join(sys.argv[1:]) or "Fortes pluies attendues cet après-midi. Limitez les déplacements."

    if arg.lower().endswith(".pdf"):
        # Pipeline F1.1-F1.4 : PDF du bulletin -> texte FR -> traduction mooré -> audio
        result = bulletin_pdf_to_moore_audio(arg, out_path="bulletin_mos.wav")
        print("FR    :", result["text_fr"])
    else:
        # Pipeline simple : texte FR -> traduction mooré -> audio mooré
        result = bulletin_to_moore_audio(arg, out_path="bulletin_mos.wav")
        print("FR    :", arg)

    print("MOORÉ :", result["text_moore"])
    print("Audio :", result["audio_path"])
