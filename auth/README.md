# Authentification — service ANAM-BF

API d'inscription, de connexion (avec 2FA), de gestion du profil, des rôles et des
permissions de la plateforme agrométéorologique. **FastAPI + SQLAlchemy, PostgreSQL
en production (SQLite pour développer), jetons JWT, mots de passe hachés avec argon2.**

Documentation interactive de toutes les routes (à donner aux équipes mobile et
back-office) : `http://localhost:8000/docs` une fois le service lancé.

## Lancer en local

```bash
cd auth
python -m venv .venv && .venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env                                 # puis adapter si besoin
python -m app.create_admin --email admin@anam.bf       # premier administrateur
uvicorn app.main:app --reload
pytest                                                 # 35 tests
```

En développement, les codes de vérification (SMS / e-mail) ne sont **pas envoyés** :
ils s'affichent dans les logs du serveur (`SMS_BACKEND=console`). Sans `JWT_SECRET`,
un secret éphémère est généré (les sessions sautent au redémarrage) ; en production
le service refuse de démarrer sans secret ni backend d'envoi réel.

## Parcours à implémenter côté mobile / back-office

**Inscription grand public**
1. `POST /auth/register` avec `method` = `phone` | `email` | `local` (+ le champ correspondant
   `phone` / `email` / `username`, `password`, et optionnellement `commune`, `language`, `full_name`).
2. Téléphone ou e-mail : un code à 6 chiffres est envoyé → `POST /auth/verify {identifier, code}`
   active le compte (10 min de validité, 3 essais ; `POST /auth/resend-code` pour un nouveau code).
3. Compte local : activé par un administrateur (`POST /admin/users/{id}/activate`), sauf si
   `LOCAL_ACCOUNT_AUTO_ACTIVATE=true`.

**Connexion** — `POST /auth/login {identifier, password}` (téléphone, e-mail ou identifiant local).
La réponse contient l'un de ces trois cas :

| Champ renseigné | Signification | Suite |
|---|---|---|
| `tokens` | Connexion terminée | Stocker `access_token` (15 min) et `refresh_token` (30 j) |
| `requires_2fa` + `challenge_token` | Compte protégé par 2FA | `POST /auth/2fa/verify {challenge_token, code}` → `tokens` |
| `requires_2fa_setup` + `setup_token` | Rôle qui exige la 2FA, pas encore configurée | `POST /auth/2fa/setup` (avec `Authorization: Bearer <setup_token>`) → afficher `otpauth_uri` en QR code ; puis `POST /auth/2fa/enable {code}` → `tokens` |

La 2FA est exigée pour les rôles `administrateur` et `agent_anam` (`REQUIRE_2FA_ROLES`) ; c'est
du TOTP standard (Google Authenticator, Microsoft Authenticator, Aegis…).

**Appels authentifiés** — en-tête `Authorization: Bearer <access_token>`.

**Renouvellement** — `POST /auth/refresh {refresh_token}` renvoie une nouvelle paire.
Le refresh token est **à usage unique** : toujours remplacer celui qu'on stocke par le nouveau.
Réutiliser un ancien refresh token ferme toutes les sessions du compte (protection contre le vol).

**Déconnexion** — `POST /auth/logout {refresh_token}` (cet appareil) ou `POST /auth/logout-all`.

**Profil** — `GET /me`, `PATCH /me` (commune, langue, canaux de réception des alertes),
`POST /me/password`. Si `must_change_password` est vrai (compte créé par un administrateur),
forcer l'écran de changement de mot de passe.

Valeurs autorisées : communes `Kaya`, `Ziniaré`, `Zitenga`, `Absouya`, `Korsimoro` ;
langues `fr`, `mos`, `en` ; canaux `sms`, `push`, `email` (SMS/e-mail exigent que le compte
ait un téléphone / une adresse e-mail).

**Administration (back-office)** — `GET /admin/users` (filtres `status`, `role`, `commune`, `q`,
pagination ; `status=pending` = comptes à valider), `POST /admin/users` (créer un agent/admin),
`PATCH /admin/users/{id}/role`, `POST /admin/users/{id}/activate|disable|reset-2fa`,
`GET /admin/stats/communes`.

## Protéger les routes des autres modules

Les modules 1, 2, 3, alertes, diffusion et back-office n'ont pas à retester les rôles :

```python
from app.rbac import require_permission

@router.post("/bulletins")
def create_bulletin(user = Depends(require_permission("content:manage"))): ...
```

Si les modules tournent dans des services séparés, ils valident le JWT (`typ = "access"`, HS256,
même `JWT_SECRET`) puis lisent le rôle en base, ou appellent `GET /me`.

Permissions par rôle (**proposition à valider avec l'ANAM**, cf. `app/rbac.py`) :

| Rôle | Permissions |
|---|---|
| `grand_public` | `content:read` |
| `observateur` | `content:read`, `observations:write` |
| `responsable_communal` | `content:read`, `stats:read` |
| `agent_anam` | + `content:manage`, `observations:write`, `users:read` |
| `administrateur` | toutes (dont `users:manage`, `roles:assign`, `config:manage`) |

## Sécurité mise en place

- Mots de passe : argon2id, 8 caractères minimum ; jamais journalisés ni renvoyés.
- Verrouillage du compte 15 min après 5 échecs (mot de passe ou code 2FA).
- Même réponse pour « identifiant inconnu » et « mauvais mot de passe », temps de calcul identique
  (pas d'énumération de comptes) ; `resend-code` répond pareil que le compte existe ou non.
- Codes de vérification : stockés hachés, expiration, nombre d'essais limité, un seul code valide à la fois.
- Refresh tokens opaques stockés hachés, rotation + détection de réutilisation.
- Secrets 2FA chiffrés en base (Fernet) ; un code TOTP ne peut pas être rejoué.
- Un compte désactivé perd l'accès immédiatement (le rôle et le statut sont relus en base à chaque requête).
- Le rôle ne peut pas être choisi à l'inscription ni modifié via `/me` ; un administrateur ne peut
  pas se rétrograder ni se désactiver lui-même.
- Événements sensibles journalisés (logger `auth.audit`) : échecs de connexion, verrouillages,
  changements de rôle, activations, réutilisation de jeton.

## Ce qui reste à faire / à décider

- **SMS Orange** : l'interface d'envoi existe (`app/notifications.py`), le branchement à l'API Orange
  est à faire dès qu'on dispose des identifiants. E-mail : `EMAIL_BACKEND=smtp` fonctionne avec un
  serveur SMTP (domaine ANAM) mais n'a pas été testé sur un vrai serveur.
- **PostgreSQL** : le code est portable et testé sur SQLite uniquement ; à valider sur PostgreSQL
  (`pip install "psycopg[binary]"`, `DATABASE_URL=postgresql+psycopg://...`). Les tables sont créées
  automatiquement au démarrage ; prévoir **Alembic** pour les migrations avant la production.
- **TLS** : à terminer au niveau du déploiement (reverse proxy ou uvicorn avec certificat) ; le service
  envoie déjà `Strict-Transport-Security` quand `ENV=prod`.
- **Limitation de débit par adresse IP** (en plus du verrouillage par compte) : à faire au niveau de la
  passerelle ou avec `slowapi`.
- **Codes de récupération 2FA** : non implémentés ; la reprise passe par `POST /admin/users/{id}/reset-2fa`.
- Points à valider avec l'ANAM : matrice des permissions ci-dessus, comptes locaux validés ou non par
  un administrateur, rôles soumis à la 2FA, contenu exact du SMS de vérification.
- Scan de vulnérabilités et non-objection de l'ANAM avant mise en production (cf. suivi des tâches).
