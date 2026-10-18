"""Colectores de contenido público. Solo APIs abiertas y feeds oficiales, sin login ni scraping.

| Fuente       | Acceso                                          | Señal de interacción          |
|--------------|-------------------------------------------------|-------------------------------|
| Bluesky      | AppView pública (app.bsky.feed.searchPosts)     | likes, reposts, respuestas     |
| Hacker News  | API pública de Algolia                          | puntos, comentarios            |
| YouTube      | Feed RSS oficial por canal                      | vistas, valoraciones           |
| Google News  | Feed RSS público de búsqueda                    | solo volumen de menciones      |
| Comunidad    | CSV que llena el equipo con piezas públicas     | lo que se vea públicamente     |

LinkedIn, Instagram y TikTok no ofrecen una API pública de descubrimiento sin login, así que
entran por el CSV de comunidad: el equipo y la comunidad de 30X actúan como sensores.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config
from .models import Post, anonymize_author, scrub

log = logging.getLogger(__name__)

USER_AGENT = "radar-contenido-30x/0.1 (prototipo hackaton; contenido publico)"


def day_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    windows, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=1), end)
        windows.append((cur, nxt))
        cur = nxt
    return windows


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# Estadísticas de la última recolección (consultas que respondieron o fallaron, duplicados…),
# para la evaluación (python -m radar.evaluate).
last_stats: dict = {}


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None,
               headers: dict | None = None) -> httpx.Response | None:
    host = urlparse(url).hostname or url
    for attempt in range(3):
        try:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code == 429:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            last_stats.setdefault("requests_ok", Counter())[host] += 1
            return r
        except httpx.HTTPError as e:
            log.warning("Fallo al consultar %s (%s)", url, e)
            await asyncio.sleep(1)
    last_stats.setdefault("requests_failed", Counter())[host] += 1
    return None


# --- Bluesky -----------------------------------------------------------------------------

async def bluesky(client: httpx.AsyncClient, start: datetime, end: datetime, per_day: int) -> list[Post]:
    """Muestra las piezas con más interacción de cada día, para cada consulta.

    Tomar el mismo número de piezas por día permite comparar la participación de cada tema
    día a día sin que el volumen total de la plataforma distorsione la señal.
    """
    url = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
    sem = asyncio.Semaphore(4)

    async def one(q: dict, since: datetime, until: datetime) -> list[Post]:
        params = {"q": q["q"], "lang": q["lang"], "sort": "top", "limit": min(per_day, 100),
                  "since": _iso(since), "until": _iso(until)}
        async with sem:
            r = await _get(client, url, params)
        if r is None:
            return []
        out = []
        for p in r.json().get("posts", []):
            rec = p.get("record", {})
            if rec.get("reply"):  # solo piezas originales, no respuestas
                continue
            did = p["author"]["did"]
            rkey = p["uri"].rsplit("/", 1)[-1]
            out.append(Post(
                id=f"bsky:{p['cid']}",
                platform="bluesky",
                url=f"https://bsky.app/profile/{did}/post/{rkey}",
                text=scrub(rec.get("text", "")),
                created_at=datetime.fromisoformat(rec["createdAt"].replace("Z", "+00:00")),
                author_hash=anonymize_author(did),
                lang=(rec.get("langs") or [""])[0],
                likes=p.get("likeCount", 0),
                shares=p.get("repostCount", 0) + p.get("quoteCount", 0),
                comments=p.get("replyCount", 0),
            ))
        return out

    tasks = [one(q, s, e) for q in config.BLUESKY_QUERIES for s, e in day_windows(start, end)]
    return [p for batch in await asyncio.gather(*tasks) for p in batch]


# --- Hacker News -------------------------------------------------------------------------

async def hackernews(client: httpx.AsyncClient, start: datetime, end: datetime, per_day: int) -> list[Post]:
    url = "https://hn.algolia.com/api/v1/search"

    async def one(q: str, since: datetime, until: datetime) -> list[Post]:
        params = {"query": q, "tags": "story", "hitsPerPage": per_day,
                  "numericFilters": f"created_at_i>={int(since.timestamp())},created_at_i<{int(until.timestamp())}"}
        r = await _get(client, url, params)
        if r is None:
            return []
        return [Post(
            id=f"hn:{h['objectID']}",
            platform="hackernews",
            url=f"https://news.ycombinator.com/item?id={h['objectID']}",
            text=scrub(h.get("title") or ""),
            created_at=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
            author_hash=anonymize_author(h.get("author") or ""),
            lang="en",
            likes=h.get("points") or 0,
            comments=h.get("num_comments") or 0,
        ) for h in r.json().get("hits", [])]

    tasks = [one(q, s, e) for q in config.HN_QUERIES for s, e in day_windows(start, end)]
    return [p for batch in await asyncio.gather(*tasks) for p in batch]


# --- YouTube (RSS oficial) ---------------------------------------------------------------

_YT = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
       "media": "http://search.yahoo.com/mrss/"}


async def youtube(client: httpx.AsyncClient, start: datetime, end: datetime) -> list[Post]:
    async def one(channel_id: str, name: str) -> list[Post]:
        r = await _get(client, "https://www.youtube.com/feeds/videos.xml", {"channel_id": channel_id})
        if r is None:
            return []
        out = []
        for e in ET.fromstring(r.content).findall("a:entry", _YT):
            published = datetime.fromisoformat(e.findtext("a:published", namespaces=_YT))
            if not (start <= published < end):
                continue
            group = e.find("media:group", _YT)
            stats = group.find("media:community/media:statistics", _YT)
            rating = group.find("media:community/media:starRating", _YT)
            title = e.findtext("a:title", namespaces=_YT) or ""
            desc = (group.findtext("media:description", namespaces=_YT) or "")[:400]
            out.append(Post(
                id=f"yt:{e.findtext('yt:videoId', namespaces=_YT)}",
                platform="youtube",
                url=e.find("a:link", _YT).get("href"),
                text=scrub(f"{title}. {desc}"),
                created_at=published,
                author_hash=anonymize_author(channel_id),
                publisher=name,
                views=int(stats.get("views", 0)) if stats is not None else 0,
                likes=int(rating.get("count", 0)) if rating is not None else 0,
            ))
        return out

    batches = await asyncio.gather(*(one(c, n) for c, n in config.YOUTUBE_CHANNELS.items()))
    return [p for b in batches for p in b]


# --- YouTube Data API v3 (opcional, con YOUTUBE_API_KEY) ---------------------------------

YT_API = "https://www.googleapis.com/youtube/v3"


def youtube_mode() -> str:
    """'api' si hay YOUTUBE_API_KEY (búsqueda por día, entra al cálculo de crecimiento); si no, 'rss'."""
    return "api" if os.environ.get("YOUTUBE_API_KEY") else "rss"


async def youtube_api(client: httpx.AsyncClient, start: datetime, end: datetime, per_day: int) -> list[Post]:
    """Los videos más vistos de cada día por consulta, con la API oficial.

    Cuota: cada búsqueda cuesta 100 unidades de las 10.000 diarias gratis; 21 días × 2 consultas
    son unas 4.300. La clave va en un encabezado para que nunca aparezca en los registros.
    """
    headers = {"X-Goog-Api-Key": os.environ["YOUTUBE_API_KEY"]}
    sem = asyncio.Semaphore(4)

    async def one(q: dict, since: datetime, until: datetime) -> list[dict]:
        params = {"part": "snippet", "type": "video", "order": "viewCount", "q": q["q"],
                  "relevanceLanguage": q["lang"], "maxResults": min(per_day, 50),
                  "publishedAfter": _iso(since), "publishedBefore": _iso(until)}
        async with sem:
            r = await _get(client, f"{YT_API}/search", params, headers)
        return [{**item, "lang": q["lang"]} for item in (r.json().get("items", []) if r else [])]

    found = [i for batch in await asyncio.gather(*(one(q, s, e) for q in config.YOUTUBE_QUERIES
                                                    for s, e in day_windows(start, end))) for i in batch]
    by_id = {i["id"]["videoId"]: i for i in found if i.get("id", {}).get("videoId")}
    stats = {}
    ids = list(by_id)
    for k in range(0, len(ids), 50):  # videos.list: 1 unidad por cada 50 videos
        r = await _get(client, f"{YT_API}/videos", {"part": "statistics", "id": ",".join(ids[k:k + 50])}, headers)
        for v in (r.json().get("items", []) if r else []):
            stats[v["id"]] = v.get("statistics", {})

    out = []
    for vid, item in by_id.items():
        sn, st = item["snippet"], stats.get(vid, {})
        published = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        if not (start <= published < end):
            continue
        out.append(Post(
            id=f"yt:{vid}",
            platform="youtube",
            url=f"https://www.youtube.com/watch?v={vid}",
            text=scrub(f"{sn.get('title', '')}. {sn.get('description', '')[:400]}"),
            created_at=published,
            author_hash=anonymize_author(sn.get("channelId", vid)),
            lang=item["lang"],
            # Sin nombre del canal: puede ser una persona.
            views=int(st.get("viewCount", 0)), likes=int(st.get("likeCount", 0)), comments=int(st.get("commentCount", 0)),
        ))
    return out


# --- Google News (RSS) -------------------------------------------------------------------

async def google_news(client: httpx.AsyncClient, start: datetime, end: datetime, per_day: int,
                      queries: list[dict] | None = None, app: str = "") -> list[Post]:
    """Consulta día por día: el feed devuelve como máximo ~100 resultados recientes, así que
    una sola consulta de varias semanas se cargaría a los últimos días y fabricaría crecimiento.

    Con `app`, las piezas quedan marcadas como noticias sobre esa app (pestañas por app) y con
    un id propio, para que no se confundan con la misma noticia en las tendencias generales."""
    sem = asyncio.Semaphore(4)

    async def one(q: dict, since: datetime, until: datetime) -> list[Post]:
        day_after = (since - timedelta(days=1)).date().isoformat()
        day_before = (until + timedelta(days=1)).date().isoformat()
        params = {"q": f"{q['q']} after:{day_after} before:{day_before}",
                  "hl": q["hl"], "gl": q["gl"], "ceid": q["ceid"]}
        async with sem:
            r = await _get(client, "https://news.google.com/rss/search", params)
        if r is None:
            return []
        out = []
        for item in ET.fromstring(r.content).iter("item"):
            published = parsedate_to_datetime(item.findtext("pubDate"))
            if not (since <= published < until):
                continue
            source = item.findtext("source") or ""
            out.append(Post(
                id=f"gn:{app + ':' if app else ''}{item.findtext('guid')}",
                platform="google_news",
                url=item.findtext("link") or "",
                text=scrub(item.findtext("title") or ""),
                created_at=published,
                author_hash=anonymize_author(source),
                publisher=source,
                lang=q["hl"][:2],
                app=app,
            ))
            if len(out) >= per_day:
                break
        return out

    tasks = [one(q, s, e) for q in (queries or config.GOOGLE_NEWS_QUERIES) for s, e in day_windows(start, end)]
    return [p for b in await asyncio.gather(*tasks) for p in b]


# --- Comunidad (CSV) ---------------------------------------------------------------------

def community_csv(path: Path, start: datetime, end: datetime) -> list[Post]:
    """Piezas públicas que el equipo o la comunidad reportan (LinkedIn, Instagram, TikTok...).

    Columnas: platform,url,text,published_at,likes,comments,shares,views,publisher
    `publisher` solo debe llenarse si es una organización (medio, marca); nunca nombres de personas.
    """
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            if not row.get("text") or not row.get("published_at"):
                continue
            published = datetime.fromisoformat(row["published_at"])
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if not (start <= published < end):
                continue
            num = lambda k: int(float(row.get(k) or 0))
            out.append(Post(
                id=f"community:{i}:{row.get('url', '')}",
                platform=(row.get("platform") or "otra").strip().lower(),
                url=row.get("url", ""),
                text=scrub(row["text"]),
                created_at=published,
                author_hash=anonymize_author(row.get("url", str(i))),
                publisher=row.get("publisher", ""),
                likes=num("likes"), comments=num("comments"), shares=num("shares"), views=num("views"),
            ))
    return out


COMMUNITY_FIELDS = ["platform", "url", "text", "published_at", "likes", "comments", "shares", "views", "publisher"]


def append_community(path: Path, row: dict) -> int:
    """Agrega un aporte al CSV de comunidad (lo crea con encabezado si no existe). Devuelve el total."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COMMUNITY_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in COMMUNITY_FIELDS})
    return count_community(path)


def count_community(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


async def collect(start: datetime, end: datetime, platforms: set[str], per_day: int,
                  community: Path | None = None) -> list[Post]:
    last_stats.clear()
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        jobs = {}
        if "bluesky" in platforms:
            jobs["bluesky"] = bluesky(client, start, end, per_day)
        if "hackernews" in platforms:
            jobs["hackernews"] = hackernews(client, start, end, max(5, per_day // 3))
        if "youtube" in platforms:
            jobs["youtube"] = (youtube_api(client, start, end, max(5, per_day // 2)) if youtube_mode() == "api"
                               else youtube(client, start, end))
        if "google_news" in platforms:
            jobs["google_news"] = google_news(client, start, end, max(5, per_day // 2))
            for app, queries in config.APP_NEWS_QUERIES.items():
                jobs[f"news_{app}"] = google_news(client, start, end, max(5, per_day // 3), queries, app)
        results = await asyncio.gather(*jobs.values())
    posts = [p for batch in results for p in batch]
    for name, batch in zip(jobs, results):
        log.info("%-12s %5d piezas", name, len(batch))
    if community and community.exists():
        extra = community_csv(community, start, end)
        log.info("%-12s %5d piezas", "comunidad", len(extra))
        posts += extra

    seen, unique = set(), []
    for p in posts:
        if p.id not in seen and p.text:
            seen.add(p.id)
            unique.append(p)
    last_stats.update(by_job={name: len(batch) for name, batch in zip(jobs, results)}, raw=len(posts),
                      duplicates=len(posts) - len({p.id for p in posts}), empty_text=sum(1 for p in posts if not p.text),
                      unique=len(unique), seconds=round(time.monotonic() - t0, 1))
    return unique
