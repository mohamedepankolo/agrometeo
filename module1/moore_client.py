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
from dataclasses import dataclass, field
from pathlib import Path

import requests

DEFAULT_TIMEOUT = 60  # secondes


class MooreApiError(RuntimeError):
    """Erreur de transport HTTP ou réponse inattendue d'un service."""


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
            r = requests.post(url, json={"email": self.email, "password": self.password}, timeout=self.timeout)
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
            r = requests.post(url, json=payload, headers=self._auth(), timeout=self.timeout)
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
        return self.translate(text, "french", "moore")

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
            r = requests.post(url, headers=self._auth, timeout=self.timeout, **kwargs)
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
def translate_fr_to_moore(text_fr: str, tclient: TranslationClient | None = None) -> str:
    """Traduction texte FR -> mooré (désormais opérationnelle)."""
    return (tclient or TranslationClient()).fr_to_moore(text_fr)


def bulletin_to_moore_audio(bulletin_fr: str, out_path: str = "bulletin_mos.wav",
                            tclient: TranslationClient | None = None,
                            sclient: MooreClient | None = None) -> dict:
    """Pipeline module 1 (voie mooré) : traduit puis synthétise.
    Renvoie {'text_moore', 'audio_path'}."""
    text_moore = translate_fr_to_moore(bulletin_fr, tclient)
    audio = (sclient or MooreClient()).tts_moore(text_moore, out_path=out_path)
    return {"text_moore": text_moore, "audio_path": audio}


# ---------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    phrase = " ".join(sys.argv[1:]) or "Fortes pluies attendues cet après-midi. Limitez les déplacements."

    # 1) Traduction (nécessite CITADEL_API_EMAIL / CITADEL_API_PASSWORD)
    tc = TranslationClient()
    mos = tc.fr_to_moore(phrase)
    print("FR    :", phrase)
    print("MOORÉ :", mos)

    # 2) Audio mooré (décommenter une fois MOORE_API_BASE_URL / MOORE_API_TOKEN dispo)
    # sc = MooreClient()
    # wav = sc.tts_moore(mos, out_path="demo_bulletin_mos.wav")
    # print("Audio :", wav)
