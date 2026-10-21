# Image du backend ANAM-BF (API) -- auto-suffisante : ffmpeg (Module 1) installé dans l'image,
# aucun paquet système requis sur la machine hôte. Contexte de build = racine du dépôt (le
# backend a besoin de module1/, module2/ et module3/ comme dossiers frères, cf. *_bridge.py).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
# torch CPU-only d'abord : ce serveur n'a pas de GPU, et le paquet par defaut tire ~1.4 Go de
# bibliotheques CUDA inutiles (cause d'un echec de build par timeout reseau le 21/10/2026).
# Une fois installe, `pip install -r requirements.txt` le laisse tel quel (version deja
# satisfaite) au lieu de retelecharger la variante GPU.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY module1/ module1/
COPY module2/ module2/
COPY module3/ module3/

WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
