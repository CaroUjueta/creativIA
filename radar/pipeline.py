"""El radar completo como una función, para usarlo desde la consola o desde la app web."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import adapt, analysis, classify, report, sources

ALL_PLATFORMS = ["bluesky", "hackernews", "youtube", "google_news"]
STEPS = 4

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
    community: Path | None = None
    out: Path = Path("out")
    no_jev: bool = False
    no_local: bool = False
    no_llm: bool = False


def run(opts: Options, progress: Callable[[int, str], None] | None = None) -> dict:
    """Corre los 4 pasos. `progress(paso, mensaje)` se llama al empezar cada uno."""
    def step(n: int, msg: str) -> None:
        log.info("%d/%d %s", n, STEPS, msg)
        if progress:
            progress(n, msg)

    if opts.days < 14:
        raise ValueError("Se necesitan al menos 14 días para tener una línea base de una semana")
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=opts.days)

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
    if use_jev:
        log.info("    %d nuevas, %d desde caché, %d tokens de entrada (≈ US$%.4f)",
                 cstats["classified"], cstats["cached"], cstats["input_tokens"], cstats["input_tokens"] * 0.042 / 1e6)

    step(3, "Detectando tendencias…")
    result = analysis.analyze(posts, start, end)
    if use_jev:
        try:
            result["emerging_terms"] = classify.filter_terms(result["emerging_terms"])
        except Exception as e:
            log.warning("    No se pudieron filtrar los términos emergentes con Jev (%s)", e)
            result["emerging_terms"] = result["emerging_terms"][:15]
    else:
        result["emerging_terms"] = result["emerging_terms"][:15]

    step(4, "Generando recomendaciones de adaptación…")
    adaptations, adapter = adapt.adapt(result["topics"][: opts.top], use_llm=not opts.no_llm)

    meta = {"classifier": cstats["classifier"], "adapter": adapter,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "jev_input_tokens": cstats["input_tokens"]}
    paths = report.write_outputs(result, adaptations, meta, opts.out, opts.top)
    return {"result": result, "paths": paths, "meta": meta}
