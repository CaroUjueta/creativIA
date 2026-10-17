"""Detección de tendencias y explicación de por qué funcionan. Todo es aritmética en código.

Método de tendencia (por tema):
1. Cada día y cada plataforma tienen una muestra comparable (las N piezas con más interacción).
2. La participación de un tema en una plataforma = suma de P(tema) / piezas de IA de la muestra.
3. Se promedia la participación entre plataformas (cada plataforma pesa igual, para que el
   volumen de noticias no tape a las redes).
4. Crecimiento = participación de la semana actual / participación en la línea base.
5. La etapa (naciente, en crecimiento, saturado, en declive) sale de crecimiento + tamaño.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config
from .models import Post

TZ = ZoneInfo(config.TIMEZONE)
SMOOTH = 0.01  # suavizado para no dividir por cero ni exagerar temas diminutos
NO_MOMENTUM = {"youtube"}
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def engagement_lift(posts: list[Post]) -> dict[str, float]:
    """Interacción relativa a la mediana de su plataforma (1.0 = típica). Sin dato → no aparece."""
    by_platform = defaultdict(list)
    for p in posts:
        value = p.views if p.platform == "youtube" else p.interactions
        if p.platform == "google_news":
            continue
        by_platform[p.platform].append((p, value))
    lifts = {}
    for items in by_platform.values():
        med = statistics.median(v for _, v in items) if items else 0
        for p, v in items:
            lifts[p.id] = (v + 1) / (med + 1)
    return lifts


def _daily_shares(posts: list[Post], days: list) -> dict[str, list[float]]:
    """Participación diaria de cada tema, promediada entre plataformas con datos ese día."""
    counts = defaultdict(lambda: defaultdict(float))   # (platform, day) -> topic -> soft count
    totals = defaultdict(int)
    for p in posts:
        key = (p.platform, p.created_at.astimezone(TZ).date())
        totals[key] += 1
        for t, prob in p.labels["topic_probs"].items():
            counts[key][t] += prob
    platforms = {p.platform for p in posts}
    series = {t: [] for t in config.TOPICS}
    for d in days:
        active = [pl for pl in platforms if totals[(pl, d)] > 0]
        for t in config.TOPICS:
            vals = [counts[(pl, d)][t] / totals[(pl, d)] for pl in active]
            series[t].append(sum(vals) / len(vals) if vals else 0.0)
    return series


def _window_share(posts: list[Post], platforms: set[str]) -> dict[str, float]:
    by_pl = defaultdict(list)
    for p in posts:
        if p.platform in platforms:
            by_pl[p.platform].append(p)
    shares = defaultdict(list)
    for items in by_pl.values():
        for t in config.TOPICS:
            shares[t].append(sum(p.labels["topic_probs"].get(t, 0.0) for p in items) / len(items))
    return {t: (sum(v) / len(v) if v else 0.0) for t, v in shares.items()}


def stage_of(growth: float, share: float, soft_count: float) -> str:
    if soft_count < 3:
        return "estable"  # muy poca evidencia para declarar tendencia
    if growth >= 1.5 and share < 0.08:
        return "naciente"
    if growth >= 1.2:
        return "en_crecimiento"
    if growth < 0.8:
        return "en_declive"
    if share >= 0.10:
        return "saturado"
    return "estable"


def _mean(xs, default=0.0):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else default


def _weighted(posts: list[Post], topic: str, key: str) -> float:
    w = [(p.labels["topic_probs"].get(topic, 0.0), p.labels[key]) for p in posts]
    total = sum(a for a, _ in w)
    return sum(a * b for a, b in w) / total if total else 0.0


def why_it_works(topic_posts: list[Post], lifts: dict[str, float]) -> dict:
    """Qué tienen en común las piezas que mejor funcionan dentro de un tema."""
    with_lift = [(p, lifts[p.id]) for p in topic_posts if p.id in lifts]
    base = statistics.median(l for _, l in with_lift) if with_lift else 1.0

    def best_by(attr: str, min_n: int = 2):
        groups = defaultdict(list)
        for p, l in with_lift:
            groups[attr_value(p, attr)].append(l)
        ranked = [(k, statistics.median(v) / base if base else 0, len(v)) for k, v in groups.items() if len(v) >= min_n]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return [{"value": k, "lift": round(lift, 2), "n": n} for k, lift, n in ranked]

    langs = Counter(p.lang or "?" for p in topic_posts)
    total = sum(langs.values()) or 1
    return {
        "hooks": best_by("hook"),
        "formats": best_by("format"),
        "publishers": Counter(p.labels["publisher"] for p in topic_posts).most_common(3),
        "timing": best_by("slot"),
        "lang_share": {k: round(v / total, 2) for k, v in langs.most_common()},
        "n_with_engagement": len(with_lift),
    }


def attr_value(p: Post, attr: str) -> str:
    if attr == "slot":
        local = p.created_at.astimezone(TZ)
        part = "mañana" if 6 <= local.hour < 12 else "tarde" if local.hour < 19 and local.hour >= 12 else "noche"
        return f"{WEEKDAYS[local.weekday()]} {part}"
    return p.labels[attr]


def analyze(posts: list[Post], start: datetime, end: datetime, current_days: int = 7) -> dict:
    ai = [p for p in posts if p.labels and p.labels["is_ai"] >= 0.5]
    split = end - timedelta(days=current_days)
    cur = [p for p in ai if p.created_at >= split]
    base = [p for p in ai if p.created_at < split]
    lifts = engagement_lift(ai)

    days, d = [], start.astimezone(TZ).date()
    while d <= (end - timedelta(seconds=1)).astimezone(TZ).date():
        days.append(d)
        d += timedelta(days=1)
    # Solo se compara crecimiento en plataformas con muestra en ambas ventanas. YouTube queda
    # fuera: su RSS trae solo los últimos 15 videos por canal y eso fabrica "crecimiento".
    n_cur, n_base = Counter(p.platform for p in cur), Counter(p.platform for p in base)
    momentum_platforms = {pl for pl in n_cur if pl not in NO_MOMENTUM and n_cur[pl] >= 10 and n_base[pl] >= 10}
    trend_posts = [p for p in ai if p.platform in momentum_platforms]
    daily = _daily_shares(trend_posts, days)
    share_cur = _window_share(cur, momentum_platforms)
    share_base = _window_share(base, momentum_platforms)

    topics = []
    for t, description in config.TOPICS.items():
        if t == "otro_ia":
            continue
        label = config.TOPIC_NAMES.get(t, description)
        soft = sum(p.labels["topic_probs"].get(t, 0.0) for p in cur)
        growth = (share_cur.get(t, 0) + SMOOTH) / (share_base.get(t, 0) + SMOOTH) if momentum_platforms else 1.0
        # Aceleración: últimos 3 días vs. los 4 anteriores de la semana actual.
        s = daily[t]
        accel = (_mean(s[-3:]) + SMOOTH) / (_mean(s[-7:-3]) + SMOOTH) if len(s) >= 7 else 1.0
        tposts = [p for p in cur if p.labels["topic"] == t]
        tlifts = [lifts[p.id] for p in tposts if p.id in lifts]
        topics.append({
            "id": t, "label": label, "description": description,
            "share_current": share_cur.get(t, 0.0), "share_baseline": share_base.get(t, 0.0),
            "growth": growth, "acceleration": accel, "soft_count": soft,
            "n_posts": len(tposts), "n_authors": len({p.author_hash for p in tposts}),
            "platforms": dict(Counter(p.platform for p in tposts)),
            "engagement": statistics.median(tlifts) if tlifts else 0.0,
            "audience_fit": _weighted(cur, t, "audience_fit"),
            "practical": _weighted(cur, t, "practical"),
            "hype": _weighted(cur, t, "hype"),
            "technical": _weighted(cur, t, "technical"),
            "latam": _weighted(cur, t, "latam"),
            "stage": stage_of(growth, share_cur.get(t, 0.0), soft),
            "daily": daily[t],
            "why": why_it_works(tposts, lifts),
            "examples": sorted(tposts, key=lambda p: lifts.get(p.id, 0) * p.labels["audience_fit"], reverse=True)[:4],
        })

    _score(topics)
    topics.sort(key=lambda x: x["score"], reverse=True)
    return {
        "topics": topics,
        "emerging_terms": emerging_terms(cur, base, current_days, max(1, (split - start).days)),
        "days": [d.isoformat() for d in days],
        "counts": {"total": len(posts), "ai": len(ai), "current": len(cur), "baseline": len(base),
                   "by_platform": dict(Counter(p.platform for p in ai)),
                   "momentum_platforms": sorted(momentum_platforms)},
        "window": {"start": start.isoformat(), "split": split.isoformat(), "end": end.isoformat()},
    }


def _norm(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    return [0.5 if hi == lo else (v - lo) / (hi - lo) for v in values]


def _score(topics: list[dict]) -> None:
    w = config.WEIGHTS
    mom = _norm([math.log(t["growth"]) + 0.5 * math.log(t["acceleration"]) for t in topics])
    eng = _norm([math.log1p(t["engagement"]) for t in topics])
    for t, m, e in zip(topics, mom, eng):
        raw = (w["momentum"] * m + w["audience_fit"] * t["audience_fit"]
               + w["engagement"] * e + w["practicality"] * t["practical"])
        raw += config.STAGE_BONUS.get(t["stage"], 0.0)
        raw *= 1 - 0.3 * t["hype"]           # el humo sin sustancia baja la prioridad
        raw *= 0.5 if t["soft_count"] < 3 else 1.0
        t["score"] = round(raw, 4)
        t["momentum_norm"] = m


# --- Términos emergentes -------------------------------------------------------------------

_STOP = set("""
a al algo ante antes así aun aunque bajo bien cada como con contra cual cuando de del desde donde
dos el ella ellos en entre era es esa ese eso esta este esto estos fue ha hace hacia han hasta hay
la las le les lo los más mas me mi mucho muy ni no nos o otra otro para pero poco por porque que
qué se ser si sí sin sobre su sus también tan te tiene todo todos tu un una uno unos y ya yo son
está están sus ser hoy cómo puede pueden nuevo nueva según vía
the a an and or of to in on for with from by at as is are was were be been it its this that these
those you your we our they their he she his her not but if so than then there here what which who
how why when will can could would should may might just more most new now about into over after up
out no yes do does did have has had get got via use using using like also one two all any
ia ai artificial intelligence inteligencia
""".split())
_NOISE = {"fuck", "fucking", "shit", "mierda", "puta", "joder", "carajo", "verga"}
_MID_CAP = re.compile(r"(?<=[\wáéíóúñ,;:] )([A-ZÁÉÍÓÚÑ][\wáéíóúñ\-\.]*[\wáéíóúñ])")
_TOKEN = re.compile(r"[a-záéíóúñü0-9][a-záéíóúñü0-9\-\.]*[a-záéíóúñü0-9]|[a-z]", re.I)


def _terms(text: str) -> tuple[set[str], set[str]]:
    """Unigramas y bigramas del texto, más el conjunto de tokens que aparecen con mayúscula inicial."""
    text = re.sub(r"https?://\S+", " ", text)
    raw = [t for t in _TOKEN.findall(text) if t.lower() not in _STOP and len(t) > 2 and not t.isdigit()]
    # Mayúscula a mitad de frase (no al inicio): indicio de nombre propio.
    capitalized = {m.lower() for m in _MID_CAP.findall(text)}
    toks = [t.lower() for t in raw if t.lower() not in _NOISE]
    return set(toks) | {f"{a} {b}" for a, b in zip(toks, toks[1:])}, capitalized


def emerging_terms(cur: list[Post], base: list[Post], cur_days: int, base_days: int, top: int = 30) -> list[dict]:
    """Términos cuya frecuencia diaria esta semana se dispara frente a la línea base.

    Atrapa lo que la taxonomía no anticipa (un producto nuevo, un nombre, una frase).
    Filtros: varios autores distintos (no un solo post viral) y, para palabras sueltas,
    que suelan escribirse con mayúscula (nombres propios: productos, empresas, eventos).
    Con Jev disponible, `classify.filter_terms` descarta además lo que no sea un concepto de IA.
    """
    def doc_freq(posts):
        df, authors, caps = Counter(), defaultdict(set), Counter()
        for p in posts:
            terms, capitalized = _terms(p.text)
            for term in terms:
                df[term] += 1
                authors[term].add(p.author_hash)
                if term in capitalized:
                    caps[term] += 1
        return df, authors, caps

    df_cur, authors, caps = doc_freq(cur)
    df_base, _, _ = doc_freq(base)
    out = []
    for term, n in df_cur.items():
        if n < 4 or len(authors[term]) < 3:
            continue
        if " " not in term and caps[term] / n < 0.6:
            continue
        if " " in term and not any(caps[w] / max(df_cur[w], 1) >= 0.6 for w in term.split()):
            continue
        rate_cur = n / cur_days
        rate_base = df_base.get(term, 0) / base_days if base else 0
        ratio = (rate_cur + 0.2) / (rate_base + 0.2)
        if ratio >= 2:
            out.append({"term": term, "count": n, "authors": len(authors[term]),
                        "ratio": round(ratio, 1), "new": df_base.get(term, 0) == 0,
                        "strength": len(authors[term]) * math.log(ratio)})
    # A igual fuerza gana el bigrama ("satya nadella" en vez de "satya" y "nadella" por separado).
    out.sort(key=lambda x: (round(x["strength"], 3), " " in x["term"]), reverse=True)
    # Quitar unigramas ya cubiertos por un bigrama del mismo tamaño, y bigramas redundantes.
    kept = []
    for o in out:
        words = o["term"].split()
        if any(set(words) <= set(k["term"].split()) or set(k["term"].split()) <= set(words) for k in kept):
            continue
        kept.append(o)
    return kept[:top]
