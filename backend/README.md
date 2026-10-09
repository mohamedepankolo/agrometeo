# Backend ANAM-BF — API de la plateforme agrométéo

Une seule application **FastAPI** (PostgreSQL en production, SQLite pour développer) qui regroupe :
authentification et rôles, bulletins et alertes avec audios/vidéos en français, anglais et mooré (Module 1),
avis, zones et carte des alertes, prévisions WRF par zone (Module 3), diffusion multicanale (SMS, push,
e-mail, WhatsApp) et back-office. Le Module 2 (observations GeoJSON) s'y ajoutera quand les fichiers de
l'ANAM seront fournis.

```
backend/
  app/                 le service (routers/ = les routes, par domaine)
  testui/app.py        interface de test (Streamlit)
  tests/               90 tests automatiques
  docs/                GUIDE_FRONTEND.md · API_REFERENCE.md · openapi.json  (à remettre aux front-end)
  scripts/export_docs.py   régénère la documentation depuis le code
../module1/            la chaîne audio/vidéo (appelée par le backend)
../module3/            lecture des fichiers de prévisions WRF/NetCDF (appelée par le backend)
```

## Démarrer

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt -r requirements-testui.txt
copy .env.example .env            # puis renseigner CITADEL_* / MOORE_* (mêmes valeurs que module1/.env)
python -m app.seed_demo           # 5 comptes de démonstration (un par rôle) — développement seulement
uvicorn app.main:app --reload     # API sur http://localhost:8000  (documentation interactive : /docs)
streamlit run testui/app.py       # interface de test sur http://localhost:8501
```

Il faut aussi **ffmpeg** installé (génération des vidéos). Le premier lancement télécharge le modèle de traduction anglaise (~300 Mo, une seule fois). Comptes de démonstration, mot de passe `Demo1234!` :
`admin@demo.test`, `agent@demo.test`, `commune@demo.test`, `observateur@demo.test`, `citoyen@demo.test`
(admin et agent configurent la 2FA à leur première connexion). Premier administrateur *réel* : `python -m app.create_admin --email ...`.

## Interface de test

`streamlit run testui/app.py` (l'API doit tourner). Elle appelle l'API exactement comme une application :
- **Inscription et connexion** : les 3 modes d'inscription, validation du code (le code « SMS » se récupère d'un clic), connexion, 2FA (secret et code calculés pour vous).
- **Profil**, **Rôles et permissions** (matrice + bouton « tester mes accès »), **Administration des comptes** (filtres, création de comptes internes, rôles, activation, réinitialisation 2FA).
- **Bulletins** (import d'un PDF, génération, lecteurs vidéo/audio, publication, diffusion, texte WhatsApp), **Alertes** (même parcours + zones, niveau, aperçu du découpage du texte), **Avis et conseils** (avec traduction automatique).
- **Carte des alertes** (niveau par zone), **Diffusion et back-office** (tableau de bord, suivi de chaque envoi, paramètres, pilote SMS).
- **Base de données et état** : tables et lignes (secrets masqués), messages « envoyés » en simulation, état de la configuration (ffmpeg, CITADEL…).

## Les rôles : comment ça marche

Un compte a **un rôle**, et chaque rôle donne des **permissions** ; chaque route de l'API exige une permission (ou est publique).
La matrice est dans [app/rbac.py](app/rbac.py) et lisible par tous sur `GET /roles`.

| Permission | Grand public | Observateur | Resp. communal | Agent ANAM | Admin |
|---|:-:|:-:|:-:|:-:|:-:|
| `content:read` — consulter bulletins, alertes, avis, carte | ✔ | ✔ | ✔ | ✔ | ✔ |
| `observations:write` — saisir des observations | | ✔ | | ✔ | ✔ |
| `stats:read` — tableau de bord, statistiques, suivi des diffusions | | | ✔ | ✔ | ✔ |
| `users:read` — consulter les comptes | | | | ✔ | ✔ |
| `content:manage` — créer/modifier bulletins, alertes, avis (brouillons) | | | | ✔ | ✔ |
| `content:publish` — publier, annuler, diffuser | | | | ✔ | ✔ |
| `users:manage` — créer, activer, désactiver des comptes | | | | | ✔ |
| `roles:assign` — attribuer des rôles | | | | | ✔ |
| `config:manage` — paramètres, zones, canaux de diffusion | | | | | ✔ |
| 2FA obligatoire à la connexion | | | | ✔ | ✔ |

**Comment un compte obtient son rôle**
1. Toute inscription publique crée un `grand_public` (impossible de choisir un autre rôle en s'inscrivant).
2. Les comptes internes (agent, responsable communal, observateur, administrateur) sont créés **par un administrateur** (`POST /admin/users`) ou, pour un compte existant, promus par `PATCH /admin/users/{id}/role`. Le compte créé doit changer son mot de passe initial.
3. Le tout premier administrateur se crée en ligne de commande : `python -m app.create_admin`.
4. Un administrateur ne peut ni se rétrograder ni se désactiver lui-même (pas de blocage accidentel). Changer un rôle prend effet **immédiatement** (le rôle est relu en base à chaque appel).

**Protéger une nouvelle route** : `Depends(require_permission("content:manage"))`. Pour changer ce qu'un rôle peut faire : modifier `ROLE_PERMISSIONS` — rien d'autre à toucher, et la documentation de l'API se met à jour toute seule (`python scripts/export_docs.py`).

## Cycle de vie des contenus

```
Alerte  :  brouillon ─► (image + génération des médias) ─► publiée ─► annulée
Bulletin:  brouillon (PDF importé, médias générés) ─► publié ─► archivé
Avis    :  brouillon ─► publié ─► retiré
```
- Seuls les contenus **publiés** sont visibles du public ; un brouillon est invisible (404) hors droits de gestion.
- Une alerte a un niveau (`jaune`, `orange`, `rouge`), des zones, un type (orages, fortes pluies, inondations, vents violents, poussière, chaleur, sécheresse) et une **date de fin de validité** : passée cette date, elle quitte la carte et `active_only`.
- La carte donne à chaque zone le niveau le plus élevé de ses alertes actives (`vert` sinon).
- La génération audio/vidéo est **asynchrone** (1 à 3 min, `media.status` : `none`/`processing`/`ready`/`failed`). Une alerte peut être publiée en texte seul si la génération échoue.

## Prévisions (Module 3)

Les fichiers de sortie du modèle WRF (NetCDF, ~5 Go chacun, fournis par l'ANAM sur support physique —
jamais par upload HTTP) sont déposés dans `wrf_incoming_dir` (hors stockage applicatif, jamais
versionnés), puis ingérés un par un :

1. `GET /forecasts/incoming` — fichiers en attente dans ce dossier.
2. `POST /forecasts/ingest {"filename": "..."}` (`content:manage`) — lit le fichier et calcule, pour
   chaque zone qui a des coordonnées (les 351 communes officielles, voir plus bas), un résumé du
   jour couvert (température min/max/moyenne, précipitations, vent moyen/max, humidité). Réponse
   immédiate (`status=processing`) ; relire `GET /forecasts/runs/{id}` jusqu'à `ready`/`failed`.
3. `GET /forecasts` — résultats, **publics** comme les autres contenus de référence. Trois façons
   de choisir les zones (combinables avec `?forecast_date=AAAA-MM-JJ`) : sans filtre (toutes les
   communes), `?pilot_only=true` (seulement les 5 pilotes), ou une seule commune par `?zone_id=...`
   (identifiant, via `GET /zones`) ou `?zone_name=Kaya` (nom exact, pratique quand on ne connaît
   pas l'identifiant).

Détails (format des fichiers, calculs, piège des `:` dans les noms de fichiers sous Windows) dans
[module3/README.md](../module3/README.md).

## Diffusion

À la publication (automatique ou manuelle), le système :
1. **cible** : une alerte avec zones → utilisateurs dont la commune correspond ; sinon → tous les comptes actifs ;
2. **filtre les canaux** : ceux choisis par l'utilisateur (`/me`) **et** activés pour ce type de contenu dans les paramètres (`diffusion.channels`, le SMS est réservé aux alertes) ;
3. **rédige** un message adapté à chaque canal et à la langue de l'utilisateur (SMS ≤ 320 caractères, push court, e-mail complet avec liens) ;
4. **envoie et trace** chaque envoi (`sent`, `simulated`, `failed` + erreur) ; les jetons d'appareils morts sont supprimés.

WhatsApp : envoi aux numéros listés dans le paramètre `diffusion.whatsapp_recipients` via l'API WhatsApp Business, **et** bouton de secours `share-kit` (texte formaté prêt à coller dans un groupe ou une chaîne). Attention : à ma connaissance, l'API officielle ne permet pas de publier *dans une chaîne ou un groupe* WhatsApp ; c'est le point à vérifier avec Meta/l'ANAM (le `share-kit` couvre ce cas).

En développement, tous les canaux sont **simulés** (`*_BACKEND=console`) : rien ne part, les messages sont visibles dans l'interface de test.
Les backends réels (Orange, FCM, SMTP, WhatsApp Cloud) sont écrits mais **non essayés en réel** faute d'identifiants (testés seulement contre des serveurs simulés).

## Configuration

Toutes les variables sont dans [.env.example](.env.example). Points clés : `ENV=prod` impose `JWT_SECRET` et interdit les envois simulés et les routes `/dev/*` ; `DATABASE_URL` pour PostgreSQL ; `PUBLIC_BASE_URL` pour des liens de médias absolus (à renseigner pour les e-mails et WhatsApp).
Les paramètres métier (canaux par type de contenu, diffusion automatique, numéros WhatsApp, durée de validité des alertes, longueur des SMS, objectif du pilote SMS…) se modifient **sans redéploiement** dans le back-office (`PUT /backoffice/settings`).

## Sécurité en place

Mots de passe argon2 · jetons JWT courts + refresh à usage unique avec détection de vol · 2FA TOTP (secrets chiffrés) · verrouillage après 5 échecs · pas d'énumération de comptes · codes de vérification hachés et limités en essais · rôle relu en base à chaque requête · fichiers envoyés contrôlés (type réel, taille) · accès aux médias non publiés protégé · journal d'audit (`auth.audit`) · en-têtes de sécurité, HSTS en production.

## Ce qu'il reste à fournir ou décider pour la mise en production

**Accès externes (bloquants pour les envois réels)**
- API SMS Orange : identifiants (client id/secret) et numéro expéditeur → `SMS_BACKEND=orange`.
- Serveur SMTP du domaine ANAM → `EMAIL_BACKEND=smtp`.
- Projet Firebase (fichier de compte de service) et lien avec l'application mobile → `PUSH_BACKEND=fcm`.
- Compte WhatsApp Business (Cloud API) si l'envoi automatique est retenu, et décision sur les chaînes/groupes.

**Données de l'ANAM**
- Contours (GeoJSON) des communes et régions : à charger via `PATCH /zones/{id}` ; sans cela la carte ne peut pas dessiner les zones, et le Module 3 n'extrait les prévisions qu'au point le plus proche (pas de moyenne sur la zone, cf. `module3/README.md`). Coordonnées ponctuelles des 351 communes déjà renseignées (source officielle OCHA/IGB, pas une approximation — voir `module3/README.md`) ; à faire valider par l'ANAM malgré tout, et contours toujours à fournir.
- Rattachement régions → communes (`commune_names`) pour cibler les utilisateurs quand une alerte vise une région (Liptako, Goulmou, Tapoa, Nakambé, Sirba…).
- Fichiers d'exemple GeoJSON (observations) → Module 2. Le Module 3 (prévisions NetCDF) a reçu 3 fichiers de test (sur une trentaine annoncés) et est déjà intégré ; l'ingestion du reste n'a pas encore été automatisée (cf. `module3/README.md`).

**Validations métier**
- Matrice des permissions ci-dessus ; rôles soumis à la 2FA ; comptes locaux validés ou non par un administrateur.
- Messages de prévention et libellés des types d'alerte (propositions rédigées à partir de vos exemples) ; durée de validité par défaut d'une alerte ; niveaux jaune/orange/rouge et leur signification.
- Textes fixes en mooré (formules d'ouverture/clôture, intitulés) et traductions : relecture par des locuteurs natifs (cf. `module1/README.md`).
- Texte des SMS et des e-mails de vérification.

**Infrastructure**
- Instance PostgreSQL, nom de domaine et certificat TLS, serveur avec ffmpeg, volume de stockage pour les fichiers générés, sauvegardes.
- URL **stable** pour le service de voix mooré (aujourd'hui un tunnel ngrok) et remplacement du service gratuit de voix française/anglaise (Edge TTS). La traduction française → anglaise est désormais faite **localement** (modèle opus-mt-fr-en : hors ligne, sans quota, ~1 Go de RAM) ; MyMemory ne sert plus que de secours.
- Migrations de base de données (Alembic) avant la production ; test complet sur PostgreSQL (aujourd'hui testé sur SQLite) ; scan de vulnérabilités et non-objection de l'ANAM.

## Tests

`pytest` (90 tests) : authentification, rôles et permissions, cycle de vie des alertes/bulletins/avis, ciblage et suivi des diffusions, carte, paramètres, canaux d'envoi (Orange, FCM, WhatsApp contre des serveurs simulés), prévisions WRF (Module 3, sur un fichier NetCDF synthétique mais structurellement identique aux fichiers réels), documentation. La génération audio/vidéo du Module 1 y est simulée (aucun appel réseau) ; elle a été vérifiée séparément en réel de bout en bout. Le Module 3 a aussi été vérifié contre les 3 vrais fichiers WRF reçus (hors suite automatisée : ~5 Go chacun).
