"""CLI: python -m radar [--days 21] [--top 10] [--platforms bluesky,hackernews,...]

Responde: "¿Cuáles son los 10 temas de IA que más están creciendo esta semana, por qué y
cómo los adaptamos para nuestra audiencia?"
"""

from __future__ import annotations

import argparse
import logging
import platform
from pathlib import Path

from . import pipeline, report


def main() -> None:
    pipeline.load_dotenv()
    ap = argparse.ArgumentParser(prog="radar", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=21, help="días hacia atrás (7 de semana actual + línea base)")
    ap.add_argument("--top", type=int, default=10, help="cuántos temas incluir en el reporte")
    ap.add_argument("--per-day", type=int, default=25, help="piezas por día y consulta en cada fuente")
    ap.add_argument("--platforms", default=",".join(pipeline.ALL_PLATFORMS), help="fuentes separadas por coma")
    ap.add_argument("--community", type=Path, help="CSV con piezas públicas aportadas por la comunidad")
    ap.add_argument("--out", type=Path, default=Path("out"), help="carpeta de salida")
    ap.add_argument("--no-jev", action="store_true", help="no usar Jev aunque haya clave")
    ap.add_argument("--no-local", action="store_true", help="sin Jev, usar palabras clave en vez del modelo local")
    ap.add_argument("--no-llm", "--no-claude", dest="no_llm", action="store_true", help="redactar la adaptación con plantillas (sin Claude ni Zen)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpx2", "typesafe_sdk", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    opts = pipeline.Options(days=args.days, top=args.top, per_day=args.per_day, platforms=args.platforms.split(","),
                            community=args.community, out=args.out, no_jev=args.no_jev, no_local=args.no_local,
                            no_llm=args.no_llm)
    try:
        out = pipeline.run(opts)
    except ValueError as e:
        ap.error(str(e))
    top, paths = out["result"]["topics"][: args.top], out["paths"]

    print()
    for i, t in enumerate(top, 1):
        print(f"{i:>2}. {t['label'][:70]:<70} {report._growth(t['growth']):>6}  {t['stage']}")
    print()
    for kind, p in paths.items():
        print(f"{kind:>5}: {p}")
    if "microsoft" in platform.release().lower():  # WSL: el navegador vive en Windows
        print(f"\nÁbrelo con: explorer.exe \"$(wslpath -w {paths['html']})\"")


if __name__ == "__main__":
    main()
