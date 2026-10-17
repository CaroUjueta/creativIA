"""CLI: python -m radar [--days 21] [--top 10] [--platforms bluesky,hackernews,...]

Responde: "¿Cuáles son los 10 temas de IA que más están creciendo esta semana, por qué y
cómo los adaptamos para nuestra audiencia?"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import adapt, analysis, classify, report, sources

ALL_PLATFORMS = ["bluesky", "hackernews", "youtube", "google_news"]


def load_dotenv(path: Path = Path(".env")) -> None:
    """Carga KEY=VALUE de .env sin pisar variables ya definidas en el entorno."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#") and value and key not in os.environ:
            os.environ[key] = value.strip().strip('"')


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="radar", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=21, help="días hacia atrás (7 de semana actual + línea base)")
    ap.add_argument("--top", type=int, default=10, help="cuántos temas incluir en el reporte")
    ap.add_argument("--per-day", type=int, default=25, help="piezas por día y consulta en cada fuente")
    ap.add_argument("--platforms", default=",".join(ALL_PLATFORMS), help="fuentes separadas por coma")
    ap.add_argument("--community", type=Path, help="CSV con piezas públicas aportadas por la comunidad")
    ap.add_argument("--out", type=Path, default=Path("out"), help="carpeta de salida")
    ap.add_argument("--no-jev", action="store_true", help="forzar clasificador heurístico")
    ap.add_argument("--no-claude", action="store_true", help="usar plantillas para la adaptación")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpx2", "typesafe_sdk", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    log = logging.getLogger("radar")

    if args.days < 14:
        ap.error("--days debe ser al menos 14 para tener una línea base de una semana")

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)

    log.info("1/4 Recolectando contenido público (%s → %s)…", start.date(), end.date())
    posts = asyncio.run(sources.collect(start, end, set(args.platforms.split(",")), args.per_day, args.community))
    log.info("    %d piezas únicas", len(posts))

    use_jev = bool(os.environ.get("TYPESAFE_API_KEY")) and not args.no_jev
    if not use_jev and not args.no_jev:
        log.warning("    Sin TYPESAFE_API_KEY: se usa el clasificador heurístico (menos preciso).")
    log.info("2/4 Clasificando piezas…")
    cstats = classify.classify(posts, use_jev)
    if use_jev:
        log.info("    %d nuevas, %d desde caché, %d tokens de entrada (≈ US$%.4f)",
                 cstats["classified"], cstats["cached"], cstats["input_tokens"], cstats["input_tokens"] * 0.042 / 1e6)

    log.info("3/4 Detectando tendencias…")
    result = analysis.analyze(posts, start, end)
    if use_jev:
        try:
            result["emerging_terms"] = classify.filter_terms(result["emerging_terms"])
        except Exception as e:
            log.warning("    No se pudieron filtrar los términos emergentes con Jev (%s)", e)
            result["emerging_terms"] = result["emerging_terms"][:15]
    else:
        result["emerging_terms"] = result["emerging_terms"][:15]

    log.info("4/4 Generando recomendaciones de adaptación…")
    top = result["topics"][: args.top]
    adaptations, adapter = adapt.adapt(top, use_claude=adapt.has_claude_credentials() and not args.no_claude)

    meta = {"classifier": cstats["classifier"], "adapter": adapter,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "jev_input_tokens": cstats["input_tokens"]}
    paths = report.write_outputs(result, adaptations, meta, args.out, args.top)

    print()
    for i, t in enumerate(top, 1):
        print(f"{i:>2}. {t['label'][:70]:<70} {report._growth(t['growth']):>6}  {t['stage']}")
    print()
    for kind, p in paths.items():
        print(f"{kind:>5}: {p}")


if __name__ == "__main__":
    main()
