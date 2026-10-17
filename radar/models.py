"""Modelo de datos normalizado: una pieza pública de contenido, sin datos personales."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

_SALT = os.environ.get("RADAR_HASH_SALT", "radar-30x")

_MENTION = re.compile(r"(?<!\w)@[\w.\-]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def anonymize_author(raw_id: str) -> str:
    """Hash irreversible del autor: sirve para contar autores distintos, no para identificarlos."""
    return hashlib.sha256(f"{_SALT}:{raw_id}".encode()).hexdigest()[:12]


def scrub(text: str) -> str:
    """Quita menciones, correos y teléfonos del texto antes de guardarlo o enviarlo a un modelo."""
    text = _EMAIL.sub("[correo]", text)
    text = _MENTION.sub("@usuario", text)
    text = _PHONE.sub("[teléfono]", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Post:
    id: str
    platform: str            # bluesky | hackernews | youtube | google_news | linkedin | instagram | tiktok ...
    url: str
    text: str                # título + cuerpo, ya limpio con scrub()
    created_at: datetime     # UTC
    author_hash: str
    publisher: str = ""      # solo para organizaciones (medio, canal de marca); vacío para personas
    lang: str = ""
    likes: int = 0
    shares: int = 0
    comments: int = 0
    views: int = 0
    labels: dict = field(default_factory=dict)  # salida del clasificador

    @property
    def interactions(self) -> int:
        return self.likes + 2 * self.shares + 2 * self.comments

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d
