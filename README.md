# creativIA · Radar de contenido

> De "qué está de moda" a "qué debemos producir, por qué y para quién".

Prototipo desarrollado en el **Hackatón 30X** · Área **Media** · Reto: *Explorar una oportunidad*.

![Python](https://img.shields.io/badge/python-3.12+-blue) ![Estado](https://img.shields.io/badge/estado-prototipo-orange)

---

## Tabla de contenidos
1. [El problema](#el-problema)
2. [La solución](#la-solución)
3. [Pregunta que responde el prototipo](#pregunta-que-responde-el-prototipo)
4. [Cómo funciona](#cómo-funciona)
5. [Funcionalidades](#funcionalidades)
6. [Ejemplo de resultado](#ejemplo-de-resultado)
7. [Stack tecnológico](#stack-tecnológico)
8. [Instalación y uso](#instalación-y-uso)
9. [¿Acierta el radar? (backtest)](#acierta-el-radar-backtest)
10. [Datos, privacidad y términos de servicio](#datos-privacidad-y-términos-de-servicio)
11. [Alcance y limitaciones](#alcance-y-limitaciones)
12. [Próximos pasos](#próximos-pasos)

---

## El problema

30X produce contenido sobre IA para líderes y equipos en Latinoamérica. Para decidir qué producir, el equipo de media necesita identificar referentes y piezas que estén funcionando en LinkedIn, Instagram, TikTok y YouTube.

Hoy eso depende de servicios de scraping de pago que cuestan miles de dólares al año y que solo resuelven la mitad de la pregunta: entregan datos, pero no explican:

- **Por qué** una pieza funcionó.
- Si la tendencia **apenas empieza** o ya está saturada.
- Si **le sirve a la audiencia** concreta del equipo.

## La solución

**creativIA · Radar de contenido** recolecta piezas públicas sobre IA de fuentes abiertas, las clasifica con **Jev** (el modelo de decisiones de TypeSafe) y responde tres preguntas:

| Pregunta | Qué hace el prototipo |
|---|---|
| **¿Qué está despegando?** | Mide la participación de cada tema día a día contra una línea base y lo ubica en una etapa: *naciente*, *en crecimiento*, *saturado*, *en declive*. Además detecta **términos emergentes** que ninguna taxonomía anticipaba. |
| **¿Por qué funciona?** | Jev etiqueta el gancho, el formato y el tipo de publicador de cada pieza; el código compara la interacción de cada grupo contra la mediana del tema y la franja horaria. |
| **¿Encaja con nuestra audiencia?** | Jev puntúa cada pieza en una escala de 0 a 3 de utilidad para ejecutivos y equipos de LatAm, y responde si es accionable, técnica, puro humo o de la región. |

Por último, un modelo generativo redacta para cada tema el ángulo, tres ganchos y el formato recomendado por plataforma: Claude si hay clave de Anthropic, o un modelo de OpenCode Zen (`glm-5.3-flash`, menos de un centavo por reporte). Sin ninguno, el radar arma la recomendación con plantillas.

> Los modelos gratuitos de chat de Zen (`*-free`) solo funcionan dentro de la app OpenCode; desde un script la API responde `FreeTierError`. Por eso la redacción usa un modelo de pago barato. Jev sí está disponible gratis (`jev-1.13-free`) por tiempo limitado.

**Costo:** Jev cobra US$0,042 por millón de tokens de entrada. Una corrida de unas 3.000 piezas se estima en unos US$0,10 (por confirmar en la primera corrida con saldo: la app muestra el costo real de cada actualización), y las piezas ya clasificadas quedan en caché, así que cada semana solo se pagan las nuevas. Frente a los miles de dólares al año de un servicio de scraping, el costo de operación es de centavos por semana.

## Pregunta que responde el prototipo

> **"¿Cuáles son los 10 temas de IA que más están creciendo esta semana, por qué, y cómo los adaptamos para nuestra audiencia?"**

## Cómo funciona

```
Bluesky · Hacker News · YouTube (API o RSS) · Google News RSS · aportes de la comunidad
                                │  (muestra comparable por día)
                                ▼
                 Limpieza de datos personales (hash de autores)
                                ▼
     Jev: 1 llamada por pieza, 10 preguntas en paralelo (tema, gancho, formato,
          publicador, encaje con la audiencia, accionable, técnico, humo, LatAm…)
                                ▼
     Código: participación diaria por tema → crecimiento, aceleración y etapa
             interacción relativa → por qué funciona · términos emergentes
                                ▼
          Prioridad = momentum + encaje con la audiencia + interacción + accionable
                                ▼
           Claude (u plantillas): ángulo, ganchos y formato por plataforma
                                ▼
                    Reporte HTML · Markdown · JSON
```

1. **Recolección** (`radar/sources.py`): APIs públicas sin login. Cada día se toman las N piezas con más interacción por consulta, para comparar *participación* y no volumen bruto.
2. **Clasificación** (`radar/classify.py`): Jev responde preguntas tipadas (*Choice*, *Score*, *Noul*) con probabilidades calibradas. El tema se guarda como distribución completa y se cuenta de forma "suave" (suma de probabilidades).
3. **Detección de tendencias** (`radar/analysis.py`): participación del tema en la semana actual frente a la línea base, promediada entre plataformas para que el volumen de noticias no tape a las redes. *Naciente* = crece al menos un 50 % y aún tiene una participación pequeña; *saturado* = grande y plano.
4. **Por qué funciona:** interacción de cada pieza relativa a la mediana de su plataforma, agrupada por gancho, formato y franja horaria (hora de Bogotá). Solo se reporta una señal si rinde al menos 1,2× la mediana.
5. **Filtro de audiencia:** el puntaje de encaje de Jev pesa un 35 % en la prioridad; el humo penaliza y la etapa temprana suma.
6. **Salida** (`radar/report.py`): reporte HTML autocontenido (con modo oscuro y diseño para móvil), Markdown y JSON.

Toda la aritmética vive en código, como recomienda TypeSafe: el modelo solo toma decisiones semánticas acotadas.

## Funcionalidades

- ✅ Detección de temas emergentes (naciente / en crecimiento / saturado / en declive) con línea base
- ✅ Términos emergentes fuera de la taxonomía (filtrados por Jev cuando hay clave)
- ✅ Explicación del "por qué funcionó" por tema (gancho, formato, franja, publicador, idioma)
- ✅ Puntaje de relevancia para la audiencia objetivo
- ✅ Recomendación de adaptación (ángulo, 3 ganchos, formato por plataforma, cuidado)
- ✅ App web local: tablero con mapa de oportunidades, ranking, feed de publicaciones destacadas, historial y botón para actualizar
- ✅ Feed vertical estilo TikTok con las publicaciones que más rindieron frente a su plataforma: pestañas Para ti / Útiles / Recientes / Guardados, filtros por plataforma y tema, doble clic para guardar y botón para saltar a la adaptación del tema
- ✅ Reporte HTML / Markdown / JSON
- ✅ Botón **Aportar** en la app: el equipo agrega publicaciones públicas de LinkedIn, Instagram o TikTok (con limpieza de datos personales y confirmación de que son públicas); también se puede usar el CSV
- ✅ **Backtest** (`python -m radar.backtest`): corre el radar en semanas pasadas sin ver el futuro y mide si acertó; el resultado aparece en la app como «¿Acierta el radar?»
- ✅ YouTube por la **API oficial** (opcional, `YOUTUBE_API_KEY`): búsqueda diaria comparable, así YouTube entra al cálculo de crecimiento
- ✅ Si Jev no responde (clave sin saldo, límite de gasto), el radar lo detecta en segundos y usa el clasificador local, sin dejar un reporte vacío
- ✅ Costo de cada actualización visible en «Cómo se calcula»

## Ejemplo de resultado

```
 1. IA en Latinoamérica                              +39%  en_crecimiento
 2. Investigación y avances científicos               −3%  estable
 3. Riesgos y seguridad de la IA                     +13%  estable
 ...
Términos emergentes: gemini argon (24 piezas, 16 autores) · satya nadella · torvalds · …
```

*Corrida real del 17-10-2026 en modo heurístico (sin clave de Jev), con 3.112 piezas de IA. Con Jev, la clasificación y el encaje con la audiencia son mucho más precisos.*

## Stack tecnológico

- **Lenguaje:** Python 3.12+
- **Modelo de decisiones:** Jev (TypeSafe) vía `typesafe-sdk`, para clasificar, puntuar y filtrar. Se conecta directo a TypeSafe, por DigitalOcean o por OpenCode Zen
- **Modelo generativo (opcional):** Claude (`claude-opus-5-5`) u OpenCode Zen (`glm-5.3-flash`), para redactar ángulos y ganchos
- **Fuentes de datos:** Bluesky AppView pública, API de Hacker News (Algolia), RSS oficial de YouTube, RSS de Google News y un CSV de comunidad
- **Almacenamiento:** caché JSONL local de clasificaciones (`data/cache/`)
- **Interfaz:** CLI y reporte HTML estático

## Instalación y uso

### Requisitos
- Python 3.12 o superior
- Una clave de Jev, por cualquiera de estas vías:
  - `TYPESAFE_API_KEY`: https://console.typesafe.ai/keys
  - `OPENROUTER_API_KEY`: https://openrouter.ai/settings/keys. OpenRouter expone el mismo endpoint System One (`https://openrouter.ai/api/v1/systemone`), así que se usa el SDK de TypeSafe sin cambios.
  - `MODEL_ACCESS_KEY` de DigitalOcean: Control Panel → **Inference → Serverless Inference → Model Access Keys**. Jev es un modelo de terceros, así que la cuenta debe estar en un nivel que lo permita.
  - `OPENCODE_API_KEY` de OpenCode Zen (https://opencode.ai/zen): usa `jev-1.13-free`, gratis por tiempo limitado.
- Opcional, para redactar ángulos y ganchos: `ANTHROPIC_API_KEY` (Claude) u `OPENCODE_API_KEY` (Zen, modelo `glm-5.3-flash`)

### Pasos

```bash
git clone <url-del-repo>
cd creativIA
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # completar las claves
.venv/bin/python -m radar.web # abre la app en http://localhost:8000
```

En la app, **Actualizar radar** corre los cuatro pasos y muestra el progreso; el selector de fecha abre reportes anteriores y la pestaña **Feed** muestra las publicaciones destacadas. La app solo escucha en este computador.

También se puede correr por consola, sin la app: `.venv/bin/python -m radar` genera `out/radar-AAAA-MM-DD.html`, que se abre directo en el navegador.

Opciones útiles:

```bash
.venv/bin/python -m radar --days 28 --top 10 --per-day 40
.venv/bin/python -m radar --platforms bluesky,hackernews
.venv/bin/python -m radar --community data/comunidad.csv   # piezas aportadas por el equipo
.venv/bin/python -m radar --no-jev --no-llm                 # modo sin claves (demo)
.venv/bin/python -m unittest discover tests                 # pruebas, sin red
```

Para ajustar la audiencia, la taxonomía, las consultas, los canales de YouTube o los pesos, edita `radar/config.py`.

### Variables de entorno

| Variable | Descripción |
|---|---|
| `TYPESAFE_API_KEY` | Clasificación con Jev directo en TypeSafe. Si no hay ninguna clave de Jev, se usa el modelo local (ver abajo). |
| `OPENROUTER_API_KEY` | Alternativa: Jev vía OpenRouter (modelo `jev-latest`). Se usa solo si no hay `TYPESAFE_API_KEY`. |
| `MODEL_ACCESS_KEY` | Alternativa: Jev vía DigitalOcean Serverless Inference (modelo `typesafe-jev-1.13.0`). Se usa solo si no hay `TYPESAFE_API_KEY` ni `OPENROUTER_API_KEY`. |
| `OPENCODE_API_KEY` | OpenCode Zen: Jev gratis (`jev-1.13-free`) si no hay clave de TypeSafe, OpenRouter ni DigitalOcean, y redacción con `glm-5.3-flash` si no hay clave de Claude. |
| `ANTHROPIC_API_KEY` | Redacción de ángulos y ganchos con Claude. Sin ella se usa Zen, y sin Zen, plantillas. |
| `RADAR_ZEN_MODEL` | Modelo de Zen para redactar (por defecto `glm-5.3-flash`). |
| `RADAR_HASH_SALT` | Sal para el hash de autores. |
| `RADAR_JEV_MODEL` | Modelo de Jev (por defecto `jev-latest`). |
| `YOUTUBE_API_KEY` | Opcional. YouTube Data API v3: búsqueda diaria de videos de IA, con lo que YouTube entra al cálculo de crecimiento. Sin ella se usa el RSS de 10 canales. |

> **Nunca subas claves reales al repositorio.** `.env` ya está en `.gitignore`.

### Sin clave de Jev: modelo local

Si no hay ninguna clave de Jev, el radar clasifica con un modelo de embeddings multilingüe que corre en el computador (`paraphrase-multilingual-MiniLM-L12-v2`, unos 220 MB que se descargan la primera vez, vía `fastembed`). Compara el significado de cada pieza con la descripción de cada tema y de la audiencia. No necesita cuentas, tarjetas ni internet para clasificar, y tarda unos 2–3 minutos con 3.000 piezas.

Es menos preciso que Jev: el encaje con la audiencia es relativo a la muestra (percentil), no una probabilidad calibrada, y el gancho, el formato y el publicador se detectan con reglas. Con `--no-local` se usa en su lugar el clasificador por palabras clave.

### CSV de comunidad (LinkedIn, Instagram, TikTok)

Estas plataformas no ofrecen una API pública de descubrimiento sin login, así que el equipo y la comunidad actúan como sensores: cuando ven una pieza pública que funciona, la anotan en `data/comunidad_plantilla.csv`:

```
platform,url,text,published_at,likes,comments,shares,views,publisher
linkedin,https://www.linkedin.com/posts/...,"Texto del post",2026-10-15T10:00:00,320,45,12,,
```

`publisher` solo se llena con organizaciones (medios, marcas), nunca con nombres de personas.

En la app, el botón **Aportar** hace lo mismo sin editar archivos: valida el enlace y la fecha, pide confirmar que la publicación es pública, borra menciones, correos y teléfonos, y la guarda en `data/comunidad.csv`, que el radar usa en cada actualización.

## ¿Acierta el radar? (backtest)

```bash
.venv/bin/python -m radar.backtest --weeks 3
```

Para cada una de las últimas semanas se corre el radar "como si fuera ese día", sin ver nada posterior, y se mide la semana siguiente. Un tema "siguió arriba" si su participación en la conversación la semana siguiente fue mayor que en sus dos semanas previas. Se compara con la alternativa obvia: seguir los temas de los que más se habla.

Corrida real del 17-10-2026 (3 semanas, 6.385 publicaciones, clasificador local):

| Métrica | Radar | Temas más populares | Cualquier tema |
|---|---|---|---|
| Temas del top 10 que siguieron por encima de lo normal | **80 %** | 67 % | 69 % |
| Participación la semana siguiente vs. su línea base | **1,08×** | 1,02× | |

- Temas marcados como *nacientes* o *en crecimiento* que siguieron arriba: **88 %** (7 de 8).
- Temas marcados *en declive* que siguieron abajo: 67 % (2 de 3).

Son pocas semanas y pocos casos: es evidencia direccional, no una prueba estadística definitiva. El detalle por semana y por tema queda en `out/backtest-AAAA-MM-DD.md`.

## Datos, privacidad y términos de servicio

- **Solo contenido público.** Todas las fuentes son APIs abiertas o feeds RSS oficiales; no se accede a nada detrás de un login.
- **Sin datos personales.** No se guardan nombres, handles ni avatares. El autor se guarda como un hash irreversible que solo sirve para contar autores distintos. Antes de guardar el texto o enviarlo a un modelo, se le quitan menciones, correos y teléfonos. Los enlaces a las piezas se conservan para que el equipo pueda verlas.
- **Términos de servicio.** No se hace scraping de HTML ni se evaden límites: se usan los endpoints públicos documentados (Bluesky AppView, Algolia HN API) y feeds RSS oficiales, con un User-Agent identificable y reintentos con espera.

## Alcance y limitaciones

- **Plataformas integradas y probadas:** Bluesky, Hacker News, Google News y YouTube por RSS (10 canales).
- **YouTube por API:** implementado y probado con respuestas simuladas; falta la primera corrida con una clave real. Sin clave, YouTube no entra en el cálculo de crecimiento (su RSS solo trae los últimos 15 videos por canal) y se usa para explicar y dar ejemplos.
- **LinkedIn, Instagram y TikTok:** no tienen una API pública de descubrimiento sin login, así que entran solo por los aportes de la comunidad (botón Aportar o CSV). No hay integración automática y no la prometemos.
- **Muestra, no censo:** la tendencia se mide sobre las piezas con más interacción de cada día, no sobre todo lo publicado.
- **Idioma:** Jev rinde mejor en inglés; las preguntas están en inglés y las piezas en español o inglés. Conviene validar con una muestra etiquetada por el equipo.
- **Jev vía OpenRouter:** la conexión y la autenticación funcionan (OpenRouter aceptó la clave), pero la clave de prueba tiene un límite de gasto de US$0 y rechazó las llamadas. La primera corrida con saldo es la prueba completa; mientras tanto, los números de esta página salen del clasificador local.
- Las explicaciones del "por qué funcionó" son **hipótesis** basadas en correlación, no causalidad demostrada. Conviene validarlas con el criterio editorial del equipo.

## Próximos pasos

- [ ] Calibrar el filtro de audiencia con 50–100 piezas etiquetadas por el equipo de 30X
- [x] Formulario en la app para que el equipo aporte piezas (sensor comunitario)
- [ ] Bot de Slack o WhatsApp que escriba en el mismo CSV de aportes
- [x] YouTube Data API (oficial) para medir crecimiento en YouTube — falta probar con clave real
- [x] Validar la detección temprana con datos históricos (backtest) — repetir con Jev y más semanas
- [ ] Programar la corrida semanal y publicar el reporte automáticamente

---

*Construido durante el Hackatón 30X.*
