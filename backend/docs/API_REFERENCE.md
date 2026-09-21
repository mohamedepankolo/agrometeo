# ANAM-BF - API de la plateforme agrométéo - référence des routes

API de la plateforme agrométéorologique de l'ANAM-BF.

**Conventions**
- Format JSON, UTF-8. Dates en UTC au format ISO 8601.
- Authentification : en-tête `Authorization: Bearer <access_token>` (voir la section *Authentification*).
  Les contenus publiés (bulletins, alertes, avis, carte, zones) sont **publics** : consultables sans compte.
- Erreurs : `{"detail": "message lisible"}` avec le code HTTP adapté (401 non connecté, 403 droits insuffisants,
  404 introuvable, 409 conflit d'état, 422 données invalides, 429 trop de tentatives).
- Listes paginées : paramètres `limit` et `offset`, réponse `{"total": N, "items": [...]}`.
- Langues : `fr` (français), `en` (anglais), `mos` (mooré).
- Génération audio/vidéo : asynchrone. Lancer, puis relire le contenu jusqu'à `media.status` = `ready`.

> Document généré automatiquement depuis le code (`python scripts/export_docs.py`). Le fichier `openapi.json` contient la même information dans un format importable par les outils.

## Authentification

Inscription, connexion, 2FA, sessions.

### `POST /auth/2fa/enable`

Confirme la configuration avec un premier code, active la 2FA et ouvre la session.

**Accès :** Jeton d'accès, ou jeton de configuration 2FA reçu à la connexion.

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `code` | string | oui |  |

**Réponse 200** : TokenPair

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `access_token` | string | oui |  |
| `refresh_token` | string | oui |  |
| `token_type` | string |  |  |
| `expires_in` | integer | oui |  |
| `must_change_password` | boolean |  |  |

### `POST /auth/2fa/setup`

Génère un secret TOTP (à scanner en QR code dans une application d'authentification).
Appelable avec un token d'accès, ou avec le `setup_token` reçu à la connexion.

**Accès :** Jeton d'accès, ou jeton de configuration 2FA reçu à la connexion.

**Réponse 200** : TwoFactorSetupResponse

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `secret` | string | oui |  |
| `otpauth_uri` | string | oui |  |

### `POST /auth/2fa/verify`

2e étape de connexion : échange le `challenge_token` + code TOTP contre les jetons.

**Accès :** Public.

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `challenge_token` | string | oui |  |
| `code` | string | oui |  |

**Réponse 200** : TokenPair

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `access_token` | string | oui |  |
| `refresh_token` | string | oui |  |
| `token_type` | string |  |  |
| `expires_in` | integer | oui |  |
| `must_change_password` | boolean |  |  |

### `POST /auth/login`

Connexion par téléphone, e-mail ou identifiant local + mot de passe.

Selon le compte, la réponse contient soit les jetons (`tokens`), soit un `challenge_token` à
échanger avec le code 2FA (`/auth/2fa/verify`), soit un `setup_token` pour configurer la 2FA
(rôles qui l'exigent : administrateur, agent ANAM).

**Accès :** Public.

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `identifier` | string | oui |  |
| `password` | string | oui |  |

**Réponse 200** : LoginResponse

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `tokens` | TokenPair (facultatif) |  |  |
| `requires_2fa` | boolean |  |  |
| `challenge_token` | string (facultatif) |  |  |
| `requires_2fa_setup` | boolean |  |  |
| `setup_token` | string (facultatif) |  |  |

### `POST /auth/logout`

Termine la session correspondant à ce refresh token (idempotent).

**Accès :** Public.

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `refresh_token` | string | oui |  |

**Réponse 204** : aucun contenu

### `POST /auth/logout-all`

Termine toutes les sessions du compte, sur tous les appareils.

**Accès :** Connexion requise (tout utilisateur connecté).

**Réponse 204** : aucun contenu

### `POST /auth/refresh`

Renouvelle la session. Le refresh token est à usage unique (rotation) : le réutiliser
après échange est traité comme un vol et ferme toutes les sessions du compte.

**Accès :** Public.

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `refresh_token` | string | oui |  |

**Réponse 200** : TokenPair

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `access_token` | string | oui |  |
| `refresh_token` | string | oui |  |
| `token_type` | string |  |  |
| `expires_in` | integer | oui |  |
| `must_change_password` | boolean |  |  |

### `POST /auth/register`

Inscription grand public : par téléphone (code SMS), e-mail (code par e-mail) ou compte local.

Le rôle attribué est toujours `grand_public` ; les rôles internes sont créés par un administrateur.

**Accès :** Public.

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `phone` | string (facultatif) |  |  |
| `email` | string (email) (facultatif) |  |  |
| `username` | string (facultatif) |  |  |
| `method` | `phone` \| `email` \| `local` | oui |  |
| `password` | string | oui |  |
| `full_name` | string (facultatif) |  |  |
| `commune` | string (facultatif) |  |  |
| `language` | Language |  |  |

**Réponse 201** : RegisterResponse

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `user_id` | string | oui |  |
| `status` | UserStatus | oui |  |
| `verification_required` | boolean | oui |  |
| `verification_channel` | string (facultatif) | oui |  |
| `message` | string | oui |  |

### `POST /auth/resend-code`

Renvoie un code. Réponse identique que le compte existe ou non (pas d'énumération de comptes).

**Accès :** Public.

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `identifier` | string | oui |  |

**Réponse 202** : MessageResponse

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `message` | string | oui |  |

### `POST /auth/verify`

Valide le code reçu par SMS / e-mail et active le compte.

**Accès :** Public.

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `identifier` | string | oui |  |
| `code` | string | oui |  |

**Réponse 200** : MessageResponse

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `message` | string | oui |  |

## Profil

Profil de l'utilisateur connecté : commune, langue, canaux de notification, appareils.

### `GET /me`

**Accès :** Connexion requise (tout utilisateur connecté).

**Réponse 200** : UserOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `phone` | string (facultatif) | oui |  |
| `email` | string (facultatif) | oui |  |
| `username` | string (facultatif) | oui |  |
| `full_name` | string (facultatif) | oui |  |
| `role` | Role | oui |  |
| `status` | UserStatus | oui |  |
| `commune` | string (facultatif) | oui |  |
| `language` | Language | oui |  |
| `notification_channels` | liste de Channel | oui |  |
| `totp_enabled` | boolean | oui |  |
| `must_change_password` | boolean | oui |  |
| `created_at` | string (date-time) | oui |  |
| `last_login_at` | string (date-time) (facultatif) | oui |  |

### `PATCH /me`

Met à jour la commune, la langue préférée et le mode de réception des alertes.

**Accès :** Connexion requise (tout utilisateur connecté).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `full_name` | string (facultatif) |  |  |
| `commune` | string (facultatif) |  |  |
| `language` | Language (facultatif) |  |  |
| `notification_channels` | liste de Channel (facultatif) |  |  |

**Réponse 200** : UserOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `phone` | string (facultatif) | oui |  |
| `email` | string (facultatif) | oui |  |
| `username` | string (facultatif) | oui |  |
| `full_name` | string (facultatif) | oui |  |
| `role` | Role | oui |  |
| `status` | UserStatus | oui |  |
| `commune` | string (facultatif) | oui |  |
| `language` | Language | oui |  |
| `notification_channels` | liste de Channel | oui |  |
| `totp_enabled` | boolean | oui |  |
| `must_change_password` | boolean | oui |  |
| `created_at` | string (date-time) | oui |  |
| `last_login_at` | string (date-time) (facultatif) | oui |  |

### `POST /me/password`

Change le mot de passe et ferme toutes les sessions (reconnexion nécessaire).

**Accès :** Connexion requise (tout utilisateur connecté).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `current_password` | string | oui |  |
| `new_password` | string | oui |  |

**Réponse 200** : MessageResponse

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `message` | string | oui |  |

## Bulletins

Bulletins agrométéorologiques avec audios et vidéos (français, anglais, mooré).

### `GET /bulletins`

Bulletins, du plus récent au plus ancien. Sans droits de gestion : uniquement les bulletins publiés.

**Accès :** Public. Une connexion avec droits de gestion donne accès aux contenus non publiés.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `status` | query |  | `published` \| `draft` \| `archived` \| `all` |  |
| `limit` | query |  | integer |  |
| `offset` | query |  | integer |  |

**Réponse 200** : BulletinList

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `total` | integer | oui |  |
| `items` | liste de BulletinOut | oui |  |

### `POST /bulletins`

Importe un bulletin PDF : extraction immédiate du texte, puis génération en arrière-plan des 3 audios
et 3 vidéos (1 à 3 minutes : relire le bulletin jusqu'à `media.status` = `ready`). Le bulletin reste en
brouillon jusqu'à `POST /bulletins/{id}/publish`.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Corps de la requête (multipart/form-data)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `file` | string | oui | Bulletin PDF de l'ANAM |

**Réponse 201** : BulletinOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `title` | string | oui |  |
| `date_text` | string (facultatif) | oui |  |
| `issued_at` | string (date-time) (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui |  |
| `pdf_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |

### `GET /bulletins/latest`

Dernier bulletin publié (écran d'accueil de l'application).

**Accès :** Public.

**Réponse 200** : BulletinOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `title` | string | oui |  |
| `date_text` | string (facultatif) | oui |  |
| `issued_at` | string (date-time) (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui |  |
| `pdf_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |

### `GET /bulletins/{bulletin_id}`

Détail d'un bulletin : sections du texte, texte lu par langue, PDF, liens des audios et vidéos.

**Accès :** Public. Une connexion avec droits de gestion donne accès aux contenus non publiés.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `bulletin_id` | path | oui | string |  |

**Réponse 200** : BulletinOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `title` | string | oui |  |
| `date_text` | string (facultatif) | oui |  |
| `issued_at` | string (date-time) (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui |  |
| `pdf_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |

### `PATCH /bulletins/{bulletin_id}`

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `bulletin_id` | path | oui | string |  |

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `title` | string (facultatif) |  |  |

**Réponse 200** : BulletinOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `title` | string | oui |  |
| `date_text` | string (facultatif) | oui |  |
| `issued_at` | string (date-time) (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui |  |
| `pdf_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |

### `DELETE /bulletins/{bulletin_id}`

Supprime un bulletin non publié (et ses fichiers).

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `bulletin_id` | path | oui | string |  |

**Réponse 204** : aucun contenu

### `POST /bulletins/{bulletin_id}/broadcast`

(Re)diffuse manuellement un bulletin publié. Suivi : `GET /backoffice/broadcasts/{id}`.

**Accès :** Connexion requise, permission `content:publish` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `bulletin_id` | path | oui | string |  |

**Réponse 202** : BroadcastOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `content_type` | string | oui |  |
| `content_id` | string | oui |  |
| `status` | string | oui |  |
| `trigger` | string | oui |  |
| `created_at` | string (date-time) | oui |  |
| `finished_at` | string (date-time) (facultatif) | oui |  |
| `target_count` | integer | oui |  |
| `sent_count` | integer | oui |  |
| `failed_count` | integer | oui |  |
| `note` | string (facultatif) | oui |  |

### `POST /bulletins/{bulletin_id}/media`

Relance la génération des audios et vidéos (après un échec, ou si les services de traduction ont évolué).

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `bulletin_id` | path | oui | string |  |

**Réponse 202** : BulletinOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `title` | string | oui |  |
| `date_text` | string (facultatif) | oui |  |
| `issued_at` | string (date-time) (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui |  |
| `pdf_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |

### `POST /bulletins/{bulletin_id}/publish`

Publie le bulletin (visible dans l'application) et, selon le paramètre, le diffuse.

**Accès :** Connexion requise, permission `content:publish` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `bulletin_id` | path | oui | string |  |
| `broadcast` | query |  | boolean (facultatif) | Diffuser tout de suite ; par défaut : paramètre `diffusion.auto_broadcast` |

**Réponse 200** : BulletinOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `title` | string | oui |  |
| `date_text` | string (facultatif) | oui |  |
| `issued_at` | string (date-time) (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui |  |
| `pdf_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |

### `GET /bulletins/{bulletin_id}/share-kit`

Texte formaté pour WhatsApp et liens des médias : bouton de diffusion manuelle du back-office.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `bulletin_id` | path | oui | string |  |

**Réponse 200** : ShareKit

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `text` | dictionnaire de string | oui |  |
| `media` | dictionnaire de MediaFiles | oui |  |
| `image_url` | string (facultatif) |  |  |
| `note` | string | oui |  |

### `POST /bulletins/{bulletin_id}/unpublish`

Retire le bulletin de l'application (archivé).

**Accès :** Connexion requise, permission `content:publish` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `bulletin_id` | path | oui | string |  |

**Réponse 200** : BulletinOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `title` | string | oui |  |
| `date_text` | string (facultatif) | oui |  |
| `issued_at` | string (date-time) (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui |  |
| `pdf_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |

## Alertes

Alertes météo : saisie, médias, publication, diffusion.

### `GET /alerts`

Liste des alertes, les plus récentes d'abord. Sans droits de gestion : uniquement les alertes publiées.

**Accès :** Public. Une connexion avec droits de gestion donne accès aux contenus non publiés.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `status` | query |  | `published` \| `draft` \| `cancelled` \| `all` |  |
| `active_only` | query |  | boolean | Seulement les alertes non expirées |
| `type_code` | query |  | string (facultatif) |  |
| `zone_id` | query |  | string (facultatif) |  |
| `limit` | query |  | integer |  |
| `offset` | query |  | integer |  |

**Réponse 200** : AlertList

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `total` | integer | oui |  |
| `items` | liste de AlertOut | oui |  |

### `POST /alerts`

Crée une alerte en brouillon. Étapes suivantes : `PUT /alerts/{id}/image`, `POST /alerts/{id}/media`
(génération des audios et vidéos), puis `POST /alerts/{id}/publish`.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `alert_type_id` | string | oui |  |
| `level` | AlertLevel | oui |  |
| `raw_text` | string | oui | Texte de l'alerte, tel que rédigé (format WhatsApp accepté) |
| `title` | string (facultatif) |  |  |
| `zone_ids` | liste de string |  |  |
| `valid_until` | string (date-time) (facultatif) |  | UTC ; par défaut : maintenant + durée de validité configurée |

**Réponse 201** : AlertOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `type` | AlertTypeOut | oui |  |
| `level` | AlertLevel | oui |  |
| `title` | string | oui |  |
| `status` | ContentStatus | oui |  |
| `is_active` | boolean | oui | Publiée et non expirée |
| `zones` | liste de ZoneOut | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui | Texte lu, par langue (disponible quand les médias sont prêts) |
| `prevention` | liste de PreventionOut | oui |  |
| `image_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `valid_until` | string (date-time) (facultatif) | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |
| `raw_text` | string (facultatif) |  | Réservé au personnel |

### `POST /alerts/preview`

Montre comment le texte saisi est découpé (date, situation, évolution, risques, conseils),
sans rien enregistrer. Sert au formulaire de validation du back-office.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `raw_text` | string | oui |  |

**Réponse 200** : AlertPreview

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `date_text` | string (facultatif) |  |  |
| `situation` | string |  |  |
| `evolution` | string |  |  |
| `risques` | liste de string |  |  |
| `conseils_intro` | string (facultatif) |  |  |
| `conseils` | liste de string |  |  |

### `GET /alerts/{alert_id}`

Détail d'une alerte : texte par langue, message de prévention, zones, liens des audios et vidéos.

**Accès :** Public. Une connexion avec droits de gestion donne accès aux contenus non publiés.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `alert_id` | path | oui | string |  |

**Réponse 200** : AlertOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `type` | AlertTypeOut | oui |  |
| `level` | AlertLevel | oui |  |
| `title` | string | oui |  |
| `status` | ContentStatus | oui |  |
| `is_active` | boolean | oui | Publiée et non expirée |
| `zones` | liste de ZoneOut | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui | Texte lu, par langue (disponible quand les médias sont prêts) |
| `prevention` | liste de PreventionOut | oui |  |
| `image_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `valid_until` | string (date-time) (facultatif) | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |
| `raw_text` | string (facultatif) |  | Réservé au personnel |

### `PATCH /alerts/{alert_id}`

Brouillon : tous les champs modifiables. Alerte publiée : seuls `level`, `title` et `valid_until`.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `alert_id` | path | oui | string |  |

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `alert_type_id` | string (facultatif) |  |  |
| `level` | AlertLevel (facultatif) |  |  |
| `raw_text` | string (facultatif) |  |  |
| `title` | string (facultatif) |  |  |
| `zone_ids` | liste de string (facultatif) |  |  |
| `valid_until` | string (date-time) (facultatif) |  |  |

**Réponse 200** : AlertOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `type` | AlertTypeOut | oui |  |
| `level` | AlertLevel | oui |  |
| `title` | string | oui |  |
| `status` | ContentStatus | oui |  |
| `is_active` | boolean | oui | Publiée et non expirée |
| `zones` | liste de ZoneOut | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui | Texte lu, par langue (disponible quand les médias sont prêts) |
| `prevention` | liste de PreventionOut | oui |  |
| `image_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `valid_until` | string (date-time) (facultatif) | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |
| `raw_text` | string (facultatif) |  | Réservé au personnel |

### `DELETE /alerts/{alert_id}`

Supprime un brouillon ou une alerte annulée (et ses fichiers). Une alerte publiée doit d'abord être annulée.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `alert_id` | path | oui | string |  |

**Réponse 204** : aucun contenu

### `POST /alerts/{alert_id}/broadcast`

Rediffuse manuellement une alerte publiée (relance, canal de secours). Suivi : `GET /backoffice/broadcasts/{id}`.

**Accès :** Connexion requise, permission `content:publish` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `alert_id` | path | oui | string |  |

**Réponse 202** : BroadcastOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `content_type` | string | oui |  |
| `content_id` | string | oui |  |
| `status` | string | oui |  |
| `trigger` | string | oui |  |
| `created_at` | string (date-time) | oui |  |
| `finished_at` | string (date-time) (facultatif) | oui |  |
| `target_count` | integer | oui |  |
| `sent_count` | integer | oui |  |
| `failed_count` | integer | oui |  |
| `note` | string (facultatif) | oui |  |

### `POST /alerts/{alert_id}/cancel`

Annule une alerte (elle disparaît de la carte et des listes publiques).

**Accès :** Connexion requise, permission `content:publish` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `alert_id` | path | oui | string |  |

**Réponse 200** : AlertOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `type` | AlertTypeOut | oui |  |
| `level` | AlertLevel | oui |  |
| `title` | string | oui |  |
| `status` | ContentStatus | oui |  |
| `is_active` | boolean | oui | Publiée et non expirée |
| `zones` | liste de ZoneOut | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui | Texte lu, par langue (disponible quand les médias sont prêts) |
| `prevention` | liste de PreventionOut | oui |  |
| `image_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `valid_until` | string (date-time) (facultatif) | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |
| `raw_text` | string (facultatif) |  | Réservé au personnel |

### `PUT /alerts/{alert_id}/image`

Envoie (ou remplace) l'image de l'alerte : radar, satellite… C'est elle qui illustre les vidéos.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `alert_id` | path | oui | string |  |

**Corps de la requête (multipart/form-data)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `file` | string | oui | Image de l'alerte (JPEG ou PNG) |

**Réponse 200** : AlertOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `type` | AlertTypeOut | oui |  |
| `level` | AlertLevel | oui |  |
| `title` | string | oui |  |
| `status` | ContentStatus | oui |  |
| `is_active` | boolean | oui | Publiée et non expirée |
| `zones` | liste de ZoneOut | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui | Texte lu, par langue (disponible quand les médias sont prêts) |
| `prevention` | liste de PreventionOut | oui |  |
| `image_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `valid_until` | string (date-time) (facultatif) | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |
| `raw_text` | string (facultatif) |  | Réservé au personnel |

### `POST /alerts/{alert_id}/media`

Lance la génération des 3 audios et 3 vidéos (français, anglais, mooré). Dure 1 à 3 minutes :
relire l'alerte (`GET /alerts/{id}`) jusqu'à `media.status` = `ready` (ou `failed`, avec `media.error`).

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `alert_id` | path | oui | string |  |

**Réponse 202** : AlertOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `type` | AlertTypeOut | oui |  |
| `level` | AlertLevel | oui |  |
| `title` | string | oui |  |
| `status` | ContentStatus | oui |  |
| `is_active` | boolean | oui | Publiée et non expirée |
| `zones` | liste de ZoneOut | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui | Texte lu, par langue (disponible quand les médias sont prêts) |
| `prevention` | liste de PreventionOut | oui |  |
| `image_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `valid_until` | string (date-time) (facultatif) | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |
| `raw_text` | string (facultatif) |  | Réservé au personnel |

### `POST /alerts/{alert_id}/publish`

Publie l'alerte (visible de tous, affichée sur la carte) et, selon le paramètre, la diffuse aux
utilisateurs concernés par SMS, notification push, e-mail et WhatsApp.

**Accès :** Connexion requise, permission `content:publish` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `alert_id` | path | oui | string |  |
| `broadcast` | query |  | boolean (facultatif) | Diffuser tout de suite ; par défaut : paramètre `diffusion.auto_broadcast` |

**Réponse 200** : AlertOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `type` | AlertTypeOut | oui |  |
| `level` | AlertLevel | oui |  |
| `title` | string | oui |  |
| `status` | ContentStatus | oui |  |
| `is_active` | boolean | oui | Publiée et non expirée |
| `zones` | liste de ZoneOut | oui |  |
| `parsed` | dictionnaire de quelconque (facultatif) | oui |  |
| `texts` | dictionnaire de string (facultatif) | oui | Texte lu, par langue (disponible quand les médias sont prêts) |
| `prevention` | liste de PreventionOut | oui |  |
| `image_url` | string (facultatif) | oui |  |
| `media` | MediaInfo | oui |  |
| `valid_until` | string (date-time) (facultatif) | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |
| `source` | string | oui |  |
| `raw_text` | string (facultatif) |  | Réservé au personnel |

### `GET /alerts/{alert_id}/share-kit`

Texte formaté pour WhatsApp (français, anglais, mooré) et liens des médias : bouton de diffusion manuelle.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `alert_id` | path | oui | string |  |

**Réponse 200** : ShareKit

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `text` | dictionnaire de string | oui |  |
| `media` | dictionnaire de MediaFiles | oui |  |
| `image_url` | string (facultatif) |  |  |
| `note` | string | oui |  |

## Avis et conseils

Avis et conseils, avis de planification anticipée.

### `GET /advisories`

Avis, du plus récent au plus ancien. Sans droits de gestion : uniquement les avis publiés.

**Accès :** Public. Une connexion avec droits de gestion donne accès aux contenus non publiés.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `kind` | query |  | AdvisoryKind (facultatif) | conseil = avis et conseils ; planification = avis de planification anticipée |
| `status` | query |  | `published` \| `draft` \| `cancelled` \| `all` |  |
| `limit` | query |  | integer |  |
| `offset` | query |  | integer |  |

**Réponse 200** : AdvisoryList

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `total` | integer | oui |  |
| `items` | liste de AdvisoryOut | oui |  |

### `POST /advisories`

Crée un avis en brouillon (texte français obligatoire ; anglais et mooré facultatifs, ou
proposés par `POST /advisories/{id}/translate`).

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `kind` | AdvisoryKind | oui |  |
| `title_fr` | string | oui |  |
| `body_fr` | string | oui |  |
| `title_en` | string (facultatif) |  |  |
| `title_mos` | string (facultatif) |  |  |
| `body_en` | string (facultatif) |  |  |
| `body_mos` | string (facultatif) |  |  |

**Réponse 201** : AdvisoryOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `kind` | AdvisoryKind | oui |  |
| `title_fr` | string | oui |  |
| `title_en` | string (facultatif) | oui |  |
| `title_mos` | string (facultatif) | oui |  |
| `body_fr` | string | oui |  |
| `body_en` | string (facultatif) | oui |  |
| `body_mos` | string (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |

### `GET /advisories/{advisory_id}`

**Accès :** Public. Une connexion avec droits de gestion donne accès aux contenus non publiés.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `advisory_id` | path | oui | string |  |

**Réponse 200** : AdvisoryOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `kind` | AdvisoryKind | oui |  |
| `title_fr` | string | oui |  |
| `title_en` | string (facultatif) | oui |  |
| `title_mos` | string (facultatif) | oui |  |
| `body_fr` | string | oui |  |
| `body_en` | string (facultatif) | oui |  |
| `body_mos` | string (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |

### `PATCH /advisories/{advisory_id}`

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `advisory_id` | path | oui | string |  |

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `title_fr` | string (facultatif) |  |  |
| `body_fr` | string (facultatif) |  |  |
| `title_en` | string (facultatif) |  |  |
| `title_mos` | string (facultatif) |  |  |
| `body_en` | string (facultatif) |  |  |
| `body_mos` | string (facultatif) |  |  |

**Réponse 200** : AdvisoryOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `kind` | AdvisoryKind | oui |  |
| `title_fr` | string | oui |  |
| `title_en` | string (facultatif) | oui |  |
| `title_mos` | string (facultatif) | oui |  |
| `body_fr` | string | oui |  |
| `body_en` | string (facultatif) | oui |  |
| `body_mos` | string (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |

### `DELETE /advisories/{advisory_id}`

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `advisory_id` | path | oui | string |  |

**Réponse 204** : aucun contenu

### `POST /advisories/{advisory_id}/broadcast`

**Accès :** Connexion requise, permission `content:publish` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `advisory_id` | path | oui | string |  |

**Réponse 202** : BroadcastOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `content_type` | string | oui |  |
| `content_id` | string | oui |  |
| `status` | string | oui |  |
| `trigger` | string | oui |  |
| `created_at` | string (date-time) | oui |  |
| `finished_at` | string (date-time) (facultatif) | oui |  |
| `target_count` | integer | oui |  |
| `sent_count` | integer | oui |  |
| `failed_count` | integer | oui |  |
| `note` | string (facultatif) | oui |  |

### `POST /advisories/{advisory_id}/publish`

**Accès :** Connexion requise, permission `content:publish` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `advisory_id` | path | oui | string |  |
| `broadcast` | query |  | boolean (facultatif) | Diffuser tout de suite ; par défaut : paramètre `diffusion.auto_broadcast` |

**Réponse 200** : AdvisoryOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `kind` | AdvisoryKind | oui |  |
| `title_fr` | string | oui |  |
| `title_en` | string (facultatif) | oui |  |
| `title_mos` | string (facultatif) | oui |  |
| `body_fr` | string | oui |  |
| `body_en` | string (facultatif) | oui |  |
| `body_mos` | string (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |

### `GET /advisories/{advisory_id}/share-kit`

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `advisory_id` | path | oui | string |  |

**Réponse 200** : ShareKit

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `text` | dictionnaire de string | oui |  |
| `media` | dictionnaire de MediaFiles | oui |  |
| `image_url` | string (facultatif) |  |  |
| `note` | string | oui |  |

### `POST /advisories/{advisory_id}/translate`

Propose une traduction automatique du titre et du texte (anglais : MyMemory, mooré : CITADEL/NLLB).
À relire avant publication. N'écrase pas l'existant sauf `overwrite=true`.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `advisory_id` | path | oui | string |  |

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `langs` | liste de `en` \| `mos` |  |  |
| `overwrite` | boolean |  |  |

**Réponse 200** : AdvisoryOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `kind` | AdvisoryKind | oui |  |
| `title_fr` | string | oui |  |
| `title_en` | string (facultatif) | oui |  |
| `title_mos` | string (facultatif) | oui |  |
| `body_fr` | string | oui |  |
| `body_en` | string (facultatif) | oui |  |
| `body_mos` | string (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |

### `POST /advisories/{advisory_id}/withdraw`

Retire un avis publié.

**Accès :** Connexion requise, permission `content:publish` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `advisory_id` | path | oui | string |  |

**Réponse 200** : AdvisoryOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `kind` | AdvisoryKind | oui |  |
| `title_fr` | string | oui |  |
| `title_en` | string (facultatif) | oui |  |
| `title_mos` | string (facultatif) | oui |  |
| `body_fr` | string | oui |  |
| `body_en` | string (facultatif) | oui |  |
| `body_mos` | string (facultatif) | oui |  |
| `status` | ContentStatus | oui |  |
| `created_at` | string (date-time) | oui |  |
| `published_at` | string (date-time) (facultatif) | oui |  |

## Zones, carte et référentiels

Zones, carte des alertes par couleur, types d'alerte, messages de prévention.

### `GET /alert-types`

Types d'alerte (orages, fortes pluies, inondations, vents violents, poussière, chaleur, sécheresse…). Public.

**Accès :** Public.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `include_inactive` | query |  | boolean |  |

**Réponse 200** : liste de AlertTypeOut
Liste de : AlertTypeOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `code` | string | oui |  |
| `label_fr` | string | oui |  |
| `label_en` | string (facultatif) | oui |  |
| `label_mos` | string (facultatif) | oui |  |
| `active` | boolean | oui |  |

### `POST /alert-types`

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `code` | string | oui |  |
| `label_fr` | string | oui |  |
| `label_en` | string (facultatif) |  |  |
| `label_mos` | string (facultatif) |  |  |
| `active` | boolean |  |  |

**Réponse 201** : AlertTypeOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `code` | string | oui |  |
| `label_fr` | string | oui |  |
| `label_en` | string (facultatif) | oui |  |
| `label_mos` | string (facultatif) | oui |  |
| `active` | boolean | oui |  |

### `PATCH /alert-types/{type_id}`

Modifie les libellés d'un type ; `active=false` le retire des choix sans casser les alertes existantes.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `type_id` | path | oui | string |  |

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `label_fr` | string (facultatif) |  |  |
| `label_en` | string (facultatif) |  |  |
| `label_mos` | string (facultatif) |  |  |
| `active` | boolean (facultatif) |  |  |

**Réponse 200** : AlertTypeOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `code` | string | oui |  |
| `label_fr` | string | oui |  |
| `label_en` | string (facultatif) | oui |  |
| `label_mos` | string (facultatif) | oui |  |
| `active` | boolean | oui |  |

### `GET /map/alerts`

Niveau d'alerte de chaque zone (vert / jaune / orange / rouge) d'après les alertes publiées et non
expirées ; en cas de plusieurs alertes sur une zone, le niveau le plus élevé l'emporte. Public.

**Accès :** Public.

**Réponse 200** : AlertMap

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `zones` | liste de MapZone | oui |  |
| `national_alerts` | liste de MapAlertSummary | oui | Alertes actives sans zone précise (tout le territoire) |

### `GET /prevention-messages`

Messages de prévention par type d'alerte. Public.

**Accès :** Public.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `alert_type_id` | query |  | string (facultatif) |  |
| `alert_type_code` | query |  | string (facultatif) |  |

**Réponse 200** : liste de PreventionOut
Liste de : PreventionOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `alert_type_id` | string | oui |  |
| `text_fr` | string | oui |  |
| `text_en` | string (facultatif) | oui |  |
| `text_mos` | string (facultatif) | oui |  |
| `active` | boolean | oui |  |

### `POST /prevention-messages`

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `alert_type_id` | string | oui |  |
| `text_fr` | string | oui |  |
| `text_en` | string (facultatif) |  |  |
| `text_mos` | string (facultatif) |  |  |
| `active` | boolean |  |  |

**Réponse 201** : PreventionOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `alert_type_id` | string | oui |  |
| `text_fr` | string | oui |  |
| `text_en` | string (facultatif) | oui |  |
| `text_mos` | string (facultatif) | oui |  |
| `active` | boolean | oui |  |

### `PATCH /prevention-messages/{message_id}`

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `message_id` | path | oui | string |  |

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `text_fr` | string (facultatif) |  |  |
| `text_en` | string (facultatif) |  |  |
| `text_mos` | string (facultatif) |  |  |
| `active` | boolean (facultatif) |  |  |

**Réponse 200** : PreventionOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `alert_type_id` | string | oui |  |
| `text_fr` | string | oui |  |
| `text_en` | string (facultatif) | oui |  |
| `text_mos` | string (facultatif) | oui |  |
| `active` | boolean | oui |  |

### `DELETE /prevention-messages/{message_id}`

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `message_id` | path | oui | string |  |

**Réponse 204** : aucun contenu

### `POST /prevention-messages/{message_id}/translate`

Propose une traduction automatique (anglais : MyMemory, mooré : CITADEL/NLLB) à partir du texte français.
Résultat à relire avant diffusion. Les traductions déjà saisies ne sont pas écrasées sauf `overwrite=true`.

**Accès :** Connexion requise, permission `content:manage` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `message_id` | path | oui | string |  |

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `langs` | liste de `en` \| `mos` |  |  |
| `overwrite` | boolean |  |  |

**Réponse 200** : PreventionOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `alert_type_id` | string | oui |  |
| `text_fr` | string | oui |  |
| `text_en` | string (facultatif) | oui |  |
| `text_mos` | string (facultatif) | oui |  |
| `active` | boolean | oui |  |

### `GET /zones`

Zones (communes pilotes et régions) utilisables pour les alertes et la carte. Public.

**Accès :** Public.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `pilot_only` | query |  | boolean | Seulement les 5 communes pilotes |

**Réponse 200** : liste de ZoneOut
Liste de : ZoneOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `name` | string | oui |  |
| `kind` | ZoneKind | oui |  |
| `is_pilot` | boolean | oui |  |
| `commune_names` | liste de string | oui |  |
| `latitude` | number (facultatif) | oui |  |
| `longitude` | number (facultatif) | oui |  |

### `POST /zones`

**Accès :** Connexion requise, permission `config:manage` (rôles : Administrateur).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `name` | string | oui |  |
| `kind` | ZoneKind |  |  |
| `is_pilot` | boolean |  |  |
| `commune_names` | liste de string |  |  |
| `latitude` | number (facultatif) |  |  |
| `longitude` | number (facultatif) |  |  |
| `geometry` | dictionnaire de quelconque (facultatif) |  | GeoJSON Polygon ou MultiPolygon |

**Réponse 201** : ZoneDetail

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `name` | string | oui |  |
| `kind` | ZoneKind | oui |  |
| `is_pilot` | boolean | oui |  |
| `commune_names` | liste de string | oui |  |
| `latitude` | number (facultatif) | oui |  |
| `longitude` | number (facultatif) | oui |  |
| `geometry` | dictionnaire de quelconque (facultatif) | oui |  |

### `GET /zones/{zone_id}`

Détail d'une zone, avec son contour GeoJSON s'il est renseigné. Public.

**Accès :** Public.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `zone_id` | path | oui | string |  |

**Réponse 200** : ZoneDetail

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `name` | string | oui |  |
| `kind` | ZoneKind | oui |  |
| `is_pilot` | boolean | oui |  |
| `commune_names` | liste de string | oui |  |
| `latitude` | number (facultatif) | oui |  |
| `longitude` | number (facultatif) | oui |  |
| `geometry` | dictionnaire de quelconque (facultatif) | oui |  |

### `PATCH /zones/{zone_id}`

Modifie une zone (ex. renseigner ses coordonnées ou son contour GeoJSON fournis par l'ANAM).

**Accès :** Connexion requise, permission `config:manage` (rôles : Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `zone_id` | path | oui | string |  |

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `name` | string (facultatif) |  |  |
| `kind` | ZoneKind (facultatif) |  |  |
| `is_pilot` | boolean (facultatif) |  |  |
| `commune_names` | liste de string (facultatif) |  |  |
| `latitude` | number (facultatif) |  |  |
| `longitude` | number (facultatif) |  |  |
| `geometry` | dictionnaire de quelconque (facultatif) |  |  |

**Réponse 200** : ZoneDetail

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `name` | string | oui |  |
| `kind` | ZoneKind | oui |  |
| `is_pilot` | boolean | oui |  |
| `commune_names` | liste de string | oui |  |
| `latitude` | number (facultatif) | oui |  |
| `longitude` | number (facultatif) | oui |  |
| `geometry` | dictionnaire de quelconque (facultatif) | oui |  |

### `DELETE /zones/{zone_id}`

**Accès :** Connexion requise, permission `config:manage` (rôles : Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `zone_id` | path | oui | string |  |

**Réponse 204** : aucun contenu

## Plateforme

Configuration publique, rôles et permissions.

### `GET /config`

Configuration publique pour l'application : langues, communes, niveaux d'alerte et couleurs, source à citer.

**Accès :** Public.

**Réponse 200** : ConfigOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `platform_name` | string | oui |  |
| `default_language` | `fr` \| `en` \| `mos` | oui |  |
| `languages` | liste de LanguageInfo | oui |  |
| `communes` | liste de string | oui |  |
| `alert_levels` | liste de AlertLevelInfo | oui |  |
| `notification_channels` | liste de `push` \| `sms` \| `email` | oui |  |
| `source_citation` | string | oui | Mention de source à afficher sur les contenus |

### `POST /events`

À appeler par l'application quand un contenu est consulté (`view`), écouté (`play_audio`), regardé
(`play_video`) ou partagé (`share`) : alimente les statistiques d'usage du back-office. Connexion facultative.

**Accès :** Public. Une connexion avec droits de gestion donne accès aux contenus non publiés.

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `content_type` | `alert` \| `bulletin` \| `advisory` | oui |  |
| `content_id` | string | oui |  |
| `kind` | `view` \| `play_audio` \| `play_video` \| `share` |  |  |
| `language` | `fr` \| `en` \| `mos` (facultatif) |  |  |

**Réponse 204** : aucun contenu

### `GET /health`

Vérifie que le service répond. Public.

**Réponse 200** : aucun contenu

### `POST /me/devices`

Enregistre le jeton Firebase (FCM) de l'appareil pour recevoir les notifications push.
À appeler après chaque connexion et quand Firebase renouvelle le jeton.

**Accès :** Connexion requise (tout utilisateur connecté).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `token` | string | oui | Jeton Firebase (FCM) de l'appareil |
| `platform` | `android` \| `ios` \| `web` |  |  |

**Réponse 204** : aucun contenu

### `DELETE /me/devices`

Supprime le jeton de l'appareil (à appeler à la déconnexion).

**Accès :** Connexion requise (tout utilisateur connecté).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `token` | query | oui | string |  |

**Réponse 204** : aucun contenu

### `GET /media/{path}`

Fichier généré (audio, vidéo, image, PDF). Les médias des contenus **publiés** sont publics ; ceux
des brouillons ne sont lisibles que par le personnel (en-tête `Authorization`, ou `?token=`).
Les URLs à utiliser sont fournies dans les champs `media` / `image_url` / `pdf_url` des contenus.

**Accès :** Public. Une connexion avec droits de gestion donne accès aux contenus non publiés.

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `path` | path | oui | string |  |
| `token` | query |  | string (facultatif) | Token d'accès, pour lire un média non publié dans une balise <video>/<audio> |

**Réponse 200** : aucun contenu

### `GET /roles`

Les 5 rôles, leurs permissions, et ceux dont la connexion exige la 2FA. Public (aucune donnée sensible).

**Accès :** Public.

**Réponse 200** : RolesOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `roles` | liste de RoleInfo | oui |  |
| `permissions` | dictionnaire de string | oui | Code de permission -> description |

## Administration

Comptes utilisateurs, rôles, statistiques par commune.

### `GET /admin/stats/communes`

Répartition des comptes actifs par commune.

**Accès :** Connexion requise, permission `stats:read` (rôles : Responsable communal, Agent ANAM, Administrateur).

**Réponse 200** : liste de CommuneStat
Liste de : CommuneStat

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `commune` | string | oui |  |
| `users` | integer | oui |  |

### `GET /admin/users`

**Accès :** Connexion requise, permission `users:read` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `status` | query |  | UserStatus (facultatif) | ex. pending = comptes à valider |
| `role` | query |  | Role (facultatif) |  |
| `commune` | query |  | string (facultatif) |  |
| `q` | query |  | string (facultatif) | recherche dans nom, e-mail, téléphone, identifiant |
| `limit` | query |  | integer |  |
| `offset` | query |  | integer |  |

**Réponse 200** : UserList

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `total` | integer | oui |  |
| `items` | liste de UserOut | oui |  |

### `POST /admin/users`

Crée un compte (agent ANAM, administrateur, responsable communal…), actif immédiatement.
L'utilisateur devra changer son mot de passe initial à sa première connexion.

**Accès :** Connexion requise, permission `users:manage` (rôles : Administrateur).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `phone` | string (facultatif) |  |  |
| `email` | string (email) (facultatif) |  |  |
| `username` | string (facultatif) |  |  |
| `password` | string | oui |  |
| `role` | Role | oui |  |
| `full_name` | string (facultatif) |  |  |
| `commune` | string (facultatif) |  |  |

**Réponse 201** : UserOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `phone` | string (facultatif) | oui |  |
| `email` | string (facultatif) | oui |  |
| `username` | string (facultatif) | oui |  |
| `full_name` | string (facultatif) | oui |  |
| `role` | Role | oui |  |
| `status` | UserStatus | oui |  |
| `commune` | string (facultatif) | oui |  |
| `language` | Language | oui |  |
| `notification_channels` | liste de Channel | oui |  |
| `totp_enabled` | boolean | oui |  |
| `must_change_password` | boolean | oui |  |
| `created_at` | string (date-time) | oui |  |
| `last_login_at` | string (date-time) (facultatif) | oui |  |

### `GET /admin/users/{user_id}`

**Accès :** Connexion requise, permission `users:read` (rôles : Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `user_id` | path | oui | string |  |

**Réponse 200** : UserOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `phone` | string (facultatif) | oui |  |
| `email` | string (facultatif) | oui |  |
| `username` | string (facultatif) | oui |  |
| `full_name` | string (facultatif) | oui |  |
| `role` | Role | oui |  |
| `status` | UserStatus | oui |  |
| `commune` | string (facultatif) | oui |  |
| `language` | Language | oui |  |
| `notification_channels` | liste de Channel | oui |  |
| `totp_enabled` | boolean | oui |  |
| `must_change_password` | boolean | oui |  |
| `created_at` | string (date-time) | oui |  |
| `last_login_at` | string (date-time) (facultatif) | oui |  |

### `POST /admin/users/{user_id}/activate`

Valide un compte en attente (ex. compte local) ou réactive un compte désactivé.

**Accès :** Connexion requise, permission `users:manage` (rôles : Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `user_id` | path | oui | string |  |

**Réponse 200** : UserOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `phone` | string (facultatif) | oui |  |
| `email` | string (facultatif) | oui |  |
| `username` | string (facultatif) | oui |  |
| `full_name` | string (facultatif) | oui |  |
| `role` | Role | oui |  |
| `status` | UserStatus | oui |  |
| `commune` | string (facultatif) | oui |  |
| `language` | Language | oui |  |
| `notification_channels` | liste de Channel | oui |  |
| `totp_enabled` | boolean | oui |  |
| `must_change_password` | boolean | oui |  |
| `created_at` | string (date-time) | oui |  |
| `last_login_at` | string (date-time) (facultatif) | oui |  |

### `POST /admin/users/{user_id}/disable`

Désactive un compte et ferme toutes ses sessions.

**Accès :** Connexion requise, permission `users:manage` (rôles : Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `user_id` | path | oui | string |  |

**Réponse 200** : UserOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `phone` | string (facultatif) | oui |  |
| `email` | string (facultatif) | oui |  |
| `username` | string (facultatif) | oui |  |
| `full_name` | string (facultatif) | oui |  |
| `role` | Role | oui |  |
| `status` | UserStatus | oui |  |
| `commune` | string (facultatif) | oui |  |
| `language` | Language | oui |  |
| `notification_channels` | liste de Channel | oui |  |
| `totp_enabled` | boolean | oui |  |
| `must_change_password` | boolean | oui |  |
| `created_at` | string (date-time) | oui |  |
| `last_login_at` | string (date-time) (facultatif) | oui |  |

### `POST /admin/users/{user_id}/reset-2fa`

Réinitialise la 2FA (téléphone perdu) : l'utilisateur devra la reconfigurer à sa prochaine connexion.

**Accès :** Connexion requise, permission `users:manage` (rôles : Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `user_id` | path | oui | string |  |

**Réponse 200** : MessageResponse

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `message` | string | oui |  |

### `PATCH /admin/users/{user_id}/role`

**Accès :** Connexion requise, permission `roles:assign` (rôles : Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `user_id` | path | oui | string |  |

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `role` | Role | oui |  |

**Réponse 200** : UserOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `phone` | string (facultatif) | oui |  |
| `email` | string (facultatif) | oui |  |
| `username` | string (facultatif) | oui |  |
| `full_name` | string (facultatif) | oui |  |
| `role` | Role | oui |  |
| `status` | UserStatus | oui |  |
| `commune` | string (facultatif) | oui |  |
| `language` | Language | oui |  |
| `notification_channels` | liste de Channel | oui |  |
| `totp_enabled` | boolean | oui |  |
| `must_change_password` | boolean | oui |  |
| `created_at` | string (date-time) | oui |  |
| `last_login_at` | string (date-time) (facultatif) | oui |  |

## Back-office

Tableau de bord, suivi des diffusions, paramètres.

### `GET /backoffice/broadcasts`

Historique des diffusions (automatiques et manuelles), les plus récentes d'abord.

**Accès :** Connexion requise, permission `stats:read` (rôles : Responsable communal, Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `content_type` | query |  | string (facultatif) |  |
| `content_id` | query |  | string (facultatif) |  |
| `limit` | query |  | integer |  |
| `offset` | query |  | integer |  |

**Réponse 200** : BroadcastList

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `total` | integer | oui |  |
| `items` | liste de BroadcastOut | oui |  |

### `GET /backoffice/broadcasts/{broadcast_id}`

Suivi d'une diffusion : décompte par canal et statut, et détail des envois (filtrables). Statut `simulated`
= envoi simulé (mode développement, rien n'est parti).

**Accès :** Connexion requise, permission `stats:read` (rôles : Responsable communal, Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `broadcast_id` | path | oui | string |  |
| `channel` | query |  | string (facultatif) |  |
| `status` | query |  | string (facultatif) |  |
| `limit` | query |  | integer |  |

**Réponse 200** : BroadcastDetail

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | string | oui |  |
| `content_type` | string | oui |  |
| `content_id` | string | oui |  |
| `status` | string | oui |  |
| `trigger` | string | oui |  |
| `created_at` | string (date-time) | oui |  |
| `finished_at` | string (date-time) (facultatif) | oui |  |
| `target_count` | integer | oui |  |
| `sent_count` | integer | oui |  |
| `failed_count` | integer | oui |  |
| `note` | string (facultatif) | oui |  |
| `by_channel` | dictionnaire de dictionnaire de integer | oui | Décompte des envois par canal et par statut |
| `deliveries` | liste de DeliveryOut | oui |  |

### `GET /backoffice/dashboard`

Indicateurs du tableau de bord : comptes, contenus diffusés, envois par canal, usage des 7 derniers jours.

**Accès :** Connexion requise, permission `stats:read` (rôles : Responsable communal, Agent ANAM, Administrateur).

**Réponse 200** : DashboardOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `users` | DashboardUsers | oui |  |
| `content` | DashboardContent | oui |  |
| `diffusion` | DashboardDiffusion | oui |  |
| `usage_last_7_days` | dictionnaire de integer | oui | type d'événement -> nombre |

### `GET /backoffice/settings`

Paramètres généraux de la plateforme et de la diffusion (valeurs actuelles, défauts inclus).

**Accès :** Connexion requise, permission `config:manage` (rôles : Administrateur).

**Réponse 200** : dictionnaire de quelconque

### `PUT /backoffice/settings`

Modifie un ou plusieurs paramètres : `{"values": {"diffusion.channels": {...}}}`. Clés inconnues refusées.

**Accès :** Connexion requise, permission `config:manage` (rôles : Administrateur).

**Corps de la requête (JSON)**

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `values` | dictionnaire de quelconque | oui | Paramètres à modifier : {clé: valeur} |

**Réponse 200** : dictionnaire de quelconque

### `GET /backoffice/sms-pilot`

Suivi du pilote SMS (objectif : 500 utilisateurs) : envois par statut, destinataires distincts, avancement.

**Accès :** Connexion requise, permission `stats:read` (rôles : Responsable communal, Agent ANAM, Administrateur).

**Réponse 200** : SmsPilotOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `target_users` | integer | oui |  |
| `users_opted_in_sms` | integer | oui | Comptes actifs ayant choisi le SMS |
| `distinct_recipients_reached` | integer | oui |  |
| `deliveries_by_status` | dictionnaire de integer | oui |  |
| `progress` | number (facultatif) | oui | Avancement vers l'objectif, entre 0 et 1 |

### `GET /backoffice/usage`

Statistiques d'usage (consultations, écoutes, lectures vidéo, partages) par jour, par langue, et contenus les plus vus.

**Accès :** Connexion requise, permission `stats:read` (rôles : Responsable communal, Agent ANAM, Administrateur).

**Paramètres**

| Nom | Où | Obligatoire | Type | Description |
|---|---|---|---|---|
| `days` | query |  | integer |  |

**Réponse 200** : UsageOut

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `days` | integer | oui |  |
| `by_day` | dictionnaire de dictionnaire de integer | oui | date -> type d'événement -> nombre |
| `by_language` | dictionnaire de integer | oui |  |
| `top_content` | liste de TopContent | oui |  |

## Valeurs possibles (énumérations)

| Type | Valeurs |
|---|---|
| `AdvisoryKind` | `conseil`, `planification` |
| `AlertLevel` | `jaune`, `orange`, `rouge` |
| `Channel` | `sms`, `push`, `email` |
| `ContentStatus` | `draft`, `published`, `cancelled`, `archived` |
| `Language` | `fr`, `mos`, `en` |
| `MediaStatus` | `none`, `processing`, `ready`, `failed` |
| `Role` | `grand_public`, `responsable_communal`, `agent_anam`, `observateur`, `administrateur` |
| `UserStatus` | `pending`, `active`, `disabled` |
| `ZoneKind` | `commune`, `region` |
