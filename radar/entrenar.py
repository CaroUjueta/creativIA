"""Entrena el clasificador local con etiquetas de un modelo grande: python -m radar.entrenar

El clasificador local compara cada pieza con la descripción de cada tema y acierta poco (38 % en
tema frente a la revisión manual). Aquí un modelo abierto grande y gratuito (Nemotron vía OpenRouter)
etiqueta una sola vez unos cientos de piezas, y con esas etiquetas se entrena una capa pequeña sobre
los embeddings del modelo local. Después el radar clasifica todo en el computador, sin red ni costo.

    python -m radar.entrenar --etiquetar 300    # pide etiquetas para 300 piezas nuevas (100 por consulta)
    python -m radar.entrenar                    # solo reentrena con las etiquetas ya guardadas

Las piezas revisadas a mano (data/evaluacion/revision_manual.csv y out/evaluacion*/etiquetado.csv)
nunca se usan para entrenar, para que la evaluación siga midiendo piezas que el modelo no vio.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import re
import time
from pathlib import Path

import numpy as np

from . import config

log = logging.getLogger("radar")

LABELS = Path("data/entrenamiento/etiquetas.jsonl")
MODEL = Path("data/modelo_local.npz")
BANK = Path("data/evaluacion/revision_manual.csv")
TEACHER = os.environ.get("RADAR_TEACHER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
BATCH = 100  # piezas por consulta: el plan gratuito de OpenRouter da 50 consultas al día

# Cada cabeza predice una pregunta; las opciones salen de config para que coincidan con Jev.
HEADS = {
    "topic": ("t", list(config.TOPICS)),
    "hook": ("g", list(config.HOOKS)),
    "format": ("f", list(config.FORMATS)),
    "hype": ("h", [0, 1]),
    "relevance": ("r", [0, 1, 2, 3]),
}


def _options(d: dict) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in d.items())


PROMPT = f"""Eres un analista de contenido. Clasificas publicaciones públicas sobre inteligencia artificial.
Para cada pieza decide:
t (tema, uno):
{_options(config.TOPICS)}
Criterio: elige el tema de lo que la pieza dice, no de las palabras sueltas. Las opiniones, quejas, chistes o debates generales sobre la IA sin un tema más concreto son ia_y_sociedad. Usa ia_en_latam solo si el foco es la región; una noticia de un país latino sobre otro tema va en ese otro tema.
g (gancho de la primera frase, uno):
{_options(config.HOOKS)}
Criterio: aplica las definiciones al pie de la letra. Un titular informativo de un medio suele ser sin_gancho; una publicación en redes que arranca con la postura o la queja del autor es opinion.
f (formato, uno):
{_options(config.FORMATS)}
h: 1 si es clickbait o exageración con poca sustancia, si no 0.
r: utilidad de 0 a 3 para ejecutivos y equipos de empresas en Latinoamérica que adoptan IA (0 nada, 1 poco, 2 útil, 3 muy útil).
Responde solo JSON: {{"piezas": [{{"i": 0, "t": "...", "g": "...", "f": "...", "h": 0, "r": 1}}, ...]}} con una entrada por pieza, en orden."""


def held_out(root: Path = Path("out")) -> set[str]:
    """Ids de las piezas de revisión manual: no se entrenan con ellas."""
    ids = set()
    for sheet in [BANK, *root.glob("evaluacion*/etiquetado.csv")]:
        if not sheet.exists():
            continue
        with sheet.open(newline="", encoding="utf-8-sig") as f:
            ids |= {r["id"] for r in csv.DictReader(f)}
    return ids


def _valid(item: dict) -> bool:
    return all(item.get(k) in opts for k, opts in HEADS.values())


def degenerate(items: list[dict]) -> bool:
    """Lote en el que casi todo trae el mismo tema y el mismo gancho: el modelo respondió en automático.

    Pasó una vez: un lote de 100 volvió entero como otro_ia y sin_gancho, y entrenar con eso hunde el tema.
    """
    if len(items) < 20:
        return False
    top = max(sum(it["t"] == t for it in items) for t in {it["t"] for it in items})
    return top / len(items) > 0.6


def ask_teacher(texts: list[str], model: str = TEACHER) -> dict[int, dict]:
    """Una consulta con un lote de piezas; devuelve las etiquetas válidas por posición."""
    import httpx

    body = {"model": model,
            "messages": [{"role": "system", "content": PROMPT},
                         {"role": "user", "content": "\n".join(f"[{i}] {t[:500]}" for i, t in enumerate(texts))}],
            "response_format": {"type": "json_object"}, "reasoning": {"effort": "low"}, "max_tokens": 60000}
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "X-Title": "Radar de contenido IA"}
    r = httpx.post("https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers, timeout=1200)
    r.raise_for_status()
    m = re.search(r"\{.*\}", r.json()["choices"][0]["message"].get("content") or "", re.S)
    if not m:
        raise RuntimeError("la respuesta no trae JSON")
    items = json.loads(m.group()).get("piezas", [])
    out = {it["i"]: it for it in items if isinstance(it, dict) and isinstance(it.get("i"), int) and _valid(it)}
    if degenerate(list(out.values())):
        raise RuntimeError("respuesta degenerada: casi todo el lote con el mismo tema")
    return out


def label(pieces: Path, n: int, seed: int = 7) -> int:
    """Etiqueta n piezas de IA que aún no tienen etiqueta y las agrega a LABELS. Se puede retomar."""
    done = {json.loads(l)["id"] for l in LABELS.read_text(encoding="utf-8").splitlines()} if LABELS.exists() else set()
    skip = done | held_out()
    pool = []
    for line in pieces.read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        if p["id"] not in skip and p.get("labels", {}).get("is_ai", 0) >= 0.5 and not p.get("app"):
            pool.append(p)
    todo = random.Random(seed).sample(pool, min(n, len(pool)))
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    for i in range(0, len(todo), BATCH):
        part = todo[i:i + BATCH]
        t0 = time.time()
        try:
            out = ask_teacher([p["text"] for p in part])
        except RuntimeError as e:  # respuesta inválida: se descarta el lote y se sigue
            log.warning("Lote %d descartado (%s).", i // BATCH + 1, str(e)[:160])
            continue
        except Exception as e:  # sin cupo diario o modelo caído: lo ya guardado sirve
            log.warning("Lote %d sin etiquetas (%s); se detiene.", i // BATCH + 1, str(e)[:160])
            break
        with LABELS.open("a", encoding="utf-8") as f:
            for j, p in enumerate(part):
                if j in out:
                    row = {"id": p["id"], "platform": p["platform"], "text": p["text"],
                           **{k: out[j][k] for k, _ in HEADS.values()}, "model": TEACHER}
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    added += 1
        log.info("Lote %d: %d de %d piezas en %.0f s", i // BATCH + 1, len(out), len(part), time.time() - t0)
    return added


def fit_softmax(X: np.ndarray, y: np.ndarray, k: int, l2: float = 1e-3, steps: int = 3000, lr: float = 0.5) -> np.ndarray:
    """Regresión logística multinomial por descenso de gradiente. Devuelve W con el sesgo en la última fila."""
    Xb = np.hstack([X, np.ones((len(X), 1))])
    Y = np.eye(k)[y]
    W = np.zeros((Xb.shape[1], k))
    for _ in range(steps):
        Z = Xb @ W
        P = np.exp(Z - Z.max(1, keepdims=True))
        P /= P.sum(1, keepdims=True)
        W -= lr * (Xb.T @ (P - Y) / len(X) + l2 * W)
    return W


def predict(W: np.ndarray, X: np.ndarray) -> np.ndarray:
    Z = np.hstack([X, np.ones((len(X), 1))]) @ W
    P = np.exp(Z - Z.max(1, keepdims=True))
    return P / P.sum(1, keepdims=True)


L2_GRID = (1e-4, 1e-3, 1e-2)


def pick_l2(X: np.ndarray, y: np.ndarray, k: int, folds: int = 5, seed: int = 7) -> tuple[float, float]:
    """Regularización elegida por validación cruzada contra las etiquetas del profesor.

    Así no se usa el banco de revisión manual para ajustar nada: el banco solo mide.
    """
    idx = np.random.default_rng(seed).permutation(len(X))
    scores = {}
    for l2 in L2_GRID:
        hits = 0
        for f in range(folds):
            test = idx[f::folds]
            train = np.setdiff1d(idx, test)
            hits += (predict(fit_softmax(X[train], y[train], k, l2=l2), X[test]).argmax(1) == y[test]).sum()
        scores[l2] = hits / len(X)
    best = max(scores, key=scores.get)
    return best, scores[best]


def train(embed, embed_model: str) -> dict:
    """Entrena una cabeza por pregunta con las etiquetas guardadas y guarda MODEL."""
    rows = [json.loads(l) for l in LABELS.read_text(encoding="utf-8").splitlines()]
    X = embed([r["text"][:1000] for r in rows])
    weights, sizes = {}, {}
    for head, (key, opts) in HEADS.items():
        y = np.array([opts.index(r[key]) for r in rows])
        l2, cv = pick_l2(X, y, len(opts))
        weights[head] = fit_softmax(X, y, len(opts), l2=l2)
        sizes[head] = f"{len(opts)} opciones, l2={l2:g}, validación cruzada {cv:.0%}"
        log.info("  %s: %s", head, sizes[head])
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(MODEL, embed_model=embed_model, n=len(rows),
                        **{f"W_{h}": w for h, w in weights.items()},
                        **{f"opts_{h}": np.array([str(o) for o in opts]) for h, (_, opts) in HEADS.items()})
    return {"piezas": len(rows), **sizes}


def main() -> None:
    from . import classify, pipeline

    pipeline.load_dotenv()
    ap = argparse.ArgumentParser(prog="radar.entrenar", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etiquetar", type=int, default=0, help="cuántas piezas nuevas pedir al modelo grande")
    ap.add_argument("--piezas", type=Path, default=None, help="archivo piezas-*.jsonl (por defecto, el más reciente)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.etiquetar:
        pieces = args.piezas or max(Path("out").glob("piezas-*.jsonl"))
        log.info("Etiquetando %d piezas de %s con %s…", args.etiquetar, pieces, TEACHER)
        log.info("Se agregaron %d piezas a %s", label(pieces, args.etiquetar), LABELS)
    if not LABELS.exists():
        ap.error(f"no hay etiquetas en {LABELS}; usa --etiquetar")
    log.info("Entrenado: %s → %s", train(classify.local_embedder(), classify.LOCAL_MODEL), MODEL)


if __name__ == "__main__":
    main()
