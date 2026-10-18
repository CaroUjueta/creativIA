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

**creativIA · Radar de contenido** recolecta piezas públicas sobre IA de fuentes abiertas, las clasifica con un **modelo local multilingüe** (gratis, sin enviar datos a terceros; listo para cambiar a **Jev**, el modelo de decisiones de TypeSafe, cuando haya una clave con acceso) y responde tres preguntas:

| Pregunta | Qué hace el prototipo |
|---|---|
| **¿Qué está despegando?** | Mide la participación de cada tema día a día contra una línea base y lo ubica en una etapa: *naciente*, *en crecimiento*, *saturado*, *en declive*. Además detecta **términos emergentes** que ninguna taxonomía anticipaba. |
| **¿Por qué funciona?** | El clasificador etiqueta el gancho, el formato y el tipo de publicador de cada pieza; el código compara la interacción de cada grupo contra la mediana del tema y la franja horaria. |
| **¿Encaja con nuestra audiencia?** | El clasificador puntúa cada pieza en una escala de 0 a 3 de utilidad para ejecutivos y equipos de LatAm, y responde si es accionable, técnica, puro humo o de la región. |

Por último, un **modelo de pesos abiertos vía OpenRouter** redacta para cada tema el ángulo, tres ganchos y el formato recomendado por plataforma, con una `OPENROUTER_API_KEY`: primero Nemotron 3 Super de NVIDIA, **gratis**, y si está saturado, DeepSeek V4.1 Flash (US$0,055 / 0,144 por millón de tokens, menos de un centavo por reporte). Alternativas: Claude (`ANTHROPIC_API_KEY`) u OpenCode Zen; sin ninguno, el radar arma la recomendación con plantillas.

> Los modelos gratuitos de chat de Zen (`*-free`) solo funcionan dentro de la app OpenCode; desde un script la API responde `FreeTierError`. Por eso la redacción va por OpenRouter.

**Costo:** hoy el radar opera a **US$0**: clasificación local y redacción con Nemotron gratis. Si se activa Jev (US$0,042 por millón de tokens de entrada), una corrida de unas 3.000 piezas se estima en unos US$0,10; la app muestra el costo real de cada actualización y las piezas ya clasificadas quedan en caché. Frente a los miles de dólares al año de un servicio de scraping, el costo de operación es cero o de centavos por semana.

## Pregunta que responde el prototipo

> **"¿Cuáles son los 10 temas de IA que más están creciendo esta semana, por qué, y cómo los adaptamos para nuestra audiencia?"**

## Cómo funciona

```
Bluesky · Hacker News · YouTube (API o RSS) · Google News RSS · aportes de la comunidad
                                │  (muestra comparable por día)
                                ▼
                 Limpieza de datos personales (hash de autores)
                                ▼
     Clasificador local multilingüe (o Jev, si hay clave con acceso): tema, gancho,
          formato, publicador, encaje con la audiencia, accionable, técnico, humo, LatAm
                                ▼
     Código: participación diaria por tema → crecimiento, aceleración y etapa
             interacción relativa → por qué funciona · términos emergentes
                                ▼
          Prioridad = momentum + encaje con la audiencia + interacción + accionable
                                ▼
    Modelo open source vía OpenRouter (o plantillas): ángulo, ganchos y formato
                                ▼
                    Reporte HTML · Markdown · JSON
```

1. **Recolección** (`radar/sources.py`): APIs públicas sin login. Cada día se toman las N piezas con más interacción por consulta, para comparar *participación* y no volumen bruto.
2. **Clasificación** (`radar/classify.py`): en el prototipo, un modelo de embeddings multilingüe que corre en el computador compara cada pieza con la descripción de cada tema y de la audiencia; el gancho, el formato y el publicador se detectan con reglas. El tema se guarda como distribución completa y se cuenta de forma "suave" (suma de probabilidades). Con una clave de Jev, el mismo paso se hace con preguntas tipadas (*Choice*, *Score*, *Noul*) y probabilidades calibradas, sin cambiar el resto del flujo.
3. **Detección de tendencias** (`radar/analysis.py`): participación del tema en la semana actual frente a la línea base, promediada entre plataformas para que el volumen de noticias no tape a las redes. *Naciente* = crece al menos un 50 % y aún tiene una participación pequeña; *saturado* = grande y plano.
4. **Por qué funciona:** interacción de cada pieza relativa a la mediana de su plataforma, agrupada por gancho, formato y franja horaria (hora de Bogotá). Solo se reporta una señal si rinde al menos 1,2× la mediana.
5. **Filtro de audiencia:** el puntaje de encaje con la audiencia pesa un 35 % en la prioridad; el humo penaliza y la etapa temprana suma.
6. **Salida** (`radar/report.py`): reporte HTML autocontenido (con modo oscuro y diseño para móvil), Markdown y JSON.

Toda la aritmética vive en código: los modelos solo clasifican y redactan, así que cada número se puede revisar.

## Funcionalidades

- ✅ Detección de temas emergentes (naciente / en crecimiento / saturado / en declive) con línea base
- ✅ Términos emergentes fuera de la taxonomía
- ✅ Explicación del "por qué funcionó" por tema (gancho, formato, franja, publicador, idioma)
- ✅ Puntaje de relevancia para la audiencia objetivo
- ✅ Recomendación de adaptación (ángulo, 3 ganchos, formato por plataforma, cuidado)
- ✅ App web local: tablero con mapa de oportunidades, ranking, feed de publicaciones destacadas, historial y botón para actualizar
- ✅ Feed vertical estilo TikTok con las publicaciones que más rindieron frente a su plataforma: pestañas Para ti / Útiles / Recientes / Guardados, filtros por plataforma y tema, doble clic para guardar y botón para saltar a la adaptación del tema
- ✅ Reporte HTML / Markdown / JSON
- ✅ Botón **Aportar** en la app: el equipo agrega publicaciones públicas de LinkedIn, Instagram o TikTok (con limpieza de datos personales y confirmación de que son públicas); también se puede usar el CSV
- ✅ **Backtest** (`python -m radar.backtest`): simula, con publicaciones públicas de las últimas semanas, qué habría dicho el radar en fechas pasadas y lo compara con lo que pasó después; el resultado aparece en la app como «¿Acierta el radar?»
- ✅ YouTube por la **API oficial** (opcional, `YOUTUBE_API_KEY`): búsqueda diaria comparable, así YouTube entra al cálculo de crecimiento
- ✅ Respaldo automático: si Jev no responde (sin acceso o sin saldo), el radar sigue con el clasificador local; si un modelo de redacción falla, pasa al siguiente y, al final, a plantillas. Nunca deja un reporte vacío
- ✅ Clasificador y costo de cada actualización visibles en «Cómo se calcula»

## Ejemplo de resultado

```
 1. Futuro del trabajo y habilidades                 +18%  estable
 2. IA para la productividad personal                 +2%  estable
 3. Educación y alfabetización en IA                 +19%  estable
 ...
Términos emergentes: argon (28 piezas, 20 autores) · torvalds · openai engineer · …
```

*Corrida real del 17-10-2026 con 3.326 piezas públicas (3.155 sobre IA), clasificadas con el modelo local y adaptadas con Nemotron vía OpenRouter, a costo cero. El orden es por prioridad (crecimiento, encaje con la audiencia, interacción y utilidad), no solo por crecimiento.*

## Stack tecnológico

- **Lenguaje:** Python 3.12+
- **Clasificación:** modelo de embeddings multilingüe local (`paraphrase-multilingual-MiniLM-L12-v2` vía `fastembed`), gratis y sin enviar datos a terceros. Jev (TypeSafe, vía `typesafe-sdk`) está integrado como opción por TypeSafe, DigitalOcean, OpenRouter u OpenCode Zen, pero no lo pudimos usar en la hackatón
- **Modelo generativo:** modelos de pesos abiertos vía OpenRouter (Nemotron 3 Super, gratis; DeepSeek V4.1 Flash como respaldo) para redactar ángulos y ganchos. Alternativas: Claude u OpenCode Zen
- **Fuentes de datos:** Bluesky AppView pública, API de Hacker News (Algolia), RSS oficial de YouTube (o YouTube Data API v3 con clave), RSS de Google News y aportes de la comunidad
- **Almacenamiento:** caché JSONL local de clasificaciones (`data/cache/`)
- **Interfaz:** app web local (servidor de la biblioteca estándar de Python), CLI y reporte HTML autocontenido

## Instalación y uso

### Requisitos
- Python 3.12 o superior
- Ninguna clave es obligatoria: sin claves, el radar clasifica con el modelo local y redacta con plantillas.
- Recomendado: `OPENROUTER_API_KEY` (https://openrouter.ai/settings/keys) para redactar ángulos y ganchos con Nemotron, gratis. Alternativas: `ANTHROPIC_API_KEY` (Claude) u `OPENCODE_API_KEY` (Zen).
- Opcional: una clave de Jev con acceso, por cualquiera de estas vías:
  - `TYPESAFE_API_KEY`: https://console.typesafe.ai/keys
  - `OPENROUTER_API_KEY` con saldo: OpenRouter expone el mismo endpoint System One (`https://openrouter.ai/api/v1/systemone`), así que se usa el SDK de TypeSafe sin cambios.
  - `MODEL_ACCESS_KEY` de DigitalOcean: Control Panel → **Inference → Serverless Inference → Model Access Keys**. Jev es un modelo de terceros, así que la cuenta debe estar en un nivel que lo permita.
  - `OPENCODE_API_KEY` de OpenCode Zen (https://opencode.ai/zen): usa `jev-1.13-free`.

### Pasos

```bash
git clone <url-del-repo>
cd creativIA
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # completar las claves (opcional)
.venv/bin/python -m radar.web # abre la app en http://localhost:8000
```

En la app, **Actualizar radar** corre los cuatro pasos y muestra el progreso; el selector de fecha abre reportes anteriores y la pestaña **Feed** muestra las publicaciones destacadas. La app solo escucha en este computador.

También se puede correr por consola, sin la app: `.venv/bin/python -m radar` genera `out/radar-AAAA-MM-DD.html`, que se abre directo en el navegador.

Opciones útiles:

```bash
.venv/bin/python -m radar --days 28 --top 10 --per-day 40
.venv/bin/python -m radar --platforms bluesky,hackernews
.venv/bin/python -m radar --community data/comunidad.csv   # piezas aportadas por el equipo
.venv/bin/python -m radar --no-jev --no-llm                 # sin modelos externos: clasificador local y plantillas
.venv/bin/python -m unittest discover tests                 # pruebas, sin red
```

Para ajustar la audiencia, la taxonomía, las consultas, los canales de YouTube o los pesos, edita `radar/config.py`.

### Variables de entorno

| Variable | Descripción |
|---|---|
| `TYPESAFE_API_KEY` | Opcional. Clasificación con Jev directo en TypeSafe. Sin ninguna clave de Jev, o si Jev no responde, se usa el modelo local (ver abajo). |
| `OPENROUTER_API_KEY` | Redacción con modelos open source y, si no hay `TYPESAFE_API_KEY` ni `MODEL_ACCESS_KEY`, Jev vía OpenRouter (modelo `jev-latest`). |
| `MODEL_ACCESS_KEY` | Jev vía DigitalOcean Serverless Inference (modelo `typesafe-jev-1.13.0`). Tiene prioridad sobre OpenRouter para clasificar. |
| `OPENCODE_API_KEY` | OpenCode Zen: Jev (`jev-1.13-free`) si no hay clave de TypeSafe, OpenRouter ni DigitalOcean, y redacción con `glm-5.3-flash` si no hay OpenRouter ni Claude. |
| `ANTHROPIC_API_KEY` | Alternativa para redactar ángulos y ganchos con Claude, si no hay `OPENROUTER_API_KEY` o OpenRouter falla. Sin ninguna, Zen, y sin Zen, plantillas. |
| `RADAR_WRITER_MODELS` | Modelos de OpenRouter para redactar, separados por coma, en orden (por defecto `nvidia/nemotron-3-super-120b-a12b:free,deepseek/deepseek-v4.1-flash`). |
| `RADAR_ZEN_MODEL` | Modelo de Zen para redactar (por defecto `glm-5.3-flash`). |
| `RADAR_HASH_SALT` | Sal para el hash de autores. |
| `RADAR_JEV_MODEL` | Modelo de Jev (por defecto `jev-latest`). |
| `YOUTUBE_API_KEY` | Opcional. YouTube Data API v3: búsqueda diaria de videos de IA, con lo que YouTube entra al cálculo de crecimiento. Sin ella se usa el RSS de 10 canales. |

> **Nunca subas claves reales al repositorio.** `.env` ya está en `.gitignore`.

### Clasificador local (el que usa el prototipo)

Si no hay una clave de Jev con acceso, el radar clasifica con un modelo de embeddings multilingüe que corre en el computador (`paraphrase-multilingual-MiniLM-L12-v2`, unos 220 MB que se descargan la primera vez, vía `fastembed`). Compara el significado de cada pieza con la descripción de cada tema y de la audiencia. No necesita cuentas, tarjetas ni internet para clasificar, y tarda unos 2–3 minutos con 3.000 piezas.

Sus límites: el encaje con la audiencia es relativo a la muestra (percentil), no una probabilidad calibrada, y el gancho, el formato y el publicador se detectan con reglas. Con `--no-local` se usa en su lugar el clasificador por palabras clave.

### CSV de comunidad (LinkedIn, Instagram, TikTok)

Estas plataformas no ofrecen una API pública de descubrimiento sin login, así que el equipo y la comunidad actúan como sensores: cuando ven una pieza pública que funciona, la anotan en `data/comunidad_plantilla.csv`:

```
platform,url,text,published_at,likes,comments,shares,views,publisher
linkedin,https://www.linkedin.com/posts/...,"Texto del post",2026-10-15T10:00:00,320,45,12,,
```

`publisher` solo se llena con organizaciones (medios, marcas), nunca con nombres de personas.

En la app, el botón **Aportar** hace lo mismo sin editar archivos: valida el enlace y la fecha, pide confirmar que la publicación es pública, borra menciones, correos y teléfonos, y la guarda en `data/comunidad.csv`, que el radar usa en cada actualización.

### Cuenta para la que se produce (@crece30x)

En la app, el botón con el nombre de la cuenta abre dos cosas:

- **Ficha de la cuenta** (`data/cuenta.json`): de qué habla, a quién le habla, tono, pilares, formatos que usa, llamado a la acción habitual, qué evitar y enlaces a sus mejores posts.
- **Exportación de Meta Business Suite** (Estadísticas → Contenido → Exportar datos, en CSV): el radar mide qué formatos, temas y ganchos le funcionan a la cuenta comparando la interacción de cada post con la mediana de la propia cuenta. **Solo se guarda lo que es público en cada post** (texto, fecha, enlace, tipo, me gusta, comentarios y vistas); alcance, guardados y compartidos son métricas privadas y se descartan al importar (`data/cuenta_metricas.csv`).

Con la ficha, cada tendencia trae una pieza **«Para @crece30x»**: pilar, formato (reel, carrusel o historia, priorizando lo que le funciona a la cuenta), estructura por láminas o momentos, caption y llamado a la acción. Ambos archivos están en `.gitignore` y se aplican en la siguiente actualización del radar.

### Publicarla en internet

**Render (gratis, la que usa la demo):** `render.yaml` crea el servicio con `render.Dockerfile`. En render.com → *New → Blueprint* se elige este repositorio y se pega `OPENROUTER_API_KEY` cuando lo pide. Arranca con el último reporte del equipo (`demo/`) y queda abierta sin contraseña para los jurados. Como el plan gratis tiene 512 MB, esa versión no trae el clasificador local (~780 MB): si se actualiza en línea, clasifica por palabras clave. Se duerme tras 15 minutos sin visitas; un monitor gratuito (p. ej. UptimeRobot cada 5 minutos a `/api/status`) la mantiene despierta.

**Desde este computador:** `bash scripts/publicar_tunel.sh [--sin-clave]` abre un túnel gratuito de Cloudflare con la app completa mientras el computador esté prendido (la URL cambia cada vez).

**Hugging Face Spaces (requiere PRO):** la app completa (Actualizar, Aportar y Cuenta) corre en un Space de Hugging Face con Docker (CPU gratis, 16 GB de RAM). Con `HF_TOKEN` (token con permiso de escritura) y `RADAR_PASSWORD` en el `.env`:

```bash
.venv/bin/python scripts/publicar_hf.py
```

El script crea el Space `usuario/creativia`, guarda las claves como secretos del Space (nunca en el código) y sube los reportes y datos a un dataset **privado** `usuario/creativia-datos`. En línea:

- **Contraseña:** sin `RADAR_PASSWORD` nadie ve el tablero, ni puede actualizar el radar o escribir aportes y datos de la cuenta. En el computador (127.0.0.1) no se pide.
- **Datos que no se pierden:** el disco del Space se borra al reiniciarse; la app recupera `data/` y `out/` del dataset privado al arrancar y los vuelve a subir después de cada actualización, aporte o cambio en la cuenta.
- El Space se duerme tras 48 horas sin visitas y despierta solo al abrirlo (1–2 minutos).

## ¿Acierta el radar? (backtest)

```bash
.venv/bin/python -m radar.backtest --weeks 3
```

No hace falta esperar semanas: las publicaciones públicas de las últimas semanas siguen disponibles. El backtest las descarga hoy y, para cada fecha de corte, le muestra al radar solo lo publicado hasta ese día y compara su predicción con lo que pasó los 7 días siguientes. Un tema "siguió arriba" si su participación en la conversación la semana siguiente fue mayor que en sus dos semanas previas. Se compara con la alternativa obvia: seguir los temas de los que más se habla.

Simulación hecha el 17-10-2026 (3 fechas de corte: 26 sep, 3 oct y 10 oct; 6.385 publicaciones; clasificador local):

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
- **Precisión del clasificador:** el modelo local es pequeño y no fue calibrado con piezas etiquetadas por 30X; el encaje con la audiencia es relativo a la muestra y el gancho y el formato salen de reglas. Conviene validarlo con 50–100 piezas etiquetadas por el equipo.
- **Jev sin acceso durante la hackatón:** está integrado por cuatro vías (TypeSafe, DigitalOcean, OpenRouter y OpenCode Zen), pero ninguna cuenta del equipo obtuvo acceso (DigitalOcean lo restringe por nivel de cuenta; la clave de OpenRouter tiene límite de gasto de US$0). Todos los números de este documento salen del clasificador local; con una clave válida, el radar cambia a Jev sin tocar código.
- Las explicaciones del "por qué funcionó" son **hipótesis** basadas en correlación, no causalidad demostrada. Conviene validarlas con el criterio editorial del equipo.

## Próximos pasos

- [ ] Calibrar el filtro de audiencia con 50–100 piezas etiquetadas por el equipo de 30X
- [x] Formulario en la app para que el equipo aporte piezas (sensor comunitario)
- [ ] Bot de Slack o WhatsApp que escriba en el mismo CSV de aportes
- [x] YouTube Data API (oficial) para medir crecimiento en YouTube — falta probar con clave real
- [x] Validar la detección temprana con datos históricos (backtest) — repetir con más semanas
- [ ] Activar Jev cuando haya una clave con acceso y comparar su precisión con el clasificador local
- [ ] Programar la corrida semanal y publicar el reporte automáticamente

---

*Construido durante el Hackatón 30X.*
