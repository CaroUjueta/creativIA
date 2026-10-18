"""Backtest: ¿lo que el radar señaló hace una semana siguió arriba la semana siguiente?

    python -m radar.backtest [--weeks 3] [--top 10]

Simulación hecha hoy con publicaciones públicas antiguas: para cada fecha de corte se corre el radar
"como si fuera ese día", sin ver nada
posterior, y se compara con lo que pasó en los 7 días siguientes:

- Acierto del top: de los temas del top del radar, cuántos tuvieron la semana siguiente una
  participación mayor a su línea base (las 2 semanas previas a la predicción).
- Mismo cálculo para la alternativa obvia: seguir los temas de los que más se habla.
- Acierto de dirección: los temas marcados como nacientes o en crecimiento, ¿siguieron arriba?
  Los marcados en declive, ¿siguieron abajo?

La participación se mide igual que en el radar (plataformas comparables, conteos suaves).
YouTube solo entra con YOUTUBE_API_KEY: su RSS trae únicamente los últimos videos de cada canal.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import analysis, pipeline, sources

log = logging.getLogger("radar")

RISING = {"naciente", "en_crecimiento"}
PLATFORMS = ["bluesky", "hackernews", "google_news", "youtube"]  # YouTube solo cuenta con la API


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 3) if flags else None


def _mean(xs: list[float]) -> float | None:
    return round(statistics.mean(xs), 3) if xs else None


def evaluate(posts: list, end: datetime, weeks: int, top: int, no_momentum: set[str] = analysis.NO_MOMENTUM) -> dict:
    """Compara predicciones y resultados en `weeks` semanas que terminan en `end`. Sin red."""
    folds = []
    for k in range(weeks, 0, -1):
        cut = end - timedelta(days=7 * k)
        start = cut - timedelta(days=21)
        history = [p for p in posts if start <= p.created_at < cut and not p.app]
        after = [p for p in posts if cut <= p.created_at < cut + timedelta(days=7) and not p.app
                 and p.labels and p.labels["is_ai"] >= 0.5]
        pred = analysis.analyze(history, start, cut, no_momentum=no_momentum)
        platforms = set(pred["counts"]["momentum_platforms"])
        if not platforms:
            log.warning("Semana %s: sin muestra comparable, se omite", cut.date())
            continue
        share_next = analysis._window_share(after, platforms)

        rows = []
        for t in pred["topics"]:  # ya vienen ordenados por el puntaje del radar
            base = t["share_baseline"]
            nxt = share_next.get(t["id"], 0.0)
            rows.append({"id": t["id"], "label": t["label"], "stage": t["stage"], "score": t["score"],
                         "growth": round(t["growth"], 2), "share_base": round(base, 4),
                         "share_pred": round(t["share_current"], 4), "share_next": round(nxt, 4),
                         "next_vs_base": round((nxt + analysis.SMOOTH) / (base + analysis.SMOOTH), 2),
                         "evidence": t["soft_count"] >= 3})
        rows = [r for r in rows if r["evidence"]]
        above = lambda r: r["share_next"] > r["share_base"]
        radar_top = rows[:top]
        popular_top = sorted(rows, key=lambda r: r["share_pred"], reverse=True)[:top]
        rising = [r for r in rows if r["stage"] in RISING]
        falling = [r for r in rows if r["stage"] == "en_declive"]
        folds.append({
            "cut": cut.isoformat(), "next_end": (cut + timedelta(days=7)).isoformat(),
            "platforms": sorted(platforms), "n_history": len(history), "n_after": len(after),
            "radar_hit": _rate([above(r) for r in radar_top]),
            "popular_hit": _rate([above(r) for r in popular_top]),
            "all_hit": _rate([above(r) for r in rows]),
            "radar_lift": _mean([r["next_vs_base"] for r in radar_top]),
            "popular_lift": _mean([r["next_vs_base"] for r in popular_top]),
            "rising_hit": _rate([above(r) for r in rising]), "n_rising": len(rising),
            "falling_hit": _rate([not above(r) for r in falling]), "n_falling": len(falling),
            "radar_top": [r["id"] for r in radar_top], "popular_top": [r["id"] for r in popular_top],
            "topics": rows,
        })

    summary = {}
    for key in ("radar_hit", "popular_hit", "all_hit", "radar_lift", "popular_lift"):
        summary[key] = _mean([f[key] for f in folds if f[key] is not None])
    # Dirección: se juntan todos los temas de todas las semanas (cada uno pesa igual).
    rising = [r for f in folds for r in f["topics"] if r["stage"] in RISING]
    falling = [r for f in folds for r in f["topics"] if r["stage"] == "en_declive"]
    summary["rising_hit"] = _rate([r["share_next"] > r["share_base"] for r in rising])
    summary["falling_hit"] = _rate([r["share_next"] <= r["share_base"] for r in falling])
    summary["n_rising"], summary["n_falling"], summary["weeks"] = len(rising), len(falling), len(folds)
    return {"summary": summary, "folds": folds, "top": top}


def render_markdown(bt: dict, meta: dict) -> str:
    s = bt["summary"]
    pct = lambda v: "—" if v is None else f"{v * 100:.0f} %"
    x = lambda v: "—" if v is None else f"{v:.2f}×"
    lines = [
        "# Backtest del radar de contenido IA", "",
        f"{s['weeks']} semanas evaluadas · clasificador: {meta['classifier']} · generado {meta['generated']}", "",
        "Simulación con publicaciones públicas ya existentes: en cada fecha de corte el radar solo ve lo publicado hasta ese día, y su predicción se compara con los 7 días siguientes.", "",
        "| Métrica | Radar | Temas más populares | Todos los temas |",
        "|---|---|---|---|",
        f"| Temas del top que siguieron por encima de su línea base | {pct(s['radar_hit'])} | {pct(s['popular_hit'])} | {pct(s['all_hit'])} |",
        f"| Participación la semana siguiente vs. su línea base | {x(s['radar_lift'])} | {x(s['popular_lift'])} | |",
        "",
        f"- Temas marcados como nacientes o en crecimiento que siguieron arriba: **{pct(s['rising_hit'])}** ({s['n_rising']} casos)",
        f"- Temas marcados en declive que siguieron abajo: **{pct(s['falling_hit'])}** ({s['n_falling']} casos)",
        "",
    ]
    for f in bt["folds"]:
        lines += [f"## Semana del {f['cut'][:10]} al {f['next_end'][:10]}", "",
                  f"Acierto del top: radar {pct(f['radar_hit'])} · populares {pct(f['popular_hit'])} · "
                  f"plataformas {', '.join(f['platforms'])}", "",
                  "| # | Tema | Etapa predicha | Línea base | Semana predicha | Semana siguiente | ¿Siguió arriba? |",
                  "|---|---|---|---|---|---|---|"]
        for i, r in enumerate(f["topics"][: bt["top"]], 1):
            lines.append(f"| {i} | {r['label']} | {r['stage']} | {r['share_base']:.1%} | {r['share_pred']:.1%} | "
                         f"{r['share_next']:.1%} | {'sí' if r['share_next'] > r['share_base'] else 'no'} |")
        lines.append("")
    lines += ["Límites: pocas semanas y fuentes públicas con sesgo técnico y angloparlante; "
              "es evidencia direccional, no una prueba estadística definitiva."]
    return "\n".join(lines)


def main() -> None:
    pipeline.load_dotenv()
    ap = argparse.ArgumentParser(prog="radar.backtest", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weeks", type=int, default=3, help="semanas a evaluar")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--per-day", type=int, default=25)
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--no-jev", action="store_true", help="no usar Jev aunque haya clave")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpx2", "typesafe_sdk"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    platforms = PLATFORMS if sources.youtube_mode() == "api" else [p for p in PLATFORMS if p != "youtube"]
    opts = pipeline.Options(per_day=args.per_day, platforms=platforms, out=args.out, no_jev=args.no_jev)
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7 * args.weeks + 21)
    posts, cstats, _ = pipeline.gather(opts, start, end, lambda n, msg: log.info("%d/2 %s", n, msg))
    bt = evaluate(posts, end, args.weeks, args.top, pipeline.no_momentum())
    meta = {"classifier": cstats["classifier"], "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "jev_error": cstats.get("jev_error", ""), "n_posts": len(posts)}

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    (args.out / f"backtest-{stamp}.json").write_text(json.dumps({**bt, "meta": meta}, ensure_ascii=False, indent=2), encoding="utf-8")
    md = render_markdown(bt, meta)
    (args.out / f"backtest-{stamp}.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
