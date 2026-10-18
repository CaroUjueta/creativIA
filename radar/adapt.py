"""Recomendación de adaptación: "¿cómo lo convertimos en contenido para nuestra audiencia?".

El clasificador no genera texto. Para redactar el ángulo y los ganchos se usa un modelo de pesos
abiertos vía OpenRouter, con las señales que ya calculamos como evidencia. Alternativas: Claude,
OpenCode Zen y, sin ninguno, plantillas. Si hay ficha de cuenta (radar.account), cada tema trae
además una pieza concreta para esa cuenta de Instagram (`para_cuenta`).
"""

from __future__ import annotations

import json
import logging
import os

from . import analysis, config

log = logging.getLogger(__name__)

CLAUDE_MODEL = os.environ.get("RADAR_CLAUDE_MODEL", "claude-opus-5-5")

HOOK_TEMPLATES = {
    "pregunta": "¿Tu equipo ya está {accion}? La mayoría de empresas en LatAm todavía no.",
    "dato_sorprendente": "Un dato que cambia la conversación sobre {tema} (y qué significa para tu empresa).",
    "noticia_urgente": "Lo que acaba de pasar con {tema} y por qué tu equipo debería enterarse hoy.",
    "contraintuitivo": "Todos hablan de {tema}. Casi todos lo están entendiendo al revés.",
    "lista_o_guia": "3 formas concretas de aplicar {tema} en tu equipo esta semana.",
    "historia_personal": "Probamos {tema} con un equipo real. Esto fue lo que pasó.",
    "advertencia": "El error que vemos en líderes de LatAm cuando adoptan {tema}.",
    "opinion": "Mi lectura sobre {tema}, sin humo y pensando en equipos de LatAm.",
    "sin_gancho": "{tema}, explicado para líderes en 60 segundos.",
}

FORMAT_BY_PLATFORM = {
    "tutorial_paso_a_paso": {"linkedin": "carrusel paso a paso", "instagram": "carrusel de 6–8 láminas", "tiktok": "video tutorial de pantalla <60 s", "youtube": "short con demo"},
    "noticia_y_analisis": {"linkedin": "post de análisis con 3 implicaciones", "instagram": "reel 'qué pasó y qué significa'", "tiktok": "video a cámara 'esto acaba de pasar'", "youtube": "short de contexto"},
    "opinion_o_ensayo": {"linkedin": "post de opinión con postura clara", "instagram": "reel a cámara", "tiktok": "video a cámara con hot take", "youtube": "video corto de reflexión"},
    "lista_de_recursos": {"linkedin": "carrusel de herramientas", "instagram": "carrusel guardable", "tiktok": "video 'X herramientas que…'", "youtube": "short de lista"},
    "caso_de_estudio": {"linkedin": "post caso real con antes/después", "instagram": "carrusel de caso", "tiktok": "storytelling a cámara", "youtube": "video de caso 5–8 min"},
    "demo_o_prueba": {"linkedin": "video nativo con demo", "instagram": "reel de demo", "tiktok": "demo en pantalla", "youtube": "short de demo"},
    "humor_o_meme": {"linkedin": "post ligero con aprendizaje", "instagram": "meme + carrusel", "tiktok": "sketch corto", "youtube": "short"},
    "pregunta_o_debate": {"linkedin": "encuesta + post de debate", "instagram": "historia con encuesta", "tiktok": "pregunta a cámara", "youtube": "post de comunidad"},
}


def _strong(rows: list[dict], n: int = 3) -> list[dict]:
    return [r for r in rows if r["n"] >= analysis.MIN_SIGNAL][:n]


def _evidence(topics: list[dict]) -> list[dict]:
    out = []
    for t in topics:
        w = t["why"]
        out.append({
            "topic_id": t["id"],
            "tema": t["label"],
            "etapa": t["stage"],
            "crecimiento_vs_base": round(t["growth"], 2),
            "encaje_audiencia_0a1": round(t["audience_fit"], 2),
            "accionable_0a1": round(t["practical"], 2),
            "tecnico_0a1": round(t["technical"], 2),
            # Descripciones y no ids internos, para que el modelo no copie "opinion_o_ensayo" al texto.
            # Solo patrones con suficientes piezas: con 2 o 3 posts, un "295×" es ruido, no evidencia.
            "ganchos_con_mejor_rendimiento": [{**h, "value": config.HOOKS.get(h["value"], h["value"])} for h in _strong(w["hooks"])],
            "formatos_con_mejor_rendimiento": [{**f, "value": config.FORMATS.get(f["value"], f["value"])} for f in _strong(w["formats"])],
            "mejores_franjas": _strong(w["timing"], 2),
            "idiomas": w["lang_share"],
            "ejemplos": [{"plataforma": p.platform, "texto": p.text[:300]} for p in t["examples"][:3]],
        })
    return out


SCHEMA = {
    "type": "object",
    "properties": {
        "temas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic_id": {"type": "string"},
                    "por_que_funciona": {"type": "string"},
                    "angulo": {"type": "string"},
                    "ganchos": {"type": "array", "items": {"type": "string"}},
                    "formatos": {
                        "type": "object",
                        "properties": {k: {"type": "string"} for k in ("linkedin", "instagram", "tiktok", "youtube")},
                        "required": ["linkedin", "instagram", "tiktok", "youtube"],
                        "additionalProperties": False,
                    },
                    "cuidado": {"type": "string"},
                    "para_cuenta": {
                        "type": "object",
                        "properties": {"pilar": {"type": "string"}, "formato": {"type": "string"},
                                       "estructura": {"type": "array", "items": {"type": "string"}},
                                       "caption": {"type": "string"}, "cta": {"type": "string"}},
                        "required": ["pilar", "formato", "estructura", "caption", "cta"],
                        "additionalProperties": False,
                    },
                },
                "required": ["topic_id", "por_que_funciona", "angulo", "ganchos", "formatos", "cuidado"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["temas"],
    "additionalProperties": False,
}

SYSTEM = f"""Eres estratega editorial de 30X, que produce contenido sobre IA para esta audiencia:
{config.AUDIENCE}

Recibes temas de IA que están creciendo en redes, con señales medidas (crecimiento, encaje con la
audiencia, ganchos y formatos que mejor rinden, ejemplos públicos). Para cada tema escribe, en
español neutro latinoamericano:
- por_que_funciona: 2–3 frases que expliquen por qué está funcionando, citando las señales (gancho,
  formato, momento, tipo de publicador). Trátalo como hipótesis, no como certeza.
- angulo: el ángulo concreto que 30X debería tomar para ejecutivos y equipos de LatAm (no copiar el
  original; aportar contexto regional, aplicación práctica y criterio).
- ganchos: 3 primeras líneas distintas listas para usar.
- formatos: una recomendación de formato por plataforma, en una frase corta (máximo 15 palabras).
- cuidado: un riesgo o matiz a evitar (humo, tecnicismo, tendencia ya saturada, etc.).
Sé específico; evita generalidades que servirían para cualquier tema.
No inventes cifras, porcentajes, estudios, empresas ni citas: usa solo los datos que recibes. Si un
gancho necesita un dato que no tienes, escribe [dato por verificar] en su lugar.
Escribe todo en español (carrusel, no carousel) y nunca copies identificadores internos con guiones bajos."""

ACCOUNT_RULES = """
Además, para cada tema escribe para_cuenta: la pieza concreta para la cuenta descrita abajo.
- pilar: el pilar de contenido de la cuenta al que pertenece (o "fuera de los pilares" si no encaja).
- formato: reel, carrusel o historia, preferiendo los formatos que le funcionan a la cuenta, con el detalle
  (por ejemplo "carrusel de 7 láminas" o "reel a cámara de 40 s").
- estructura: 4–7 pasos (láminas del carrusel o momentos del reel), cada uno en una frase.
- caption: el texto del post, 2–4 frases en el tono de la cuenta, sin hashtags inventados de marca.
- cta: el llamado a la acción, coherente con el que usa la cuenta.
"""


def system_prompt(account_ctx: str = "") -> str:
    return SYSTEM + (ACCOUNT_RULES + "\n" + account_ctx if account_ctx else "")


def _with_claude(topics: list[dict], system: str) -> dict[str, dict]:
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _schema(system)}},
        system=system,
        messages=[{"role": "user", "content": json.dumps(_evidence(topics), ensure_ascii=False)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declinó la solicitud")
    text = next(b.text for b in response.content if b.type == "text")
    return {t["topic_id"]: t for t in json.loads(text)["temas"]}


def _schema(system: str) -> dict:
    """Con cuenta, `para_cuenta` es obligatorio; sin cuenta no se pide."""
    item = SCHEMA["properties"]["temas"]["items"]
    if ACCOUNT_RULES in system:
        return {**SCHEMA, "properties": {"temas": {**SCHEMA["properties"]["temas"],
                "items": {**item, "required": item["required"] + ["para_cuenta"]}}}}
    props = {k: v for k, v in item["properties"].items() if k != "para_cuenta"}
    return {**SCHEMA, "properties": {"temas": {**SCHEMA["properties"]["temas"], "items": {**item, "properties": props}}}}


def _for_account(t: dict, hook_line: str, fmt: str, account: dict) -> dict:
    """Pieza para la cuenta sin modelo: formato que mejor le funciona y estructura fija."""
    profile, perf = account.get("profile") or {}, account.get("performance") or {}
    allowed = profile.get("formatos") or ["reel", "carrusel"]
    best = next((r["value"] for r in perf.get("by_type", []) if r["value"] in allowed), None)
    kind = best or ("carrusel" if "carrusel" in allowed and fmt in ("tutorial_paso_a_paso", "lista_de_recursos", "caso_de_estudio") else allowed[0])
    short = t["label"].split(":")[0].lower()
    words = set(f"{t['label']} {t.get('description', '')}".lower().split())
    pilar = max(profile.get("pilares") or ["fuera de los pilares"], key=lambda p: len(words & set(p.lower().split())))
    steps = {"carrusel": [f"Portada: {hook_line}", f"Qué está pasando con {short}, en una frase",
                          "Por qué le importa a un líder en LatAm", "3 acciones para esta semana", "El error más común",
                          "Cierre con una pregunta para los comentarios"],
             "reel": [f"0–3 s: {hook_line}", f"Contexto de {short} en una frase", "Un ejemplo concreto de una empresa en LatAm [dato por verificar]",
                      "Qué hacer esta semana", "Llamado a la acción"]}
    return {"pilar": pilar, "formato": {"carrusel": "carrusel de 6 láminas", "reel": "reel a cámara de 30–45 s"}.get(kind, kind),
            "estructura": steps.get(kind, steps["reel"]),
            "caption": f"{hook_line} Te contamos qué está cambiando con {short} y qué puedes aplicar en tu equipo desde esta semana.",
            "cta": profile.get("cta") or "Guarda este post y compártelo con tu equipo."}


def _with_templates(topics: list[dict], account: dict | None = None) -> dict[str, dict]:
    out = {}
    for t in topics:
        w = {k: (_strong(v, 99) if k in ("hooks", "formats", "timing") else v) for k, v in t["why"].items()}
        hook = w["hooks"][0]["value"] if w["hooks"] else "lista_o_guia"
        fmt = w["formats"][0]["value"] if w["formats"] else "tutorial_paso_a_paso"
        short = t["label"].split(":")[0].split("(")[0].strip().lower()
        reasons = []
        # Solo se menciona una señal si rinde claramente por encima de la mediana del tema.
        if w["hooks"] and w["hooks"][0]["lift"] >= 1.2:
            reasons.append(f"las piezas cuyo gancho es «{config.HOOKS[hook].lower()}» rinden {w['hooks'][0]['lift']}× la mediana del tema")
        if w["formats"] and w["formats"][0]["lift"] >= 1.2:
            reasons.append(f"el formato «{config.FORMATS[fmt].lower()}» rinde {w['formats'][0]['lift']}× la mediana")
        if w["timing"] and w["timing"][0]["lift"] >= 1.2:
            reasons.append(f"la franja con mejor respuesta es {w['timing'][0]['value']} (hora de Bogotá)")
        if t["stage"] in ("naciente", "en_crecimiento"):
            reasons.insert(0, f"su participación creció {(t['growth'] - 1) * 100:.0f}% frente a la línea base")
        es = w["lang_share"].get("es", 0)
        if es < 0.3:
            reasons.append("casi toda la conversación está en inglés: hay espacio para llegar primero en español")
        out[t["id"]] = {
            "topic_id": t["id"],
            "por_que_funciona": ("Hipótesis: " + "; ".join(reasons) + ".") if reasons else "Pocas piezas con interacción medible; revisar ejemplos manualmente.",
            "angulo": f"Bajar «{short}» a decisiones concretas para líderes de equipos en LatAm: qué cambia, qué probar esta semana y qué ignorar.",
            # El gancho que mejor rinde va primero; se completa con otros dos distintos.
            "ganchos": [HOOK_TEMPLATES[h].format(tema=short, accion=f"aprovechando {short}")
                        for h in dict.fromkeys([hook, "lista_o_guia", "advertencia", "contraintuitivo"])][:3],
            "formatos": FORMAT_BY_PLATFORM.get(fmt, FORMAT_BY_PLATFORM["tutorial_paso_a_paso"]),
            "cuidado": ("Tema muy técnico: traducir a impacto de negocio." if t["technical"] > 0.5 else
                        "Tema saturado: diferenciarse con un caso regional." if t["stage"] == "saturado" else
                        "Verificar los datos antes de publicar; la señal viene de una muestra."),
        }
        if account and account.get("profile"):
            out[t["id"]]["para_cuenta"] = _for_account(t, out[t["id"]]["ganchos"][0], fmt, account)
    return out


ZEN_URL = "https://opencode.ai/inference/openai/v1/chat/completions"
# Los modelos "-free" de Zen solo funcionan dentro de la app OpenCode (la API responde
# FreeTierError), así que aquí se usa uno de pago barato: US$0,15 / 0,50 por millón de tokens
# de entrada / salida, menos de un centavo por reporte. Lista y precios: https://opencode.ai/docs/zen/
ZEN_MODEL = os.environ.get("RADAR_ZEN_MODEL", "glm-5.3-flash")

ZEN_FORMAT = """
Responde SOLO con un objeto JSON, sin texto adicional ni bloques de código, con esta forma:
{"temas": [{"topic_id": "...", "por_que_funciona": "...", "angulo": "...",
  "ganchos": ["...", "...", "..."],
  "formatos": {"linkedin": "...", "instagram": "...", "tiktok": "...", "youtube": "..."},
  "cuidado": "..."}]}
Incluye un elemento por cada tema recibido, con el mismo topic_id."""
ZEN_ACCOUNT = """
Si se pide para_cuenta, agrégalo a cada tema así:
  "para_cuenta": {"pilar": "...", "formato": "...", "estructura": ["...", "..."], "caption": "...", "cta": "..."}"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _valid(item: dict, with_account: bool = False) -> bool:
    required = {"topic_id", "por_que_funciona", "angulo", "ganchos", "formatos", "cuidado"}
    ok = (required <= item.keys() and isinstance(item["ganchos"], list)
          and isinstance(item["formatos"], dict))
    if ok and with_account:
        pc = item.get("para_cuenta")
        ok = isinstance(pc, dict) and {"pilar", "formato", "estructura", "caption", "cta"} <= pc.keys() and isinstance(pc["estructura"], list)
    return ok


def _with_chat(topics: list[dict], url: str, api_key: str, model: str, name: str, extra: dict | None = None,
               system: str = SYSTEM, account: dict | None = None) -> dict[str, dict]:
    """Redacción con un modelo vía una API compatible con OpenAI (OpenRouter u OpenCode Zen)."""
    import httpx

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system + "\n" + ZEN_FORMAT + (ZEN_ACCOUNT if account else "")},
            {"role": "user", "content": json.dumps(_evidence(topics), ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        **(extra or {}),
    }
    headers = {"Authorization": f"Bearer {api_key}", "X-Title": "Radar de contenido IA"}
    with httpx.Client(timeout=300) as client:
        r = client.post(url, json=body, headers=headers)
        if r.status_code == 400:  # no todos los modelos aceptan response_format
            body.pop("response_format")
            r = client.post(url, json=body, headers=headers)
        r.raise_for_status()
    content = r.json()["choices"][0]["message"].get("content")
    if not content:
        raise RuntimeError("respuesta vacía")
    items = [t for t in _parse_json(content).get("temas", []) if isinstance(t, dict) and _valid(t, bool(account))]
    out = {t["topic_id"]: t for t in items}
    # Si el modelo omitió algún tema o devolvió uno incompleto, ese tema usa plantilla.
    missing = [t for t in topics if t["id"] not in out]
    if len(missing) == len(topics):
        raise RuntimeError("la respuesta no trajo temas válidos")
    if missing:
        log.warning("%s omitió %d temas; se completan con plantillas.", name, len(missing))
        out.update(_with_templates(missing, account))
    return out


def _with_zen(topics: list[dict], system: str, account: dict | None) -> dict[str, dict]:
    return _with_chat(topics, ZEN_URL, os.environ["OPENCODE_API_KEY"], ZEN_MODEL, "Zen", system=system, account=account)


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Modelos de pesos abiertos, en orden. Primero Nemotron 3 Super de NVIDIA, gratis (con límite de uso
# diario), para que el saldo se use solo en Jev. Si está saturado, DeepSeek V4.1 Flash: US$0,055 / 0,144
# por millón de tokens de entrada / salida, menos de un centavo por reporte. Lista: https://openrouter.ai/models
OPENROUTER_MODELS = [m.strip() for m in os.environ.get(
    "RADAR_WRITER_MODELS", "nvidia/nemotron-3-super-120b-a12b:free,deepseek/deepseek-v4.1-flash").split(",") if m.strip()]


BATCH = 5  # temas por llamada: con muchos, el modelo gratuito se queda sin tokens y responde vacío


def _with_openrouter(topics: list[dict], system: str, account: dict | None) -> tuple[dict[str, dict], str]:
    """Redacta por lotes; un lote que ningún modelo logra redactar queda con plantillas."""
    out, used = {}, []
    for i in range(0, len(topics), BATCH):
        part = topics[i:i + BATCH]
        try:
            items, model = _openrouter_batch(part, system, account)
            used.append(model)
        except RuntimeError as e:
            log.warning("Lote %d sin redactar (%s); se usan plantillas.", i // BATCH + 1, e)
            items = _with_templates(part, account)
        out.update(items)
    if not used:
        raise RuntimeError(f"ningún modelo respondió ({', '.join(OPENROUTER_MODELS)})")
    return out, ", ".join(dict.fromkeys(used))


def _openrouter_batch(topics: list[dict], system: str, account: dict | None) -> tuple[dict[str, dict], str]:
    errors = []
    for model in OPENROUTER_MODELS:
        try:
            # Esfuerzo de razonamiento bajo: es redacción, no un problema difícil, y así responde rápido.
            out = _with_chat(topics, OPENROUTER_URL, os.environ["OPENROUTER_API_KEY"], model, model,
                             {"reasoning": {"effort": "low"}, "max_tokens": 16000}, system, account)
            return out, model
        except Exception as e:
            log.warning("OpenRouter no pudo redactar con %s (%s).", model, str(e)[:160])
            errors.append(model)
    raise RuntimeError(f"ningún modelo respondió ({', '.join(errors)})")


def has_claude_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.path.isdir(os.path.expanduser("~/.config/anthropic")))


def adapt(topics: list[dict], use_llm: bool, account: dict | None = None) -> tuple[dict[str, dict], str]:
    """Redacta con un modelo open source vía OpenRouter; si no, Claude, Zen o plantillas.

    `account` = {"profile": ficha, "performance": lo que le funciona, "context": texto para el modelo}.
    """
    account = account if account and account.get("profile") else None
    system = system_prompt(account["context"] if account else "")
    if use_llm and os.environ.get("OPENROUTER_API_KEY"):
        try:
            out, model = _with_openrouter(topics, system, account)
            return out, f"openrouter ({model})"
        except Exception as e:
            log.warning("No se pudo redactar con OpenRouter (%s).", e)
    if use_llm and has_claude_credentials():
        try:
            return _with_claude(topics, system), f"claude ({CLAUDE_MODEL})"
        except Exception as e:
            log.warning("No se pudo usar Claude (%s).", e)
    if use_llm and os.environ.get("OPENCODE_API_KEY"):
        try:
            return _with_zen(topics, system, account), f"opencode zen ({ZEN_MODEL})"
        except Exception as e:
            log.warning("No se pudo usar OpenCode Zen (%s).", e)
    return _with_templates(topics, account), "plantillas"
