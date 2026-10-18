"""La cuenta para la que se produce: por defecto @crece30x en Instagram.

Dos fuentes, ambas aportadas por el equipo de la cuenta:
- Ficha (data/cuenta.json): de qué habla, a quién le habla, tono, pilares, formatos y mejores posts.
- Exportación de Meta Business Suite (data/cuenta_metricas.csv): las publicaciones propias con sus
  métricas. Solo se guarda lo que cualquiera ve en el post (texto, fecha, enlace, tipo, me gusta,
  comentarios y vistas); alcance, guardados y compartidos son privados y se descartan al importar.

Con eso, el radar mide qué temas, ganchos y formatos le funcionan a la cuenta y la redacción
aterriza cada tendencia en una pieza para esa cuenta.
"""

from __future__ import annotations

import csv
import io
import json
import statistics
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import config
from .models import Post, anonymize_author, scrub

PROFILE = Path("data/cuenta.json")
METRICS = Path("data/cuenta_metricas.csv")
FORMATS = ["reel", "carrusel", "imagen", "historia"]
DEFAULT = {"handle": "@crece30x", "red": "instagram", "descripcion": "", "audiencia": "", "tono": "",
           "pilares": [], "formatos": ["reel", "carrusel"], "cta": "", "evitar": "", "mejores_posts": []}
FIELDS = ["url", "text", "published_at", "type", "likes", "comments", "views"]

# Encabezados posibles de la exportación de Meta (en inglés o en español), sin tildes y en minúscula.
HEADERS = {
    "text": ["description", "descripcion", "caption", "texto", "title", "titulo"],
    "published_at": ["publish time", "hora de publicacion", "fecha de publicacion", "date", "fecha", "published"],
    "url": ["permalink", "enlace permanente", "enlace", "link", "url"],
    "type": ["post type", "tipo de publicacion", "tipo", "type"],
    "likes": ["likes", "me gusta", "reactions", "reacciones"],
    "comments": ["comments", "comentarios"],
    "views": ["views", "visualizaciones", "reproducciones", "plays"],
}
TYPES = {"reel": "reel", "video": "reel", "carousel": "carrusel", "carrusel": "carrusel", "album": "carrusel",
         "image": "imagen", "imagen": "imagen", "photo": "imagen", "foto": "imagen", "story": "historia", "historia": "historia"}


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _lines(value) -> list[str]:
    if isinstance(value, list):
        items = value
    else:
        items = str(value or "").replace(",", "\n").splitlines()
    return [str(x).strip()[:80] for x in items if str(x).strip()][:8]


def load_profile(path: Path = PROFILE) -> dict | None:
    if not path.exists():
        return None
    return {**DEFAULT, **json.loads(path.read_text(encoding="utf-8"))}


def validate_profile(body: dict) -> dict:
    """Revisa la ficha. Lanza ValueError con un mensaje para mostrar en el formulario."""
    handle = str(body.get("handle", "")).strip()
    if not handle.startswith("@") or not 2 <= len(handle) <= 40 or " " in handle:
        raise ValueError("El usuario de la cuenta debe empezar con @, sin espacios.")
    posts = []
    for line in str(body.get("mejores_posts", "")).splitlines() if not isinstance(body.get("mejores_posts"), list) else body["mejores_posts"]:
        url = str(line).strip()
        if not url:
            continue
        host = urlparse(url).hostname or ""
        if urlparse(url).scheme != "https" or not host.endswith("instagram.com"):
            raise ValueError("Los mejores posts deben ser enlaces públicos de instagram.com (https://…).")
        posts.append(url[:300])
    text = lambda k, n: scrub(str(body.get(k, "")).strip())[:n]
    return {"handle": handle, "red": "instagram", "descripcion": text("descripcion", 600), "audiencia": text("audiencia", 400),
            "tono": text("tono", 300), "pilares": _lines(body.get("pilares")),
            "formatos": [f for f in FORMATS if f in (body.get("formatos") or [])] or DEFAULT["formatos"],
            "cta": text("cta", 200), "evitar": text("evitar", 300), "mejores_posts": posts[:10]}


def save_profile(body: dict, path: Path = PROFILE) -> dict:
    profile = validate_profile(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def _number(value: str) -> int:
    digits = "".join(c for c in str(value) if c.isdigit())
    return int(digits) if digits else 0


def _date(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%m/%d/%Y %H:%M", "%m/%d/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            d = datetime.strptime(value, fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_meta_csv(text: str) -> list[dict]:
    """Lee la exportación de Meta Business Suite y devuelve solo las columnas públicas."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if len(rows) < 2:
        raise ValueError("El archivo no tiene publicaciones.")
    head = [_plain(h) for h in rows[0]]
    cols = {}
    for field, names in HEADERS.items():
        idx = next((i for name in names for i, h in enumerate(head) if h == name), None)
        if idx is not None:
            cols[field] = idx
    if not {"text", "published_at"} <= cols.keys():
        raise ValueError("No encontré las columnas de descripción y fecha. Exporta desde Meta Business Suite → Estadísticas → Contenido.")
    out = []
    for r in rows[1:]:
        get = lambda f: r[cols[f]] if f in cols and cols[f] < len(r) else ""
        published = _date(get("published_at"))
        text_ = scrub(get("text"))
        if not published or not text_:
            continue
        kind = next((v for k, v in TYPES.items() if k in _plain(get("type"))), "imagen")
        out.append({"url": get("url")[:300], "text": text_[:2200], "published_at": published.isoformat(), "type": kind,
                    "likes": _number(get("likes")), "comments": _number(get("comments")), "views": _number(get("views"))})
    if not out:
        raise ValueError("No se pudo leer ninguna publicación (revisa las fechas y descripciones).")
    return out


def save_metrics(text: str, path: Path = METRICS) -> dict:
    rows = parse_meta_csv(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return metrics_status(path)


def metrics_status(path: Path = METRICS) -> dict:
    if not path.exists():
        return {"count": 0}
    with path.open(newline="", encoding="utf-8") as f:
        dates = [r["published_at"][:10] for r in csv.DictReader(f)]
    return {"count": len(dates), "from": min(dates, default=""), "to": max(dates, default="")}


def load_posts(path: Path = METRICS) -> list[Post]:
    if not path.exists():
        return []
    profile = load_profile() or DEFAULT
    with path.open(newline="", encoding="utf-8") as f:
        return [Post(id=f"cuenta:{r['url'] or i}", platform="instagram", url=r["url"], text=r["text"],
                     created_at=datetime.fromisoformat(r["published_at"]), author_hash=anonymize_author(profile["handle"]),
                     likes=int(r["likes"] or 0), comments=int(r["comments"] or 0), views=int(r["views"] or 0),
                     publisher=r["type"])  # el tipo de publicación viaja en `publisher` (es una marca, no una persona)
                for i, r in enumerate(csv.DictReader(f))]


def performance(posts: list[Post]) -> dict | None:
    """Qué le funciona a la cuenta: interacción de cada post frente a la mediana de la cuenta."""
    if len(posts) < 5:
        return None
    score = {p.id: p.likes + 2 * p.comments for p in posts}
    med = statistics.median(score.values())
    lift = {k: (v + 1) / (med + 1) for k, v in score.items()}

    def by(key, names=None, min_n=2):
        groups = defaultdict(list)
        for p in posts:
            groups[key(p)].append(lift[p.id])
        rows = [{"value": k, "label": (names or {}).get(k, k), "lift": round(statistics.median(v), 2), "n": len(v)}
                for k, v in groups.items() if len(v) >= min_n]
        return sorted(rows, key=lambda r: r["lift"], reverse=True)

    labeled = [p for p in posts if p.labels]
    best = sorted(posts, key=lambda p: lift[p.id], reverse=True)[:5]
    return {
        "n": len(posts), "from": min(p.created_at for p in posts).date().isoformat(),
        "to": max(p.created_at for p in posts).date().isoformat(),
        "by_type": by(lambda p: p.publisher),
        "by_topic": by(lambda p: p.labels["topic"], config.TOPIC_NAMES) if labeled else [],
        "by_hook": by(lambda p: p.labels["hook"], {k: v for k, v in config.HOOKS.items()}) if labeled else [],
        "top_posts": [{"url": p.url, "text": p.text[:160], "type": p.publisher, "date": p.created_at.date().isoformat(),
                       "lift": round(lift[p.id], 1)} for p in best],
    }


def context(profile: dict | None, perf: dict | None) -> str:
    """Texto para el modelo que redacta: la cuenta y lo que le funciona."""
    if not profile:
        return ""
    parts = [f"Cuenta para la que se produce: {profile['handle']} en Instagram."]
    for key, label in (("descripcion", "De qué habla"), ("audiencia", "A quién le habla"), ("tono", "Tono"),
                       ("cta", "Llamado a la acción habitual"), ("evitar", "Evitar")):
        if profile.get(key):
            parts.append(f"{label}: {profile[key]}")
    if profile.get("pilares"):
        parts.append("Pilares de contenido: " + "; ".join(profile["pilares"]))
    parts.append("Formatos que usa: " + ", ".join(profile.get("formatos") or DEFAULT["formatos"]))
    if perf:
        fmt = lambda rows: ", ".join(f"{r['label']} ({r['lift']}×, {r['n']} posts)" for r in rows[:3])
        parts.append(f"Lo que le funciona (interacción pública de {perf['n']} posts propios frente a su mediana):")
        if perf["by_type"]:
            parts.append("- Formatos: " + fmt(perf["by_type"]))
        if perf["by_topic"]:
            parts.append("- Temas: " + fmt(perf["by_topic"]))
        if perf["by_hook"]:
            parts.append("- Ganchos: " + fmt(perf["by_hook"]))
    return "\n".join(parts)
