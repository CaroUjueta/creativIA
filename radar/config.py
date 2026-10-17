"""Configuración editable del radar: audiencia, taxonomía de temas, fuentes y pesos.

Todo lo que el equipo de contenido querría ajustar sin tocar la lógica vive aquí.
"""

AUDIENCE = (
    "Ejecutivos, líderes y equipos de empresas en Latinoamérica que están aprendiendo "
    "a usar inteligencia artificial en su trabajo. No son ingenieros de machine learning: "
    "buscan entender qué cambia en su negocio, cómo adoptar IA en sus equipos y qué "
    "herramientas usar, con ejemplos prácticos y en español."
)

# Taxonomía cerrada de temas de IA. Jev elige uno por pieza (Choice).
# La clave es el id; el valor es la descripción que ve el modelo y el título del reporte.
TOPICS: dict[str, str] = {
    "agentes_ia": "Agentes de IA que ejecutan tareas de forma autónoma (agentic AI, automatización de flujos con agentes)",
    "productividad_personal": "Usar IA para ser más productivo en el trabajo diario (correos, reuniones, documentos, prompts)",
    "adopcion_empresarial": "Cómo las empresas adoptan IA: estrategia, casos de uso, ROI, transformación de procesos",
    "liderazgo_y_equipos": "Liderazgo, gestión de equipos y cultura organizacional frente a la IA",
    "futuro_del_trabajo": "Empleo, habilidades, reemplazo o aumento de trabajos, upskilling y reskilling por la IA",
    "nuevos_modelos": "Lanzamientos y comparaciones de modelos de IA (GPT, Claude, Gemini, Llama, DeepSeek, etc.)",
    "herramientas_no_code": "Herramientas de IA sin código o de bajo código para crear apps, automatizaciones o contenido",
    "programacion_con_ia": "Programar con IA: asistentes de código, vibe coding, desarrollo de software con IA",
    "contenido_y_marketing": "IA para marketing, ventas, creación de contenido, imagen y video generativo",
    "regulacion_y_etica": "Regulación, ética, sesgos, privacidad, derechos de autor y gobernanza de la IA",
    "seguridad_y_riesgos": "Riesgos de la IA: desinformación, deepfakes, ciberseguridad, alucinaciones",
    "educacion_ia": "Educación y aprendizaje de IA: cursos, alfabetización en IA, IA en escuelas y universidades",
    "inversion_y_mercado": "Mercado, inversión, valuaciones, burbuja de la IA, resultados de empresas tecnológicas",
    "infraestructura_y_chips": "Chips, centros de datos, energía, cómputo y costos de infraestructura de IA",
    "ia_en_latam": "IA en Latinoamérica: ecosistema, startups, políticas públicas y casos de la región",
    "investigacion_ia": "Avances científicos e investigación en IA (papers, AGI, razonamiento, benchmarks)",
    "ia_y_sociedad": "Impacto social y cultural de la IA, opinión pública, debates generales",
    "otro_ia": "Otro tema relacionado con IA que no encaja en las categorías anteriores",
}

TOPIC_NAMES: dict[str, str] = {
    "agentes_ia": "Agentes de IA",
    "productividad_personal": "IA para la productividad personal",
    "adopcion_empresarial": "Adopción de IA en empresas",
    "liderazgo_y_equipos": "Liderazgo y equipos frente a la IA",
    "futuro_del_trabajo": "Futuro del trabajo y habilidades",
    "nuevos_modelos": "Nuevos modelos de IA",
    "herramientas_no_code": "Herramientas no-code con IA",
    "programacion_con_ia": "Programar con IA",
    "contenido_y_marketing": "IA para marketing y contenido",
    "regulacion_y_etica": "Regulación y ética de la IA",
    "seguridad_y_riesgos": "Riesgos y seguridad de la IA",
    "educacion_ia": "Educación y alfabetización en IA",
    "inversion_y_mercado": "Mercado e inversión en IA",
    "infraestructura_y_chips": "Chips, energía e infraestructura",
    "ia_en_latam": "IA en Latinoamérica",
    "investigacion_ia": "Investigación y avances científicos",
    "ia_y_sociedad": "IA y sociedad",
    "otro_ia": "Otros temas de IA",
}

HOOKS: dict[str, str] = {
    "pregunta": "Abre con una pregunta al lector",
    "dato_sorprendente": "Abre con un dato, cifra o estadística sorprendente",
    "noticia_urgente": "Abre con una noticia o anuncio reciente ('acaba de salir', 'última hora')",
    "contraintuitivo": "Abre con una afirmación polémica o contraintuitiva que rompe una creencia",
    "lista_o_guia": "Promete una lista, guía, pasos o recursos ('5 herramientas', 'cómo hacer')",
    "historia_personal": "Abre con una historia o experiencia personal",
    "advertencia": "Abre con una advertencia, error común o miedo ('deja de hacer esto')",
    "opinion": "Abre directamente con una opinión o reflexión del autor",
    "sin_gancho": "No tiene un gancho claro; empieza de forma plana o descriptiva",
}

FORMATS: dict[str, str] = {
    "tutorial_paso_a_paso": "Tutorial o explicación paso a paso de cómo hacer algo",
    "noticia_y_analisis": "Noticia con análisis o contexto",
    "opinion_o_ensayo": "Opinión, ensayo o reflexión",
    "lista_de_recursos": "Lista de herramientas, prompts o recursos",
    "caso_de_estudio": "Caso de estudio o ejemplo real de una empresa o persona",
    "demo_o_prueba": "Demostración o prueba de una herramienta o modelo",
    "humor_o_meme": "Humor, meme o sátira",
    "pregunta_o_debate": "Pregunta abierta o invitación al debate",
}

PUBLISHERS: dict[str, str] = {
    "medio_de_comunicacion": "Un medio de comunicación o periodista publicando una noticia",
    "empresa_o_marca": "Una empresa, marca o producto hablando de sí mismo",
    "experto_o_creador": "Un experto, consultor o creador de contenido especializado compartiendo conocimiento",
    "persona_comun": "Una persona común compartiendo su experiencia u opinión",
    "investigador_o_academico": "Un investigador o académico",
}

# Consultas por fuente. Se combinan español e inglés: las tendencias de IA suelen nacer
# en inglés y llegar después a LatAm, y esa diferencia de tiempo es parte de la señal.
BLUESKY_QUERIES: list[dict] = [
    {"q": "inteligencia artificial", "lang": "es"},
    {"q": "IA", "lang": "es"},
    {"q": "AI agents", "lang": "en"},
    {"q": "AI", "lang": "en"},
]

HN_QUERIES: list[str] = ["AI", "LLM", "agents", "OpenAI", "Claude", "Gemini"]

GOOGLE_NEWS_QUERIES: list[dict] = [
    {"q": "inteligencia artificial empresas", "hl": "es-419", "gl": "CO", "ceid": "CO:es-419"},
    {"q": "inteligencia artificial", "hl": "es-419", "gl": "MX", "ceid": "MX:es-419"},
    {"q": "artificial intelligence business", "hl": "en-US", "gl": "US", "ceid": "US:en"},
]

# Canales de YouTube de referencia (feed RSS público oficial). Añadir los que el equipo siga.
YOUTUBE_CHANNELS: dict[str, str] = {
    "UCbfYPyITQ-7l4upoX8nvctg": "Two Minute Papers",
    "UCNJ1Ymd5yFuUPtn21xtRbbw": "AI Explained",
    "UCawZsQWqfGSbCI5yjkdVkTA": "Matthew Berman",
    "UChpleBmo18P08aKCIgti38g": "Matt Wolfe",
    "UCsBjURrPoezykLs9EqgamOA": "Fireship",
    "UCrDwWp7EBBv4NwvScIpBDOA": "Anthropic",
    "UCXZCJLdBC09xxGZ6gcdrc6A": "OpenAI",
    "UCP7jMXSY2xbc3KCAE0MHQ-A": "Google DeepMind",
    "UCy5znSnfMsDwaLlROnZ7Qbg": "Dot CSV",
    "UC55-mxUj5Nj3niXFReG44OQ": "Platzi",
}

# Pesos del puntaje final por tema (se combinan en código, no en el modelo).
WEIGHTS = {
    "momentum": 0.40,       # crecimiento de la participación del tema vs. la línea base
    "audience_fit": 0.35,   # qué tan útil es para la audiencia objetivo (Jev Score)
    "engagement": 0.15,     # interacción mediana de las piezas del tema
    "practicality": 0.10,   # qué tan accionable es (Jev Noul)
}

# Bonificación por etapa: preferimos llegar temprano a una tendencia.
STAGE_BONUS = {"naciente": 0.10, "en_crecimiento": 0.05, "saturado": -0.05, "en_declive": -0.10, "estable": 0.0}

TIMEZONE = "America/Bogota"
