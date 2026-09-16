# Module 1 — Traduction et audio (mooré)

Chaîne de traitement du **Module 1** de la plateforme agrométéorologique ANAM-BF :
**texte du bulletin (FR) → traduction en mooré → restitution audio (TTS)**.

## Contenu

| Fichier | Rôle |
|--------|------|
| `moore_client.py` | Clients API : traduction (FR↔mooré), parole (TTS/ASR/S2ST) + pipeline `bulletin_to_moore_audio` |
| `test_tts.py` | Petit script de test du service TTS mooré |
| `.env.example` | Modèle de configuration (à copier en `.env`) |
| `requirements.txt` | Dépendances Python |

## Prérequis

- Python 3.10+
- `pip install -r requirements.txt`

## Configuration

Copier `.env.example` en `.env` et renseigner les valeurs, **puis exporter les variables**
(le fichier `.env` n'est jamais committé, cf. `.gitignore`).

Windows (PowerShell) :
```powershell
$env:CITADEL_API_EMAIL    = "citadel.api.user@citadel.bf"
$env:CITADEL_API_PASSWORD = "..."
$env:MOORE_API_BASE_URL   = "https://.../"
$env:MOORE_API_TOKEN      = "s2s_pat_..."
```

Linux / macOS :
```bash
export CITADEL_API_EMAIL="citadel.api.user@citadel.bf"
export CITADEL_API_PASSWORD="..."
export MOORE_API_BASE_URL="https://.../"
export MOORE_API_TOKEN="s2s_pat_..."
```

## Utilisation

**Traduction seule** (nécessite les variables `CITADEL_*`) :
```bash
python moore_client.py "Fortes pluies attendues cet apres-midi."
```

**Test du service TTS** (nécessite `MOORE_API_*`) :
```bash
python test_tts.py "ne y yibeoogo, yamba"
```

**Pipeline complet** (traduction FR → mooré puis audio) : voir la fonction
`bulletin_to_moore_audio()` dans `moore_client.py`.

## État (au moment du commit)

- ✅ Traduction FR → mooré : opérationnelle et testée.
- ✅ TTS mooré (texte → audio) : opérationnelle et testée.
- ⏳ TTS français / anglais : à intégrer côté service.

## Sécurité

- Ne **jamais** committer `.env` ni de token/mot de passe en clair.
- Le token du service parole et les identifiants de traduction se configurent
  uniquement via les variables d'environnement.
