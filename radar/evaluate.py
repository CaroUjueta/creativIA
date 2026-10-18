"""Evaluación del radar: python -m radar.evaluate [--puntuar]

Sin opciones, mide lo que se puede medir solo con los datos de la última corrida (out/radar-*.json y
out/piezas-*.jsonl) y deja hojas CSV para lo que necesita criterio humano:

  out/evaluacion/privacidad.csv       30 piezas al azar para buscar fugas de datos personales
  out/evaluacion/etiquetado.csv       50 piezas para etiquetar a mano (tema, gancho, formato, humo, relevancia)
  out/evaluacion/top10.csv            ¿cada tema tiene sentido? ¿30X publicaría sobre esto?
  out/evaluacion/recomendaciones.csv  rúbrica de 1 a 5 para cada recomendación

Con --puntuar, lee esas hojas ya llenas y calcula acuerdo con humanos, fugas y promedios de la rúbrica.
El informe queda en out/evaluacion-AAAA-MM-DD.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from . import analysis, config
from .models import Post

OUT = Path("out")
SHEETS = OUT / "evaluacion"
SEED = 30  # misma muestra en cada evaluación de la misma corrida
YES = {"si", "sí", "s", "yes", "y", "1", "x"}

# Lo que el limpiador debió quitar. Se busca en el texto y en el enlace guardado.
LEAKS = {
    "mención": re.compile(r"(?<![\w@/.])@(?!usuario\b)[A-Za-z0-9_][A-Za-z0-9_.]{1,}"),
    "correo": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "teléfono": re.compile(r"(?<![\w/])\+?\d[\d\s().-]{8,}\d(?![\w/])"),
}
# Enlaces que nombran a una persona (Bluesky incluye el usuario en la URL del post).
URL_HANDLE = re.compile(r"bsky\.app/profile/(?!did:)([^/]+)")


def _latest(pattern: str) -> Path:
    files = sorted(OUT.glob(pattern), reverse=True)
    if not files:
        raise SystemExit(f"No hay {pattern} en {OUT}/. Corre primero: python -m radar")
    return files[0]


def load() -> tuple[dict, list[Post]]:
    report = json.loads(_latest("radar-*.json").read_text(encoding="utf-8"))
    stamp = report["meta"]["generated"][:10]
    posts_file = OUT / f"piezas-{stamp}.jsonl"
    if not posts_file.exists():
        raise SystemExit(f"Falta {posts_file}. Corre de nuevo python -m radar (las corridas nuevas guardan las piezas).")
    posts = []
    for line in posts_file.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        posts.append(Post(**{**d, "created_at": datetime.fromisoformat(d["created_at"])}))
    return report, posts


def pct(x: float) -> str:
    return f"{x * 100:.0f} %"


def _source(p: Post) -> str:
    return f"noticias {p.app}" if p.app else p.platform


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# --- 1. Recolección --------------------------------------------------------------------------

def collection(report: dict, posts: list[Post]) -> list[str]:
    meta, stats = report["meta"], report["meta"].get("collection", {})
    by = Counter(_source(p) for p in posts)
    total = sum(by.values())
    top_src, top_n = by.most_common(1)[0]
    ok, failed = Counter(stats.get("requests_ok", {})), Counter(stats.get("requests_failed", {}))
    n_req = sum(ok.values()) + sum(failed.values())
    err = sum(failed.values()) / n_req if n_req else 0
    ai = [p for p in posts if p.labels and p.labels.get("is_ai", 0) >= 0.5]
    es = sum(p.lang == "es" for p in ai) / len(ai) if ai else 0
    latam = sum(p.labels.get("latam", 0) >= 0.5 for p in ai) / len(ai) if ai else 0
    no_metrics = Counter(p.platform for p in posts if p.platform != "google_news" and not (p.likes or p.comments or p.shares or p.views))
    silent = [k for k, v in stats.get("by_job", {}).items() if not v]
    lines = ["## 1. Recolección", "", "| Fuente | Piezas | % |", "|---|---:|---:|"]
    lines += [f"| {k} | {v:,} | {pct(v / total)} |" for k, v in by.most_common()]
    lines += ["",
              f"- Fuente dominante: **{top_src}** con {pct(top_n / total)}" + (" ⚠ más de la mitad: los resultados se inclinan hacia ella." if top_n / total > 0.5 else "."),
              f"- Piezas de IA en español: **{pct(es)}**; con relación explícita a Latinoamérica: {pct(latam)}.",
              f"- Duplicados eliminados: {stats.get('duplicates', '—')}; sin texto: {stats.get('empty_text', '—')}.",
              f"- Consultas: {n_req:,}, fallidas {sum(failed.values())} (**{pct(err)}**)" + (f": {', '.join(f'{h} {n}' for h, n in failed.most_common())}." if failed else "."),
              f"- Piezas sin métricas de interacción (Google News no las trae, por diseño): {', '.join(f'{k} {v}' for k, v in no_metrics.items()) or 'ninguna'}.",
              f"- Tiempo: recolección {stats.get('seconds', '—')} s; corrida completa {meta.get('seconds', '—')} s.",
              f"- Meta (todas las fuentes responden, menos de 5 % de errores): **{'cumple' if not silent and err < 0.05 else 'no cumple'}**"
              + (f" — sin piezas: {', '.join(silent)}." if silent else "."), ""]
    return lines


# --- 2. Privacidad ---------------------------------------------------------------------------

def privacy(posts: list[Post]) -> list[str]:
    hits = Counter()
    examples = []
    for p in posts:
        for kind, rx in LEAKS.items():
            m = rx.search(p.text)
            if m:
                hits[kind] += 1
                if len(examples) < 5:
                    examples.append(f"{p.id}: …{p.text[max(0, m.start() - 20):m.end() + 10]}…")
    handles = sum(1 for p in posts if URL_HANDLE.search(p.url))
    dids = sum(1 for p in posts if "bsky.app/profile/did:" in p.url)
    people = sum(1 for p in posts if p.publisher and p.platform in ("bluesky", "hackernews"))
    rows = [{"id": p.id, "fuente": _source(p), "texto": p.text, "publicado_por": p.publisher, "enlace": p.url,
             "fuga (sí/no)": "", "qué se escapó": ""} for p in random.Random(SEED).sample(posts, min(30, len(posts)))]
    _write(SHEETS / "privacidad.csv", rows)
    return ["## 2. Privacidad", "",
            f"- Búsqueda automática en {len(posts):,} textos: " + (", ".join(f"{k} {v}" for k, v in hits.items()) or "**0 fugas**") + ".",
            *([f"  - Ejemplos: {e}" for e in examples]),
            "  Las coincidencias de «teléfono» suelen ser cifras o fechas largas; revisarlas antes de darlas por fuga.",
            f"- Enlaces con el usuario del autor a la vista: **{handles}**. Los {dids} enlaces de Bluesky usan el identificador técnico (DID), no el nombre; "
            "al abrirlos se ve el perfil público, como en cualquier enlace a una publicación.",
            f"- Autores personas con nombre guardado: {people} (el autor se guarda como hash).",
            f"- Revisión humana: `{SHEETS / 'privacidad.csv'}` (30 piezas). Marquen «fuga» con sí/no. Meta: cero fugas.", ""]


# --- 3. Clasificación ------------------------------------------------------------------------

def _bucket_fit(x: float) -> int:
    return min(3, int(x * 4))


def classification(report: dict, posts: list[Post]) -> list[str]:
    mode = report["meta"]["classifier"]
    ai = [p for p in posts if p.labels and p.labels.get("is_ai", 0) >= 0.5 and not p.app]
    lines = ["## 3. Calidad de la clasificación", "",
             f"Clasificador de esta corrida: **{mode}**" + (" (Jev no estuvo disponible; se evalúa el clasificador local)." if mode != "jev" else ".") , ""]
    for field, names in (("topic", config.TOPIC_NAMES), ("hook", None), ("format", None), ("publisher", None)):
        c = Counter(p.labels[field] for p in ai)
        top, n = c.most_common(1)[0]
        flag = " ⚠ casi todo en una categoría" if n / len(ai) > 0.6 else ""
        lines.append(f"- **{field}**: {len(c)} categorías usadas; la mayor, «{(names or {}).get(top, top)}», tiene {pct(n / len(ai))}{flag}.")
    conf = sorted(p.labels.get("topic_confidence", 0) for p in ai)
    q = statistics.quantiles(conf, n=4)
    lines += [f"- Confianza en el tema: mediana {q[1]:.2f} (cuartiles {q[0]:.2f}–{q[2]:.2f}).",
              f"- Humo y relevancia del clasificador local son percentiles de la muestra: se comparan como «humo» = cuartil más alto y relevancia 0–3 = cuartil." if mode == "local" else ""]
    sample = random.Random(SEED).sample(ai, min(50, len(ai)))
    _write(SHEETS / "etiquetado.csv", [{"id": p.id, "fuente": _source(p), "texto": p.text[:600], "tema": "", "gancho": "",
                                        "formato": "", "humo (sí/no)": "", "relevancia (0-3)": ""} for p in sample])
    key = {p.id: {"tema": p.labels["topic"], "gancho": p.labels["hook"], "formato": p.labels["format"],
                  "humo": p.labels.get("hype", 0) >= (0.75 if mode == "local" else 0.5),
                  "relevancia": _bucket_fit(p.labels.get("audience_fit", 0)), "confianza": p.labels.get("topic_confidence", 0)}
           for p in sample}
    (SHEETS / "etiquetado_clave.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    opts = SHEETS / "opciones.md"
    opts.write_text("# Valores válidos para etiquetado.csv\n\n" + "\n".join(
        f"## {title}\n" + "\n".join(f"- `{k}`: {v}" for k, v in d.items()) + "\n"
        for title, d in (("tema", config.TOPICS), ("gancho", config.HOOKS), ("formato", config.FORMATS))) +
        "\n## humo\nsí / no: ¿es clickbait o exageración con poca sustancia?\n\n## relevancia\n0 nada · 1 poco · 2 útil · 3 muy útil para ejecutivos y equipos de LatAm\n",
        encoding="utf-8")
    lines += ["", f"- Etiquetado humano: `{SHEETS / 'etiquetado.csv'}` (50 piezas, sin las etiquetas del modelo para no sesgar). "
              f"Valores válidos en `{opts}`. Luego: `python -m radar.evaluate --puntuar`. Meta: 70 % o más en tema y gancho.", ""]
    return [l for l in lines if l is not None]


# --- 4. Tendencias ---------------------------------------------------------------------------

def _window(report: dict) -> tuple[datetime, datetime]:
    w = report["window"]
    return datetime.fromisoformat(w["start"]), datetime.fromisoformat(w["end"])


def trends(report: dict, posts: list[Post]) -> list[str]:
    start, end = _window(report)
    base = [p for p in posts if not p.app]
    no_mom = set() if "youtube" in report["counts"].get("momentum_platforms", []) else analysis.NO_MOMENTUM
    full = analysis.analyze(base, start, end, no_momentum=no_mom)
    top = [t["id"] for t in full["topics"][:10]]
    rng = random.Random(SEED)
    overlaps, seen = [], Counter()
    for _ in range(20):  # ¿cambia el top 10 si falta el 15 % de las piezas?
        sub = analysis.analyze(rng.sample(base, int(len(base) * 0.85)), start, end, no_momentum=no_mom)
        ids = [t["id"] for t in sub["topics"][:10]]
        overlaps.append(len(set(ids) & set(top)))
        seen.update(ids)
    stages = Counter(t["stage"] for t in full["topics"])
    bt = sorted(OUT.glob("backtest-*.json"), reverse=True)
    lines = ["## 4. Detección de tendencias", ""]
    if bt:
        b = json.loads(bt[0].read_text(encoding="utf-8"))["summary"]
        lines.append(f"- Backtest ({bt[0].name}): {json.dumps(b, ensure_ascii=False)[:400]}")
        lines.append("  Para repetirlo con los datos de hoy: `python -m radar.backtest --weeks 3`.")
    else:
        lines.append("- Backtest: no hay resultados. Corre `python -m radar.backtest --weeks 3`.")
    stable = statistics.mean(overlaps)
    lines += [f"- Estabilidad: quitando al azar el 15 % de las piezas (20 veces), el top 10 conserva en promedio **{stable:.1f} de 10** temas "
              f"(mínimo {min(overlaps)})." + (" Meta (mayoría coincidente): cumple." if stable > 5 else " ⚠ el top 10 es ruidoso."),
              "  Temas del top 10 completo y en cuántas de las 20 repeticiones aparecen: " +
              ", ".join(f"{config.TOPIC_NAMES.get(t, t)} {seen[t]}/20" for t in top) + ".",
              "- Etapas: " + ", ".join(f"{k} {v}" for k, v in stages.most_common()) +
              (" ⚠ casi todo en una etapa: revisar umbrales." if stages.most_common(1)[0][1] > 0.7 * len(full["topics"]) else "."), ""]
    _write(SHEETS / "top10.csv", [{"puesto": i, "tema": t["label"], "etapa": t["stage"], "crecimiento": f"{(t['growth'] - 1) * 100:+.0f} %",
                                   "ejemplo 1": t["examples"][0].text[:160] if t["examples"] else "",
                                   "ejemplo 2": t["examples"][1].text[:160] if len(t["examples"]) > 1 else "",
                                   "¿tiene sentido? (sí/no)": "", "¿30X publicaría? (sí/no)": "", "comentario": ""}
                                  for i, t in enumerate(full["topics"][:10], 1)])
    lines += [f"- Revisión humana del top 10 y encaje con 30X: `{SHEETS / 'top10.csv'}`.", ""]
    return lines


# --- 5. Priorización, humo y factores de éxito ----------------------------------------------

def priority(report: dict, posts: list[Post]) -> list[str]:
    start, end = _window(report)
    base = [p for p in posts if not p.app]
    with_h = analysis.analyze(base, start, end)["topics"]
    without = [dict(t) for t in with_h]
    analysis._score(without, hype_penalty=0.0)
    without.sort(key=lambda t: t["score"], reverse=True)
    rank_with = {t["id"]: i for i, t in enumerate(with_h, 1)}
    moves = sorted(((rank_with[t["id"]] - i, t) for i, t in enumerate(without, 1)), key=lambda x: -x[0])
    lines = ["## 5. Priorización, humo y factores de éxito", "",
             "- Efecto de la multa por humo (puestos que pierde cada tema al aplicarla):"]
    for d, t in moves[:4]:
        if d > 0:
            lines.append(f"  - {t['label']}: baja {d} puesto(s); humo promedio {t['hype']:.2f}.")
    if not any(d > 0 for d, _ in moves):
        lines.append("  - La multa no cambia el orden en esta corrida.")
    weak, strong = [], []
    for t in with_h[:10]:
        for kind in ("hooks", "formats", "timing"):
            for s in t["why"][kind][:1]:
                if s["lift"] >= 1.2:
                    (weak if s["n"] < 5 else strong).append(f"{t['label']} · {kind} «{s['value']}» {s['lift']}× (n={s['n']})")
    lines += [f"- Factores de éxito del top 10: {len(strong)} con 5 piezas o más, **{len(weak)} débiles** (menos de 5 piezas).",
              *[f"  - débil: {w}" for w in weak[:8]], ""]
    return lines


# --- 6. Recomendaciones ----------------------------------------------------------------------

NUM = re.compile(r"\d+(?:[.,]\d+)?\s*%?")
DURATION = re.compile(r"[<>~]?\d+(?:\s*[-–]\s*\d+)?\s*(?:seg\w*|s\b|min\w*|láminas?|slides?|pasos?|horas?|palabras|días?)", re.I)


def recommendations(report: dict) -> list[str]:
    adaptations = report.get("adaptations", {})
    topics = {t["id"]: t for t in report["topics"]}
    suspicious, pending, rows = [], 0, []
    for tid, a in adaptations.items():
        t = topics.get(tid, {})
        # Cifras permitidas: las que el sistema calculó o que aparecen en los ejemplos.
        allowed = {f"{(t.get('growth', 1) - 1) * 100:.0f}"} | set(re.findall(r"\d+", json.dumps(t.get("examples", []), ensure_ascii=False)))
        allowed |= {str(x) for x in range(0, 11)}  # "3 formas", "5 pasos": cantidades del formato, no datos
        why = t.get("why", {})
        allowed |= {re.sub(r"\D", "", str(r.get(k, ""))) for rows in why.values() if isinstance(rows, list)
                    for r in rows if isinstance(r, dict) for k in ("lift", "n")}
        # Duraciones y cantidades de láminas son parte del formato, no datos.
        text = DURATION.sub(" ", json.dumps(a, ensure_ascii=False))
        pending += text.count("dato por verificar")
        for m in NUM.findall(text):
            digits = re.sub(r"\D", "", m.split(",")[0].split(".")[0])
            if digits and digits not in allowed and re.sub(r"\D", "", m) not in allowed:
                suspicious.append(f"{t.get('label', tid)}: «{m.strip()}»")
        pc = a.get("para_cuenta") or {}
        rows.append({"tema": t.get("label", tid), "ángulo": a.get("angulo", ""), "ganchos": " | ".join(a.get("ganchos", [])),
                     "formato instagram": (a.get("formatos") or {}).get("instagram", ""), "pieza para la cuenta": pc.get("caption", ""),
                     "fidelidad (1-5)": "", "especificidad (1-5)": "", "encaje (1-5)": "", "accionable (1-5)": "", "comentario": ""})
    if rows:
        _write(SHEETS / "recomendaciones.csv", rows)
    return ["## 6. Recomendaciones", "",
            f"- Redactadas con: {report['meta'].get('adapter', '—')}; {len(adaptations)} temas.",
            f"- Cifras que no salen de los datos calculados ni de los ejemplos (posible dato inventado): **{len(suspicious)}**",
            *[f"  - {s}" for s in suspicious[:10]],
            f"- Marcas «[dato por verificar]» (el modelo pidió un dato en vez de inventarlo): {pending}.",
            f"- Rúbrica humana (fidelidad, especificidad, encaje, accionable, de 1 a 5): `{SHEETS / 'recomendaciones.csv'}`. Meta: promedio 4 o más y cero datos inventados.", ""]


# --- Transversal -----------------------------------------------------------------------------

def cost(report: dict) -> list[str]:
    m = report["meta"]
    adapter = m.get("adapter", "")
    free = ":free" in adapter or "plantillas" in adapter
    total = m.get("n_classified", 0) + m.get("n_cached", 0)
    return ["## Transversal: costo y repetibilidad", "",
            f"- Clasificación: {m.get('classifier')} · costo US${m.get('jev_cost_usd', 0):.4f}"
            + (" (modelo local: sin costo)." if m.get("classifier") != "jev" else "."),
            f"- Redacción: {adapter}" + (" · sin costo (modelo gratuito o plantillas)." if free else " · revisar el uso en OpenRouter."),
            f"- **Costo de esta corrida: US${m.get('jev_cost_usd', 0) + 0:.2f}**" + (" (cero)." if free and m.get("classifier") != "jev" else "."),
            f"- Caché: {m.get('n_cached', 0)} de {total} piezas no se volvieron a pagar"
            + (" (la caché solo aplica a Jev; el modelo local no cobra)." if m.get("classifier") != "jev" else "."), ""]


# --- Puntuar las hojas llenas ----------------------------------------------------------------

def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def score() -> list[str]:
    lines = ["# Resultados de la revisión humana", ""]
    priv = [r for r in _read(SHEETS / "privacidad.csv") if r["fuga (sí/no)"].strip()]
    if priv:
        leaks = [r for r in priv if r["fuga (sí/no)"].strip().lower() in YES]
        lines.append(f"- Privacidad: {len(priv)} piezas revisadas, **{len(leaks)} fugas**" +
                     ("".join(f"\n  - {r['id']}: {r['qué se escapó']}" for r in leaks) or "."))
    labels = [r for r in _read(SHEETS / "etiquetado.csv") if r["tema"].strip()]
    key_file = SHEETS / "etiquetado_clave.json"
    if labels and key_file.exists():
        key = json.loads(key_file.read_text(encoding="utf-8"))
        agree = Counter()
        n = Counter()
        conf_hit = {"alta": [0, 0], "baja": [0, 0]}
        med = statistics.median(k["confianza"] for k in key.values())
        for r in labels:
            k = key.get(r["id"])
            if not k:
                continue
            for col, field in (("tema", "tema"), ("gancho", "gancho"), ("formato", "formato")):
                if r[col].strip():
                    n[col] += 1
                    agree[col] += r[col].strip() == k[field]
            if r["humo (sí/no)"].strip():
                n["humo"] += 1
                agree["humo"] += (r["humo (sí/no)"].strip().lower() in YES) == k["humo"]
            if r["relevancia (0-3)"].strip().isdigit():
                n["relevancia ±1"] += 1
                agree["relevancia ±1"] += abs(int(r["relevancia (0-3)"]) - k["relevancia"]) <= 1
            b = conf_hit["alta" if k["confianza"] >= med else "baja"]
            b[0] += r["tema"].strip() == k["tema"]
            b[1] += 1
        lines.append(f"- Acuerdo con humanos ({len(labels)} piezas): " +
                     ", ".join(f"{q} **{pct(agree[q] / n[q])}**" for q in n) + ". Meta: 70 % o más en tema y gancho.")
        lines.append("- Tema según confianza del modelo: " +
                     ", ".join(f"confianza {k} {pct(v[0] / v[1])} ({v[1]} piezas)" for k, v in conf_hit.items() if v[1]) +
                     ". Si la alta acierta más, conviene filtrar las de baja confianza.")
    top = [r for r in _read(SHEETS / "top10.csv") if r["¿tiene sentido? (sí/no)"].strip()]
    if top:
        ok = sum(r["¿tiene sentido? (sí/no)"].strip().lower() in YES for r in top)
        pub = sum(r["¿30X publicaría? (sí/no)"].strip().lower() in YES for r in top)
        lines.append(f"- Top 10: {ok} de {len(top)} tienen sentido; 30X publicaría sobre {pub} de {len(top)}.")
    recs = [r for r in _read(SHEETS / "recomendaciones.csv") if r["fidelidad (1-5)"].strip()]
    if recs:
        cols = ["fidelidad (1-5)", "especificidad (1-5)", "encaje (1-5)", "accionable (1-5)"]
        means = {c: statistics.mean(float(r[c]) for r in recs if r[c].strip()) for c in cols}
        lines.append(f"- Recomendaciones ({len(recs)} calificadas): " + ", ".join(f"{c.split(' ')[0]} {v:.1f}" for c, v in means.items())
                     + f"; promedio **{statistics.mean(means.values()):.1f}**. Meta: 4 o más.")
    if len(lines) == 2:
        lines.append("Todavía no hay hojas llenas en " + str(SHEETS) + ".")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(prog="radar.evaluate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puntuar", action="store_true", help="calcular resultados con las hojas ya llenas")
    args = ap.parse_args()
    if args.puntuar:
        lines = score()
        path = OUT / f"evaluacion-humana-{date.today().isoformat()}.md"
    else:
        report, posts = load()
        lines = [f"# Evaluación del radar · corrida {report['meta']['generated']}", "",
                 *collection(report, posts), *privacy(posts), *classification(report, posts),
                 *trends(report, posts), *priority(report, posts), *recommendations(report), *cost(report)]
        path = OUT / f"evaluacion-{date.today().isoformat()}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nInforme: {path}")


if __name__ == "__main__":
    main()
