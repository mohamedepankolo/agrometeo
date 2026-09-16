"""
test_tts.py - teste le service TTS moore (audio) depuis TA machine.

Lancer :
    py -3.11 test_tts.py "ne y yibeoogo, yamba"

Config optionnelle (recommandee) :
    set MOORE_API_BASE_URL=https://xxxx.ngrok-free.dev    (URL actuelle du service)
    set MOORE_API_TOKEN=s2s_pat_...                        (si un admin te l'a donne)

Dependance : pip install requests
"""

import os
import sys
import requests

BASE_URL = os.environ.get("MOORE_API_BASE_URL", "https://iodine-april-bulb.ngrok-free.dev").rstrip("/")
TOKEN = os.environ.get("MOORE_API_TOKEN", "")            # vide par defaut, expres
TEXT = " ".join(sys.argv[1:]) or "ne y yibeoogo, yamba"

url = f"{BASE_URL}/api/tts_moore"
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "ngrok-skip-browser-warning": "true",                # evite la page d'avertissement ngrok
}

print("Appel :", url)
print("Token :", "(fourni)" if TOKEN else "(vide)")

try:
    r = requests.post(url, data={"text": TEXT}, headers=headers, timeout=30)
except Exception as e:
    print("\nERREUR DE CONNEXION ->", type(e).__name__, str(e)[:200])
    print("=> Le tunnel ngrok est probablement mort / expire. Demande la NOUVELLE URL aux admins.")
    sys.exit(1)

ctype = r.headers.get("content-type", "")
print("Statut:", r.status_code, "| type:", ctype)

if r.ok and ("audio" in ctype or r.content[:4] == b"RIFF"):
    with open("test.wav", "wb") as f:
        f.write(r.content)
    print("OK -> audio enregistre dans test.wav (", len(r.content), "octets )")
elif r.status_code in (401, 403):
    print("=> AUTH REQUISE : il faut un token valide (s2s_pat_...). Demande-le aux admins.")
    print("Reponse:", r.text[:300])
else:
    print("Reponse (debut):", r.text[:400])
