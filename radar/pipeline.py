"""El radar completo como una función, para usarlo desde la consola o desde la app web."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import account, adapt, analysis, classify, report, sources

ALL_PLATFORMS = ["bluesky", "hackernews", "youtube", "google_news"]
STEPS = 4
COMMUNITY_CSV = Path("data/comunidad.csv")  # aportes del equipo; se usa si existe
JEV_USD_PER_M_INPUT = 0.042  # precio de Jev en OpenRouter (solo se cobra la entrada)

log = logging.getLogger("radar")


def load_dotenv(path: Path = Path(".env")) -> None:
    """Carga KEY=VALUE de .env sin pisar variables ya definidas en el entorno."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#") and value and key not in os.environ:
            os.environ[key] = value.strip().strip('"')


@dataclass
class Options:
    days: int = 21
    top: int = 10
    per_day: int = 25
    platforms: list[str] = field(default_factory=lambda: list(ALL_PLATFORMS))
    community: Path | None = COMMUNITY_CSV
    out: Path = Path("out")
    no_jev: bool = False
    no_local: bool = False
    no_llm: bool = False


def no_momentum() -> set[str]:
    return set() if sources.youtube_mode() == "api" else analysis.NO_MOMENTUM


def gather(opts: Options, start: datetime, end: datetime, step: Callable[[int, str], None]) -> tuple[list, dict, bool]:
    """Pasos 1 y 2: recolecta y clasifica. Lo comparten el reporte y el backtest."""
    step(1, f"Recolectando contenido público ({start.date()} → {end.date()})…")
    posts = asyncio.run(sources.collect(start, end, set(opts.platforms), opts.per_day, opts.community))
    log.info("    %d piezas únicas", len(posts))

    use_jev = classify.jev_provider() is not None and not opts.no_jev
    use_local = not use_jev and not opts.no_local and classify.local_available()
    if not use_jev and not opts.no_jev:
        fallback = "el modelo local (menos preciso que Jev)" if use_local else "el clasificador por palabras clave (aproximado)"
        log.warning("    Sin TYPESAFE_API_KEY, OPENROUTER_API_KEY, MODEL_ACCESS_KEY ni OPENCODE_API_KEY: se usa %s.", fallback)
    step(2, f"Clasificando {len(posts)} piezas…")
    cstats = classify.classify(posts, use_jev, use_local)
    cstats["cost_usd"] = cstats["input_tokens"] * JEV_USD_PER_M_INPUT / 1e6
    use_jev = cstats["classifier"] == "jev"  # falso si Jev no respondió y se usó el respaldo
    if use_jev:
        log.info("    %d nuevas, %d desde caché, %d tokens de entrada (≈ US$%.4f)",
                 cstats["classified"], cstats["cached"], cstats["input_tokens"], cstats["cost_usd"])
    return posts, cstats, use_jev


def run(opts: Options, progress: Callable[[int, str], None] | None = None) -> dict:
    """Corre los 4 pasos. `progress(paso, mensaje)` se llama al empezar cada uno."""
    def step(n: int, msg: str) -> None:
        log.info("%d/%d %s", n, STEPS, msg)
        if progress:
            progress(n, msg)

    if opts.days < 14:
        raise ValueError("Se necesitan al menos 14 días para tener una línea base de una semana")
    t0 = time.monotonic()
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=opts.days)

    posts, cstats, use_jev = gather(opts, start, end, step)

    t_collect = sources.last_stats.get("seconds")
    step(3, "Detectando tendencias…")
    # Las noticias sobre cada app solo alimentan su pestaña, no las tendencias generales.
    result = analysis.analyze([p for p in posts if not p.app], start, end, no_momentum=no_momentum())
    result["by_app"] = analysis.by_app(posts, start, end, no_momentum=no_momentum())
    if use_jev and not cstats["jev_error"]:
        try:
            result["emerging_terms"] = classify.filter_terms(result["emerging_terms"])
        except Exception as e:
            log.warning("    No se pudieron filtrar los términos emergentes con Jev (%s)", e)
            result["emerging_terms"] = result["emerging_terms"][:15]
    else:
        result["emerging_terms"] = result["emerging_terms"][:15]

    # La cuenta para la que se produce (ficha y exportación de Meta), si el equipo las cargó.
    profile, own = account.load_profile(), account.load_posts()
    if own:
        classify.classify(own, use_jev, cstats["classifier"] == "local")
    perf = account.performance(own)
    result["account"] = {"profile": profile, "performance": perf} if profile or perf else None

    step(4, "Generando recomendaciones de adaptación…")
    # Ideas para el top general y para el top de cada app (el mismo tema comparte ideas).
    wanted = {t["id"] for t in result["topics"][: opts.top]}
    wanted |= {t["id"] for v in result["by_app"].values() for t in v["topics"][: opts.top]}
    adaptations, adapter = adapt.adapt([t for t in result["topics"] if t["id"] in wanted], use_llm=not opts.no_llm,
                                       account={"profile": profile, "performance": perf, "context": account.context(profile, perf)})

    meta = {"classifier": cstats["classifier"], "adapter": adapter, "top": opts.top,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "jev_input_tokens": cstats["input_tokens"],
            "jev_cost_usd": round(cstats["cost_usd"], 4), "n_classified": cstats["classified"], "n_cached": cstats["cached"],
            "jev_error": cstats.get("jev_error", ""),
            "collection": {k: dict(v) if isinstance(v, dict) else v for k, v in sources.last_stats.items()},
            "seconds": round(time.monotonic() - t0, 1), "collect_seconds": t_collect}
    paths = report.write_outputs(result, adaptations, meta, opts.out, opts.top)
    # Las piezas ya clasificadas (públicas y limpias de datos personales), para la evaluación.
    paths["posts"] = paths["json"].with_name(paths["json"].name.replace("radar-", "piezas-").replace(".json", ".jsonl"))
    with paths["posts"].open("w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")
    return {"result": result, "paths": paths, "meta": meta}
