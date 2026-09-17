# Module 1 — Bulletins agrométéo en audio et vidéo (FR / anglais / mooré)

Chaîne de traitement du **Module 1** de la plateforme agrométéorologique ANAM-BF
(cf. cahier des charges, section 6.1) :

**bulletin PDF (FR) → extraction du texte et des images → traduction (mooré/anglais)
→ synthèse vocale → vidéo (image + audio synchronisés par section).**

## Pour la personne qui intègre ça au frontend

Le point d'entrée à connaître est **`generate_bulletin_all.py`**. Il prend un
bulletin PDF (format "Bulletin Spécifique RECLIM" de l'ANAM) et produit
**6 fichiers**, nommés d'après le PDF source, dans le dossier de sortie choisi :

| Fichier | Contenu | Format |
|---|---|---|
| `<nom>_fr.mp3` | Audio français | mp3 |
| `<nom>_en.mp3` | Audio anglais | mp3 |
| `<nom>_mos.wav` | Audio mooré | wav |
| `<nom>_fr.mp4` | Vidéo française | mp4, 1280px de large |
| `<nom>_en.mp4` | Vidéo anglaise | mp4, 1280px de large |
| `<nom>_mos.mp4` | Vidéo mooré | mp4, 1280px de large |

Chaque vidéo montre, dans l'ordre : la carte "temps observé" (pendant la partie
correspondante de l'audio), puis la carte "prévisions", puis le logo ANAM/météo
Burkina (pendant la partie "avis et conseils", si elle existe dans le bulletin).
Les images intermédiaires (cartes, logo) ne sont **pas** conservées dans le
dossier de sortie — seuls les 6 fichiers ci-dessus en sortent.

```bash
python generate_bulletin_all.py "chemin/vers/bulletin.pdf" dossier_de_sortie
```

Si le dossier de sortie est omis, les fichiers sont créés à côté du PDF source.
Le dossier est créé automatiquement s'il n'existe pas.

### Variantes plus ciblées (si le frontend n'a besoin que d'une partie)

- `generate_bulletin_audio.py <pdf> [dossier]` → les 3 audios **+** les 3 images
  (cartes/logo) séparément, sans vidéo. Utile si le frontend veut composer
  lui-même l'affichage (image statique + lecteur audio) plutôt qu'une vidéo.
- `generate_bulletin_video.py <pdf> [dossier]` → seulement la vidéo française
  (`<nom>_fr.mp4`), plus rapide si seul le FR est nécessaire.
- `bulletin_parser.py <pdf>` → affiche juste le texte extrait (observé /
  prévisions / conseils), sans appeler aucune API. Utile pour vérifier qu'un
  nouveau format de bulletin est bien reconnu avant de lancer la génération
  complète.

## Contenu du dossier

| Fichier | Rôle |
|---|---|
| `bulletin_parser.py` | Extraction du PDF : sections de texte (F1.2) + images cartes/logo (F1.4) |
| `moore_client.py` | Traduction FR↔mooré (CITADEL/NLLB) + synthèse vocale mooré (CITADEL) |
| `french_tts.py` | Synthèse vocale FR/EN (Edge TTS) + traduction FR→anglais (MyMemory) |
| `generate_bulletin_all.py` | **Point d'entrée principal** — 3 audios + 3 vidéos pour un bulletin |
| `generate_bulletin_audio.py` | 3 audios + 3 images (sans vidéo) |
| `generate_bulletin_video.py` | Vidéo française seule |
| `lexicon.py` / `lexicons/` | Lexiques météo FR-mooré (référence terminologique, F1.7) |
| `reference_pairs/` | Bulletins audio réels + transcriptions (validation de la structure) |
| `samples/` | Bulletins PDF d'exemple |
| `test_tts.py` | Petit script de test bas niveau du service TTS mooré |
| `.env.example` | Modèle de configuration (à copier en `.env`) |
| `requirements.txt` | Dépendances Python |

## Prérequis

- Python 3.10+
- `pip install -r requirements.txt`
- [ffmpeg](https://ffmpeg.org/) installé et accessible dans le PATH (utilisé pour
  assembler les vidéos et convertir l'audio)

## Configuration

Copier `.env.example` en `.env` et renseigner les valeurs (nécessaire pour la
traduction et le TTS mooré, via CITADEL — le FR/EN via Edge TTS et MyMemory ne
demandent pas de clé). Le fichier `.env` n'est jamais committé (cf. `.gitignore`).

Windows (PowerShell), à charger dans chaque nouvelle session avant de lancer un
script :
```powershell
Get-Content .env | Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' } | ForEach-Object {
    $name, $value = $_.Split('=', 2)
    Set-Item "env:$name" $value
}
```

Linux / macOS :
```bash
export $(grep -v '^#' .env | xargs)
```

## État actuel / limites connues

- ✅ Extraction PDF (texte + images), traduction FR↔mooré, traduction FR→anglais,
  synthèse vocale FR/EN/mooré, génération vidéo dans les 3 langues : opérationnel
  et testé sur plusieurs bulletins réels.
- ⏳ Les phrases-titres récurrentes et la formule d'ouverture/clôture mooré sont
  des traductions automatiques (NLLB) — **à faire valider par CITADEL/ANAM ou un
  locuteur natif avant toute diffusion publique** (cf. commentaires dans
  `bulletin_parser.py`).
- ⏳ La traduction anglaise (MyMemory) est correcte mais littérale, non relue.
- ⏳ Le TTS français/anglais (Edge TTS) et la traduction anglaise (MyMemory)
  reposent sur des services tiers gratuits sans garantie de disponibilité en
  production — solutions provisoires en attendant un TTS FR/EN natif côté CITADEL.
- 🔲 Pas encore fait : gestion des alertes météo (F1.6, format texte plutôt que
  PDF), diffusion WhatsApp (F1.5, bloquée en attendant l'accès à l'API WhatsApp
  Business), tests sur un plus grand échantillon de bulletins.

## Sécurité

- Ne **jamais** committer `.env` ni de token/mot de passe en clair.
- Les identifiants CITADEL (traduction, TTS mooré) se configurent uniquement via
  les variables d'environnement.
