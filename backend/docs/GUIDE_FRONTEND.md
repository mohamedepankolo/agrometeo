# Guide d'intégration — API ANAM-BF

Pour les développeurs de l'application mobile et du back-office web. Ce guide explique **comment enchaîner
les appels** ; le détail de chaque route (champs, types, droits) est dans `API_REFERENCE.md`, et
`openapi.json` s'importe directement dans Postman, Insomnia ou un générateur de client.

La documentation interactive (essais en direct) est aussi servie par l'API elle-même : `<adresse>/docs`.

## 1. Bases

| | |
|---|---|
| Format | JSON en UTF-8 (sauf envois de fichiers : `multipart/form-data`) |
| Dates | UTC, ISO 8601 (`2026-09-21T14:30:00`). Afficher en heure locale (Burkina Faso = UTC+0) |
| Authentification | `Authorization: Bearer <access_token>` |
| Langues | `fr`, `en`, `mos` (mooré) |
| Listes | `?limit=20&offset=0` → `{"total": 57, "items": [...]}` |
| Erreurs | `{"detail": "message lisible"}` — à afficher tel quel à l'utilisateur |

Codes d'erreur : `401` non connecté ou token expiré · `403` droits insuffisants · `404` introuvable ·
`409` action impossible dans l'état actuel (ex. publier deux fois) · `413`/`415` fichier trop gros / mauvais type ·
`422` données invalides · `429` compte verrouillé après trop d'essais · `502` service externe indisponible.

**Contenus publics** : bulletins, alertes, avis, carte, zones et médias *publiés* se lisent **sans compte**.
Un compte n'est nécessaire que pour le profil, les notifications et la gestion.

## 2. Inscription et connexion (application mobile)

```
POST /auth/register   {"method":"phone","phone":"70123456","password":"...","commune":"Kaya","language":"mos"}
   → 201 {"user_id", "status":"pending", "verification_required":true, "verification_channel":"sms"}
POST /auth/verify     {"identifier":"70123456","code":"482913"}        → compte activé
POST /auth/login      {"identifier":"70123456","password":"..."}
   → 200 {"tokens": {"access_token","refresh_token","expires_in":900}}
```

- `method` : `phone` (code par SMS), `email` (code par e-mail) ou `local` (identifiant + mot de passe,
  activé ensuite par un administrateur).
- Code : 6 chiffres, valable 10 minutes, 3 essais. Bouton « renvoyer » → `POST /auth/resend-code {"identifier"}`.
- Le téléphone se saisit avec 8 chiffres (`70123456`) ou au format international (`+22670123456`).
- Mot de passe : 8 caractères minimum.

**Gestion des jetons** (à implémenter une fois dans la couche réseau) :
1. Garder `access_token` (15 min) en mémoire et `refresh_token` (30 jours) dans le stockage sécurisé du téléphone.
2. Sur `401`, appeler `POST /auth/refresh {"refresh_token"}` : on reçoit **une nouvelle paire — remplacer les deux**.
   Le refresh token est à usage unique ; le rejouer ferme toutes les sessions (protection contre le vol).
3. Si le refresh échoue (`401`) : renvoyer l'utilisateur à l'écran de connexion.
4. Déconnexion : `POST /auth/logout {"refresh_token"}`, et `DELETE /me/devices?token=<jeton FCM>`.

**2FA (comptes ANAM / administrateurs, back-office)** — la réponse de `/auth/login` a alors l'une de ces formes :

| Réponse | À faire |
|---|---|
| `requires_2fa: true` + `challenge_token` | Demander le code à 6 chiffres de l'application d'authentification → `POST /auth/2fa/verify {"challenge_token","code"}` → jetons |
| `requires_2fa_setup: true` + `setup_token` | 1re connexion : `POST /auth/2fa/setup` (en-tête `Bearer <setup_token>`) → afficher `otpauth_uri` en **QR code** ; puis `POST /auth/2fa/enable {"code"}` (même en-tête) → jetons |

Si `must_change_password` est vrai dans les jetons : imposer `POST /me/password` avant tout autre écran.

## 3. Écrans de l'application mobile ↔ routes

| Écran | Routes |
|---|---|
| **Accueil / dernier bulletin** | `GET /bulletins/latest` |
| **Bulletin (texte + lecteur audio)** | `GET /bulletins/{id}` → `texts[lang]` (texte), `media.files[lang].audio` / `.video` (URLs à lire), `pdf_url` |
| **Historique des bulletins** | `GET /bulletins?limit=20&offset=0` |
| **Alertes en cours** | `GET /alerts?active_only=true` ; détail `GET /alerts/{id}` (texte, `prevention`, vidéo, image) |
| **Carte** | `GET /map/alerts` → chaque zone avec `level` (`vert`/`jaune`/`orange`/`rouge`) ; couleurs et libellés dans `GET /config` |
| **Avis et conseils / planification** | `GET /advisories?kind=conseil` ou `kind=planification` |
| **Profil** | `GET /me`, `PATCH /me` (commune, langue, canaux `sms`/`push`/`email`), `POST /me/password` |
| **Notifications push** | après connexion : `POST /me/devices {"token":"<jeton FCM>","platform":"android"}` |
| **Paramètres de l'app** | `GET /config` (langues, communes, niveaux d'alerte + couleurs, source à citer) |

- **Langue d'écoute** : l'utilisateur choisit `fr`, `en` ou `mos` ; lire `media.files[lang]`. Sa préférence est dans `/me` (`language`).
- **Citer la source** : afficher `source` (« Source : ANAM… ») sur chaque bulletin et alerte.
- **Médias** : `media.files.<lang>.audio|video` sont des URLs directement lisibles (audio mp3/wav, vidéo mp4, avec lecture partielle
  pour les lecteurs). Si `media.status` ≠ `ready`, n'afficher que le texte.
- **Statistiques d'usage** : envoyer `POST /events {"content_type":"bulletin","content_id":"…","kind":"view|play_audio|play_video|share","language":"mos"}`
  (réponse 204 ; connexion facultative).
- **Hors-ligne** : mettre en cache le dernier bulletin et les alertes actives ; les identifiants sont stables.

## 4. Back-office web

| Écran | Routes |
|---|---|
| **Connexion admin** | section 2 (avec 2FA) ; les droits de l'utilisateur : `GET /me` (rôle) + `GET /roles` (permissions par rôle) |
| **Tableau de bord** | `GET /backoffice/dashboard`, `GET /backoffice/usage?days=30`, `GET /backoffice/sms-pilot` |
| **Bulletins** | import `POST /bulletins` (multipart, champ `file`) → prévisualiser → `POST /bulletins/{id}/publish` ; `.../unpublish`, `.../media` (régénérer), `.../broadcast`, `.../share-kit` |
| **Alertes** | formulaire → `POST /alerts` → `PUT /alerts/{id}/image` → `POST /alerts/{id}/media` → prévisualiser → `POST /alerts/{id}/publish` ; `.../cancel`, `.../broadcast`, `.../share-kit` |
| **Avis** | `POST /advisories` → `.../translate` → `.../publish`, `.../withdraw` |
| **Prévention / types / zones** | `/prevention-messages`, `/alert-types`, `/zones` (CRUD, avec droits) |
| **Utilisateurs et rôles** | `GET /admin/users?status=pending`, `POST /admin/users`, `PATCH /admin/users/{id}/role`, `.../activate`, `.../disable`, `.../reset-2fa`, `GET /admin/stats/communes` |
| **Diffusion** | `GET /backoffice/broadcasts`, `GET /backoffice/broadcasts/{id}` (détail par canal) |
| **Paramètres** | `GET/PUT /backoffice/settings` (canaux par type de contenu, diffusion automatique, numéros WhatsApp, durée de validité…) |

**Génération des audios et vidéos = asynchrone** (1 à 3 minutes). Le flux :
1. `POST /alerts/{id}/media` (ou import d'un bulletin) → réponse immédiate, `media.status = "processing"`.
2. Relire `GET /alerts/{id}` toutes les 3 à 5 s tant que `media.status = "processing"`.
3. `ready` → afficher les lecteurs ; `failed` → afficher `media.error` et proposer « Réessayer ».
4. Ne pas publier pendant `processing` (l'API répond `409`).

**Prévisualiser un média non publié** : les fichiers d'un brouillon exigent d'être connecté. Dans une balise
`<video>`/`<audio>` (qui ne peut pas envoyer d'en-tête), ajouter `?token=<access_token>` à l'URL.

**Champs texte de l'alerte** : `raw_text` accepte le message WhatsApp tel que rédigé (emojis, puces). Avant enregistrement,
`POST /alerts/preview {"raw_text"}` montre comment il est découpé (date, situation, évolution, risques, conseils).

**Diffusion** : à la publication, `?broadcast=true|false` force ou empêche l'envoi ; sans paramètre, c'est le
réglage `diffusion.auto_broadcast`. Le suivi par canal est dans `/backoffice/broadcasts/{id}` (statut `simulated` =
mode test, rien n'est réellement parti).

**Bouton « Partager sur WhatsApp » (secours)** : `GET .../share-kit` renvoie le texte déjà formaté (gras `*…*`, puces, emojis) dans les
trois langues, plus les liens vidéo/audio/image, à copier dans le groupe ou la chaîne WhatsApp.

## 5. Rôles et droits

`GET /roles` (public) donne la matrice à jour. Résumé :

| Rôle | Peut |
|---|---|
| `grand_public` | Consulter les contenus publiés |
| `observateur` | + saisir des observations de terrain |
| `responsable_communal` | + consulter tableau de bord et statistiques |
| `agent_anam` | + créer/modifier/publier/diffuser bulletins, alertes, avis ; consulter les comptes |
| `administrateur` | Tout : comptes, rôles, zones, paramètres |

Le **back-office doit masquer** les actions non permises (utiliser les permissions de `/roles`), mais c'est **l'API qui fait foi** :
une action interdite renvoie toujours `403`.

## 6. Tester sans attendre le backend de production

- `<adresse>/docs` : essayer chaque route.
- Comptes de démonstration (environnement de test seulement), mot de passe `Demo1234!` :
  `admin@demo.test`, `agent@demo.test`, `commune@demo.test`, `observateur@demo.test`, `citoyen@demo.test`.
  Admin et agent doivent configurer la 2FA à la première connexion.
- En environnement de test, les SMS/e-mails/notifications sont **simulés** : le code de vérification d'une inscription se lit
  avec `GET /dev/verification-code?identifier=70123456` (route absente en production).
