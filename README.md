# [Nombre del proyecto]

> De "qué está de moda" a "qué debemos producir, por qué y para quién".

Prototipo desarrollado en el **Hackatón 30X** · Área **Media** · Reto: *Explorar una oportunidad*.

[Badges opcionales: licencia, Python/Node, estado del proyecto]

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
9. [Datos, privacidad y términos de servicio](#datos-privacidad-y-términos-de-servicio)
10. [Alcance y limitaciones](#alcance-y-limitaciones)
11. [Demo](#demo)
12. [Equipo](#equipo)
13. [Próximos pasos](#próximos-pasos)
14. [Licencia](#licencia)

---

## El problema

30X produce contenido sobre IA para líderes y equipos en Latinoamérica. Para decidir qué producir, el equipo de media necesita identificar referentes y piezas que estén funcionando en LinkedIn, Instagram, TikTok y YouTube.

Hoy eso depende de servicios de scraping de pago que cuestan miles de dólares al año y que resuelven solo la mitad de la pregunta: entregan datos, pero no explican:

- **Por qué** una pieza funcionó.
- Si la tendencia **apenas empieza** o ya está saturada.
- Si **le sirve a la audiencia** concreta del equipo.

Es el mismo problema de cualquier marca, medio o creador que produce contenido de forma continua.

## La solución

**[Nombre del proyecto]** es un radar de tendencias de contenido que descubre piezas públicas sobre IA y responde tres preguntas:

| Pregunta | Qué hace el prototipo |
|---|---|
| **¿Qué está despegando?** | Detecta temas y formatos en crecimiento temprano, no solo los que ya son masivos. |
| **¿Por qué funciona?** | Analiza gancho, formato, tema, momento y tipo de publicador. |
| **¿Encaja con nuestra audiencia?** | Prioriza según el perfil objetivo: ejecutivos y equipos de Latinoamérica que están aprendiendo IA. |

## Pregunta que responde el prototipo

> **"¿Cuáles son los 10 temas de IA que más están creciendo esta semana en [plataforma], por qué, y cómo los adaptamos para nuestra audiencia?"**

## Cómo funciona

```
[Fuentes públicas]  →  [Recolección]  →  [Normalización]
                                              ↓
[Reporte / dashboard]  ←  [Priorización por audiencia]  ←  [Análisis con LLM]
                                              ↑
                                    [Detección de crecimiento]
```

1. **Recolección:** [describir fuentes: APIs oficiales, RSS, datasets abiertos, búsqueda web, etc.].
2. **Detección de tendencias:** [describir método: velocidad de crecimiento de interacciones, comparación contra línea base, frecuencia de aparición de temas en ventanas de tiempo, etc.].
3. **Explicación:** un modelo de lenguaje clasifica cada pieza por gancho, formato, tema y momento, y genera una explicación de por qué funcionó.
4. **Filtro de audiencia:** [describir cómo se puntúa la relevancia para ejecutivos y equipos de LatAm].
5. **Salida:** un reporte con los temas priorizados y una recomendación de adaptación para cada uno.

## Funcionalidades

- [ ] Detección de temas emergentes (diferencia entre tendencia naciente y saturada)
- [ ] Explicación del "por qué funcionó" por pieza
- [ ] Puntaje de relevancia para la audiencia objetivo
- [ ] Recomendación de adaptación (ángulo, formato, gancho sugerido)
- [ ] Reporte [semanal / en dashboard / exportable]

> Marca con ✅ solo lo que realmente funciona en la demo.

## Ejemplo de resultado

```
Tema #1: [ejemplo]
  Señal de crecimiento: [métrica]
  Por qué funciona: [gancho / formato / momento]
  Relevancia para la audiencia: [alta / media / baja] — [motivo]
  Cómo adaptarlo: [recomendación]
```

[Pegar aquí una captura o un resultado real generado por el prototipo.]

## Stack tecnológico

- **Lenguaje(s):** [ ]
- **Backend / orquestación:** [ ]
- **Modelos de IA:** [ ]
- **Fuentes de datos:** [ ]
- **Almacenamiento:** [ ]
- **Interfaz:** [ ]
- **Despliegue:** [ ]

## Instalación y uso

### Requisitos
- [Versión de Python/Node]
- [Claves de API necesarias]

### Pasos

```bash
git clone [url-del-repo]
cd [carpeta]
[comando de instalación de dependencias]
cp .env.example .env   # completar las variables de entorno
[comando para ejecutar]
```

### Variables de entorno

| Variable | Descripción |
|---|---|
| `[NOMBRE_API_KEY]` | [para qué se usa] |

> **Nunca subas claves reales al repositorio.** Usa `.env` y manténlo en `.gitignore`.

## Datos, privacidad y términos de servicio

Este proyecto respeta las restricciones del reto:

- **Solo contenido público.** No se accede a datos privados ni a contenido detrás de un login de terceros.
- **Sin datos personales.** [Explicar qué se almacena: por ejemplo, métricas agregadas y texto de piezas públicas, sin perfiles individuales.]
- **Términos de servicio.** [Indicar cómo se obtienen los datos: APIs oficiales, fuentes abiertas, datos de ejemplo, etc., y confirmar que no se usan técnicas que violen los términos de las plataformas.]

## Alcance y limitaciones

- **Plataformas cubiertas en este prototipo:** [indicar las que realmente están integradas].
- **Plataformas en el diseño pero no implementadas:** [indicar].
- **Limitaciones conocidas:** [calidad de los datos, tamaño de la muestra, sesgos del modelo, idioma, etc.].
- Las explicaciones del "por qué funcionó" son **hipótesis generadas por un modelo**, no causalidad demostrada. Conviene validarlas con el criterio editorial del equipo.

## Demo

- 🎥 Video: [enlace]
- 🌐 Despliegue: [enlace]
- 📊 Presentación: [enlace]

## Equipo

| Nombre | Rol |
|---|---|
| [Nombre] | [Rol] |

## Próximos pasos

- [ ] [Ampliar a más plataformas]
- [ ] [Validar la detección temprana con datos históricos]
- [ ] [Incorporar retroalimentación de la comunidad como señal]
- [ ] [Calibrar el filtro de audiencia con el equipo de 30X]

## Licencia

[MIT / Apache-2.0 / otra]. Revisa también las licencias de las APIs, datasets y modelos que uses.

---

*Construido durante el Hackatón 30X.*
