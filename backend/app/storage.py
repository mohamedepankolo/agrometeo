"""Stockage local des fichiers (PDF, images, audios, vidéos). Les chemins en base sont RELATIFS
à STORAGE_DIR, pour pouvoir déplacer le dossier (ou passer plus tard à un stockage objet)."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from .config import get_settings

_MAGIC = {
    "pdf": [b"%PDF"],
    "image": [b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"],  # JPEG, PNG
}
_EXT = {b"\xff\xd8\xff": ".jpg", b"\x89PNG\r\n\x1a\n": ".png", b"%PDF": ".pdf"}


def root() -> Path:
    p = Path(get_settings().storage_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def content_dir(kind: str, content_id: str) -> Path:
    d = root() / kind / content_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel(path: Path) -> str:
    return path.resolve().relative_to(root()).as_posix()


def absolute(rel_path: str) -> Path:
    p = (root() / rel_path).resolve()
    if root() not in p.parents:
        raise ValueError("chemin hors du stockage")
    return p


def media_url(rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    return f"{get_settings().public_base_url.rstrip('/')}/media/{rel_path}"


def save_upload(upload: UploadFile, dest_dir: Path, basename: str, expected: str) -> Path:
    """Enregistre un fichier envoyé après avoir vérifié sa taille et son type réel (pas seulement l'extension)."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Fichier trop volumineux (max {get_settings().max_upload_mb} Mo).")
    magic = next((m for m in _MAGIC[expected] if data.startswith(m)), None)
    if magic is None:
        label = "PDF" if expected == "pdf" else "JPEG ou PNG"
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Le fichier doit être un {label} valide.")
    dest = dest_dir / f"{basename}{_EXT[magic]}"
    for old in dest_dir.glob(f"{basename}.*"):
        old.unlink(missing_ok=True)
    dest.write_bytes(data)
    return dest
