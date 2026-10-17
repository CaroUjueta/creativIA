"""Salidas del radar: reporte HTML autocontenido, Markdown y JSON."""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from . import config

STAGE_LABEL = {
    "naciente": "Naciente", "en_crecimiento": "En crecimiento", "saturado": "Saturado",
    "en_declive": "En declive", "estable": "Estable",
}
PLATFORM_LABEL = {
    "bluesky": "Bluesky", "hackernews": "Hacker News", "youtube": "YouTube", "google_news": "Google News",
    "linkedin": "LinkedIn", "instagram": "Instagram", "tiktok": "TikTok",
}

e = html.escape


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _growth(g: float) -> str:
    return f"{'+' if g >= 1 else '−'}{abs(g - 1) * 100:.0f}%"


def _sparkline(values: list[float], split_index: int, w: int = 220, h: int = 44) -> str:
    if not values:
        return ""
    hi = max(values) or 1
    step = w / max(1, len(values) - 1)
    pts = " ".join(f"{i * step:.1f},{h - 4 - (v / hi) * (h - 8):.1f}" for i, v in enumerate(values))
    x = split_index * step
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
            f'aria-label="Participación diaria del tema">'
            f'<rect x="{x:.1f}" y="0" width="{w - x:.1f}" height="{h}" class="spark-cur"/>'
            f'<polyline points="{pts}" class="spark-line"/></svg>')


def top_topics(result: dict, n: int = 10) -> list[dict]:
    return result["topics"][:n]


def render_html(result: dict, adaptations: dict, meta: dict, n: int = 10) -> str:
    days = result["days"]
    split_day = result["window"]["split"][:10]
    split_index = next((i for i, d in enumerate(days) if d >= split_day), len(days) - 1)
    counts = result["counts"]
    cards = []
    for rank, t in enumerate(top_topics(result, n), 1):
        a = adaptations.get(t["id"], {})
        w = t["why"]
        examples = "".join(
            f'<li><span class="pl">{e(PLATFORM_LABEL.get(p.platform, p.platform))}</span> '
            f'<a href="{e(p.url)}" target="_blank" rel="noopener">{e(p.text[:140])}{"…" if len(p.text) > 140 else ""}</a></li>'
            for p in t["examples"][:3])
        hooks = "".join(f"<li>{e(h)}</li>" for h in a.get("ganchos", []))
        formats = "".join(f"<li><b>{e(PLATFORM_LABEL.get(k, k))}:</b> {e(v)}</li>" for k, v in a.get("formatos", {}).items())
        signals = []
        if w["hooks"] and w["hooks"][0]["lift"] >= 1.2:
            signals.append(f'Gancho que más rinde: <b>{e(w["hooks"][0]["value"].replace("_", " "))}</b> ({w["hooks"][0]["lift"]}×)')
        if w["formats"] and w["formats"][0]["lift"] >= 1.2:
            signals.append(f'Formato: <b>{e(w["formats"][0]["value"].replace("_", " "))}</b> ({w["formats"][0]["lift"]}×)')
        if w["timing"] and w["timing"][0]["lift"] >= 1.2:
            signals.append(f'Franja: <b>{e(w["timing"][0]["value"])}</b>')
        if w["publishers"]:
            signals.append("Publican: " + ", ".join(e(k.replace("_", " ")) for k, _ in w["publishers"][:2]))
        cards.append(f"""
<article class="card">
  <header class="card-h">
    <span class="rank">{rank}</span>
    <div class="title"><h2>{e(t["label"])}</h2>
      <div class="badges"><span class="stage stage-{t["stage"]}">{STAGE_LABEL[t["stage"]]}</span>
      <span class="muted">{t["n_posts"]} piezas · {t["n_authors"]} autores · {", ".join(e(PLATFORM_LABEL.get(k, k)) for k in t["platforms"])}</span></div>
    </div>
  </header>
  <div class="metrics">
    <div><span class="k">Crecimiento</span><span class="v">{_growth(t["growth"])}</span></div>
    <div><span class="k">Participación</span><span class="v">{_pct(t["share_current"])}</span></div>
    <div><span class="k">Encaje audiencia</span><span class="v">{_pct(t["audience_fit"])}</span></div>
    <div><span class="k">Accionable</span><span class="v">{_pct(t["practical"])}</span></div>
    <div class="sparkbox">{_sparkline(t["daily"], split_index)}<span class="k">participación diaria · sombreado = semana actual</span></div>
  </div>
  <div class="cols">
    <section><h3>Por qué funciona</h3><p>{e(a.get("por_que_funciona", ""))}</p>
      <p class="signals">{" · ".join(signals) or "Pocas piezas con interacción medible."}</p></section>
    <section><h3>Cómo lo adaptamos</h3><p>{e(a.get("angulo", ""))}</p>
      <h4>Ganchos</h4><ul>{hooks}</ul><h4>Formato por plataforma</h4><ul>{formats}</ul>
      <p class="warn"><b>Cuidado:</b> {e(a.get("cuidado", ""))}</p></section>
  </div>
  <details><summary>Piezas de referencia</summary><ul class="ex">{examples}</ul></details>
</article>""")

    terms = "".join(
        f'<li><b>{e(t["term"])}</b> <span class="muted">{t["count"]} piezas · {t["authors"]} autores · '
        f'{"nuevo" if t["new"] else f"{t["ratio"]}× la base"}</span></li>' for t in result["emerging_terms"])
    sources = " · ".join(f"{e(PLATFORM_LABEL.get(k, k))}: {v}" for k, v in counts["by_platform"].items())
    warn = "" if meta["classifier"] == "jev" else (
        '<p class="banner">Modo heurístico: no se encontró <code>TYPESAFE_API_KEY</code>, así que la clasificación '
        'usa palabras clave en vez de Jev. Los temas y el encaje con la audiencia son aproximados.</p>')

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Radar de contenido IA</title>
<style>
:root {{ --bg:#f7f6f3; --card:#fff; --ink:#1d1d1f; --muted:#6b6b70; --line:#e4e2dc; --accent:#3d5afe;
  --naciente:#0a7d4f; --crec:#2f6fd6; --sat:#a15c00; --decl:#b3261e; --est:#6b6b70; --spark:rgba(61,90,254,.09); }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141416; --card:#1d1d20; --ink:#ececf0;
  --muted:#9a9aa2; --line:#2e2e33; --accent:#8c9eff; --naciente:#4cc38a; --crec:#7aa7ff; --sat:#f0b45b; --decl:#ff8a80; --est:#9a9aa2; --spark:rgba(140,158,255,.12); }} }}
:root[data-theme="dark"] {{ --bg:#141416; --card:#1d1d20; --ink:#ececf0; --muted:#9a9aa2; --line:#2e2e33; --accent:#8c9eff;
  --naciente:#4cc38a; --crec:#7aa7ff; --sat:#f0b45b; --decl:#ff8a80; --est:#9a9aa2; --spark:rgba(140,158,255,.12); }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1040px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:clamp(22px,4vw,32px); margin:0 0 6px; letter-spacing:-.01em; }}
.lede {{ color:var(--muted); margin:0 0 20px; }}
.banner {{ border:1px solid var(--sat); color:var(--sat); padding:10px 14px; border-radius:8px; }}
.summary {{ display:flex; flex-wrap:wrap; gap:8px 20px; color:var(--muted); font-size:13px; margin-bottom:24px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px; margin:0 0 16px; }}
.card-h {{ display:flex; gap:14px; align-items:flex-start; }}
.rank {{ font-size:26px; font-weight:700; color:var(--accent); min-width:32px; font-variant-numeric:tabular-nums; }}
h2 {{ font-size:18px; margin:2px 0 6px; }}
h3 {{ font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:0 0 6px; }}
h4 {{ font-size:13px; margin:12px 0 4px; }}
.badges {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; font-size:13px; }}
.stage {{ font-weight:600; font-size:12px; padding:2px 8px; border-radius:99px; border:1px solid currentColor; }}
.stage-naciente {{ color:var(--naciente); }} .stage-en_crecimiento {{ color:var(--crec); }}
.stage-saturado {{ color:var(--sat); }} .stage-en_declive {{ color:var(--decl); }} .stage-estable {{ color:var(--est); }}
.muted {{ color:var(--muted); }}
.metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)) minmax(0,2fr); gap:12px; margin:16px 0; padding:12px 0;
  border-top:1px solid var(--line); border-bottom:1px solid var(--line); }}
.metrics .k {{ display:block; font-size:12px; color:var(--muted); }}
.metrics .v {{ font-size:20px; font-weight:600; font-variant-numeric:tabular-nums; }}
.spark {{ width:100%; height:44px; display:block; }} .spark-line {{ fill:none; stroke:var(--accent); stroke-width:2; vector-effect:non-scaling-stroke; }}
.spark-cur {{ fill:var(--spark); }}
.cols {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; }}
.cols p {{ margin:0 0 8px; }} .cols ul {{ margin:0; padding-left:18px; }}
.signals {{ font-size:13px; color:var(--muted); }}
.warn {{ font-size:13px; margin-top:10px !important; }}
details {{ margin-top:12px; font-size:14px; }} summary {{ cursor:pointer; color:var(--accent); }}
.ex {{ padding-left:18px; }} .ex li {{ margin:4px 0; }} .pl {{ font-size:12px; color:var(--muted); }}
a {{ color:var(--accent); }}
.terms {{ columns:2; padding-left:18px; }} .terms li {{ break-inside:avoid; margin:3px 0; }}
.method {{ font-size:14px; color:var(--muted); }} .method li {{ margin:4px 0; }}
@media (max-width:720px) {{ .metrics {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .sparkbox {{ grid-column:1/-1; }}
  .cols {{ grid-template-columns:1fr; }} .terms {{ columns:1; }} }}
</style></head><body><main>
<h1>Los {n} temas de IA que más están creciendo esta semana</h1>
<p class="lede">Por qué funcionan y cómo adaptarlos para ejecutivos y equipos de Latinoamérica.
Semana del {e(result["window"]["split"][:10])} al {e(result["window"]["end"][:10])}, comparada con los {len(days) - 7} días anteriores.</p>
{warn}
<div class="summary"><span>{counts["ai"]} piezas de IA analizadas ({counts["current"]} esta semana)</span><span>{sources}</span>
<span>Crecimiento medido en: {", ".join(e(PLATFORM_LABEL.get(p, p)) for p in counts["momentum_platforms"]) or "—"}</span>
<span>Clasificación: {e(meta["classifier"])}</span><span>Adaptación: {e(meta["adapter"])}</span><span>Generado {e(meta["generated"])}</span></div>
{"".join(cards)}
<article class="card"><h3>Términos emergentes</h3>
<p class="muted">Palabras y frases cuya frecuencia se disparó esta semana frente a la línea base. Atrapan lo que la taxonomía no anticipa.</p>
<ul class="terms">{terms or "<li>Sin términos con señal suficiente.</li>"}</ul></article>
<article class="card method"><h3>Cómo se calcula</h3><ul>
<li><b>Muestra comparable:</b> cada día se toman las piezas con más interacción por consulta y plataforma, para comparar participación (no volumen bruto).</li>
<li><b>Clasificación:</b> Jev (TypeSafe) responde en una sola llamada por pieza: tema, gancho, formato, tipo de publicador, encaje con la audiencia (escala 0–3) y si es accionable, técnica, humo o de LatAm. El tema se cuenta como probabilidad, no como etiqueta ganadora.</li>
<li><b>Tendencia:</b> participación del tema esta semana vs. la línea base, promediada entre plataformas. Naciente = crece ≥50% con participación pequeña; saturado = grande y plano.</li>
<li><b>Por qué funciona:</b> interacción relativa a la mediana de cada plataforma, agrupada por gancho, formato y franja horaria (hora de Bogotá). Son hipótesis, no causalidad.</li>
<li><b>Prioridad:</b> {", ".join(f"{k} {v:.0%}" for k, v in config.WEIGHTS.items())}, más bonificación por llegar temprano y penalización por humo.</li>
<li><b>Privacidad:</b> solo contenido público; los autores se guardan como hash irreversible y el texto se limpia de menciones, correos y teléfonos.</li>
</ul></article>
</main></body></html>"""


def render_markdown(result: dict, adaptations: dict, meta: dict, n: int = 10) -> str:
    lines = [f"# Los {n} temas de IA que más están creciendo esta semana",
             f"Semana {result['window']['split'][:10]} → {result['window']['end'][:10]} · "
             f"clasificación: {meta['classifier']} · adaptación: {meta['adapter']}", ""]
    for rank, t in enumerate(top_topics(result, n), 1):
        a = adaptations.get(t["id"], {})
        lines += [
            f"## {rank}. {t['label']}",
            f"- **Señal de crecimiento:** {_growth(t['growth'])} vs. línea base · etapa: {STAGE_LABEL[t['stage']]} · "
            f"{t['n_posts']} piezas de {t['n_authors']} autores",
            f"- **Relevancia para la audiencia:** {_pct(t['audience_fit'])} · accionable {_pct(t['practical'])}",
            f"- **Por qué funciona:** {a.get('por_que_funciona', '')}",
            f"- **Cómo adaptarlo:** {a.get('angulo', '')}",
            *[f"  - Gancho: {h}" for h in a.get("ganchos", [])],
            *[f"  - {PLATFORM_LABEL.get(k, k)}: {v}" for k, v in a.get("formatos", {}).items()],
            f"- **Cuidado:** {a.get('cuidado', '')}",
            *[f"- Referencia ({p.platform}): {p.url}" for p in t["examples"][:3]],
            "",
        ]
    if result["emerging_terms"]:
        lines.append("## Términos emergentes")
        lines += [f"- {t['term']} ({t['count']} piezas, {t['authors']} autores)" for t in result["emerging_terms"]]
    return "\n".join(lines) + "\n"


def write_outputs(result: dict, adaptations: dict, meta: dict, out_dir: Path, n: int = 10) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    paths = {"html": out_dir / f"radar-{stamp}.html", "md": out_dir / f"radar-{stamp}.md", "json": out_dir / f"radar-{stamp}.json"}
    paths["html"].write_text(render_html(result, adaptations, meta, n), encoding="utf-8")
    paths["md"].write_text(render_markdown(result, adaptations, meta, n), encoding="utf-8")
    serializable = {**result, "topics": [{**t, "examples": [p.to_dict() for p in t["examples"]]} for t in result["topics"]],
                    "adaptations": adaptations, "meta": meta}
    paths["json"].write_text(json.dumps(serializable, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return paths
