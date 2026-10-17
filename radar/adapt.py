"""Recomendación de adaptación: "¿cómo lo convertimos en contenido para nuestra audiencia?".

Jev decide y clasifica, pero no genera texto. Para redactar el ángulo y los ganchos se usa
Claude (si hay ANTHROPIC_API_KEY o un perfil de `ant auth login`), con las señales que ya
calculamos como evidencia. Sin Claude, se arma una recomendación con plantillas.
"""

from __future__ import annotations

import json
import logging
import os

from . import config

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
            "ganchos_con_mejor_rendimiento": w["hooks"][:3],
            "formatos_con_mejor_rendimiento": w["formats"][:3],
            "mejores_franjas": w["timing"][:2],
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
- formatos: una recomendación de formato por plataforma.
- cuidado: un riesgo o matiz a evitar (humo, tecnicismo, tendencia ya saturada, etc.).
Sé específico; evita generalidades que servirían para cualquier tema."""


def _with_claude(topics: list[dict]) -> dict[str, dict]:
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(_evidence(topics), ensure_ascii=False)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declinó la solicitud")
    text = next(b.text for b in response.content if b.type == "text")
    return {t["topic_id"]: t for t in json.loads(text)["temas"]}


def _with_templates(topics: list[dict]) -> dict[str, dict]:
    out = {}
    for t in topics:
        w = t["why"]
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


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _valid(item: dict) -> bool:
    required = {"topic_id", "por_que_funciona", "angulo", "ganchos", "formatos", "cuidado"}
    return (required <= item.keys() and isinstance(item["ganchos"], list)
            and isinstance(item["formatos"], dict))


def _with_zen(topics: list[dict]) -> dict[str, dict]:
    """Redacción con un modelo de OpenCode Zen (API compatible con OpenAI)."""
    import httpx

    body = {
        "model": ZEN_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM + "\n" + ZEN_FORMAT},
            {"role": "user", "content": json.dumps(_evidence(topics), ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {os.environ['OPENCODE_API_KEY']}"}
    with httpx.Client(timeout=180) as client:
        r = client.post(ZEN_URL, json=body, headers=headers)
        if r.status_code == 400:  # no todos los modelos aceptan response_format
            body.pop("response_format")
            r = client.post(ZEN_URL, json=body, headers=headers)
        r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    items = [t for t in _parse_json(content).get("temas", []) if isinstance(t, dict) and _valid(t)]
    out = {t["topic_id"]: t for t in items}
    # Si el modelo omitió algún tema o devolvió uno incompleto, ese tema usa plantilla.
    missing = [t for t in topics if t["id"] not in out]
    if len(missing) == len(topics):
        raise RuntimeError("la respuesta no trajo temas válidos")
    if missing:
        log.warning("Zen omitió %d temas; se completan con plantillas.", len(missing))
        out.update(_with_templates(missing))
    return out


def has_claude_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.path.isdir(os.path.expanduser("~/.config/anthropic")))


def adapt(topics: list[dict], use_llm: bool) -> tuple[dict[str, dict], str]:
    """Redacta con Claude si hay credenciales, si no con Zen, y si no con plantillas."""
    if use_llm and has_claude_credentials():
        try:
            return _with_claude(topics), f"claude ({CLAUDE_MODEL})"
        except Exception as e:
            log.warning("No se pudo usar Claude (%s).", e)
    if use_llm and os.environ.get("OPENCODE_API_KEY"):
        try:
            return _with_zen(topics), f"opencode zen ({ZEN_MODEL})"
        except Exception as e:
            log.warning("No se pudo usar OpenCode Zen (%s).", e)
    return _with_templates(topics), "plantillas"
