from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api_docs import annotate_access
from .config import get_settings
from .db import init_db, new_session
from .routers import admin, advisories, alerts, auth, backoffice, bulletins, dev, me, platform, reference
from .seed import seed_reference_data

DESCRIPTION = """
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
"""

TAGS = [
    {"name": "Authentification", "description": "Inscription, connexion, 2FA, sessions."},
    {"name": "Profil", "description": "Profil de l'utilisateur connecté : commune, langue, canaux de notification, appareils."},
    {"name": "Bulletins", "description": "Bulletins agrométéorologiques avec audios et vidéos (français, anglais, mooré)."},
    {"name": "Alertes", "description": "Alertes météo : saisie, médias, publication, diffusion."},
    {"name": "Avis et conseils", "description": "Avis et conseils, avis de planification anticipée."},
    {"name": "Zones, carte et référentiels", "description": "Zones, carte des alertes par couleur, types d'alerte, messages de prévention."},
    {"name": "Plateforme", "description": "Configuration publique, rôles et permissions."},
    {"name": "Médias", "description": "Fichiers audio, vidéo, image et PDF."},
    {"name": "Statistiques d'usage", "description": "Événements de consultation envoyés par l'application."},
    {"name": "Administration", "description": "Comptes utilisateurs, rôles, statistiques par commune."},
    {"name": "Back-office", "description": "Tableau de bord, suivi des diffusions, paramètres."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # échoue tôt si la configuration est invalide (ex. JWT_SECRET en prod)
    init_db()
    db = new_session()
    try:
        seed_reference_data(db)
    finally:
        db.close()
    yield


app = FastAPI(title="ANAM-BF - API de la plateforme agrométéo", description=DESCRIPTION, version="1.0.0",
              openapi_tags=TAGS, lifespan=lifespan)

_settings = get_settings()
if _settings.cors_origin_list:
    app.add_middleware(CORSMiddleware, allow_origins=_settings.cors_origin_list, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    if not request.url.path.startswith("/media/"):
        response.headers["Cache-Control"] = "no-store"
    if get_settings().is_prod:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


_routers = [auth, me, platform, reference, bulletins, alerts, advisories, admin, backoffice]
if _settings.dev_tools:
    _routers.append(dev)
for module in _routers:
    annotate_access(module.router)
    app.include_router(module.router)


@app.get("/health", tags=["Plateforme"])
def health():
    """Vérifie que le service répond. Public."""
    return {"status": "ok"}
