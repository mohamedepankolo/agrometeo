from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import init_db
from .routers import admin, auth, me


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # échoue tôt si la configuration est invalide (ex. JWT_SECRET en prod)
    init_db()
    yield


app = FastAPI(
    title="ANAM-BF — Authentification",
    description="Inscription, connexion (+ 2FA), profil, rôles et permissions de la plateforme agrométéorologique.",
    version="0.1.0",
    lifespan=lifespan,
)

_settings = get_settings()
if _settings.cors_origin_list:
    app.add_middleware(CORSMiddleware, allow_origins=_settings.cors_origin_list, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    if get_settings().is_prod:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.include_router(auth.router)
app.include_router(me.router)
app.include_router(admin.router)


@app.get("/health", tags=["Technique"])
def health():
    return {"status": "ok"}
