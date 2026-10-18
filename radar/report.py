"""Salidas del radar: reporte HTML autocontenido, Markdown y JSON."""

from __future__ import annotations

import base64
import json
import re
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


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _growth(g: float) -> str:
    return f"{'+' if g >= 1 else '−'}{abs(g - 1) * 100:.0f}%"


def top_topics(result: dict, n: int = 10) -> list[dict]:
    return result["topics"][:n]


def _clip(text: str, n: int) -> str:
    return text[:n] + ("…" if len(text) > n else "")


def _feed_text(post: dict) -> str:
    text = post["text"]
    if post["platform"] == "youtube":  # título + descripción: la descripción suele ser una lista de enlaces
        text = re.split(r"https?://", text, maxsplit=1)[0].rstrip(" :-|")
    return _clip(text, 260 if post["platform"] == "youtube" else 420)


def _example(p) -> dict:
    """Acepta un Post o el dict que queda al leerlo del JSON de salida."""
    get = p.get if isinstance(p, dict) else lambda k, d=None: getattr(p, k, d)
    text = get("text", "") or ""
    return {"platform": PLATFORM_LABEL.get(get("platform"), get("platform")), "url": get("url", ""),
            "text": text[:180] + ("…" if len(text) > 180 else ""), "date": str(get("created_at", ""))[:10]}


def _signals(why: dict) -> list[dict]:
    """Solo las señales que rinden claramente por encima de la mediana del tema."""
    out = []
    for kind, label, names in (("hooks", "Gancho", config.HOOKS), ("formats", "Formato", config.FORMATS),
                               ("timing", "Franja (Bogotá)", {})):
        if why.get(kind) and why[kind][0]["lift"] >= 1.2:
            top = why[kind][0]
            out.append({"kind": label, "value": top["value"].replace("_", " "), "hint": names.get(top["value"], ""),
                        "lift": top["lift"], "n": top["n"]})
    return out


def _topic(rank: int, t: dict, adaptations: dict) -> dict:
    return {
        "rank": rank, "id": t["id"], "label": t["label"], "description": t.get("description", ""),
        "stage": t["stage"], "growth": t["growth"], "share": t["share_current"], "share_base": t["share_baseline"],
        "fit": t["audience_fit"], "practical": t["practical"], "hype": t.get("hype", 0),
        "n_posts": t["n_posts"], "n_authors": t["n_authors"], "daily": t["daily"],
        "platforms": {PLATFORM_LABEL.get(k, k): v for k, v in t["platforms"].items()},
        "signals": _signals(t["why"]),
        "publishers": [k.replace("_", " ") for k, _ in t["why"].get("publishers", [])[:2]],
        "lang_es": t["why"].get("lang_share", {}).get("es", 0),
        "adaptation": adaptations.get(t["id"], {}),
        "examples": [_example(p) for p in t["examples"][:4]],
    }


def _payload(result: dict, adaptations: dict, meta: dict, n: int) -> dict:
    days = result["days"]
    split_day = result["window"]["split"][:10]
    topics = [_topic(rank, t, adaptations) for rank, t in enumerate(top_topics(result, n), 1)]
    by_app = {PLATFORM_LABEL.get(k, k): {"momentum": v["momentum"], "n": v["n_current"],
                                         "sources": {PLATFORM_LABEL.get(s, s): c for s, c in v.get("sources", {}).items()},
                                         "topics": [_topic(r, t, adaptations) for r, t in enumerate(v["topics"][:n], 1)]}
              for k, v in result.get("by_app", {}).items()}
    counts = result["counts"]
    return {
        "n": n, "days": days, "split_index": next((i for i, d in enumerate(days) if d >= split_day), len(days) - 1),
        "window": {k: v[:10] for k, v in result["window"].items()},
        "counts": {**counts, "by_platform": {PLATFORM_LABEL.get(k, k): v for k, v in counts["by_platform"].items()},
                   "momentum_platforms": [PLATFORM_LABEL.get(k, k) for k in counts["momentum_platforms"]]},
        "meta": meta, "stages": STAGE_LABEL, "topics": topics, "by_app": by_app, "account": result.get("account"), "terms": result["emerging_terms"],
        "feed": [{**f, "platform": PLATFORM_LABEL.get(f["platform"], f["platform"]), "text": _feed_text(f),
                  "topic_label": config.TOPIC_NAMES.get(f["topic"], f["topic"]), "hook": f["hook"].replace("_", " ")}
                 for f in result.get("feed", [])],
        "weights": {k: v for k, v in config.WEIGHTS.items()},
    }


def latest_backtest(out_dir: Path) -> dict | None:
    """Resumen del backtest más reciente en out/ (python -m radar.backtest), si existe."""
    files = sorted(out_dir.glob("backtest-*.json"), reverse=True)
    if not files:
        return None
    bt = json.loads(files[0].read_text(encoding="utf-8"))
    last = bt["folds"][-1] if bt["folds"] else None
    return {"summary": bt["summary"], "meta": bt["meta"], "top": bt["top"],
            "last": last and {"cut": last["cut"], "next_end": last["next_end"],
                              "topics": [{k: r[k] for k in ("label", "stage", "share_base", "share_next")}
                                         for r in last["topics"][: bt["top"]]]}}


def render_html(result: dict, adaptations: dict, meta: dict, n: int = 10, backtest: dict | None = None) -> str:
    data = json.dumps({**_payload(result, adaptations, meta, n), "backtest": backtest}, ensure_ascii=False, default=str)
    # Evita que un texto con "</script>" cierre la etiqueta de datos.
    data = data.replace("<", "\\u003c")
    return HTML_TEMPLATE.replace("__N__", str(n)).replace("__LOGO__", LOGO).replace("__DATA__", data)


def render_empty(n: int = 10) -> str:
    """Página sin datos, con el botón para correr el radar por primera vez."""
    return HTML_TEMPLATE.replace("__N__", str(n)).replace("__LOGO__", LOGO).replace("__DATA__", "null")


# Logo de CreativIA embebido: el reporte es un solo archivo que se abre sin la app.
LOGO = "data:image/png;base64," + base64.b64encode((Path(__file__).parent / "assets" / "logo.png").read_bytes()).decode()

HTML_TEMPLATE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CreativIA · Radar de contenido</title>
<link rel="icon" type="image/png" href="__LOGO__">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
/* Claro u oscuro según el sistema; Tendencias y Feed comparten los mismos colores. */
:root{
  --bg:#fff; --s1:#fff; --s2:#efefef; --s3:#e0e0e0; --line:#dbdbdb; --ink:#000; --ink-2:#262626; --muted:#737373;
  --blue:#0095f6; --pink:#ff3040; --cyan:#25f4ee; --up:#00a35c;
  --ig:linear-gradient(45deg,#feda75 0%,#fa7e1e 25%,#d62976 50%,#962fbf 75%,#4f5bd5 100%);
  --naciente:#00a3a3; --en_crecimiento:#d62976; --saturado:#f77737; --en_declive:#a8a8a8; --estable:#8e8e8e;
  --chart-cur:rgba(0,0,0,.035);
  color-scheme:light dark;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#000; --s1:#121212; --s2:#262626; --s3:#363636; --line:#262626; --ink:#f5f5f5; --ink-2:#dbdbdb; --muted:#a8a8a8;
  --chart-cur:rgba(255,255,255,.05);
}}
body.feed-mode{overflow:hidden}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}
button{font:inherit;color:inherit}
.num{font-variant-numeric:tabular-nums}
[hidden]{display:none !important}

/* Barra superior */
.bar{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line)}
.bar-in{max-width:975px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:9px;font-weight:800;font-size:19px;letter-spacing:-.03em}
.brand-mark{width:30px;height:30px;flex:none;background:url(__LOGO__) center/contain no-repeat}
.seg{display:inline-flex;background:var(--s2);border-radius:10px;padding:3px}
.seg button{background:none;border:0;color:var(--muted);padding:6px 16px;border-radius:8px;cursor:pointer;font-weight:700;font-size:14px}
.seg button[aria-pressed="true"]{background:var(--s1);color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.12)}
.actions{display:flex;gap:8px;align-items:center}
.hist{background:var(--s2);color:var(--ink);border:0;border-radius:8px;padding:8px 10px;font:inherit;font-size:13px;font-weight:600}
.run-btn{display:inline-flex;align-items:center;gap:6px;background:var(--blue);color:#fff;border:0;border-radius:8px;padding:8px 14px;font-weight:700;font-size:13px;cursor:pointer}
.run-btn:hover{background:#1877f2}
.mode{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--muted);padding:6px 4px}
.mode i{width:7px;height:7px;border-radius:50%;background:var(--up)}
.mode.local i{background:#f5a623}.mode.heuristico i{background:var(--pink)}

/* Pestañas y chips compartidos */
.tabs-top{display:flex;justify-content:center;gap:24px;padding:14px 16px 4px}
.ttab{background:none;border:0;color:var(--muted);font-weight:700;font-size:16px;padding:4px 2px;cursor:pointer;position:relative}
.ttab:hover{color:var(--ink-2)}
.ttab[aria-selected="true"]{color:var(--ink)}
.ttab[aria-selected="true"]::after{content:"";position:absolute;left:30%;right:30%;bottom:-6px;height:3px;border-radius:3px;background:var(--ink)}
.chips{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.chip{background:var(--s2);border:0;color:var(--ink);border-radius:8px;padding:7px 14px;font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap}
.chip:hover{background:var(--s3)}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
.sel{background:var(--s2);color:var(--ink);border:0;border-radius:8px;padding:8px 12px;font:inherit;font-size:13px;font-weight:600;max-width:220px}

/* Explorar */
.wrap{max-width:975px;margin:0 auto;padding:0 16px}
.stories{display:flex;gap:16px;overflow-x:auto;padding:20px 2px 14px;scrollbar-width:none}
.stories::-webkit-scrollbar{display:none}
.story{flex:none;width:74px;background:none;border:0;padding:0;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:6px}
.ring{width:70px;height:70px;border-radius:50%;padding:3px;background:var(--ig);display:grid;place-items:center}
.story.cold .ring{background:var(--s3)}
.story.seen .ring{background:var(--s3)}
.ring-in{width:100%;height:100%;border-radius:50%;border:3px solid var(--bg);background:linear-gradient(160deg,var(--g1),var(--g2));background-size:cover;background-position:center;display:grid;place-items:center;color:#fff;font-weight:900;font-size:20px;text-shadow:0 1px 6px rgba(0,0,0,.3);overflow:hidden}
.story span.lbl{font-size:12px;color:var(--ink-2);max-width:74px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;margin:6px 0 14px}
.head h1{font-size:24px;font-weight:800;letter-spacing:-.03em;margin:0}
.head p{margin:2px 0 0;color:var(--muted);font-size:13px}
.head p b{color:#f5a623;font-weight:600}

.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;grid-auto-flow:dense}
.cv{position:relative;aspect-ratio:1;border:0;padding:0;cursor:pointer;overflow:hidden;background:linear-gradient(150deg,var(--g1),var(--g2));color:#fff;text-align:left;container-type:inline-size;border-radius:4px}
.cv.big{grid-column:span 2;grid-row:span 2}
.cv.tall{grid-row:span 2;aspect-ratio:auto}
.cv img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transition:transform .4s}
.cv.photo::before{content:"";position:absolute;inset:0;z-index:1;background:linear-gradient(to top,var(--g2) 22%,color-mix(in srgb,var(--g2) 55%,transparent) 55%,rgba(0,0,0,.08) 100%)}
.cv:not(.photo)::before{content:"";position:absolute;inset:0;background:radial-gradient(90% 70% at 85% 10%,rgba(255,255,255,.28),transparent 60%)}
.cv-in{position:absolute;inset:0;z-index:2;display:flex;flex-direction:column;justify-content:space-between;padding:7cqi}
.cv-top{display:flex;justify-content:space-between;align-items:flex-start;gap:6px}
.cv-rank{font-weight:900;font-size:max(13px,9cqi);line-height:1;letter-spacing:-.04em}
.cv-g{background:#fff;color:#000;border-radius:999px;padding:.25em .6em;font-weight:800;font-size:max(11px,5.5cqi);white-space:nowrap}
.cv-g.down,.cv-g.flat{background:rgba(255,255,255,.25);color:#fff}
.cv-name{font-weight:900;letter-spacing:-.035em;line-height:1.02;font-size:max(14px,11cqi);display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:4;overflow:hidden;text-wrap:balance}
.cv.big .cv-name{font-size:max(22px,9.5cqi)}
.cv-meta{display:block;margin-top:.5em;font-size:max(11px,4.6cqi);font-weight:600;opacity:.9}
.cv-meta{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.cv:hover img{transform:scale(1.05)}
.cv:hover::after{content:"";position:absolute;inset:0;background:rgba(0,0,0,.12);z-index:1}
.cv:focus-visible{outline:3px solid var(--blue);outline-offset:2px}

.sect{margin:34px 0 0}
.sect h2{font-size:17px;font-weight:800;margin:0 0 4px;letter-spacing:-.02em}
.sect>p{margin:0 0 12px;color:var(--muted);font-size:13px}
.tags{display:flex;flex-wrap:wrap;gap:8px}
.tag{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:999px;padding:7px 14px;font-size:14px;font-weight:600;background:var(--s1)}
.tag small{font-size:12px;font-weight:700;color:var(--up)}
.tag .new{background:var(--ig);color:#fff;font-size:10px;font-weight:800;border-radius:4px;padding:2px 6px;letter-spacing:.03em}
details.fold{border-top:1px solid var(--line);margin-top:34px;padding-top:4px}
details.fold+details.fold{margin-top:0}
details.fold summary{cursor:pointer;font-weight:700;font-size:15px;padding:14px 0;list-style:none;display:flex;justify-content:space-between}
details.fold summary::-webkit-details-marker{display:none}
details.fold summary::after{content:"+";font-weight:400;font-size:22px;line-height:1;color:var(--muted)}
details.fold[open] summary::after{content:"−"}
details.fold ul{color:var(--ink-2);font-size:14px;padding-left:18px;margin:0 0 16px}
details.fold li{margin:6px 0}
.map svg{width:100%;height:auto;display:block;overflow:visible}
.map .axis{stroke:var(--line)}
.map .grid-l{stroke:var(--line);stroke-dasharray:3 5}
.map text{fill:var(--muted);font-size:11px;font-family:Inter,sans-serif}
.map .hot{fill:#d62976;font-weight:700;font-size:12px}
.bubble{cursor:pointer}
.bubble circle{fill-opacity:.85;stroke:var(--bg);stroke-width:2}
.bubble text{font-weight:800;font-size:12px;text-anchor:middle;dominant-baseline:central;fill:#fff}
.bubble:hover circle{fill-opacity:1}
.cap{color:var(--muted);font-size:13px;margin:8px 0 16px}
footer{color:var(--muted);font-size:12px;text-align:center;padding:24px 16px 40px}
.empty{max-width:440px;margin:80px auto;text-align:center;color:var(--muted);padding:0 16px}
.empty h2{color:var(--ink);font-size:24px;margin:0 0 8px}
.empty .run-btn{margin-top:16px;padding:12px 20px;font-size:15px}
.stage{display:inline-flex;align-items:center;gap:5px;font-weight:600;color:var(--c)}
.stage::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--c)}

/* Historias */
.sv{position:fixed;inset:0;z-index:45;background:#1a1a1a;display:grid;place-items:center;padding:12px}
.sv-card{position:relative;height:min(100%,860px);aspect-ratio:9/16;max-width:100%;border-radius:12px;overflow:hidden;background:linear-gradient(165deg,var(--g1),var(--g2));color:#fff;display:flex;flex-direction:column;padding:14px 18px 20px}
.sv-card>img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:saturate(1.1)}
.sv-card.photo::before{content:"";position:absolute;inset:0;z-index:1;background:linear-gradient(to top,var(--g2) 38%,color-mix(in srgb,var(--g2) 50%,transparent) 62%,rgba(0,0,0,.45) 100%)}
.sv-card>*:not(img){position:relative;z-index:2}
.sv-bars{display:flex;gap:4px}
.sv-bars i{flex:1;height:3px;border-radius:3px;background:rgba(255,255,255,.35);overflow:hidden}
.sv-bars i b{display:block;height:100%;width:0;background:#fff}
.sv-bars i.done b{width:100%}
.sv-bars i.on b{animation:fill var(--dur,6s) linear forwards}
.sv.paused .sv-bars i.on b{animation-play-state:paused}
@keyframes fill{to{width:100%}}
.sv-head{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:14px;font-weight:700}
.sv-head .brand-mark{width:30px;height:30px}
.sv-head span{opacity:.75;font-weight:500}
.sv-x{margin-left:auto;background:none;border:0;color:#fff;cursor:pointer;padding:4px;display:grid}
.sv-body{flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:14px;padding-bottom:6px}
.sv-kick{font-size:14px;font-weight:700;opacity:.9}
.sv-name{font-size:clamp(30px,5.2vh,46px);font-weight:900;letter-spacing:-.04em;line-height:1;margin:0;text-wrap:balance}
.sv-g{font-size:clamp(44px,9vh,80px);font-weight:900;letter-spacing:-.05em;line-height:.9}
.sv-g small{display:block;font-size:14px;letter-spacing:0;font-weight:600;opacity:.85;margin-top:6px}
.sv-hook{background:#fff;color:#000;border-radius:14px;padding:12px 14px;font-weight:700;font-size:15px;line-height:1.35;box-shadow:0 8px 24px rgba(0,0,0,.2)}
.sv-hook small{display:block;color:#737373;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}
.sv-cta{align-self:center;background:#fff;color:#000;border:0;border-radius:999px;padding:10px 20px;font-weight:800;cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.sv-tap{position:absolute;top:70px;bottom:90px;width:40%;z-index:3;background:none;border:0;cursor:pointer}
.sv-tap.prev{left:0}.sv-tap.next{right:0}
.sv-stage{height:min(calc(100dvh - 24px),860px);display:flex;align-items:center;gap:20px}
.sv-stage .sv-card{height:100%}
.sv-arrow{flex:none;width:32px;height:32px;border-radius:50%;border:0;background:rgba(255,255,255,.85);color:#000;display:grid;place-items:center;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.3)}
.sv-arrow:hover{background:#fff}
.sv-stage{position:relative}

/* Detalle, como un post abierto de Instagram */
.sheet{position:fixed;inset:0;z-index:40;display:grid;place-items:center;padding:24px}
.sheet-bg{position:absolute;inset:0;background:rgba(0,0,0,.65)}
.panel{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 420px;width:min(1040px,100%);height:min(680px,100%);background:var(--s1);border-radius:8px;overflow:hidden;animation:zoom .18s ease-out}
@keyframes zoom{from{transform:scale(.97);opacity:0}}
@keyframes slide-u{from{transform:translateY(60px);opacity:0}}
.p-cover{position:relative;background:linear-gradient(150deg,var(--g1),var(--g2));color:#fff;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-end;padding:32px;container-type:inline-size}
.p-cover img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.p-cover.photo::before{content:"";position:absolute;inset:0;z-index:1;background:linear-gradient(to top,var(--g2) 25%,color-mix(in srgb,var(--g2) 45%,transparent) 60%,rgba(0,0,0,.1) 100%)}
.p-cover>*:not(img){position:relative;z-index:2}
.p-cover .k{font-weight:700;font-size:15px;opacity:.9}
.p-cover h2{margin:6px 0 0;font-size:max(30px,8cqi);font-weight:900;letter-spacing:-.04em;line-height:1;text-wrap:balance}
.p-cover .big-g{font-size:max(44px,13cqi);font-weight:900;letter-spacing:-.05em;line-height:1;margin-top:14px}
.p-side{display:flex;flex-direction:column;min-height:0;border-left:1px solid var(--line)}
.p-head{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--line)}
.p-av{width:34px;height:34px;border-radius:50%;padding:2px;background:var(--ig);flex:none}
.p-av i{display:block;width:100%;height:100%;border-radius:50%;border:2px solid var(--s1);background:linear-gradient(160deg,var(--g1),var(--g2))}
.p-head b{display:block;font-size:14px;line-height:1.2}
.p-head small{font-size:12px;color:var(--muted)}
.x{margin-left:auto;flex:none;width:34px;height:34px;border-radius:50%;border:0;background:none;cursor:pointer;display:grid;place-items:center;color:var(--ink)}
.x:hover{background:var(--s2)}
.x:focus{outline:none}.x:focus-visible{outline:2px solid var(--blue)}
.p-body{flex:1;overflow-y:auto;padding:16px}
.p-desc{margin:0 0 14px;font-size:14px;color:var(--ink-2)}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin:0 0 14px;text-align:center;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:12px 0}
.stat b{display:block;font-size:18px;font-weight:800;letter-spacing:-.02em}
.stat span{font-size:11px;color:var(--muted);line-height:1.25;display:block}
.g.up{color:var(--up)}.g.down,.g.flat{color:var(--muted)}
.chart{margin:0 0 16px}
.chart svg{width:100%;height:90px;display:block}
.chart .line{fill:none;stroke:#d62976;stroke-width:2.2;vector-effect:non-scaling-stroke}
.chart .area{fill:url(#ga)}
.chart .cur{fill:var(--chart-cur)}
.chart-x{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:4px}
.ptabs{display:flex;gap:20px;border-bottom:1px solid var(--line);margin:0 0 14px}
.ptab{background:none;border:0;color:var(--muted);font-weight:700;font-size:14px;padding:8px 0;border-bottom:2px solid transparent;margin-bottom:-1px;cursor:pointer}
.ptab[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--ink)}
.lead{font-size:15px;margin:0 0 14px;color:var(--ink)}
h4{font-size:13px;color:var(--muted);font-weight:600;margin:16px 0 8px}
.hooks{display:grid;gap:8px}
.hook{display:flex;gap:10px;align-items:flex-start;justify-content:space-between;background:var(--s2);border-radius:18px 18px 18px 4px;padding:11px 14px}
.hook p{margin:0;font-weight:600;font-size:14px}
.copy{flex:none;display:inline-flex;align-items:center;gap:4px;border:0;background:none;color:var(--blue);font-size:12px;font-weight:700;cursor:pointer;padding:2px 0}
.copy.ok{color:var(--up)}
.fmts{display:grid}
.fmt{display:grid;grid-template-columns:10px 80px minmax(0,1fr);gap:10px;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line);font-size:14px}
.fmt:last-child{border-bottom:0}
.fmt.on{background:var(--s2);border-radius:10px;padding:10px;border-bottom:0;margin-bottom:6px}
.fmt.on span{color:var(--ink);font-weight:600}
.fmt.dim{opacity:.55}
.net{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:4px 0 6px}
.net>span{font-size:13px;font-weight:600;color:var(--muted)}
.net .chip i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:1px}
.sv-fmt{margin-top:8px;font-size:13px;font-weight:600;opacity:.95}
.fmt i{width:8px;height:8px;border-radius:50%;align-self:center}
.fmt b{font-weight:700}
.fmt span{color:var(--ink-2)}
.careful{display:flex;gap:10px;margin-top:14px;font-size:14px;color:var(--ink-2)}
.careful::before{content:"!";flex:none;width:20px;height:20px;border-radius:50%;background:#f5a623;color:#000;font-weight:800;font-size:13px;display:grid;place-items:center}
.sigs{display:grid}
.sig{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid var(--line);font-size:14px}
.sig span{color:var(--muted)}
.sig b{text-transform:capitalize;color:var(--ink)}
.sig .lift{color:var(--up);font-weight:800;white-space:nowrap}
.note{color:var(--muted);font-size:13px}
.refs{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.refs li a{display:block;background:var(--s2);border-radius:12px;padding:12px 14px;text-decoration:none}
.refs li a:hover{background:var(--s3)}
.refs .m{display:flex;gap:8px;align-items:center;font-size:12px;color:var(--muted);margin-bottom:4px}
.refs .m i{width:7px;height:7px;border-radius:50%}
.refs p{margin:0;font-size:14px}
.to-feed{margin-top:14px;width:100%;background:var(--blue);color:#fff;border:0;border-radius:8px;padding:10px;font-weight:700;cursor:pointer}

/* Feed vertical */
.tk-top{display:flex;flex-direction:column;align-items:center;gap:10px;padding:0 16px 10px}
.tk-top .tabs-top{padding-bottom:6px}
.tk{height:calc(100dvh - var(--tk-off,170px));overflow-y:auto;scroll-snap-type:y mandatory;scrollbar-width:none;overscroll-behavior:contain;outline:none}
.tk::-webkit-scrollbar{display:none}
.tk-item{height:100%;scroll-snap-align:start;scroll-snap-stop:always;display:flex;justify-content:center;padding:6px 16px 16px}
.tk-stage{height:100%;display:flex;align-items:flex-end;gap:14px;min-width:0}
.tk-card{position:relative;height:100%;aspect-ratio:9/16;max-width:calc(100vw - 110px);border-radius:16px;overflow:hidden;background:linear-gradient(165deg,var(--g1),var(--g2));display:flex;flex-direction:column;padding:18px;color:#fff;user-select:none;-webkit-user-select:none}
.tk-card::before{content:"";position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,.6),transparent 50%);pointer-events:none;z-index:1}
.tk-card>*{position:relative;z-index:2}
.tk-card>.tk-blur{position:absolute;z-index:0}
.tk-row{display:flex;justify-content:space-between;align-items:center;gap:8px}
.tk-plat{display:inline-flex;align-items:center;gap:6px;background:rgba(0,0,0,.35);padding:5px 10px;border-radius:999px;font-size:12px;font-weight:700}
.tk-plat i{width:8px;height:8px;border-radius:50%}
.tk-fire{display:inline-flex;align-items:center;gap:4px;background:#fff;color:#000;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:800;white-space:nowrap}
.tk-fire svg{color:var(--pink)}
.tk-body{flex:1;display:flex;flex-direction:column;justify-content:center;min-height:0;padding:12px 0}
.tk-text{margin:0;font-weight:800;letter-spacing:-.015em;line-height:1.22;overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:11;overflow:hidden}
.tk-text.l{font-size:clamp(22px,3.6vh,32px);line-height:1.15}
.tk-text.m{font-size:clamp(18px,2.8vh,24px)}.tk-text.s{font-size:clamp(15px,2.2vh,19px);font-weight:700}
.tk-meta{font-size:14px}
.tk-meta b{font-weight:800}
.tk-meta span{opacity:.8}
.tk-cap{margin:6px 0 0;font-size:15px;line-height:1.4;font-weight:600;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden}
.tk-tags{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;align-items:center}
.tk-tag{background:none;border:0;color:#fff;font-weight:800;padding:0;cursor:pointer;font-size:14px}
.tk-tag:hover{text-decoration:underline}
.tk-hook{background:rgba(255,255,255,.2);border-radius:4px;padding:2px 7px;font-size:12px;font-weight:600}
.tk-card.yt{background:#111}
.tk-blur{inset:-30px;background-size:cover;background-position:center;filter:blur(28px) brightness(.5);transform:scale(1.1)}
.tk-media{display:block;position:relative;margin:0 -18px;color:#fff}
.tk-media img{width:100%;display:block;aspect-ratio:16/9;object-fit:cover;background:#000}
.tk-play{position:absolute;inset:0;margin:auto;width:60px;height:60px;border-radius:50%;background:rgba(0,0,0,.55);display:grid;place-items:center}
.tk-media:hover .tk-play{background:var(--pink)}
.tk-rail{display:flex;flex-direction:column;gap:14px;align-items:center;padding-bottom:6px}
.tk-act{display:flex;flex-direction:column;align-items:center;gap:4px;background:none;border:0;color:var(--ink);text-decoration:none;cursor:pointer;font-size:12px;font-weight:700;padding:0}
div.tk-act{cursor:default}
.tk-ic{width:48px;height:48px;border-radius:50%;background:var(--s2);display:grid;place-items:center;transition:transform .15s}
a.tk-act:hover .tk-ic,button.tk-act:hover .tk-ic{background:var(--s3)}
button.tk-act:active .tk-ic{transform:scale(.88)}
.tk-save[aria-pressed="true"] .tk-ic{background:var(--pink)}
.tk-save[aria-pressed="true"] svg{fill:currentColor}
.tk-adapt .tk-ic{background:var(--ink);color:var(--bg)}
.tk-adapt:hover .tk-ic{opacity:.85}
.tk-burst{position:absolute;left:50%;top:45%;width:120px;height:120px;margin:-60px;color:var(--pink);pointer-events:none;z-index:3;animation:pop .9s ease-out forwards}
@keyframes pop{0%{transform:scale(.3) rotate(-12deg);opacity:0}15%{transform:scale(1.2) rotate(6deg);opacity:1}30%{transform:scale(1) rotate(0)}100%{transform:translateY(-70px);opacity:0}}
.tk-nav{position:fixed;right:28px;top:50%;transform:translateY(-50%);display:flex;flex-direction:column;gap:10px;align-items:center;color:var(--muted);font-size:12px;font-weight:600;z-index:5}
.tk-nav button{width:46px;height:46px;border-radius:50%;border:0;background:var(--s2);color:var(--ink);cursor:pointer;display:grid;place-items:center}
.tk-nav button:hover{background:var(--s3)}
body:not(.feed-mode) .tk-nav{display:none}
.tk-empty{height:100%;display:grid;place-items:center;align-content:center;gap:6px;color:var(--muted);text-align:center;padding:24px}
.tk-empty b{color:var(--ink);font-size:18px}
.tk-note{text-align:center;color:var(--muted);font-size:11px;margin:0;padding:0 16px 8px}

/* Progreso al actualizar */
.add-btn{display:inline-flex;align-items:center;gap:6px;background:var(--s2);color:var(--ink);border:0;border-radius:8px;padding:8px 12px;font-weight:700;font-size:13px;cursor:pointer}
.add-btn:hover{background:var(--s3)}
.form{display:grid;gap:12px}
.form label{display:grid;gap:5px;font-size:13px;font-weight:600}
.form input,.form select,.form textarea{width:100%;background:var(--s2);color:var(--ink);border:1px solid transparent;border-radius:8px;padding:9px 11px;font:inherit;font-size:14px;font-weight:400}
.form input:focus,.form select:focus,.form textarea:focus{outline:none;border-color:var(--blue)}
.form textarea{min-height:96px;resize:vertical}
.form .row2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px}
.form .row4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.form small{color:var(--muted);font-weight:400}
.form .check{display:flex;gap:8px;align-items:flex-start;font-weight:500}
.form .check input{width:auto;margin-top:3px}
.form-actions{display:flex;gap:8px;justify-content:flex-end;align-items:center}
.form-msg{font-size:13px;margin-right:auto}
.form-msg.err{color:var(--pink)}.form-msg.ok{color:var(--up)}
.form fieldset{border:0;padding:0;margin:0;display:flex;gap:14px;flex-wrap:wrap;font-size:13px}
.form legend{font-size:13px;font-weight:600;margin-bottom:5px}
.form hr{border:0;border-top:1px solid var(--line);margin:6px 0}
.acct{background:var(--s1);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:14px}
.acct h4{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.acct .pill{display:inline-block;background:var(--s2);border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700;margin:0 6px 8px 0}
.acct ol{margin:6px 0 10px;padding-left:20px;font-size:14px;line-height:1.45}
.acct .cap{font-size:14px;line-height:1.45;margin:0 0 8px}
.acct .cta{font-size:14px;font-weight:700}
.perf{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.perf>div{border:1px solid var(--line);border-radius:12px;padding:12px 14px;background:var(--s1)}
.perf h3{margin:0 0 8px;font-size:13px;color:var(--muted);font-weight:700}
.perf li{display:flex;justify-content:space-between;gap:10px;font-size:14px;padding:3px 0}
.perf ul{list-style:none;margin:0;padding:0}
.perf a{color:inherit;text-decoration:none}.perf a:hover{text-decoration:underline}
.ghost{background:none;border:0;color:var(--muted);font-weight:600;cursor:pointer;padding:8px 10px}
.run-card.wide{width:min(560px,100%);max-height:calc(100dvh - 32px);overflow:auto}
.proof{margin-top:34px;border:1px solid var(--line);border-radius:14px;padding:18px 18px 14px}
.proof h2{margin:0 0 2px;font-size:18px;font-weight:800}
.proof>p{margin:0 0 14px;color:var(--muted);font-size:14px}
.proof-k{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.proof-k div{background:var(--s2);border-radius:10px;padding:12px}
.proof-k b{display:block;font-size:26px;font-weight:800;letter-spacing:-.02em}
.proof-k span{font-size:12.5px;color:var(--muted);line-height:1.35;display:block}
.proof-bars{display:grid;grid-template-columns:150px minmax(0,1fr) 48px;gap:8px 10px;align-items:center;margin:14px 0 6px;font-size:13px}
.proof-bars i{display:block;height:10px;border-radius:5px;background:var(--s2);overflow:hidden}
.proof-bars i em{display:block;height:100%;background:var(--ig)}
.proof-bars i em.plain{background:var(--muted)}
.proof .cap{font-size:12.5px;color:var(--muted);margin:8px 0 0}
@media (max-width:600px){.proof-k{grid-template-columns:1fr}.proof-bars{grid-template-columns:110px minmax(0,1fr) 40px}.form .row4{grid-template-columns:repeat(2,minmax(0,1fr))}.add-btn .run-label{display:none}}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);display:grid;place-items:center;z-index:50;padding:16px}
.run-card{background:var(--s1);border-radius:16px;padding:24px;width:min(440px,100%)}
.run-card h3{margin:0 0 4px;font-size:20px;font-weight:800}
.run-card p{margin:0 0 16px;color:var(--muted);font-size:14px}
.steps{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.steps li{display:flex;gap:10px;align-items:center;color:var(--muted);font-size:14px}
.steps li i{width:22px;height:22px;border-radius:50%;border:2px solid var(--s3);display:grid;place-items:center;font-style:normal;font-size:12px;flex:none}
.steps li.done{color:var(--ink)}.steps li.done i{background:var(--cyan);border-color:var(--cyan);color:#000;font-weight:800}
.steps li.on{color:var(--ink);font-weight:600}.steps li.on i{border-color:var(--pink);border-top-color:transparent;animation:spin .8s linear infinite}
.run-err{margin-top:14px;color:var(--pink);font-size:14px}
.run-err button{margin-top:10px;background:var(--s2);border:0;border-radius:8px;padding:6px 12px;cursor:pointer}
@keyframes spin{to{transform:rotate(360deg)}}


.cv.w2{grid-column:span 2;aspect-ratio:2/1}
.cv.w3{grid-column:span 3;aspect-ratio:3/1}
.cv.w2 .cv-in{padding:3.5cqi}.cv.w3 .cv-in{padding:2.4cqi}
.cv.w2 .cv-name{font-size:max(16px,5.5cqi)}.cv.w3 .cv-name{font-size:max(16px,3.8cqi)}
.cv.w2 .cv-rank{font-size:max(13px,4.5cqi)}.cv.w3 .cv-rank{font-size:max(13px,3cqi)}
.cv.w2 .cv-g,.cv.w3 .cv-g{font-size:max(11px,2.4cqi)}
.cv.w2 .cv-meta,.cv.w3 .cv-meta{font-size:max(11px,2cqi)}

@media (max-width:735px){
  .bar-in{padding:8px 12px}
  .run-label,.mode span,.brand-name{display:none}
  .hist{max-width:112px}
  .run-btn{padding:9px 11px}
  .stories{gap:12px;padding-top:14px}
  .story{width:66px}.ring{width:64px;height:64px}
  .grid{gap:3px}
  .cv{border-radius:2px}
  .cv-name{font-size:max(12px,11cqi)}
  .cv-meta{display:none}
  .cv.big .cv-meta,.cv.w2 .cv-meta,.cv.w3 .cv-meta{display:-webkit-box}
  .sheet{padding:0;align-items:end}
  .panel{grid-template-columns:1fr;grid-template-rows:auto minmax(0,1fr);width:100%;height:94dvh;border-radius:14px 14px 0 0;animation:slide-u .22s ease-out}
  .p-cover{min-height:200px;padding:20px}
  .p-side{border-left:0}
  .stats{grid-template-columns:repeat(4,minmax(0,1fr))}
  .sv{padding:0}.sv-stage{height:100%;width:100%}.sv-card{height:100%;border-radius:0;aspect-ratio:auto;width:100%}.sv-arrow{position:absolute;top:30%;transform:translateY(-50%);z-index:4;width:30px;height:30px;background:rgba(255,255,255,.7)}.sv-arrow.prev{left:max(8px,env(safe-area-inset-left,0px))}.sv-arrow.next{right:max(8px,env(safe-area-inset-right,0px))}
  .tk-item{padding:0 8px 8px}
  .tk-stage{position:relative;width:100%}
  .tk-card{width:100%;max-width:none;aspect-ratio:auto;border-radius:14px;padding:14px}
  .tk-meta,.tk-body{padding-right:58px}
  .tk-rail{position:absolute;right:8px;bottom:16px;z-index:3;gap:10px}
  .tk-act{color:#fff}
  .tk-ic{width:42px;height:42px;background:rgba(0,0,0,.35)}
  .tk-adapt .tk-ic{background:#fff;color:#000}
  .tk-nav{display:none}
  .tk-media{margin:0 -14px}
}
@media (prefers-reduced-motion:reduce){.tk-burst,.panel{animation:none}.steps li.on i{animation:none}.cv img{transition:none}}
</style></head>
<body>
<header class="bar"><div class="bar-in">
  <div class="brand"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">CreativIA</span></div>
  <div class="seg" role="group" aria-label="Vista"><button data-view="radar" aria-pressed="true">Tendencias</button><button data-view="feed" aria-pressed="false">Feed</button></div>
  <div class="actions"><select class="hist" id="hist" aria-label="Reportes anteriores" hidden></select>
    <button class="add-btn" id="add" aria-label="Aportar una publicación" hidden><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg><span class="run-label">Aportar</span></button>
    <button class="add-btn" id="acct-btn" aria-label="Cuenta para la que se produce" hidden><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg><span class="run-label" id="acct-label">Cuenta</span></button>
    <button class="run-btn" id="run" aria-label="Actualizar radar" hidden><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg><span class="run-label">Actualizar</span></button>
    <span class="mode" id="mode"><i></i><span></span></span></div>
</div></header>

<main>
<div class="empty" id="empty" hidden><h2>Todavía no hay radar</h2><p>Recolecta el contenido público de esta semana para ver qué temas de IA están creciendo.</p>
  <button class="run-btn" data-run>Correr el radar</button></div>

<div class="view" id="view-radar"><div class="wrap">
  <div class="stories" id="stories" aria-label="Historias de los temas"></div>
  <div class="net" id="net-row" role="group" aria-label="Tendencias por app"><span>Tendencias en</span><div class="chips" id="net"></div></div>
  <div class="head"><div><h1>Tendencias de la semana</h1><p id="sub"></p></div><div class="chips" id="filters"></div></div>
  <div class="grid" id="grid"></div>
  <section class="sect" id="acct-sect" hidden></section>
  <section class="sect"><h2>Palabras que están sonando</h2><p>Se dispararon esta semana y todavía no tienen tema propio.</p><div class="tags" id="terms"></div></section>
  <section class="proof" id="proof" hidden></section>
  <details class="fold" id="map-fold"><summary>Mapa de oportunidades</summary><div class="map"><svg id="map" viewBox="0 0 640 380" role="img" aria-label="Crecimiento frente a utilidad para la audiencia"></svg></div>
    <p class="cap">Más a la derecha, más crece. Más arriba, más útil para la audiencia. El tamaño es cuánto se habla del tema.</p></details>
  <details class="fold"><summary>Cómo se calcula</summary><ul id="method"></ul></details>
  <footer id="foot"></footer>
</div></div>

<div class="view" id="view-feed" hidden>
  <div class="tk-top">
    <div class="tabs-top" role="tablist" aria-label="Orden del feed">
      <button class="ttab tk-tab" role="tab" data-sort="lift" aria-selected="true">Para ti</button>
      <button class="ttab tk-tab" role="tab" data-sort="fit" aria-selected="false">Útiles</button>
      <button class="ttab tk-tab" role="tab" data-sort="new" aria-selected="false">Recientes</button>
      <button class="ttab tk-tab" role="tab" data-sort="saved" aria-selected="false">Guardados</button>
    </div>
    <div class="chips"><div class="chips" id="tk-plat"></div><select class="sel" id="tk-topic" aria-label="Filtrar por tema"></select></div>
  </div>
  <div class="tk" id="tk" tabindex="-1" aria-label="Publicaciones destacadas"></div>
  <p class="tk-note">Solo contenido público, sin nombres de autores. Google News no trae interacción y no aparece aquí.</p>
  <div class="tk-nav"><button id="tk-up" aria-label="Anterior"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 15l-6-6-6 6"/></svg></button>
    <span id="tk-count" class="num"></span>
    <button id="tk-down" aria-label="Siguiente"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg></button></div>
</div>
</main>

<div class="sv" id="sv" hidden role="dialog" aria-modal="true" aria-label="Historias"></div>
<div class="sheet" id="sheet" hidden><div class="sheet-bg" data-close></div><div class="panel" id="detail" role="dialog" aria-modal="true" aria-label="Detalle del tema"></div></div>

<div class="overlay" id="overlay" hidden><div class="run-card" role="dialog" aria-modal="true" aria-labelledby="run-t">
  <h3 id="run-t">Actualizando el radar</h3><p>Toma entre 20 segundos y unos minutos.</p>
  <ol class="steps" id="steps"></ol><div class="run-err" id="run-err" hidden></div></div></div>

<div class="overlay" id="contrib" hidden><div class="run-card wide" role="dialog" aria-modal="true" aria-labelledby="contrib-t">
  <h3 id="contrib-t">Aportar una publicación</h3>
  <p>¿Viste algo de IA funcionando en LinkedIn, Instagram o TikTok? Agrégalo y entra en la próxima actualización. Solo contenido público.</p>
  <form class="form" id="contrib-form" novalidate>
    <label>Enlace<input name="url" type="url" placeholder="https://www.linkedin.com/posts/…" required></label>
    <div class="row2"><label>Red<select name="platform">
        <option value="linkedin">LinkedIn</option><option value="instagram">Instagram</option><option value="tiktok">TikTok</option>
        <option value="youtube">YouTube</option><option value="x">X</option><option value="facebook">Facebook</option><option value="threads">Threads</option><option value="otra">Otra</option></select></label>
      <label>Fecha de publicación<input name="published_at" type="date" required></label></div>
    <label>Texto de la publicación<textarea name="text" placeholder="Pega aquí el texto o la descripción del video" required></textarea>
      <small>Se borran automáticamente menciones, correos y teléfonos.</small></label>
    <div class="row4"><label>Me gusta<input name="likes" type="number" min="0" inputmode="numeric"></label>
      <label>Comentarios<input name="comments" type="number" min="0" inputmode="numeric"></label>
      <label>Compartidos<input name="shares" type="number" min="0" inputmode="numeric"></label>
      <label>Vistas<input name="views" type="number" min="0" inputmode="numeric"></label></div>
    <label>Publicado por <small>(solo si es una marca o un medio; nunca nombres de personas)</small><input name="publisher" maxlength="80"></label>
    <label class="check"><input type="checkbox" name="public"> Es una publicación pública, la vi sin iniciar sesión en una cuenta ajena y no tiene datos personales.</label>
    <div class="form-actions"><span class="form-msg" id="contrib-msg" role="status"></span>
      <button type="button" class="ghost" id="contrib-close">Cerrar</button><button class="run-btn" type="submit">Guardar aporte</button></div>
  </form></div></div>

<div class="overlay" id="acct" hidden><div class="run-card wide" role="dialog" aria-modal="true" aria-labelledby="acct-t">
  <h3 id="acct-t">Cuenta para la que producimos</h3>
  <p>Con esta ficha, cada tendencia trae una pieza lista para la cuenta: pilar, formato, estructura, caption y llamado a la acción.</p>
  <form class="form" id="acct-form" novalidate>
    <div class="row2"><label>Cuenta de Instagram<input name="handle" placeholder="@crece30x" required></label>
      <label>Llamado a la acción habitual<input name="cta" maxlength="200" placeholder="Guarda este post…"></label></div>
    <label>De qué habla la cuenta<textarea name="descripcion" maxlength="600"></textarea></label>
    <label>A quién le habla<input name="audiencia" maxlength="400"></label>
    <label>Tono<input name="tono" maxlength="300" placeholder="Directo, práctico, cercano…"></label>
    <label>Pilares de contenido <small>(uno por línea)</small><textarea name="pilares" style="min-height:72px"></textarea></label>
    <fieldset><legend>Formatos que usa</legend>
      <label class="check"><input type="checkbox" name="formatos" value="reel"> Reel</label>
      <label class="check"><input type="checkbox" name="formatos" value="carrusel"> Carrusel</label>
      <label class="check"><input type="checkbox" name="formatos" value="imagen"> Imagen</label>
      <label class="check"><input type="checkbox" name="formatos" value="historia"> Historia</label></fieldset>
    <label>Qué evitar<input name="evitar" maxlength="300"></label>
    <label>Mejores posts <small>(enlaces públicos de instagram.com, uno por línea)</small><textarea name="mejores_posts" style="min-height:72px"></textarea></label>
    <div class="form-actions"><span class="form-msg" id="acct-msg" role="status"></span><button class="run-btn" type="submit">Guardar ficha</button></div>
    <hr>
    <label>Exportación de Meta Business Suite <small>(Estadísticas → Contenido → Exportar datos, en CSV). Solo se guarda lo público de cada post: texto, fecha, enlace, tipo, me gusta, comentarios y vistas.</small>
      <input type="file" name="csv" accept=".csv,text/csv"></label>
    <div class="form-actions"><span class="form-msg" id="acct-csv-msg" role="status"></span>
      <button type="button" class="ghost" id="acct-close">Cerrar</button></div>
  </form></div></div>

<script type="application/json" id="data">__DATA__</script>
<script>
(() => {
const D = JSON.parse(document.getElementById("data").textContent);
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pct = x => `${Math.round(x * 100)}%`;
const growth = g => { const v = Math.round((g - 1) * 100); return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v)}%`; };
const gClass = g => growth(g) === "0%" ? "flat" : g >= 1 ? "up" : "down";
const fmtDay = d => new Date(d + "T12:00:00").toLocaleDateString("es", {day: "numeric", month: "short"});
const stageVar = s => `var(--${s})`;
const root = document.documentElement;
const PCOLOR = {"Bluesky": "#1185fe", "Hacker News": "#ff6600", "YouTube": "#ff0033", "Google News": "#4285f4", "LinkedIn": "#0a66c2", "Instagram": "#d62976", "TikTok": "#25f4ee"};
const NAMES = {linkedin: "LinkedIn", instagram: "Instagram", tiktok: "TikTok", youtube: "YouTube"};
const GRADS = [["#ff5f6d", "#c2185b"], ["#4facfe", "#3a47d5"], ["#f7971e", "#e1306c"], ["#11998e", "#0b6e8a"], ["#b06ab3", "#4568dc"],
               ["#fbb034", "#f05a28"], ["#00c6ff", "#6a3de8"], ["#ee0979", "#7b2ff7"], ["#43cea2", "#185a9d"], ["#8e2de2", "#3b1c8c"]];
// El mismo tema tiene el mismo color en Tendencias y en el Feed.
const gradFor = id => { let h = 0; for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0; return GRADS[h % GRADS.length]; };
const gradStyle = id => { const [g1, g2] = gradFor(id); return `--g1:${g1};--g2:${g2}`; };
const hashtag = s => "#" + s.normalize("NFC").replace(/[^\p{L}\p{N} ]/gu, "").split(/\s+/).filter(Boolean).map(w => w[0].toUpperCase() + w.slice(1)).join("");
const ytId = url => (url.match(/[?&]v=([\w-]{11})/) || url.match(/youtu\.be\/([\w-]{11})/) || [])[1];
const svgI = (d, size = 24) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const ICONS = {
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z"/>',
  comment: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  share: '<path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  save: '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
  bulb: '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2V17h6v-.3c0-.8.4-1.5 1-2A7 7 0 0 0 12 2z"/>',
  open: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14L21 3"/>',
  fire: '<path d="M12 2s5 4.5 5 10a5 5 0 0 1-10 0c0-2 1-3.5 1-3.5S9 11 11 11c0-4 1-9 1-9z" fill="currentColor" stroke="none"/>',
  play: '<path d="M8 5v14l11-7z" fill="currentColor" stroke="none"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>',
};
const num = n => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1000)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);

// App web: actualizar el radar e historial (solo cuando lo sirve `python -m radar.web`)
const APP = window.RADAR_APP;
const STEP_NAMES = ["Recolectar contenido público", "Clasificar publicaciones", "Detectar tendencias", "Escribir ideas de adaptación"];
function showRun(st) {
  $("#overlay").hidden = false;
  $("#steps").innerHTML = STEP_NAMES.map((n, i) => {
    const k = i + 1, cls = st.step > k || st.state === "done" ? "done" : st.step === k ? "on" : "";
    return `<li class="${cls}"><i>${cls === "done" ? "✓" : ""}</i>${esc(st.step === k && st.message ? st.message : n)}</li>`;
  }).join("");
  const err = $("#run-err");
  err.hidden = st.state !== "error";
  if (st.state === "error") err.innerHTML = `${esc(st.error)}<br><button id="run-close">Cerrar</button>`;
}
async function poll() {
  const st = await fetch("/api/status").then(r => r.json());
  if (st.state === "running") { showRun(st); setTimeout(poll, 1000); }
  else if (st.state === "done") { showRun(st); location.href = "/"; }
  else if (st.state === "error") showRun(st);
}
async function startRun() {
  showRun({step: 1, state: "running"});
  const r = await fetch("/api/run", {method: "POST"});
  if (!r.ok && r.status !== 409) { showRun({state: "error", error: (await r.json()).error}); return; }
  poll();
}
document.addEventListener("click", e => {
  if (e.target.closest("#run,[data-run]")) startRun();
  if (e.target.closest("#run-close")) $("#overlay").hidden = true;
});
// Aportes de la comunidad: LinkedIn, Instagram y TikTok entran por aquí, sin login ni scraping.
const PLAT_BY_HOST = [["linkedin.", "linkedin"], ["instagram.", "instagram"], ["tiktok.", "tiktok"], ["youtube.", "youtube"], ["youtu.be", "youtube"],
                      ["x.com", "x"], ["twitter.", "x"], ["facebook.", "facebook"], ["threads.", "threads"]];
const contribForm = $("#contrib-form");
function openContrib() {
  $("#contrib").hidden = false;
  contribForm.published_at.value ||= new Date().toISOString().slice(0, 10);
  $("#contrib-msg").textContent = "";
  contribForm.url.focus();
}
contribForm.url.addEventListener("input", () => {
  const hit = PLAT_BY_HOST.find(([h]) => contribForm.url.value.toLowerCase().includes(h));
  if (hit) contribForm.platform.value = hit[1];
});
contribForm.addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(contribForm));
  body.public = contribForm.public.checked;
  const msg = $("#contrib-msg");
  msg.className = "form-msg"; msg.textContent = "Guardando…";
  try {
    const r = await fetch("/api/community", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    const keep = {platform: body.platform, published_at: body.published_at};
    contribForm.reset(); contribForm.platform.value = keep.platform; contribForm.published_at.value = keep.published_at;
    msg.className = "form-msg ok"; msg.textContent = `¡Gracias! Van ${j.count} aportes. Entra en la próxima actualización.`;
  } catch (err) { msg.className = "form-msg err"; msg.textContent = err.message || "No se pudo guardar"; }
});
document.addEventListener("click", e => {
  if (e.target.closest("#add")) openContrib();
  if (e.target.closest("#contrib-close") || e.target.id === "contrib") $("#contrib").hidden = true;
});
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#contrib").hidden) $("#contrib").hidden = true; });

// Ficha de la cuenta y exportación de Meta. Entran en la próxima actualización del radar.
const acctForm = $("#acct-form");
const metricsTxt = m => m.count ? `${m.count} publicaciones importadas (${m.from} a ${m.to}).` : "Todavía no hay exportación.";
async function openAcct() {
  $("#acct").hidden = false; $("#acct-msg").textContent = "";
  try {
    const j = await (await fetch("/api/account")).json(), pf = j.profile;
    for (const k of ["handle", "cta", "descripcion", "audiencia", "tono", "evitar"]) acctForm[k].value = pf[k] || "";
    acctForm.pilares.value = (pf.pilares || []).join("\n");
    acctForm.mejores_posts.value = (pf.mejores_posts || []).join("\n");
    $$('input[name="formatos"]', acctForm).forEach(c => c.checked = (pf.formatos || []).includes(c.value));
    $("#acct-csv-msg").className = "form-msg"; $("#acct-csv-msg").textContent = metricsTxt(j.metrics);
  } catch (err) {}
  acctForm.handle.focus();
}
acctForm.addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(acctForm));
  delete body.csv;
  body.formatos = $$('input[name="formatos"]:checked', acctForm).map(c => c.value);
  const msg = $("#acct-msg");
  msg.className = "form-msg"; msg.textContent = "Guardando…";
  try {
    const r = await fetch("/api/account", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    $("#acct-label").textContent = j.profile.handle;
    msg.className = "form-msg ok"; msg.textContent = "Guardada. Se aplica en la próxima actualización.";
  } catch (err) { msg.className = "form-msg err"; msg.textContent = err.message || "No se pudo guardar"; }
});
acctForm.csv.addEventListener("change", async () => {
  const file = acctForm.csv.files[0], msg = $("#acct-csv-msg");
  if (!file) return;
  msg.className = "form-msg"; msg.textContent = "Importando…";
  try {
    const r = await fetch("/api/account/metrics", {method: "POST", headers: {"Content-Type": "text/csv"}, body: await file.text()});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    msg.className = "form-msg ok"; msg.textContent = metricsTxt(j.metrics) + " Se aplica en la próxima actualización.";
  } catch (err) { msg.className = "form-msg err"; msg.textContent = err.message || "No se pudo importar"; }
  acctForm.csv.value = "";
});
document.addEventListener("click", e => {
  if (e.target.closest("#acct-btn")) openAcct();
  if (e.target.closest("#acct-close") || e.target.id === "acct") $("#acct").hidden = true;
});
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#acct").hidden) $("#acct").hidden = true; });

if (APP) {
  $("#run").hidden = false;
  $("#add").hidden = false;
  $("#acct-btn").hidden = false;
  if (APP.reports.length) {
    const h = $("#hist"); h.hidden = false;
    h.innerHTML = APP.reports.map(r => `<option value="${esc(r)}" ${r === APP.current ? "selected" : ""}>${esc(fmtDay(r.replace("radar-", "")))}</option>`).join("");
    h.onchange = () => { location.href = "/?r=" + encodeURIComponent(h.value); };
  }
  fetch("/api/status").then(r => r.json()).then(st => { if (st.state === "running") poll(); });
}
if (!D) {
  $$(".view,.seg,#mode").forEach(el => el.remove());
  $("#empty").hidden = false;
  if (!APP) $("[data-run]").replaceWith(Object.assign(document.createElement("code"), {textContent: "python -m radar.web"}));
  return;
}

const C = D.counts, mode = D.meta.classifier;
const FEED = D.feed || [];
$("#mode").classList.add(mode);
$("#mode span").textContent = {jev: "Jev", local: "Modo local", heuristico: "Modo básico"}[mode] || mode;
$("#mode").title = mode === "jev" ? "Clasificado con Jev" : D.meta.jev_error ? `Jev no respondió (${D.meta.jev_error}); se usó el respaldo` : "Sin clave de Jev: resultados aproximados";
// Pestañas por app: "General" usa el cálculo de siempre; cada app tiene su propio ranking y
// crecimiento, calculados con noticias y artículos sobre IA en esa app (analysis.by_app).
const BYP = D.by_app || {};
const NETS = ["LinkedIn", "Instagram", "TikTok", "YouTube"].filter(k => BYP[k]);
const FMT_KEY = {LinkedIn: "linkedin", Instagram: "instagram", TikTok: "tiktok", YouTube: "youtube"};
const SRC_TXT = {"Google News": ["noticia", "noticias"], YouTube: ["video", "videos"]};
let net = "todas";
try { const v = localStorage.getItem("radar-net"); if (NETS.includes(v)) net = v; } catch (e) {}
let T = D.topics, MOM = true;
const fmtFor = t => (t.adaptation?.formatos || {})[FMT_KEY[net]] || "";
const G = t => MOM ? growth(t.growth) : "—";

function renderSub() {
  const warn = txt => ` · <b>●</b> ${txt}`;
  if (net === "todas") {
    $("#sub").innerHTML = `${fmtDay(D.window.split)} – ${fmtDay(D.window.end)} · ${C.ai.toLocaleString("es")} publicaciones · ${Object.keys(C.by_platform).length} fuentes` +
      (mode === "jev" ? "" : warn("sin Jev, números aproximados"));
    return;
  }
  const v = BYP[net];
  const parts = Object.entries(v.sources || {}).map(([k, c]) => `${c} ${(SRC_TXT[k] || ["aporte de la comunidad", "aportes de la comunidad"])[c === 1 ? 0 : 1]}`);
  $("#sub").innerHTML = `${fmtDay(D.window.split)} – ${fmtDay(D.window.end)} · Noticias y artículos sobre IA en ${esc(net)} · ${parts.join(" · ")}` +
    (v.n < 20 ? warn("pocos datos, tómalo como pista") : "") +
    (MOM ? "" : warn("sin semanas comparables: el orden es por utilidad e interacción, no por crecimiento"));
}

// Portada de cada tema: la miniatura de un video del tema si existe; si no, un bloque de color.
const thumbFor = t => {
  const yt = [...t.examples, ...FEED.filter(p => p.topic === t.id)].map(p => p.platform === "YouTube" && ytId(p.url)).find(Boolean);
  return yt ? `https://i.ytimg.com/vi/${yt}/hqdefault.jpg` : null;
};
const THUMB = {};
[D.topics, ...Object.values(BYP).map(v => v.topics)].flat().forEach(t => { THUMB[t.id] ??= thumbFor(t); });
const STOP = new Set(["ia", "y", "e", "de", "del", "la", "el", "en", "con", "para", "frente", "a", "los", "las"]);
const shortName = label => { const w = label.split(/\s+/).find(x => !STOP.has(x.toLowerCase())) || label; return w[0].toUpperCase() + w.slice(1); };

// Historias
function renderStories() {
  $("#stories").innerHTML = T.map((t, i) => `
  <button class="story ${MOM && t.growth < 1 && !["naciente", "en_crecimiento"].includes(t.stage) ? "cold" : ""}" data-i="${i}" aria-label="${esc(`Historia ${t.rank}: ${t.label}`)}">
    <span class="ring"><span class="ring-in" style="${gradStyle(t.id)}${THUMB[t.id] ? `;background-image:url('${THUMB[t.id]}')` : ""}">${THUMB[t.id] ? "" : t.rank}</span></span>
    <span class="lbl">${esc(shortName(t.label))}</span></button>`).join("");
}
$("#stories").addEventListener("click", e => { const s = e.target.closest(".story"); if (s) openStories(+s.dataset.i); });

// Cuadrícula de portadas. El #1 ocupa 2×2 y la última fila se completa con una portada ancha.
let stageFilter = "todos";
function cover(t, cls) {
  const img = THUMB[t.id];
  const pill = MOM ? `${t.growth >= 1 ? "▲" : "▼"} ${growth(t.growth).replace(/^[+−]/, "")}` : `${t.n_posts} pub.`;
  const meta = fmtFor(t) ? `${esc(net)}: ${esc(fmtFor(t))}` : MOM ? `${t.n_posts} publicaciones · ${esc(D.stages[t.stage])}` : `útil para ${pct(t.fit)} de la audiencia`;
  return `<button class="cv ${cls} ${img ? "photo" : ""}" data-id="${esc(t.id)}" style="${gradStyle(t.id)}" aria-label="${esc(`${t.rank}. ${t.label}, ${G(t)}`)}">
    ${img ? `<img src="${img}" alt="" loading="lazy">` : ""}
    <span class="cv-in"><span class="cv-top"><span class="cv-rank">${t.rank}</span><span class="cv-g num ${MOM ? gClass(t.growth) : "flat"}">${pill}</span></span>
      <span><span class="cv-name">${esc(t.label)}</span><span class="cv-meta">${meta}</span></span></span></button>`;
}
function renderGrid() {
  const ts = T.filter(t => stageFilter === "todos" || t.stage === stageFilter);
  const big = ts.length >= 3, rest = ts.length - (big ? 3 : 0), tail = rest % 3;
  $("#grid").innerHTML = ts.map((t, i) => {
    const last = i === ts.length - 1 && (!big || i >= 3);
    return cover(t, i === 0 && big ? "big" : last && tail === 1 ? "w3" : last && tail === 2 ? "w2" : "");
  }).join("") || '<p class="note">Sin publicaciones de esta red en la semana.</p>';
}
$("#grid").addEventListener("click", e => { const c = e.target.closest(".cv"); if (c) openTopic(c.dataset.id); });
function renderFilters() {
  stageFilter = "todos";
  const used = [...new Set(T.map(t => t.stage))];
  $("#filters").hidden = !MOM;
  $("#filters").innerHTML = [["todos", "Todos"], ...used.map(s => [s, D.stages[s]])].map(([k, v], i) => `<button class="chip" data-f="${k}" aria-pressed="${i === 0}">${esc(v)}</button>`).join("");
}
$("#filters").addEventListener("click", e => {
  const b = e.target.closest(".chip"); if (!b) return;
  stageFilter = b.dataset.f; $$("#filters .chip").forEach(x => x.setAttribute("aria-pressed", x === b)); renderGrid();
});

// Mapa: crecimiento (x) vs. utilidad para la audiencia (y)
function renderMap() {
  $("#map-fold").hidden = !MOM || !T.length;
  if (!MOM || !T.length) return;
  const W = 640, H = 380, PAD = {l: 36, r: 16, t: 20, b: 34};
  const xMax = Math.max(0.2, ...T.map(t => Math.abs(t.growth - 1))) * 1.15;
  const fy = T.map(t => t.fit);
  const yMin = Math.max(0, Math.min(...fy) - 0.12), yMax = Math.min(1, Math.max(...fy) + 0.1);
  const sx = v => PAD.l + (v + xMax) / (2 * xMax) * (W - PAD.l - PAD.r);
  const sy = v => PAD.t + (1 - (v - yMin) / ((yMax - yMin) || 1)) * (H - PAD.t - PAD.b);
  const maxShare = Math.max(...T.map(t => t.share)) || 1;
  const yMid = (yMin + yMax) / 2;
  let svg = `<line class="grid-l" x1="${sx(0)}" x2="${sx(0)}" y1="${PAD.t}" y2="${H - PAD.b}"/>` +
    `<line class="grid-l" x1="${PAD.l}" x2="${W - PAD.r}" y1="${sy(yMid)}" y2="${sy(yMid)}"/>` +
    `<line class="axis" x1="${PAD.l}" x2="${W - PAD.r}" y1="${H - PAD.b}" y2="${H - PAD.b}"/>` +
    `<text class="hot" x="${W - PAD.r - 4}" y="${PAD.t + 4}" text-anchor="end">Oportunidad ↗</text>` +
    `<text x="${sx(0)}" y="${H - PAD.b + 18}" text-anchor="middle">0%</text>` +
    `<text x="${PAD.l}" y="${H - PAD.b + 18}">${growth(1 - xMax)}</text>` +
    `<text x="${W - PAD.r}" y="${H - PAD.b + 18}" text-anchor="end">${growth(1 + xMax)}</text>` +
    `<text x="10" y="${(PAD.t + H - PAD.b) / 2}" transform="rotate(-90 10 ${(PAD.t + H - PAD.b) / 2})" text-anchor="middle">más útil →</text>`;
  [...T].sort((a, b) => b.share - a.share).forEach(t => {
    const r = 13 + 20 * Math.sqrt(t.share / maxShare);
    svg += `<g class="bubble" data-id="${esc(t.id)}" tabindex="0" role="button" aria-label="${esc(t.rank + ". " + t.label)}">` +
      `<title>${esc(`${t.label} · ${growth(t.growth)} · útil ${pct(t.fit)}`)}</title>` +
      `<circle cx="${sx(t.growth - 1)}" cy="${sy(t.fit)}" r="${r}" fill="${gradFor(t.id)[0]}"/>` +
      `<text x="${sx(t.growth - 1)}" y="${sy(t.fit)}">${t.rank}</text></g>`;
  });
  $("#map").innerHTML = svg;
}
$("#map").addEventListener("click", e => { const g = e.target.closest(".bubble"); if (g) openTopic(g.dataset.id); });
$("#map").addEventListener("keydown", e => { const g = e.target.closest(".bubble"); if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openTopic(g.dataset.id); } });

function setNet(n) {
  net = n;
  T = net === "todas" ? D.topics : BYP[net].topics;
  MOM = net === "todas" || BYP[net].momentum;
  $$("#net .chip").forEach(x => x.setAttribute("aria-pressed", x.dataset.n === net));
  renderSub(); renderStories(); renderFilters(); renderGrid(); renderMap();
}
$("#net-row").hidden = !NETS.length;
$("#net").innerHTML = [["todas", "General"], ...NETS.map(k => [k, k])].map(([k, v]) =>
  `<button class="chip" data-n="${esc(k)}" aria-pressed="false">${k === "todas" ? "" : `<i style="background:${PCOLOR[k] || "#999"}"></i>`}${esc(v)}</button>`).join("");
$("#net").addEventListener("click", e => {
  const b = e.target.closest(".chip"); if (!b) return;
  try { localStorage.setItem("radar-net", b.dataset.n); } catch (e) {}
  setNet(b.dataset.n);
});
setNet(net);

// Palabras que están sonando
$("#terms").innerHTML = D.terms.length ? D.terms.map(t => `<span class="tag" title="${t.count} publicaciones de ${t.authors} autores">${esc(t.term)}${t.new ? '<span class="new">NUEVO</span>' : `<small>▲ ${t.ratio}×</small>`}</span>`).join("")
  : '<span class="note">Nada con señal suficiente esta semana.</span>';

// La cuenta para la que se produce: qué le funciona (exportación de Meta) y sus pilares (ficha).
const ACC = D.account || null, HANDLE = ACC?.profile?.handle || "";
const TYPE_NAME = {reel: "Reel", carrusel: "Carrusel", imagen: "Imagen", historia: "Historia"};
if (HANDLE) $("#acct-label").textContent = HANDLE;
if (ACC) {
  const pf = ACC.performance, pillars = ACC.profile?.pilares || [];
  const list = (rows, name) => rows.length
    ? `<ul>${rows.slice(0, 4).map(r => `<li><span>${esc(name(r))}</span><b class="num">${r.lift}×</b></li>`).join("")}</ul>`
    : '<p class="note">Pocos posts para comparar.</p>';
  const link = p => p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.text.slice(0, 60))}…</a>` : `<span>${esc(p.text.slice(0, 60))}…</span>`;
  $("#acct-sect").hidden = false;
  $("#acct-sect").innerHTML = `<h2>Lo que le funciona a ${esc(HANDLE || "la cuenta")}</h2>` + (pf
    ? `<p>Interacción pública (me gusta y comentarios) de ${pf.n} posts propios, del ${fmtDay(pf.from)} al ${fmtDay(pf.to)}, frente a la mediana de la cuenta.${pillars.length ? ` Pilares: ${pillars.map(esc).join(" · ")}.` : ""}</p>
      <div class="perf"><div><h3>Formatos</h3>${list(pf.by_type, r => TYPE_NAME[r.value] || r.value)}</div>
        <div><h3>Temas</h3>${list(pf.by_topic, r => r.label)}</div>
        <div><h3>Ganchos</h3>${list(pf.by_hook, r => r.label)}</div>
        <div><h3>Sus mejores posts</h3><ul>${pf.top_posts.map(p => `<li>${link(p)}<b class="num">${p.lift}×</b></li>`).join("")}</ul></div></div>`
    : `<p>${pillars.length ? `Pilares: ${pillars.map(esc).join(" · ")}. ` : ""}Importa la exportación de Meta (botón ${esc(HANDLE || "Cuenta")}) para medir qué formatos, temas y ganchos le funcionan.</p>`);
}
function forAccount(t, a) {
  const pc = a.para_cuenta; if (!pc) return "";
  const tl = ACC?.performance?.by_topic.find(r => r.value === t.id);
  return `<div class="acct"><h4>Para ${esc(HANDLE || "la cuenta")}</h4>
    <span class="pill">${esc(pc.pilar)}</span><span class="pill">${esc(pc.formato)}</span>${tl ? `<span class="pill">En la cuenta rinde ${tl.lift}×</span>` : ""}
    <ol>${(pc.estructura || []).map(x => `<li>${esc(x)}</li>`).join("")}</ol>
    <p class="cap">${esc(pc.caption)}</p><p class="cta">${esc(pc.cta)}</p>
    <button class="copy" data-copy="${esc(`${pc.caption}\n\n${pc.cta}`)}">${svgI(ICONS.copy, 14)}Copiar caption</button></div>`;
}

// Visor de historias: un tema por historia, avanza solo; tocar a los lados para ir y volver.
let svIdx = 0;
function openStories(i) { $("#sv").hidden = false; document.body.style.overflow = "hidden"; showStory(i); }
function closeStories() { $("#sv").hidden = true; if ($("#sheet").hidden) document.body.style.overflow = document.body.classList.contains("feed-mode") ? "hidden" : ""; }
function showStory(i) {
  if (i < 0) i = 0;
  if (i >= T.length) return closeStories();
  svIdx = i;
  const t = T[i], a = t.adaptation || {}, img = THUMB[t.id];
  $$(".story")[i]?.classList.add("seen");
  $("#sv").innerHTML = `<div class="sv-stage">
    <button class="sv-arrow prev" data-sv="-1" aria-label="${i === 0 ? "Repetir historia" : "Historia anterior"}">${svgI('<path d="M15 18l-6-6 6-6"/>', 18)}</button>
    <div class="sv-card ${img ? "photo" : ""}" style="${gradStyle(t.id)}">
    ${img ? `<img src="${img}" alt="">` : ""}
    <div class="sv-bars">${T.map((_, k) => `<i class="${k < i ? "done" : k === i ? "on" : ""}"><b></b></i>`).join("")}</div>
    <div class="sv-head"><span class="brand-mark" aria-hidden="true"></span>CreativIA <span>${fmtDay(D.window.end)}</span>
      <button class="sv-x" data-sv-close aria-label="Cerrar historias">${svgI(ICONS.x, 22)}</button></div>
    <button class="sv-tap prev" data-sv="-1" aria-label="Anterior"></button><button class="sv-tap next" data-sv="1" aria-label="Siguiente"></button>
    <div class="sv-body">
      <div class="sv-kick">#${t.rank} de la semana · ${esc(D.stages[t.stage])}</div>
      <h2 class="sv-name">${esc(t.label)}</h2>
      <div class="sv-g num">${G(t)}<small>${t.n_posts} publicaciones · útil para ${pct(t.fit)} de la audiencia</small></div>
      ${a.ganchos?.length ? `<div class="sv-hook"><small>Idea de gancho</small>${esc(a.ganchos[0])}</div>` : ""}
      ${a.para_cuenta ? `<div class="sv-fmt">Para ${esc(HANDLE)}: ${esc(a.para_cuenta.formato)} · ${esc(a.para_cuenta.pilar)}</div>`
        : fmtFor(t) ? `<div class="sv-fmt">Formato para ${esc(net)}: ${esc(fmtFor(t))}</div>` : ""}
      <button class="sv-cta" data-sv-open="${esc(t.id)}">Ver ideas ${svgI('<path d="M9 18l6-6-6-6"/>', 16)}</button>
    </div></div>
    <button class="sv-arrow next" data-sv="1" aria-label="${i === T.length - 1 ? "Terminar historias" : "Historia siguiente"}">${svgI('<path d="M9 18l6-6-6-6"/>', 18)}</button></div>`;
  $(".sv-bars i.on b").addEventListener("animationend", () => showStory(svIdx + 1));
}
$("#sv").addEventListener("click", e => {
  if (e.target.closest("[data-sv-close]") || e.target === $("#sv") || e.target.classList.contains("sv-stage")) return closeStories();
  const step = e.target.closest("[data-sv]"); if (step) return showStory(svIdx + +step.dataset.sv);
  const o = e.target.closest("[data-sv-open]"); if (o) { closeStories(); openTopic(o.dataset.svOpen); }
});
$("#sv").addEventListener("pointerdown", e => { if (e.target.closest(".sv-tap")) $("#sv").classList.add("paused"); });
addEventListener("pointerup", () => $("#sv").classList.remove("paused"));
document.addEventListener("keydown", e => {
  if ($("#sv").hidden) return;
  if (e.key === "ArrowRight") showStory(svIdx + 1);
  if (e.key === "ArrowLeft") showStory(svIdx - 1);
  if (e.key === "Escape") closeStories();
});

// Detalle, como un post abierto
function chart(t) {
  const v = t.daily, n = v.length, hi = Math.max(...v) * 1.15 || 1, w = 600, h = 90;
  const x = i => i / Math.max(1, n - 1) * w, y = val => h - 4 - val / hi * (h - 8);
  const pts = v.map((val, i) => `${x(i).toFixed(1)},${y(val).toFixed(1)}`);
  const xs = x(D.split_index);
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <defs><linearGradient id="ga" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#d62976" stop-opacity=".3"/><stop offset="1" stop-color="#d62976" stop-opacity="0"/></linearGradient></defs>
    <rect class="cur" x="${xs}" y="0" width="${w - xs}" height="${h}"/>
    <path class="area" d="M0,${h} L${pts.join(" L")} L${w},${h} Z"/><polyline class="line" points="${pts.join(" ")}"/></svg>`;
}
let lastFocus = null;
function openTopic(id) {
  const t = [T, D.topics, ...Object.values(BYP).map(v => v.topics)].flat().find(x => x.id === id); if (!t) return;
  const a = t.adaptation || {}, img = THUMB[t.id];
  const sigs = t.signals.length ? `<div class="sigs">${t.signals.map(s =>
      `<div class="sig" title="${esc(s.hint)}"><span>${esc(s.kind)}: <b>${esc(s.value)}</b></span><span class="lift num">${s.lift}× más interacción${s.n < 5 ? ` · débil (${s.n} piezas)` : ""}</span></div>`).join("")}</div>`
    : `<p class="note">Pocas publicaciones con interacción medible para este tema.</p>`;
  $("#detail").setAttribute("style", gradStyle(t.id));
  $("#detail").innerHTML = `
    <div class="p-cover ${img ? "photo" : ""}">${img ? `<img src="${img}" alt="">` : ""}
      <div class="k">#${t.rank} de la semana</div><h2>${esc(t.label)}</h2>
      <div class="big-g num">${G(t)}</div></div>
    <div class="p-side">
      <div class="p-head"><span class="p-av"><i></i></span><div><b>${esc(hashtag(t.label))}</b><small><span class="stage" style="--c:${stageVar(t.stage)}">${esc(D.stages[t.stage])}</span> · ${t.n_posts} publicaciones</small></div>
        <button class="x" data-close aria-label="Cerrar">${svgI(ICONS.x, 20)}</button></div>
      <div class="p-body">
        <p class="p-desc">${esc(t.description)}</p>
        <div class="stats">
          <div class="stat"><b class="num g ${MOM ? gClass(t.growth) : "flat"}">${G(t)}</b><span>crecimiento</span></div>
          <div class="stat"><b class="num">${pct(t.share)}</b><span>de la conversación</span></div>
          <div class="stat"><b class="num">${pct(t.fit)}</b><span>útil para la audiencia</span></div>
          <div class="stat"><b class="num">${pct(t.practical)}</b><span>se puede aplicar</span></div>
        </div>
        <div class="chart">${chart(t)}<div class="chart-x"><span>${fmtDay(D.days[0])}</span><span>esta semana →</span><span>${fmtDay(D.days[D.days.length - 1])}</span></div></div>
        <div class="ptabs" role="tablist">
          <button class="ptab" role="tab" data-p="adapt" aria-selected="true">Ideas</button>
          <button class="ptab" role="tab" data-p="why" aria-selected="false">Por qué funciona</button>
          <button class="ptab" role="tab" data-p="refs" aria-selected="false">Ejemplos</button>
        </div>
        <div class="ppanel" data-p="adapt">
          ${forAccount(t, a)}
          <p class="lead">${esc(a.angulo)}</p>
          <h4>Ganchos</h4>
          <div class="hooks">${(a.ganchos || []).map(h => `<div class="hook"><p>${esc(h)}</p><button class="copy" data-copy="${esc(h)}">${svgI(ICONS.copy, 14)}Copiar</button></div>`).join("")}</div>
          <h4>${fmtFor(t) ? `Formato para ${esc(net)}` : "Formato por red"}</h4>
          <div class="fmts">${Object.entries(a.formatos || {}).sort((x, y) => (y[0] === FMT_KEY[net]) - (x[0] === FMT_KEY[net])).map(([k, v]) => { const name = NAMES[k] || k;
            const cls = !FMT_KEY[net] ? "" : k === FMT_KEY[net] ? "on" : "dim";
            return `<div class="fmt ${cls}"><i style="background:${PCOLOR[name] || "#999"}"></i><b>${esc(name)}</b><span>${esc(v)}</span></div>`; }).join("")}</div>
          ${a.cuidado ? `<div class="careful">${esc(a.cuidado)}</div>` : ""}
        </div>
        <div class="ppanel" data-p="why" hidden>
          <p class="lead">${esc(a.por_que_funciona)}</p>
          ${sigs}
          <p class="note">${net === "todas" ? "" : `Calculado solo con noticias y publicaciones sobre ${esc(net)}. `}${t.publishers.length ? `Publican sobre todo: ${esc(t.publishers.join(", "))}. ` : ""}${Math.round(t.lang_es * 100)}% en español. Son pistas sacadas de la muestra, no una regla.</p>
        </div>
        <div class="ppanel" data-p="refs" hidden>
          <ul class="refs">${t.examples.map(p => `<li><a href="${esc(p.url)}" target="_blank" rel="noopener"><div class="m"><i style="background:${PCOLOR[p.platform] || "#999"}"></i>${esc(p.platform)}${p.date ? ` · ${fmtDay(p.date)}` : ""}</div><p>${esc(p.text)}</p></a></li>`).join("") || '<li class="note">Sin ejemplos.</li>'}</ul>
          ${FEED.some(p => p.topic === t.id) ? `<button class="to-feed" data-feed-topic="${esc(t.id)}">Ver en el feed</button>` : ""}
        </div>
      </div>
    </div>`;
  lastFocus = document.activeElement;
  $("#sheet").hidden = false;
  document.body.style.overflow = "hidden";
  $("#detail .x").focus();
  try { history.replaceState(null, "", "#" + id); } catch (e) {}
}
function closeTopic() {
  if ($("#sheet").hidden) return;
  $("#sheet").hidden = true;
  document.body.style.overflow = "";
  try { history.replaceState(null, "", location.pathname + location.search + (document.body.classList.contains("feed-mode") ? "#feed" : "")); } catch (e) {}
  lastFocus?.focus?.({preventScroll: true});
}
$("#sheet").addEventListener("click", e => {
  if (e.target.closest("[data-close]")) return closeTopic();
  const tab = e.target.closest(".ptab");
  if (tab) {
    $$(".ptab").forEach(x => x.setAttribute("aria-selected", x === tab));
    $$(".ppanel").forEach(p => p.hidden = p.dataset.p !== tab.dataset.p);
  }
  const btn = e.target.closest(".copy");
  if (btn) {
    const label = btn.innerHTML;
    const done = () => { btn.textContent = "Copiado"; btn.classList.add("ok"); setTimeout(() => { btn.innerHTML = label; btn.classList.remove("ok"); }, 1400); };
    const text = btn.dataset.copy;
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => fallback(text, done)); else fallback(text, done);
  }
  const ft = e.target.closest("[data-feed-topic]");
  if (ft) { closeTopic(); tkTopic = ft.dataset.feedTopic; $("#tk-topic").value = tkTopic; setView("feed"); renderFeed(); }
});
document.addEventListener("keydown", e => { if (e.key === "Escape" && $("#sv").hidden) closeTopic(); });
function fallback(text, done) {
  const ta = Object.assign(document.createElement("textarea"), {value: text}); document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) {} ta.remove();
}

// Metodología
const W8 = Object.entries(D.weights).map(([k, v]) => `${k.replace("_", " ")} ${Math.round(v * 100)}%`).join(", ");
$("#method").innerHTML = [
  "Cada día se toman las publicaciones con más interacción por consulta y red, para comparar de qué se habla y no cuánto se publica.",
  `${mode === "jev" ? "Jev (TypeSafe)" : mode === "local" ? "Un clasificador local multilingüe" : "Un clasificador por palabras clave"} clasifica cada publicación: tema, gancho, formato, quién publica y qué tan útil es para ejecutivos y equipos de LatAm.`,
  "Las pestañas por app (LinkedIn, Instagram, TikTok, YouTube) repiten el cálculo con noticias y artículos sobre IA en esa app, buscados día por día en Google News, más los aportes de la comunidad y, en YouTube, los videos. Esas noticias no entran en la vista General.",
  `Un tema crece cuando su porcentaje de la conversación sube frente a las semanas anteriores (redes usadas: ${esc(C.momentum_platforms.join(", ") || "—")}).`,
  "«Por qué funciona» compara la interacción de cada publicación con la típica de su red, agrupada por gancho, formato y hora (Bogotá).",
  `Orden del ranking: ${esc(W8)}, con un extra por llegar temprano y un descuento por humo.`,
  "Solo contenido público. Los autores se guardan como un código irreversible y se borran menciones, correos y teléfonos.",
].map(x => `<li>${x}</li>`).join("");
// ¿Acierta el radar? Resultado del backtest más reciente (python -m radar.backtest).
const BT = D.backtest;
if (BT && BT.summary.weeks) {
  const S = BT.summary, pct = v => v == null ? "—" : `${Math.round(v * 100)}%`, x = v => v == null ? "—" : `${v.toFixed(2)}×`;
  const bar = (v, plain) => `<i><em class="${plain ? "plain" : ""}" style="width:${Math.round((v || 0) * 100)}%"></em></i>`;
  $("#proof").hidden = false;
  $("#proof").innerHTML = `<h2>¿Acierta el radar?</h2>
    <p>Simulación con publicaciones públicas de las últimas semanas: en ${S.weeks} fechas de corte le mostramos al radar solo lo publicado hasta ese día y comparamos su predicción con lo que pasó los 7 días siguientes.</p>
    <div class="proof-k">
      <div><b>${pct(S.radar_hit)}</b><span>de los temas de su top ${BT.top} siguieron por encima de lo normal la semana siguiente</span></div>
      <div><b>${pct(S.rising_hit)}</b><span>de los temas que marcó «en crecimiento» o «naciente» siguieron arriba (${S.n_rising} casos)</span></div>
      <div><b>${x(S.radar_lift)}</b><span>su participación habitual tuvieron esos temas la semana siguiente (los más populares: ${x(S.popular_lift)})</span></div>
    </div>
    <div class="proof-bars">
      <span>Radar</span>${bar(S.radar_hit)}<b>${pct(S.radar_hit)}</b>
      <span>Seguir lo más popular</span>${bar(S.popular_hit, 1)}<b>${pct(S.popular_hit)}</b>
      <span>Cualquier tema</span>${bar(S.all_hit, 1)}<b>${pct(S.all_hit)}</b>
    </div>
    <p class="cap">«Por encima de lo normal»: más participación en la conversación que en sus dos semanas previas. Clasificador del backtest: ${esc(BT.meta.classifier)} · ${BT.meta.n_posts.toLocaleString("es")} publicaciones · ${esc(BT.meta.generated)}. Pocas semanas: es evidencia direccional, no una prueba estadística definitiva.</p>`;
}

const SRC_NAMES = {bluesky: "Bluesky", hackernews: "Hacker News", youtube: "YouTube", google_news: "Google News"};
const community = Object.entries(C.by_platform).filter(([k]) => !(k in SRC_NAMES)).reduce((a, [, v]) => a + v, 0);
$("#method").insertAdjacentHTML("beforeend", [
  `Cobertura: Bluesky, Hacker News y Google News por API o RSS públicos; YouTube por el RSS oficial de 10 canales (no entra al cálculo de crecimiento porque solo trae los últimos videos). LinkedIn, Instagram y TikTok no tienen API pública sin login: entran solo por aportes de la comunidad (${community} en esta semana).`,
  mode === "jev" && D.meta.jev_cost_usd != null
    ? `Costo de esta actualización: US$${D.meta.jev_cost_usd.toFixed(4)} en Jev (${(D.meta.n_classified || 0).toLocaleString("es")} publicaciones nuevas; ${(D.meta.n_cached || 0).toLocaleString("es")} ya estaban clasificadas y no se pagan otra vez).`
    : D.meta.jev_error ? `Jev no respondió en esta actualización (${esc(D.meta.jev_error)}); se usó el clasificador ${esc(mode)}.` : "",
].filter(Boolean).map(x => `<li>${x}</li>`).join(""));
$("#foot").textContent = `Generado ${D.meta.generated} · ` + Object.entries(C.by_platform).map(([k, v]) => `${k} ${v}`).join(" · ");

// Feed vertical
const adaptable = new Set([D.topics, ...Object.values(BYP).map(v => v.topics)].flat().map(t => t.id));
let saved = new Set();
try { saved = new Set(JSON.parse(localStorage.getItem("radar-saved") || "[]")); } catch (e) {}
const persist = () => { try { localStorage.setItem("radar-saved", JSON.stringify([...saved])); } catch (e) {} };
let tkSort = "lift", tkPlat = "todas", tkTopic = "todos";
const plats = [...new Set(FEED.map(p => p.platform))];
$("#tk-plat").innerHTML = [["todas", "Todas"], ...plats.map(p => [p, p])].map(([k, v], i) => `<button class="chip" data-p="${esc(k)}" aria-pressed="${i === 0}">${esc(v)}</button>`).join("");
const topicsInFeed = [...new Map(FEED.map(p => [p.topic, p.topic_label])).entries()];
$("#tk-topic").innerHTML = `<option value="todos">Todos los temas</option>` + topicsInFeed.map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");

function tkCard(p) {
  const yt = p.platform === "YouTube" ? ytId(p.url) : null;
  const [g1, g2] = gradFor(p.topic);
  const size = p.text.length < 110 ? "l" : p.text.length < 230 ? "m" : "s";
  const lift = p.lift >= 10 ? Math.round(p.lift) : p.lift;
  const acts = (p.platform === "YouTube" ? [[ICONS.eye, p.views, "vistas"]] : [[ICONS.heart, p.likes, "me gusta"], [ICONS.comment, p.comments, "comentarios"], [ICONS.share, p.shares, "compartidos"]])
    .map(([ic, v, l]) => `<div class="tk-act" title="${num(v)} ${l}"><span class="tk-ic">${svgI(ic)}</span>${num(v)}</div>`).join("");
  const thumb = yt ? `https://i.ytimg.com/vi/${yt}/hqdefault.jpg` : "";
  const body = yt
    ? `<div class="tk-body"><a class="tk-media" href="${esc(p.url)}" target="_blank" rel="noopener" aria-label="Ver video en YouTube"><img src="${thumb}" alt="" loading="lazy"><span class="tk-play">${svgI(ICONS.play, 26)}</span></a></div>`
    : `<div class="tk-body"><p class="tk-text ${size}">${esc(p.text)}</p></div>`;
  return `<section class="tk-item"><div class="tk-stage">
    <article class="tk-card ${yt ? "yt" : ""}" data-id="${esc(p.id)}" style="--g1:${g1};--g2:${g2}">
      ${yt ? `<div class="tk-blur" style="background-image:url('${thumb}')"></div>` : ""}
      <div class="tk-row"><span class="tk-plat"><i style="background:${PCOLOR[p.platform] || "#fff"}"></i>${esc(p.platform)}</span>
        <span class="tk-fire" title="Interacción frente a la publicación típica de ${esc(p.platform)}">${svgI(ICONS.fire, 14)}${lift}× su red</span></div>
      ${body}
      <div class="tk-meta"><b>@${esc(p.platform.toLowerCase().replace(/\s+/g, ""))}</b> <span>· ${fmtDay(p.created_at.slice(0, 10))}</span>
        ${yt ? `<p class="tk-cap">${esc(p.text)}</p>` : ""}
        <div class="tk-tags"><button class="tk-tag" data-topic="${esc(p.topic)}">${esc(hashtag(p.topic_label))}</button><span class="tk-hook">gancho: ${esc(p.hook)}</span></div></div>
    </article>
    <div class="tk-rail">${acts}
      <button class="tk-act tk-save" data-id="${esc(p.id)}" aria-pressed="${saved.has(p.id)}"><span class="tk-ic">${svgI(ICONS.save)}</span>Guardar</button>
      ${adaptable.has(p.topic) ? `<button class="tk-act tk-adapt" data-topic="${esc(p.topic)}"><span class="tk-ic">${svgI(ICONS.bulb)}</span>Ideas</button>` : ""}
      <a class="tk-act" href="${esc(p.url)}" target="_blank" rel="noopener"><span class="tk-ic">${svgI(ICONS.open)}</span>Abrir</a>
    </div></div></section>`;
}
let tkObserver;
function renderFeed() {
  let items = FEED.filter(p => (tkPlat === "todas" || p.platform === tkPlat) && (tkTopic === "todos" || p.topic === tkTopic));
  if (tkSort === "saved") items = items.filter(p => saved.has(p.id));
  items.sort((a, b) => tkSort === "new" ? b.created_at.localeCompare(a.created_at) : tkSort === "fit" ? b.audience_fit - a.audience_fit : b.lift - a.lift);
  const tk = $("#tk");
  tk.innerHTML = items.length ? items.map(tkCard).join("")
    : `<div class="tk-empty"><b>${tkSort === "saved" ? "Aún no guardas nada" : FEED.length ? "Nada con estos filtros" : "Este reporte no tiene feed"}</b>
       <span>${tkSort === "saved" ? "Toca Guardar o haz doble clic en una publicación." : FEED.length ? "Prueba con otra red o tema." : "Actualiza el radar para generarlo."}</span></div>`;
  tk.scrollTop = 0;
  $("#tk-count").textContent = items.length ? `1 / ${items.length}` : "";
  tkObserver?.disconnect();
  tkObserver = new IntersectionObserver(entries => entries.forEach(en => {
    if (en.isIntersecting) $("#tk-count").textContent = `${[...tk.children].indexOf(en.target) + 1} / ${items.length}`;
  }), {root: tk, threshold: 0.6});
  $$(".tk-item", tk).forEach(el => tkObserver.observe(el));
}
const tkStep = dir => { const tk = $("#tk"); tk.scrollBy({top: dir * tk.clientHeight, behavior: "smooth"}); };
$("#tk-up").onclick = () => tkStep(-1);
$("#tk-down").onclick = () => tkStep(1);
document.addEventListener("keydown", e => {
  if (!document.body.classList.contains("feed-mode") || e.target.closest("select,input,textarea")) return;
  if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); tkStep(1); }
  if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); tkStep(-1); }
});
$("#view-feed .tabs-top").addEventListener("click", e => {
  const b = e.target.closest(".tk-tab"); if (!b) return;
  tkSort = b.dataset.sort; $$(".tk-tab").forEach(x => x.setAttribute("aria-selected", x === b)); renderFeed();
});
$("#tk-plat").addEventListener("click", e => {
  const b = e.target.closest(".chip"); if (!b) return;
  tkPlat = b.dataset.p; $$("#tk-plat .chip").forEach(x => x.setAttribute("aria-pressed", x === b)); renderFeed();
});
$("#tk-topic").onchange = e => { tkTopic = e.target.value; renderFeed(); };
function toggleSave(id, on) {
  on ? saved.add(id) : saved.delete(id); persist();
  $$(`.tk-save[data-id="${CSS.escape(id)}"]`).forEach(b => b.setAttribute("aria-pressed", on));
}
$("#tk").addEventListener("click", e => {
  const save = e.target.closest(".tk-save");
  if (save) toggleSave(save.dataset.id, !saved.has(save.dataset.id));
  const tag = e.target.closest(".tk-tag");
  if (tag) { tkTopic = tag.dataset.topic; $("#tk-topic").value = tkTopic; renderFeed(); }
  const idea = e.target.closest(".tk-adapt");
  if (idea) openTopic(idea.dataset.topic);
});
$("#tk").addEventListener("dblclick", e => {
  const card = e.target.closest(".tk-card"); if (!card || e.target.closest("a,button")) return;
  toggleSave(card.dataset.id, true);
  const heart = document.createElement("div"); heart.className = "tk-burst";
  heart.innerHTML = `<svg viewBox="0 0 24 24" width="120" height="120" fill="currentColor">${ICONS.heart}</svg>`;
  card.appendChild(heart); setTimeout(() => heart.remove(), 900);
});
function sizeFeed() {
  if (!document.body.classList.contains("feed-mode")) return;
  root.style.setProperty("--tk-off", `${$(".bar").offsetHeight + $(".tk-top").offsetHeight + $(".tk-note").offsetHeight}px`);
}
addEventListener("resize", sizeFeed);
renderFeed();

function setView(v) {
  $$(".seg button").forEach(b => b.setAttribute("aria-pressed", b.dataset.view === v));
  $("#view-radar").hidden = v !== "radar"; $("#view-feed").hidden = v !== "feed";
  document.body.classList.toggle("feed-mode", v === "feed");
  scrollTo(0, 0);
  if (v === "feed") { sizeFeed(); $("#tk").focus({preventScroll: true}); try { history.replaceState(null, "", "#feed"); } catch (e) {} }
  else try { history.replaceState(null, "", location.pathname + location.search); } catch (e) {}
}
$(".seg").addEventListener("click", e => { const b = e.target.closest("button"); if (b) setView(b.dataset.view); });

const start = decodeURIComponent(location.hash.slice(1));
if (start === "feed") setView("feed");
else if ([T, D.topics].flat().some(t => t.id === start)) openTopic(start);
})();
</script>
</body></html>"""

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
    paths["html"].write_text(render_html(result, adaptations, meta, n, latest_backtest(out_dir)), encoding="utf-8")
    paths["md"].write_text(render_markdown(result, adaptations, meta, n), encoding="utf-8")
    plain = lambda ts: [{**t, "examples": [p.to_dict() for p in t["examples"]]} for t in ts]
    serializable = {**result, "topics": plain(result["topics"]),
                    "by_app": {k: {**v, "topics": plain(v["topics"])} for k, v in result.get("by_app", {}).items()},
                    "adaptations": adaptations, "meta": meta}
    paths["json"].write_text(json.dumps(serializable, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return paths
