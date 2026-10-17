"""Clasificación de cada pieza con Jev (TypeSafe).

Una sola llamada por pieza hace todas las preguntas en paralelo (patrón "fan-out"):
tema, gancho, formato, tipo de publicador, encaje con la audiencia y varias preguntas sí/no.
Jev devuelve probabilidades calibradas, así que el tema se guarda como distribución completa
y la tendencia se calcula con conteos "suaves" (suma de probabilidades), no con la etiqueta ganadora.

Toda la aritmética (conteos, crecimiento, pesos) se hace en código, como recomienda TypeSafe.
Sin TYPESAFE_API_KEY se usa un clasificador por palabras clave, mucho menos preciso, marcado
como "heuristico" en el reporte.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

from . import config
from .models import Post

log = logging.getLogger(__name__)

JEV_MODEL = os.environ.get("RADAR_JEV_MODEL", "jev-latest")
CACHE = Path(os.environ.get("RADAR_CACHE", "data/cache/labels.jsonl"))

AUDIENCE_LEVELS = [
    "Irrelevant for this audience",
    "Tangential: interesting, but with no application to their work or decisions",
    "Relevant: helps them understand a change that affects their business or team",
    "Highly relevant: they could apply it right away in their work or decisions",
]


def _questions():
    from typesafe_sdk import Choice, Noul, Score

    return {
        "is_ai": Noul(
            instructions="Is the main subject of `text` artificial intelligence (AI, IA, machine learning, LLMs, chatbots, AI products or AI companies)?",
        ),
        "topic": Choice(
            instructions="Which topic best describes what `text` is mainly about?",
            criteria=config.TOPICS,
        ),
        "hook": Choice(
            instructions="How does the first sentence of `text` try to capture attention?",
            criteria=config.HOOKS,
        ),
        "format": Choice(
            instructions="What content format is `text`?",
            criteria=config.FORMATS,
        ),
        "publisher": Choice(
            instructions="Judging only from the writing in `text`, what kind of publisher most likely wrote it?",
            criteria=config.PUBLISHERS,
        ),
        "audience_fit": Score(
            instructions={
                "audience": config.AUDIENCE,
                "question": "How useful is the subject of `text` for `audience`?",
            },
            criteria=AUDIENCE_LEVELS,
        ),
        "practical": Noul(
            instructions="Does `text` give a concrete, actionable takeaway that a business professional could apply?",
        ),
        "technical": Noul(
            instructions="Does understanding `text` require programming or machine learning expertise?",
        ),
        "hype": Noul(
            instructions="Is `text` clickbait or exaggerated hype with little substance?",
        ),
        "latam": Noul(
            instructions="Does `text` mention Latin America, a Latin American country, or Spanish-speaking audiences?",
        ),
    }


def _state(p: Post) -> dict:
    return {"platform": p.platform, "text": p.text[:2000]}


def _labels_from_response(r) -> dict:
    c, s, n = r.choices, r.scores, r.nouls
    return {
        "classifier": "jev",
        "is_ai": n["is_ai"].noul,
        "topic": c["topic"].choice,
        "topic_probs": dict(c["topic"].probabilities),
        "topic_confidence": c["topic"].confidence,
        "hook": c["hook"].choice,
        "hook_confidence": c["hook"].confidence,
        "format": c["format"].choice,
        "publisher": c["publisher"].choice,
        # El score va de 0 a 3; se normaliza a 0–1 para combinarlo con los demás factores.
        "audience_fit": s["audience_fit"].score / (len(AUDIENCE_LEVELS) - 1),
        "audience_confidence": s["audience_fit"].confidence,
        "practical": n["practical"].noul,
        "technical": n["technical"].noul,
        "hype": n["hype"].noul,
        "latam": n["latam"].noul,
    }


async def _classify_jev(posts: list[Post], concurrency: int) -> int:
    from typesafe_sdk import AsyncTypeSafeClient, TypeSafeAuthenticationError

    questions = _questions()
    sem = asyncio.Semaphore(concurrency)
    tokens = 0

    async with AsyncTypeSafeClient(model=JEV_MODEL) as client:
        async def one(p: Post):
            nonlocal tokens
            async with sem:
                try:
                    r = await client.system_one(_state(p), questions)
                except TypeSafeAuthenticationError as e:
                    raise InvalidKey from e
                except Exception as e:  # una pieza fallida no debe tumbar el reporte
                    log.warning("Jev falló en %s: %s", p.id, e)
                    return
            p.labels = _labels_from_response(r)
            tokens += r.usage.input_tokens if r.usage else 0

        tasks = [asyncio.create_task(one(p)) for p in posts]
        try:
            await asyncio.gather(*tasks)
        except InvalidKey:
            for t in tasks:
                t.cancel()
            raise
    return tokens


class InvalidKey(Exception):
    pass


def filter_terms(terms: list[dict], keep: int = 15) -> list[dict]:
    """Deja solo los términos emergentes que son un concepto concreto del mundo de la IA.

    Una sola llamada: el estado es la lista de términos y hay una pregunta sí/no por término.
    """
    from typesafe_sdk import Noul, TypeSafeClient

    if not terms:
        return terms
    words = [t["term"] for t in terms]
    with TypeSafeClient(model=JEV_MODEL) as client:
        r = client.system_one(
            {"terms": words},
            {f"t{i}": Noul(instructions=f"Is `terms[{i}]` the name of a specific AI product, model, company, "
                                         f"person, event or concept discussed in AI news?")
             for i in range(len(words))},
        )
    for i, t in enumerate(terms):
        t["ai_relevance"] = r.nouls[f"t{i}"].noul
    return [t for t in terms if t["ai_relevance"] >= 0.5][:keep]


# --- Respaldo heurístico -----------------------------------------------------------------

_KW = {
    "agentes_ia": r"\bagent(e|es|s|ic)?\b|agéntic|mcp\b|autonom",
    "productividad_personal": r"productiv|prompt|correo|email|reuni|meeting|copilot",
    "adopcion_empresarial": r"empresa|compan|enterprise|negocio|business|roi\b|adopci|adopt",
    "liderazgo_y_equipos": r"líder|lider|leader|equipo|team|ceo\b|cultura|manager",
    "futuro_del_trabajo": r"empleo|trabajo|jobs?\b|layoff|despido|habilidad|skill|reskill|upskill|workforce",
    "nuevos_modelos": r"gpt|claude|gemini|llama|deepseek|mistral|grok|qwen|modelo|model\b|release|lanz",
    "herramientas_no_code": r"no.?code|low.?code|zapier|make\.com|n8n|lovable|bolt|herramienta",
    "programacion_con_ia": r"code|cod(e|igo|ing)|program|developer|desarroll|vibe|cursor|github",
    "contenido_y_marketing": r"marketing|ventas|sales|contenido|content|video|imagen|image|sora|midjourney",
    "regulacion_y_etica": r"regula|ley\b|law\b|ética|ethic|sesgo|bias|copyright|derechos|privac|gobern",
    "seguridad_y_riesgos": r"deepfake|desinforma|misinfo|segur|secur|riesgo|risk|halluc|alucin|scam|fraud",
    "educacion_ia": r"educa|curso|course|escuela|school|universi|estudiant|student|aprend|learn",
    "inversion_y_mercado": r"inversi|invest|valuaci|valuation|burbuja|bubble|stock|acci[oó]n|bolsa|market|funding|ipo\b",
    "infraestructura_y_chips": r"chip|nvidia|gpu|data.?cent|centro de datos|energ|power|cómputo|compute",
    "ia_en_latam": r"latam|latinoam|méxico|mexico|colombia|argentin|chile|perú|peru|brasil|brazil",
    "investigacion_ia": r"paper|research|investigaci|benchmark|agi\b|reasoning|razonam|arxiv",
    "ia_y_sociedad": r"sociedad|society|cultur|arte|art\b|opini|human",
}
_AI = re.compile(r"\b(ia|ai|a\.i\.|inteligencia artificial|artificial intelligence|llms?|chatgpt|openai|anthropic|claude|gemini|copilot|machine learning|genai|agentes?|agents?)\b", re.I)


def _classify_heuristic(p: Post) -> dict:
    t = p.text.lower()
    hits = {k: len(re.findall(rx, t)) for k, rx in _KW.items()}
    total = sum(hits.values())
    probs = {k: (v / total if total else 0.0) for k, v in hits.items()}
    probs["otro_ia"] = 0.0 if total else 1.0
    topic = max(probs, key=probs.get)
    first = t.split(".")[0]
    hook = ("pregunta" if "?" in first else
            "lista_o_guia" if re.match(r"^\W*\d+\s", first) or re.search(r"c[oó]mo |how to", first) else
            "dato_sorprendente" if re.search(r"\d+\s?%|\$\s?\d|\d+ (mil|millones|billion|million)", first) else
            "noticia_urgente" if re.search(r"acaba de|just |breaking|última hora|anuncia|announce|launch|lanza", first) else
            "advertencia" if re.search(r"deja de|stop |cuidado|error|mistake|warning", first) else
            "opinion")
    business = bool(re.search(r"empresa|negocio|business|equipo|team|líder|leader|trabajo|work|product", t))
    return {
        "classifier": "heuristico",
        "is_ai": 1.0 if _AI.search(p.text) else 0.0,
        "topic": topic, "topic_probs": probs, "topic_confidence": max(probs.values()),
        "hook": hook, "hook_confidence": 0.0,
        "format": "tutorial_paso_a_paso" if re.search(r"c[oó]mo |how to|guía|guide|paso", t) else
                  "noticia_y_analisis" if p.platform in ("google_news", "hackernews") else "opinion_o_ensayo",
        "publisher": "medio_de_comunicacion" if p.platform == "google_news" else
                     "experto_o_creador" if p.platform == "youtube" else "persona_comun",
        "audience_fit": 0.67 if business else 0.33, "audience_confidence": 0.0,
        "practical": 0.6 if re.search(r"c[oó]mo |how to|tips|consejo|guía|guide|paso", t) else 0.2,
        "technical": 0.7 if p.platform == "hackernews" else 0.2,
        "hype": 0.5 if "!" in t else 0.2,
        "latam": 1.0 if re.search(_KW["ia_en_latam"], t) else 0.0,
    }


# --- Caché --------------------------------------------------------------------------------

def _load_cache() -> dict[str, dict]:
    if not CACHE.exists():
        return {}
    out = {}
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        out[row["id"]] = row["labels"]
    return out


def _append_cache(posts: list[Post]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as f:
        for p in posts:
            if p.labels.get("classifier") == "jev":
                f.write(json.dumps({"id": p.id, "labels": p.labels}, ensure_ascii=False) + "\n")


def classify(posts: list[Post], use_jev: bool, concurrency: int = 16) -> dict:
    """Etiqueta las piezas in situ. Devuelve estadísticas del proceso para el reporte."""
    stats = {"classifier": "jev" if use_jev else "heuristico", "cached": 0, "classified": 0, "input_tokens": 0}
    if not use_jev:
        for p in posts:
            p.labels = _classify_heuristic(p)
        stats["classified"] = len(posts)
        return stats

    cache = _load_cache()
    pending = []
    for p in posts:
        if p.id in cache:
            p.labels = cache[p.id]
            stats["cached"] += 1
        else:
            pending.append(p)
    if pending:
        log.info("Clasificando %d piezas con %s (%d en caché)…", len(pending), JEV_MODEL, stats["cached"])
        try:
            stats["input_tokens"] = asyncio.run(_classify_jev(pending, concurrency))
        except InvalidKey:
            raise SystemExit("TYPESAFE_API_KEY inválida: revisa la clave en https://console.typesafe.ai/keys")
        done = [p for p in pending if p.labels]
        _append_cache(done)
        stats["classified"] = len(done)
        failed = len(pending) - len(done)
        if failed:
            log.warning("%d piezas sin clasificar (se excluyen del análisis)", failed)
    return stats
