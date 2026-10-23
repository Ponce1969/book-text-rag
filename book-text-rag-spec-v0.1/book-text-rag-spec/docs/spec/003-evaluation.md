# 003 — Evaluación de recuperación

## Objetivo

Medir si el sistema recupera la evidencia correcta para preguntas sobre libros técnicos. No confundir la calidad del recuperador con la calidad de una respuesta generada.

## Dataset inicial

Objetivo orientativo: 30–50 preguntas para el libro piloto, divididas entre:
- léxicas: identificadores, nombres exactos, acrónimos o frases concretas;
- conceptuales: paráfrasis y preguntas cuyo vocabulario difiere del texto;
- mixtas: concepto más término técnico exacto.

Cada pregunta debe tener una lista de uno o más pasajes relevantes anotados por una persona. Guardar la versión del libro y el criterio de relevancia. La IA puede sugerir preguntas o pasajes, pero no cerrar etiquetas sin revisión.

## Comparación

Comparar bajo el mismo corpus, versión de fragmentación, filtros y `top_k`:
1. BM25/léxico;
2. vectorial;
3. híbrida, con fusión RRF si corresponde.

RRF combina rangos, no puntuaciones brutas de escalas incompatibles. `k=60` puede servir como valor inicial; no es un valor universal que deba optimizarse en el MVP.

## Métricas iniciales

- **Recall@k:** proporción de pasajes relevantes que aparecen entre los primeros k resultados; útil para saber si se recuperó la evidencia.
- **MRR:** posición del primer resultado relevante, promediada entre consultas.
- **Precision@k:** proporción de los primeros k resultados que son relevantes, si el dataset etiqueta los resultados recuperados de forma suficiente.
- **Latencia:** registrar al menos mediana y p95 cuando haya suficientes consultas; informar el tamaño de la muestra.
- **Coste de ingesta:** tiempo y coste monetario de embeddings si se usan APIs.
- **Tamaño del índice:** registrar para comparar coste operativo.

No asumir que “Context Precision/Recall” de una librería de evaluación y Precision@k/Recall@k son idénticas: definir exactamente la métrica y su implementación. En la primera iteración, evitar introducir Ragas solo para calcular métricas de ranking sencillas.

## Reglas de validez

- Comparar configuraciones con el mismo conjunto de preguntas.
- No ajustar el sistema con las preguntas de prueba y después presentar esas mismas preguntas como evaluación independiente.
- Registrar corpus, fragmentación, análisis léxico (tokenizer y sus opciones), modelo de embeddings, configuración de búsqueda, `index_version` y versión de código junto a los resultados.
- Mostrar resultados por categoría y globales; la media global puede ocultar fallos en consultas exactas.
- Revisar manualmente errores representativos y cambios de ranking.

## Criterio de decisión

Elegir la opción menos compleja que cumpla los umbrales acordados por el propietario. No fijar porcentajes de mejora arbitrarios antes de conocer la línea base. Si dos opciones son similares, priorizar menor coste operativo y mejor trazabilidad.
