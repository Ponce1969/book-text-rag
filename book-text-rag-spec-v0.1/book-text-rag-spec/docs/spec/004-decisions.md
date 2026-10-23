# 004 — Registro de decisiones y cuestiones abiertas

Estado: v0.29. Separar decisiones ya tomadas de las que requieren evidencia o aprobación.

## Decisiones de arquitectura acordadas

- `book-text-rag` es un proyecto independiente y complementario a `book-graph-rag`.
- La Orange Pi será infraestructura de servicio; no ejecutar modelos locales de embeddings/generación para este proyecto.
- Una capa de aplicación compartida servirá a CLI, API HTTP y MCP.
- La salida principal será evidencia textual con procedencia, no texto generado por un LLM.
- BM25 es la línea base; vectorial e híbrida deben evaluarse antes de fijar la estrategia definitiva.
- Ingesta reproducible, versiones documentales y configuración de fragmentación son requisitos.
- Reranking, contextual retrieval, caché semántica y enrutamiento entre grafo/RAG quedan fuera del MVP.
- Los agentes MCP tendrán acceso de lectura por defecto; las operaciones administrativas quedan separadas.

## Decisiones cerradas en Fase 0 (piloto)

### D-01 — Libro y formato piloto · CERRADA

- **Decisión:** el piloto es *AI Engineering* (Chip Huyen), en su **original en inglés**, con fuente **PDF con capa de texto** (no escaneado).
- **Evidencia:** 784 páginas; 170.620 palabras; capa de texto real (no requiere OCR); 178 bookmarks en 3 niveles; 5 candidatos auditados.
- **Motivo:** es el candidato con extracción más limpia y su tema (RAG, embeddings, recuperación, evaluación) coincide con lo que los agentes construyen.
- **Formato y páginas:** el PDF es una conversión con reflujo; la numeración impresa equivale a `página PDF − 1` de forma constante en 776 de 783 páginas. La **página física del PDF** es la referencia canónica; el número impreso es un dato secundario y no debe presentarse como página de la edición editorial.
- **Consecuencias:** el corpus operativo son los capítulos (páginas PDF 25–716); se excluyen el front matter (1–24) y el back matter (Index 717–775, About 776–784). El nombre de archivo no se cambia todavía.
- **Aprobación:** propietario, 2026-10-10.

### D-04 — Extracción documental · CERRADA para el piloto

- **Decisión:** extractor principal **`pdftotext -layout`**.
- **No se usa** `-table` de forma global (mejora la separación de columnas en algunas tablas, pero fragmenta los captions de prosa y es específico de Xpdf, no existe en Poppler).
- **No se implementa OCR**: el PDF piloto tiene capa de texto.
- **PyMuPDF y pdfplumber quedan descartados para el MVP**; reevaluar solo ante un fallo observado en la evaluación. PyMuPDF conserva mejor símbolos matemáticos (`×`, `√`) y palabras que Xpdf rompe (`sof tmax`), pero eso no justifica todavía otra dependencia ni una segunda ruta de extracción.
- **Procedencia:** registrar documento, **página física del PDF**, extractor y versión del extractor.
- **Normalización:** conservar el texto extraído como evidencia original. Las variantes con y sin guion (`open-ended` / `openended`) se resolverán en la capa de recuperación si las pruebas lo justifican, no por sustitución global en la extracción.
- **Limitación conocida:** la extracción con Xpdf/Poppler puede perder fidelidad en fórmulas y algunos símbolos. No intentar corregirlos indiscriminadamente con sustituciones globales.
- **Precisión de redacción:** `-layout` **mejora la representación espacial del texto de las tablas sin pérdida léxica observada en la muestra**; **no** equivale a reconstruir un modelo estructurado de filas, columnas y celdas. No debe documentarse como «resuelve las tablas».
- **Evidencia:** comparación read-only de 12 páginas (5 con tablas, entre ellas las de mayor densidad; figura, texto mínimo, tres inicios de capítulo, prosa densa, Index y matemática). `default → -layout`: mismo conteo de palabras y Jaccard 1,000 en las páginas de tabla. Fragmentos y métricas en el informe de D-04 (artefacto temporal, no versionado).
- **Aprobación:** propietario, 2026-10-10.

### D-05 — Fragmentación inicial · CERRADA (estrategia estructural)

**Hallazgos medidos (evidencia, no decisiones):**

- 178 bookmarks en 3 niveles (L1 14 / L2 52 / L3 112), con destinos válidos y sin violaciones de orden ni de anidamiento.
- Dentro de los capítulos (páginas 25–716) hay **126 hojas**: mínimo 121 / p25 476 / mediana 946 / p75 1.506 / máximo 4.673 palabras. **47 hojas superan 1.200 palabras y 11 superan 2.500**; 116 de 137 hojas abarcan más de una página.
- La distribución es continua: el porcentaje de hojas que supera un tope dado va del 83% (400 palabras) al 27% (1.500). **Ningún tamaño universal encaja en la jerarquía.**
- De 178 encabezados, 29 comienzan en la primera línea de una página y **137 (77%) a mitad de página**; 12 no se localizaron por coincidencia de texto.
- 5.099 bloques separados por línea en blanco: mediana 18 palabras, p75 48, máximo 319. Incluyen encabezados, captions, filas de tabla y cajas `NOTE`/`TIP`, no solo prosa.
- 217 líneas de caption (168 `Figure`, 49 `Table`) en 209 páginas; el número del caption codifica el capítulo.
- No se detectaron running headers; casi toda página termina con su número (página PDF − 1).
- Riesgos medidos: la cola de la sección anterior cae en la página de inicio de la siguiente (137/178); el texto propio de un L2 precede a su primer L3; el Index son 59 páginas / 6.541 palabras de término+número.

**Decisión adoptada (estrategia estructural):**

1. La unidad de fragmento es la **jerarquía documental**: la hoja más profunda disponible (L3 → L2 → L1). El tamaño es solo un tope de desborde, no el criterio de corte.
2. Cuando una unidad empieza a mitad de página, el fragmento **arranca en su encabezado**, no al inicio de la página.
3. Las unidades que superan el tope se dividen en **límites de párrafo**, sin cruzar nunca el límite de la unidad.
4. El texto propio de un nodo padre anterior a su primer hijo se conserva como fragmento propio, con el camino del padre.
5. Los bloques de tabla **no se parten**: caption y filas permanecen juntos y se etiquetan como tabla. No se reconstruye un modelo de celdas y los valores no se asocian a columnas.
6. El front matter y el back matter (incluido el Index) quedan **fuera** de los fragmentos.
7. Si se usa overlap, queda **dentro de la misma unidad**.
8. Todo fragmento conserva procedencia: documento, rango de páginas físicas del PDF, camino de sección, nivel, tipo de bloque, captions asociados, hash de contenido, extractor y versión, y versión de la configuración de fragmentación. Los **nombres públicos** de esos campos quedaron fijados en D-07.

**Aprobación:** propietario, 2026-10-10.

### D-02 — Motor de almacenamiento e índice · CERRADA (decisión arquitectónica del piloto)

**Decisión adoptada:**

1. **Motor: SQLite + FTS5 + sqlite-vec**, con **versión fijada**.
   - `sqlite-vec` fijado en **0.1.9** (licencia MIT/Apache-2.0). Es un proyecto **pre-v1**: el pin es obligatorio y una actualización se trata como un cambio que exige reindexado y re-evaluación.
   - FTS5 aporta **BM25 real** (la función `bm25()`), sin extensión adicional.
   - La versión de SQLite la provee el intérprete del host y se registra en la procedencia (3.50.4 fue la medida en el entorno de desarrollo).
2. **Un solo motor con dos índices:** FTS5 para el léxico y `vec0` para el vectorial. En 0.1.9 el vectorial es **brute-force, sin ANN**; a la escala del piloto (~146.900 palabras ⇒ cientos de fragmentos y vectores de pocos MB) no es un problema.
3. **Índice reconstruible.** El índice es un artefacto derivado y desechable. Se registran las fuentes canónicas, las versiones y los parámetros necesarios para reconstruirlo.
4. **PostgreSQL + pgvector + pg_textsearch** queda como **alternativa documentada**: sin implementación ni instalación en esta fase. Se activa solo si aparecen concurrencia real, filtros SQL plenos o necesidad de consistencia mantenida por el motor.
5. **Neo4j queda descartado para este proyecto por acoplamiento operativo, no por incapacidad técnica general.** Su Community Edition es GPLv3, su backup online es exclusivo de Enterprise (en CE hay que detener la base de datos) y la instancia se comparte con `book-graph-rag`.

**Fuentes canónicas y parámetros a registrar para reconstruir el índice:**

- Documento fuente: archivo y hash de contenido.
- Extractor: nombre, versión y **configuración efectiva** observada (el real del host) ([D] `D-19` §2).
- **Analizador léxico:** `tokenizer` y sus opciones —insumo **separado**, que **no** forma parte de `chunking_config_version`— ([D] `D-10`, cierre de PD-13).
- Outline y jerarquía de bookmarks (nivel → sección → subsección).
- Reglas de exclusión (front matter y back matter).
- **Configuración de fragmentación y anclaje:** el **manifiesto de `D-10`** —quince campos, `schema = "chunking_config/v3"`, incluida `anchoring_procedure`— y su `chunking_config_version` ([D] `D-10`; `D-19` §3).
- **Revisión del código del pipeline de ingesta:** forma **pendiente de Q-1/Q-2** ([D] `D-15` §8.3): revisión del árbol de fuentes **o** identidad del código ejecutado; si no se adopta como insumo de `index_version`, se registra junto a los resultados ([D] `003`, Reglas de validez) y como procedencia interna por fragmento ([D] `001` §6).
- Modelo de embeddings, proveedor y dimensiones (D-03, cuando se decida).
- Versión de SQLite y la versión fijada de `sqlite-vec`.

**Alcance de esta fase:** no se instala ninguna dependencia, no se crea el índice, no se modifica código y no se toca el proyecto Neo4j.

**Aprobación:** propietario, 2026-10-10.

### D-07 — Contratos públicos · CERRADA (contrato del MVP léxico)

**Decisión adoptada**

Tres capacidades, nombradas una sola vez y serializadas por transporte más adelante: `search`, `get_document` y `health`.

`search` — entrada: `query` (obligatorio, no vacío), `top_k` (entero; por defecto 10, máximo 50, configurable), `mode` (por defecto `lexical`; en el MVP **solo se acepta `lexical`**), `document_ids` (opcional). `filters` queda fuera del MVP.

`search` — salida: `query`, `mode` efectivo, `index_version` y una lista ordenada de resultados. Todos los campos están siempre presentes; un valor genuinamente desconocido es `null`, nunca se omite ni se inventa. Cada resultado: `rank` (1-based), `score`, `document_id`, `document_version`, `chunk_id`, `content`, `section_path`, `pdf_page_start`, `pdf_page_end`.

`score` es la relevancia léxica del recuperador y **no es comparable entre consultas distintas**; se interpreta junto con `index_version`. El orden lo fija `rank`, no la magnitud de `score`.

`get_document` — entrada: `document_id` y `document_version` opcional. Salida: `document_id`, `document_version`, `title`, `source_format`, `page_count`, `index_version`, `status` ∈ {`indexed`, `not_indexed`}. Nunca devuelve el libro completo.

`health` — salida: `status`, `dependencies` y `capabilities.available_modes`. Sin secretos ni rutas.

**Errores.** Forma única y estable `{ "error": { "code", "message", "details" } }`, con `code` en {`invalid_request`, `document_not_found`, `mode_not_available`, `index_unavailable`}. `message` es legible y sin detalles internos; `details` nunca incluye rutas del sistema ni secretos; `invalid_request` puede llevar `details.field`; `mode_not_available` lleva `details.mode` y `details.available_modes`.

**Identificadores públicos frente a identificadores internos.** `document_id` es un slug estable asignado en la ingesta; `document_version` deriva del hash del contenido de la fuente; `chunk_id` es `{document_id}:{document_version_short}:{ordinal}` (1-based, orden de lectura), determinista y reconstruible; `section_path` es una lista ordenada de cadenas (capítulo → sección → subsección) y la sección no se codifica en `chunk_id` para no duplicar la fuente de verdad. **Ningún identificador de almacenamiento** (los `rowid` internos de SQLite, de FTS5 o de `vec0`, ni rutas de archivo) **se expone en el contrato**.

**Versión del documento frente a versión del índice.** Son independientes y ambas viajan en la respuesta: `document_version` cambia cuando cambia la fuente; `index_version` es una huella de los insumos de construcción del índice (hash del documento, extractor, su versión y su configuración efectiva, `chunking_config_version`, tokenizer del análisis léxico, versión de SQLite, versión fijada de `sqlite-vec` **y el descriptor de embeddings de `D-11 §4.1`**), por lo que cambia aunque la fuente no cambie.

**Límites.** Consulta máxima 1000 caracteres; `top_k` máximo 50; timeout por defecto 5 s. Todos configurables; los valores por defecto no son constantes universales.

**Campos reservados** (no se agregan ahora; cuando lleguen deben ser aditivos, nunca renombres): aceptar `vector`/`hybrid`, `retriever` por resultado, rangos o puntuaciones por recuperador, modelo y dimensiones de embeddings, métrica de similitud.

**Aprobación:** propietario, 2026-10-10.

### D-03 — Embeddings · PARCIALMENTE CERRADA

**Decisión adoptada:**

- Se **difiere la selección del modelo de embeddings**. La búsqueda léxica (BM25 vía FTS5) es la línea base del MVP y **no se bloquea** por esta elección.
- **Candidatos preseleccionados** para cuando la fase vectorial se apruebe: `voyage-4` (Voyage AI) y `text-embedding-3-small` (OpenAI). La elección se hará por **medición sobre el conjunto etiquetado**, no por precio.
- **El coste no decide.** La ingesta del piloto (~200.000 tokens estimados) cuesta menos de tres centavos en todos los candidatos y **cero** en la serie 4 de Voyage (pool de 200M tokens gratuitos). En consulta tampoco: el coste relevante del camino de lectura es la **latencia y la dependencia externa**, no la factura.
- **Prohibido el free tier de Gemini para el texto del libro**: declara usar el contenido para mejorar los productos de Google. Si alguna vez se evalúa `gemini-embedding-001`, debe ser en el tier pago.
- **Reglas de versionado, aplicables a cualquier modelo futuro:** cambiar el modelo, su versión o la dimensión exige **regenerar todos los vectores, reconstruir el índice y reevaluar la recuperación**. Nunca se mezclan vectores de modelos o dimensiones distintas en un mismo espacio. Un truncado tipo Matryoshka (por ejemplo 1536 → 512) cuenta como cambio de dimensión. Re-embeber con la misma fuente produce un **nuevo `index_version`** con el **mismo `document_version`** (D-07).
- **Requisitos de registro cuando existan vectores:** proveedor, modelo y versión, dimensión efectivamente usada, métrica de distancia, normalización y quién la aplica, límite de entrada y política de truncado, texto embebido verbatim con su `content_hash`, y la versión de configuración de embeddings. **`index_version` incorpora el modelo de embeddings** desde el acto que añade el séptimo insumo (`D-11 §4.1`): la identidad de una construcción vectorial distingue proveedor, identificador y versión del modelo, dimensión efectiva, política de dimensión, operación de normalización del cliente, plantilla de texto aplicada y política de entrada. **Hechos documentados que sostienen este apartado** —cuya validación empírica en la integración queda pendiente—: los embeddings del modelo se devuelven **normalizados a norma L2** y `text-embedding-3-small` cuenta tokens con **`cl100k_base`**. Por eso el descriptor **no** declara la normalización del proveedor —es comportamiento del modelo— y sí declara el tokenizador con el que se mide el límite de entrada. **Acortar dimensiones** exige distinguir el camino: pedir el acortado al proveedor o recortar y re-normalizar en el cliente (`dimension_policy`).

**Lo que queda abierto:** la elección del proveedor y del modelo, y la dimensión efectiva. Ambas se resuelven con la medición de la fase vectorial.

**Aprobación:** propietario, 2026-10-10.

### D-06 — Transporte MCP y límites de acceso · CERRADA (dirección arquitectónica de Fase 0)

**Es un cierre arquitectónico, no una validación.** Fija la dirección acordada; **no** afirma que la integración esté implementada ni validada. Quedan pendientes compatibilidad, autenticación, configuración y operación (VAL-D06-01 … VAL-D06-05).

**Decisión adoptada:**

1. **Transporte: Streamable HTTP.** El SSE heredado queda descartado: Pi no lo admite y la especificación MCP lo marca como deprecado.
2. **Ubicación:** el servidor MCP se ejecuta en la Orange Pi, junto al índice SQLite, conforme a D-02.
3. **Red:** el servicio escucha **exclusivamente** en la interfaz Tailscale de la Orange Pi. No se permite enlazar a `0.0.0.0`, publicar el servicio en Internet ni configurar redirecciones de puerto en el router.
4. **Consumidor inicial:** Pi / Gentle Shell en Windows. No se incorporan requisitos para otros clientes hasta que exista una necesidad explícita.
5. **Autenticación:** bearer token **independiente** para este servicio. El secreto se almacena fuera del repositorio y se entrega al consumidor mediante configuración local protegida. **No** se reutiliza automáticamente el token de otro servicio MCP.
6. **Aislamiento operativo:** el servicio tiene **nombre de unit y puerto propios**, distintos de `mcp-server.service` y del puerto `:8003` del servicio de bookgraph. **Nunca** se ejecuta una instancia manual junto al servicio: dos procesos compitiendo por el mismo puerto produjeron el incidente de **43.558 reinicios** documentado en ese host.
7. **Superficie MCP:** únicamente las operaciones de lectura de D-07 — `search`, `get_document` y `health`. La ingesta, la reconstrucción del índice y cualquier operación administrativa quedan fuera de la interfaz MCP de consulta.
8. **Validación de solicitudes:** se respetan los límites de D-07, incluidos `query` de hasta 1.000 caracteres, `top_k` de hasta 50 y el timeout definido allí. El timeout de 60 s del cliente Pi **no sustituye** el límite de consulta del servicio.
9. **Exposición de herramientas en Pi:** `deferred` o `codemode` como **preferencia conservadora**. `direct` es **técnicamente admisible** con tres herramientas (el límite es diez) y puede adoptarse con una justificación; no es una restricción técnica.
10. **Observabilidad:** los logs no registran texto crudo de consultas, contenido recuperado, secretos ni rutas sensibles. Se usan metadatos mínimos y, cuando corresponda, fingerprints protegidos. Los detalles se cierran en el diseño operativo.
11. **Registro en el consumidor (provisional):** se acepta el ámbito **user-level** de `~/.pi/agent/mcp-adapter.json`, por ser el **único mecanismo identificado** para el adaptador actual. Se documenta como **mecanismo actual identificado, no como garantía permanente del arnés**. Debe verificarse antes de implementar. No se modifican configuraciones globales de Pi ni el adaptador.

**Resueltas en esta decisión:** OD-2 (HTTP directo, no puente SSH) y OD-6 (`health` sí se expone).

**Aprobación:** propietario, 2026-10-10.

### D-08 — Topología y despliegue del servicio MCP · CERRADA

**Decisión adoptada — OD-1, ciclo de vida:**

- El MCP es un **proceso independiente**, con **unidad systemd propia** y **entorno `uv` propio**.
- El proceso MCP abre el índice SQLite en **modo de solo lectura**.
- La **ingesta y la reindexación quedan reservadas a la CLI**.
- La integración del MCP en una **única aplicación** junto con la API HTTP queda **descartada para el MVP**.
- **Motivo:** convierte la separación entre consulta y administración en una propiedad estructural del proceso, en lugar de una restricción de configuración (D-06 punto 7 y `001 §8`), y aísla el radio de impacto en un host con historial de ciclos de reinicio por puertos compartidos. No duplica casos de uso: `001 §4` ya define una sola capa de aplicación con adaptadores por transporte.

**Decisión adoptada — OD-3, puerto y unidad:**

- **Puerto objetivo: `8020`.**
- **Unidad systemd: `book-text-rag-mcp.service`.**
- El servicio se enlaza **exclusivamente a la interfaz Tailscale**, con **configuración fail-closed**. **No se permite escuchar en `0.0.0.0`.**
- El **puerto debe comprobarse nuevamente antes del despliegue**.

**Contrato de solo lectura — precisión y verificación:**

- La restricción aplica al **índice SQLite** y a **cualquier otro dato persistente del proyecto**: el proceso de consulta no crea, modifica ni elimina datos persistidos. No altera la superficie definida en D-06 punto 7 (las operaciones de lectura de D-07, y ninguna otra).
- **Única escritura admitida:** el registro operativo de metadatos de D-06 punto 10, con el contenido allí acotado (sin texto crudo de consultas, sin contenido recuperado, sin secretos ni rutas sensibles).
- El proceso **no debe requerir permiso de escritura sobre el archivo del índice**. Si el motor necesitara archivos auxiliares junto al índice, deben declararse explícitamente en el diseño operativo en lugar de darse por supuestos.
- **Estado: requisito documental, no propiedad implementada ni verificada.** La implementación deberá **demostrar** estas propiedades con evidencia; declararlas en la documentación no las acredita.

**Límites de la evidencia de OD-3:**

- El inventario de puertos es una **fotografía**: «libre hoy» **no** equivale a «sin asignar», y no se inspeccionaron los archivos de despliegue de otros proyectos.
- La cobertura de unidades se limitó a `/etc/systemd/system/` más un listado filtrado; un unit empaquetado que reclamara un puerto no habría aparecido.
- La reserva del puerto **no** puede garantizarse por inspección; solo se reduce la probabilidad de colisión.

**Alcance:** esta decisión **no autoriza** reservar el puerto ni crear la unidad systemd. Queda sujeta al requisito previo **RP-01**, resuelto documentalmente en **D-14**.

**Aprobación:** propietario, 2026-10-10.

### D-09 — Política de autenticación del servicio MCP y requisitos operativos del token · CERRADA

**Qué cierra y qué no.** Cierra la **política documental** de autenticación y los **requisitos** que la implementación deberá satisfacer. **No** cierra la implementación, **no** cierra ninguna decisión operativa y **no** declara verificado ningún comportamiento: los detalles operativos siguen expresamente pendientes, en la lista al final de esta decisión.

**Alcance y vigencia.** D-09 completa la política de autenticación y **no reemplaza** lo ya acordado. Siguen vigentes: el token independiente, el secreto fuera del repositorio y la entrega por configuración local protegida (**D-06 punto 5**); la superficie pública (**D-06 punto 7** y **D-07**); el proceso independiente, la unidad systemd propia y el enlace a la interfaz Tailscale (**D-08**); y la observabilidad sin secretos (**D-06 punto 10**). **D-09 no reabre ni modifica D-06, D-07 ni D-08**, y **no introduce códigos nuevos** en el contrato de errores de D-07.

**Principios y requisitos adoptados:**

- **Forma del secreto.** El secreto es un **archivo externo al repositorio**, con permisos restrictivos (0600) y propietario del usuario del servicio. El repositorio no lo contiene en texto, ni en configuración versionada, ni en ejemplos.
- **Inyección: preferencia, no elección resuelta.** Se **prefiere** el mecanismo nativo de systemd para credenciales, porque evita depositar el valor en el entorno del proceso y en el archivo de la unidad. `EnvironmentFile=` se conserva **únicamente como alternativa condicionada** a una evaluación explícita de sus riesgos: por ese camino el valor queda en el entorno del proceso. **Ninguno de los dos se declara elegido**: la elección requiere evidencia del entorno futuro y se resuelve antes de implementar.
- **Propiedad exigida a la inyección.** El **valor** no debe aparecer en la línea de comandos, en el archivo de la unidad, en la configuración versionada, en los logs ni en mensajes de error. La **ruta** del secreto es configuración; el valor, no.
- **Entrega al consumidor autorizado.** La entrega es **fuera de banda** —nunca por chat, commit ni ticket— y el token **nunca** se incorpora al archivo de configuración versionado del consumidor. El uso de una **variable de entorno de ámbito de usuario** se registra como **opción candidata**, **no** como mecanismo definitivo: queda sujeto a comprobar que el secreto esté disponible para el cliente cuando se inicia desde el menú. Si esa vía no resulta fiable, **la elección de una alternativa deberá documentarse antes de implementar la integración**.
- **Rotación: continuidad como requisito a satisfacer y verificar.** La rotación debe poder realizarse **sin interrumpir el acceso y sin ampliar la exposición** del servicio. Es un **requisito que la implementación deberá satisfacer y verificar**; **no** es un comportamiento garantizado hoy. Deben distinguirse tres cosas diferentes: que el **proceso esté disponible** (escucha y responde), que una **credencial sea aceptada**, y que una **revocación sea efectiva** (el valor anterior deje de ser aceptado). Si la implementación no puede garantizar una rotación sin interrupción de acceso, **deberá documentar la limitación y solicitar una decisión antes del despliegue**. El rechazo del valor anterior durante la ventana de desincronización **no se promete como inmediato**: depende del mecanismo de carga o relectura del secreto, que sigue pendiente.
- **Revocación.** Rotar el secreto **es** el mecanismo de revocación: con un único token no hay revocación selectiva. La **efectividad** de la revocación —que el valor anterior deje de ser aceptado— **no está establecida**, porque depende de cuándo el servicio carga o relee el secreto. Mientras ese punto siga sin definirse, no puede afirmarse ni su inmediatez ni el comportamiento observable frente a un token revocado.
- **Credenciales ausentes o inválidas.** La autenticación pertenece a la **capa de transporte** y se resuelve **antes** del contrato de aplicación: se responde de forma **genérica**, **sin** distinguir el caso, **sin** filtrar el valor presentado, **sin** devolverlo y **sin** introducir códigos nuevos en el enum de errores de D-07. En el transporte HTTP de D-06 el código esperado es `401`. El valor nunca se registra; el fallo puede registrarse como metadato (marca temporal y resultado), conforme a **D-06 punto 10**.
- **Estado.** El cierre es **documental**: fija la política y los requisitos operativos del token. **No** cierra la implementación ni los detalles operativos de la lista siguiente. **Nada está implementado ni verificado.**

**Decisiones operativas pendientes — explícitamente fuera del cierre de D-09:**

- Mecanismo de inyección y su disponibilidad en el entorno futuro.
- Momento en que el servicio carga o relee el secreto, del que dependen la efectividad y la inmediatez de la revocación.
- Orden de rotación, ventana admisible y eventual solapamiento temporal de dos tokens.
- Ubicación exacta del archivo del secreto y su exclusión de las copias de seguridad.
- Mecanismo concreto de entrega al consumidor y su verificación.
- Comportamiento observable frente a un token revocado.
- Confirmar si puede garantizarse una rotación sin interrupción de acceso; si no, documentar la limitación y solicitar una decisión antes del despliegue.

**Aprobación:** propietario, 2026-10-10.

### D-10 — Configuración de indexación léxica del piloto · CERRADA

**Qué cierra y qué no.** Fija los parámetros que integran `chunking_config_version` y el analizador léxico que forma parte de `index_version`. Cierra **PD-13**, **P-01** y **P-02**. **No** declara verificado ningún comportamiento, **no** cierra ninguna cuestión operativa y **no** altera la composición de `index_version` fijada en `001 §6.1` y recogida en D-07. Los valores que adopta son **provisionales** y su revisión está reglada aquí.

**PD-13 — Analizador léxico de FTS5.**

- Se adopta **`unicode61` con `remove_diacritics=2`** como analizador inicial del índice léxico.
- **`porter` queda fuera de la configuración inicial.** Es una transformación dependiente del idioma que vuelve menos explicable la línea base, y no existe medición que la justifique. Se evalúa **después**, como configuración propia.
- El analizador, con sus opciones, es un **insumo separado de `index_version`** (definido en `001 §6.1` y recogido en D-07) y se registra junto a cada resultado de evaluación (`003`).

**P-01 — Unidad de conteo y tope.**

- **Unidad: palabras.** Es determinista, no depende del analizador léxico ni de ningún proveedor de embeddings, y la distribución medida ya está expresada en palabras. El tope es **solo un umbral de desborde** (D-05 pto. 1): el corte lo decide la jerarquía, así que el tope no necesita coincidir con la tokenización del índice.
- **Tope provisional: 1.500 palabras**, valor **aproximado al p75 medido de 1.506 palabras** (126 hojas en capítulos: p25 476 / mediana 946 / p75 1.506 / máximo 4.673). Las **34 hojas que lo superan incluyen a las 11 que superan 2.500 palabras**. Preserva intactas alrededor del 73 % de las hojas y acota la cola.
- **Límite de la evidencia:** el tope **no** proviene de ninguna medición de calidad de recuperación y deriva de la distribución de un único libro. **No es un valor óptimo.**
- **Regla de revisión:** cuando exista la base etiquetada, si la recuperación muestra pérdida de precisión atribuible al tamaño del fragmento, se revisa el tope. Todo cambio genera un **nuevo `chunking_config_version`** y un nuevo `index_version`, y obliga a repetir la evaluación con el mismo conjunto de preguntas (`003`).

**P-02 — Overlap.**

- **Overlap provisional: 0 palabras.** El corte ya se produce en límites de párrafo y dentro de la misma unidad (D-05 ptos. 3 y 7), y cada fragmento conserva su camino de sección, por lo que la pérdida de contexto en la frontera queda acotada. Evita duplicación, mantiene el índice mínimo y no infla resultados redundantes en `Precision@k`.
- **Regla de revisión:** si la evaluación muestra pérdida en los límites, se introduce solapamiento **dentro de la misma unidad**, expresado en palabras, como nueva versión de configuración.

**Versionado.**

- `chunking_config_version` se identifica mediante una **huella determinista de la configuración estructural y de sus parámetros efectivos**: las reglas estructurales de D-05 aplicadas, junto con la unidad de conteo, el tope y el solapamiento adoptados aquí, y las tres reglas incorporadas por `D-19` §3 —fin de contenido, exclusión del mobiliario de página y procedimiento de anclaje—.
- El **analizador léxico permanece como insumo separado** de `index_version` y **no** forma parte de `chunking_config_version`.
- **No se altera la composición de `index_version` fijada en `001 §6.1` y recogida en D-07.**
- **Algoritmo:** `chunking_config_version` es el resultado de **SHA-256** sobre los bytes canónicos de la configuración, expresado en hexadecimal y **truncado a sus 12 primeros caracteres**, conforme al formato que `001 §6.1` ya fija para las huellas del proyecto.
- **Entrada canónica:** un objeto JSON con **exactamente** estos campos, **en este orden**, todos obligatorios y ninguno opcional: `schema`, `segmentation_unit`, `heading_start`, `split_boundary`, `parent_own_text`, `table_blocks`, `excluded_regions`, `overlap_scope`, `count_unit`, `max_words`, `overlap_words`, `content_end`, `page_furniture`, `anchoring_procedure`, `geometry_tool`. El manifiesto es **declarativo**: enuncia qué reglas se aplicaron, no las deduce. Valores adoptados: `schema` = `"chunking_config/v3"`; `segmentation_unit` = `"hierarchy_leaf"`; `heading_start` = `true`; `split_boundary` = `"paragraph_within_unit"`; `parent_own_text` = `"own_fragment"`; `table_blocks` = `"atomic"`; `excluded_regions` = `["front_matter","back_matter","index"]`; `overlap_scope` = `"same_unit"`; `count_unit` = `"words"`; `max_words` = `1500`; `overlap_words` = `0`; `content_end` = `"next_heading"`; `page_furniture` = `"excluded"`; `anchoring_procedure` = `"anchoring/v1"`; `geometry_tool` = la **herramienta de geometría efectiva** de la ingesta —marcadores, tipografía y coordenadas—, registrada por corrida. `index` se declara **además** de `back_matter` porque D-05 pto. 6 lo nombra explícitamente dentro de ella: la enumeración **no** implica que sean regiones disjuntas, y el orden declarado es `front_matter`, `back_matter`, `index`.
- **Representación de valores:** enumerados en `snake_case` minúscula; enteros sin separadores de miles, sin decimales y sin comillas; booleanos como `true`/`false`. `schema` versiona **únicamente la estructura del manifiesto** —campos, tipos y orden—; los cambios de **configuración** se reflejan en `chunking_config_version`, **no** en `schema`.
- **Serialización canónica:** JSON en **UTF-8 sin BOM**, cadenas normalizadas **NFC**, claves en el orden de la lista anterior (ni alfabético ni dependiente de la librería), **sin espacios** alrededor de `,` y `:`, **sin salto de línea final**, y arreglos en el orden declarado. La huella se calcula sobre **esos bytes exactos**.
- **Ejemplo ilustrativo:** bytes canónicos de la configuración adoptada, en una sola línea, sin espacios y sin salto final: `{"schema":"chunking_config/v3","segmentation_unit":"hierarchy_leaf","heading_start":true,"split_boundary":"paragraph_within_unit","parent_own_text":"own_fragment","table_blocks":"atomic","excluded_regions":["front_matter","back_matter","index"],"overlap_scope":"same_unit","count_unit":"words","max_words":1500,"overlap_words":0,"content_end":"next_heading","page_furniture":"excluded","anchoring_procedure":"anchoring/v1","geometry_tool":"PyMuPDF 1.26.7"}`
- **Efecto exigido:** todo cambio relevante en las reglas estructurales de D-05 aplicadas o en los parámetros adoptados aquí —tope, solapamiento, unidad de conteo, fin de contenido, mobiliario de página, procedimiento de anclaje o herramienta de geometría— **debe producir una entrada canónica distinta** y, **salvo colisión de la huella truncada, un identificador distinto**. La unicidad de la entrada canónica es una propiedad del manifiesto y de su serialización determinista; la unicidad del identificador depende además de la resistencia a colisiones del hash truncado.
- **Correspondencia entre manifiesto y comportamiento.** El manifiesto **no se redacta aparte**: debe **derivarse de la misma fuente de configuración que el fragmentador consume**, de modo que declarar una regla distinta de la aplicada exija cambiar el código que fragmenta. Sobre esa base, la correspondencia debe ser **verificable con propiedades observables de los fragmentos producidos, sin inspeccionar el interior del pipeline**: (i) el arranque en el encabezado se verifica según **RP-02**; (ii) ningún fragmento cruza el límite de su unidad; (iii) los bloques de tabla aparecen enteros; (iv) ningún fragmento proviene del front matter, del back matter ni del Index; (v) el **único** fragmento que puede superar `max_words` es un bloque de tabla declarado atómico: la atomicidad de las tablas (D-05 pto. 5) **prevalece** sobre el tope, que es solo un umbral de desborde, y superarlo en ese caso **no invalida** la configuración ni su huella. (vi) la cobertura entre unidades consecutivas es **contigua y sin solape** (`D-18` §2.5); (vii) ninguna línea del contenido es un **número de página** (`D-18` §3.6). **Criterio documental: no verificado en esta etapa.**
- **Limitación conocida:** el truncamiento a 12 caracteres hexadecimales (48 bits) se **hereda** de `001 §6.1` y no se revisa aquí. A la escala de este proyecto el riesgo de colisión es despreciable, pero una colisión sería **silenciosa**: dos configuraciones distintas se leerían como la misma.

**Regla de evaluación de alternativas.** Una alternativa de analizador (por ejemplo `porter`) se evalúa como **configuración separada**: produce su propio `index_version`, se mide con el **mismo conjunto de preguntas** y sus resultados se registran aparte. **Nunca** se altera retrospectivamente una línea base ya congelada: cambiarla equivale a crear una configuración nueva.

**Aprobación:** propietario, 2026-10-11.

### D-11 — Huellas del proyecto: alcance, algoritmo y serialización canónica · CERRADA

**Qué cierra y qué no.** Cierra **RP-03** y completa el alcance de las huellas de la ingesta. Fija **alcance, algoritmo y representación** de las cuatro huellas del proyecto. **No** declara verificado ningún comportamiento, **no** cierra ninguna cuestión operativa, **no** cambia la composición de `index_version` fijada en `001 §6.1` y **no** modifica la definición de `chunking_config_version` de D-10, **salvo** la **política de emisión de sus bytes** añadida por esta extensión.

**Algoritmo común: SHA-256**, en hexadecimal en minúsculas, para las cuatro huellas. Un **único algoritmo** por coherencia con D-10, por estar en la biblioteca estándar de Python —sin dependencias nuevas, conforme a `AGENTS.md`— y porque ninguna de las cuatro tiene requisitos de rendimiento o de tamaño que justifiquen una excepción.

**1. `document_version` — versión del documento.**

- Cubre los **bytes originales del archivo fuente** tal como se recibe, **sin normalización alguna**: no se re-codifica ni se normalizan finales de línea. **No** incluye el nombre ni la ruta del archivo: renombrarlo no cambia la versión.
- **No** cubre el texto extraído. La extracción es un insumo de construcción del índice, no del documento: si cambia el extractor cambia `index_version` y **no** `document_version`, que es la independencia ya fijada en `001 §6.1` y D-07.
- Valor formal: **SHA-256, hexadecimal en minúsculas, 64 caracteres**, sin truncar. Es este valor el que viaja en el contrato.

**2. `document_version_short` — forma corta.**

- Son los **primeros 12 caracteres** del valor formal de `document_version`. **No** se calcula una segunda huella.
- Se usa **únicamente** dentro de `chunk_id`, conforme a la notación de `001 §6.1`.

**3. `content_hash` — huella del fragmento.**

- Cubre la **representación UTF-8 del contenido lógico definitivo que se persiste** —la cadena de `content` tal como queda definida antes de guardarse—, y se calcula **antes de cualquier operación de almacenamiento**: el motor de almacenamiento no interviene en la huella.
- La codificación **no añade BOM** y **no** se aplica normalización posterior.
- **Distinción exigida:** el **texto extraído** —salida del extractor, con su estructura y su espaciado— y el **contenido lógico definitivo** —`content`, ya recortado a su unidad y con las transformaciones que el pipeline aplique— **no son necesariamente idénticos**. La huella cubre el segundo. Cualquier normalización debe ocurrir **antes** de definir ese contenido, de modo que la huella corresponda siempre al texto servido y pueda comprobarse contra él.
- Valor formal: **SHA-256, hexadecimal en minúsculas, 64 caracteres**. Es un valor de **integridad**, no un identificador de dirección: **no** se trunca.

**4. `index_version` — versión del índice.**

- **Composición:** los **seis insumos** de `001 §6.1` se conservan **intactos y en ese orden** — (1) hash del documento, (2) extractor, su versión y su configuración efectiva, (3) `chunking_config_version`, (4) tokenizer del análisis léxico, (5) versión de SQLite, (6) versión fijada de `sqlite-vec` —, y **§4.1** añade el **séptimo insumo, último**: el descriptor de `embeddings`, después de `sqlite_vec_version`. **No** se agrega, se quita, se reordena ni se modifica ninguno de los seis originales.
- **Entrada canónica:** un objeto JSON con **exactamente siete campos**, en ese orden: `document_version`, `extractor`, `chunking_config_version`, `tokenizer`, `sqlite_version`, `sqlite_vec_version`, `embeddings`. Los valores **escalares son cadenas**; los únicos valores que no son cadenas son `extractor`, cuyo valor es un **arreglo ordenado de tres cadenas**: nombre del extractor, su versión y su **configuración efectiva** (`D-19` §2), y `embeddings`, el **arreglo de descriptores** que fija **§4.1** —cero elementos en una construcción léxica, uno en una construcción con componentes de embeddings—. `tokenizer` es la **cadena de declaración del tokenizer tal como se usa en la definición del índice** (por ejemplo `unicode61 remove_diacritics 2`); las versiones se escriben **como cadenas**, sin reformatear (por ejemplo `3.50.4`, `0.1.9`), y **nunca** se tratan como números.
- **Serialización canónica.** Hereda de D-10 y se mantiene: JSON en **UTF-8 sin BOM**; claves en el orden fijado arriba (ni alfabético ni dependiente de la librería); **sin espacios** alrededor de `,` y `:`; **sin salto de línea final**; arreglos en el orden declarado. Las cadenas se normalizan a **NFC antes** de serializarlas.
- **Reglas de escape, que D-10 no fija** y sin las cuales la serialización no es reproducible:
  - la comilla doble se escribe siempre como `\"` y la barra invertida siempre como `\\`;
  - los caracteres **U+0000–U+001F** se representan **siempre** como `\u00xx`, con dígitos hexadecimales **en minúsculas**, **incluidos** los que JSON también permitiría escribir con escapes cortos (`\b`, `\t`, `\n`, `\f`, `\r`): no se usan formas cortas;
  - la barra inclinada `/` **no** se escapa;
  - los caracteres **no ASCII** se emiten **literalmente en UTF-8**, sin convertirlos a escapes Unicode.
- **Caja del hexadecimal, que D-10 tampoco fija:** el resumen se expresa en **minúsculas** antes de truncarlo.
- **Diferencia declarada:** D-10 fija el formato —UTF-8 sin BOM, NFC, orden de las claves, ausencia de espacios alrededor de los separadores, ausencia de salto de línea final y orden de los arreglos— pero **no** la política de escape ni la caja del hexadecimal. Esta decisión **no afirma que la serialización sea idéntica a la de D-10**: hereda sus reglas y **añade** estas. **No se modifica el texto de D-10.** El ejemplo canónico de D-10 solo contiene valores ASCII, así que la política de escape no lo altera.
- **Alcance de la política de emisión para `chunking_config_version`.** D-10 fija tres cosas que esta bullet no toca: los **campos** del manifiesto con su representación de valores y su orden —la **semántica y la estructura** de la configuración—, el **resultado** de la huella —SHA-256 sobre los bytes canónicos— y su **truncamiento a 12 caracteres**, que sigue siendo regla de D-10 (línea «Algoritmo») y que aquí no se introduce ni se revisa. Lo único que esta bullet añade es la **política de emisión de esos bytes**: se emiten con **la misma codificación y escape que el resto de esta decisión** — UTF-8 sin BOM, cadenas normalizadas a NFC antes de serializar, `\\` y `\"` para barra invertida y comilla doble, U+0000–U+001F siempre como `\u00xx` con dígitos **en minúsculas** (sin formas cortas), `/` sin escapar, no-ASCII literal en UTF-8 — y el resumen se escribe en **hexadecimal en minúsculas** antes del truncamiento que D-10 ya fija. Esta regla **no modifica la definición de campos, valores ni semántica de D-10**: dice cómo se emiten los bytes que D-10 ya define. El manifiesto adoptado contiene únicamente ASCII, así que la política no altera su ejemplo canónico; queda fijada para cualquier valor futuro.
- **Cálculo:** se aplica **SHA-256 sobre los bytes exactos** resultantes de esa serialización; el resumen se expresa en **hexadecimal en minúsculas** y se **trunca a sus 12 primeros caracteres**.
- **Valores ausentes o inválidos:** el cálculo **no admite sustitutos**. Si alguno de los siete insumos falta o no es válido —campo omitido, cadena vacía, `null` o tipo incorrecto; en `embeddings`, además, lo que fija §4.1—, **`index_version` no se calcula** y la indexación **falla de forma explícita**: no se usa valor por defecto ni marcador de posición. Sustituir un insumo etiquetaría índices distintos como iguales en silencio, que es la clase de fallo que `002` y D-10 evitan.

**Truncamiento y colisiones.** `chunking_config_version`, `index_version` y `document_version_short` se truncan a **12 caracteres hexadecimales (48 bits)**, conforme a `001 §6.1`. A la escala del proyecto el riesgo de colisión es despreciable, pero una colisión sería **silenciosa**. `content_hash` no se trunca porque es un valor de integridad.

**§4.1 Insumo `embeddings` (séptimo insumo de `index_version`).**

`index_version` incorpora un séptimo insumo, **al final** de la entrada canónica y después de `sqlite_vec_version`. Su valor es un **array de descriptores** con **cero o un** elemento: cero para una construcción **léxica**, uno para una construcción con componentes de embeddings. Cada descriptor es un **objeto** con exactamente los ocho campos siguientes, **en este orden declarado**, sin campos adicionales:

| # | Campo | Tipo | Gramática |
|---|---|---|---|
| 1 | `provider` | cadena | no vacía |
| 2 | `model_id` | cadena | no vacía |
| 3 | `model_version` | cadena | `snapshot:<id>` \| `alias:<id>@<fecha>` (gramática abajo) |
| 4 | `dimension` | entero | ≥ 1; se emite en dígitos decimales, sin signo ni ceros a la izquierda |
| 5 | `dimension_policy` | cadena | `native` \| `provider_shortened` \| `client_shortened` |
| 6 | `client_normalization` | cadena | `none` \| `l2` |
| 7 | `text_template` | cadena | `none` \| `template:<64 hex minúsculas>` |
| 8 | `input_policy` | cadena | `none` \| `reject_over:<tokenizador>/<n>` |

**Gramática de `model_version`.** Dos formas mutuamente excluyentes: `snapshot:<id>` y `alias:<id>@<fecha>`. `<id>` es una secuencia de **1 a 128** caracteres del conjunto `[a-z0-9._-]` —sin `:`, sin `@`, sin espacios y sin mayúsculas—. `<fecha>` es una fecha ISO 8601 completa `YYYY-MM-DD` que debe ser un **día de calendario válido**; se rechazan, por ejemplo, `2026-02-30` o `2026-13-01`. El prefijo es exactamente `snapshot` o `alias`, en minúsculas y seguido de `:`; en la forma de alias el `@` aparece **una sola vez**. Se rechaza cualquier otro valor: un alias desnudo, `default`, una fecha incompleta, un `<id>` con caracteres fuera del conjunto, o los dos prefijos juntos.

**Consecuencia sobre la etiqueta.** La entrada canónica es una función determinista de sus siete insumos: cambiar el valor de **cualquiera** de los ocho campos del descriptor cambia los bytes de la entrada y, por tanto, la etiqueta. Con SHA-256, dos entradas distintas producen etiquetas distintas **salvo que ocurra una colisión** de la función —evento que se considera despreciable en la práctica, pero que **no** se declara imposible—. Esta sección no introduce ninguna garantía criptográfica nueva: se apoya en la misma función que §4 ya adopta.

**`snapshot` frente a `alias`.** `snapshot:<id>` designa una instantánea que **el proveedor declara inmutable**; su inmutabilidad es un **compromiso del proveedor, no una propiedad verificada por el proyecto**, y es lo que permite sostener que una construcción es reproducible. `alias:<id>@<fecha>` designa un alias **mutable** resuelto en esa fecha: es una identificación **aproximada**, y dos construcciones con el mismo descriptor pueden producir vectores distintos si el proveedor actualiza el modelo detrás del alias. **Estas tres reglas son normativas del proyecto, no garantías del proveedor:** (i) exigir `snapshot` cuando exista, (ii) admitir `alias` solo en su ausencia, (iii) exigir que la fecha sea la de resolución. El proveedor no documenta ninguna de las tres. La fecha de resolución **registra cuándo resolvimos el alias, no qué implementación respondió**: no identifica por sí sola la versión exacta que atendió la ingesta ni permite reconstruirla. **Ninguna de las dos formas convierte a `model_id` y `model_version` en garantía de que el comportamiento remoto permanezca idéntico de forma permanente**: identifican la configuración declarada, no el comportamiento futuro del proveedor.

**Normalización.** El descriptor registra **solo operaciones del cliente**. La normalización que el propio modelo aplica a su salida queda **atribuida al modelo** y **no** se declara en un campo del descriptor: se considera parte de lo que identifica `model_id` y `model_version`, **sin que ello garantice** que el comportamiento del proveedor permanezca idéntico en el futuro. `client_normalization` describe únicamente lo que el cliente hace con el vector devuelto.

**Acortado de dimensiones.** `dimension_policy` distingue **cómo** se obtuvo la dimensión efectiva, porque los caminos no se asumen equivalentes: `native` (la salida tiene la dimensión nativa del modelo), `provider_shortened` (se pidió el acortado al proveedor, p. ej. con el parámetro `dimensions`) y `client_shortened` (el cliente recortó componentes y **debe** re-normalizar). Invariantes: `client_shortened` exige `client_normalization = l2`; `provider_shortened` exige `dimension` menor que la dimensión nativa del modelo; `dimension_policy = native` exige `dimension` igual a la nativa.

**Plantilla de texto — validación.** Cuando se use una plantilla, su texto debe contener **exactamente un** marcador `{text}`, que designa dónde se inserta el contenido a embeber. Se **rechazan** las plantillas con cero marcadores, con más de uno, con cualquier otra secuencia entre llaves (`{…}`), con variantes del marcador (`{ text }`, `{TEXT}`, `{{text}}`) y con llaves sueltas: un `{` o un `}` que no forme parte exacta de `{text}` es formato inválido. La validación es de **formato**, se comprueba al ingerir y una plantilla inválida **hace fallar la operación**; no se corrige ni se normaliza.

**Plantilla de texto — huella.** `text_template` vale `none` o `template:<64 hex minúsculas>`. La huella es el **SHA-256 completo** de los **bytes UTF-8 exactos del texto de la plantilla tal como se persiste**: sin normalización Unicode, sin recorte de espacios ni de saltos de línea y sin ninguna otra transformación implícita. No se abrevia: no hay restricción documentada que lo justifique. Con `text_template ≠ none` el texto exacto **debe persistirse** para recomputar la huella; dos plantillas que difieran en un solo byte —incluida la normalización Unicode— son plantillas **distintas** con huellas distintas.

**Política de entrada.** `input_policy` declara qué hace **la aplicación** según el conteo de tokens del fragmento, e incluye el tokenizador con el que se cuenta. `none` significa que la aplicación **no impone un límite propio ni aplica truncado**: se embebe el texto completo del fragmento. **No** significa que no existan límites del proveedor, y **tampoco garantiza** que el proveedor acepte la entrada ni que la ingesta vaya a tener éxito: describe únicamente la ausencia de control propio. `reject_over:<tokenizador>/<n>` significa que la aplicación **cuenta los tokens con el tokenizador declarado** y, si el fragmento excede `n`, **rechaza la operación**; el conteo y el rechazo ocurren **antes de enviar** el fragmento al proveedor; no recorta, no omite y no trunca en silencio. **El rechazo es la única estrategia admitida**: adoptar truncado exigiría un acto posterior que defina estrategia, punto de corte y su efecto sobre `content_hash`. **El valor concreto de este campo queda pendiente de decisión**; el identificador del tokenizador debe estar declarado y el conteo debe hacerse con él.

**Integración del fallo con los contratos vigentes.** El rechazo es un **fallo explícito de la ingesta**. **Lo único garantizado hoy proviene de T3:** si el fallo ocurre **dentro** de T3, la transacción revierte y **la unidad no se persiste**. **La transición de estado de la referencia queda pendiente de integración:** depende de dónde se ubique el paso de embeddings en la secuencia T1→T2→T3, decisión que este acto **no** toma, de modo que aquí **no se fija un estado final** ni se afirma que la referencia quede en «incompleta». Si el fallo ocurre **antes** de T3, T3 no se ejecuta y esa garantía no aplica. **No se introducen códigos de error nuevos ni se modifican contratos.**

**Emisión canónica.** El objeto del descriptor se emite **compacto** —sin espacios y con `,` como separador, como el resto de la entrada—, con sus ocho campos en el orden declarado y con la **misma política de escape** de §4 (sin reutilizar `json.dumps` ni `json_canonico`). El array vacío se emite como `[]`, sin casos especiales: es el resultado natural de la misma emisión de arrays. La entrada canónica resultante es la de los seis insumos actuales **más** `,"embeddings":…` inmediatamente antes de la llave de cierre; el descriptor es, por tanto, el **último** campo.

**Cambio de época declarado.** Añadir este insumo cambia el valor de `index_version` para **todas** las construcciones, incluidas las léxicas, aunque sus seis insumos no cambien. El cambio es **único y explícito**, no silencioso: no existen etiquetas persistidas, de modo que no hay migración, y las etiquetas calculadas antes de este acto quedan **sustituidas**. La línea base léxica congelada **no se ve afectada**: su identidad registrada es `document_version` junto a `chunking_config_version`, y `chunking_config_version` y el manifiesto canónico no cambian.

**Prueba de regresión exigida.** La implementación deberá demostrar, para cada vector normativo existente, que los seis insumos conservan **exactamente** sus bytes canónicos. La comparación es entre **secuencias de bytes completas** —no entre valores reconstruidos ni órdenes de campos—: los bytes nuevos deben ser iguales a los anteriores con `,"embeddings":[]` insertado antes de la llave de cierre. Sin esa prueba, este apartado no puede considerarse implementado.

**Sin sustitutos.** Un descriptor ausente, incompleto o con un valor fuera de la gramática **no se completa ni se inventa**: `index_version` no se calcula y la indexación falla de forma explícita, con la misma política que los seis insumos originales.

**Aprobación:** propietario, 2026-10-11; **§4.1** aprobado por el propietario el 2026-10-19.

### D-12 — Estructura física del proyecto · APROBADA como dirección documental; sujetas a aprobación: normalización, `deploy/` y `requires-python`; licencia pendiente

**Estado de esta decisión y distinción de alcance.** Esta decisión se aplica como **propuesta documental de estructura aprobada por el propietario «en lo sustancial»**. Se distinguen tres niveles que **no son equivalentes y no deben confundirse**:

- **Aprobado:** la *propuesta documental de estructura* que cierra **GAP-C** —raíz y nombre; estructura lógica de capas conforme a `001 §4`; ubicación de pruebas, configuración y documentación; empaquetado y punto de entrada; relación con `AGENTS.md` y `uv`—, como **dirección documental**, sin ningún efecto de implementación.
- **Sujetas a aprobación expresa del propietario, y por tanto NO aprobadas por esta decisión:** (a) la **normalización futura de la especificación** (§1); (b) la **adopción del directorio `deploy/`** (§3); (c) el **piso `requires-python = ">=3.13"`** (§4). Cada una conserva su marca propia dentro del texto de su sección.
- **Pendiente de decisión del propietario:** la **licencia** (§5).

**Qué cierra y qué no.** Cierra **GAP-C** —la estructura física del proyecto, vacío registrado en la auditoría de Fase 0— en su alcance documental, como propuesta de estructura. **No** crea directorios ni archivos, **no** ejecuta `git init`, **no** mueve, borra ni duplica ningún archivo, **no** añade arquitectura nueva, **no** altera ninguna decisión cerrada y **no convierte en aprobadas** las decisiones sujetas a aprobación listadas arriba: materializa en ubicaciones concretas las capas ya fijadas en `001 §4` y las reglas ya vigentes en `AGENTS.md`. Toda operación sobre el sistema de archivos o el repositorio es **futura** —de la creación del proyecto— y exige autorización expresa.

**1. Raíz y nombre del repositorio.** *(Aprobado como dirección documental, salvo la normalización, que está sujeta a aprobación.)*

- La raíz es el directorio actual `book-text-rag`. El nombre ya es el correcto y de él derivan el paquete (`book_text_rag`), la unit de D-08 (`book-text-rag-mcp.service`) y la convención de nombres de `data/` (`huyen-ai-engineering.pdf`).
- El repositorio Git se inicializa **en esa raíz** al crear el proyecto, con rama por defecto `main` y sin confirmaciones automáticas: el primer commit es decisión del propietario. `.gitignore` ya existe en la raíz y cubre lo necesario: fuentes de libros, `data/extracted/` y `data/derived/`, bases `*.sqlite` con sus `-wal`/`-shm`, artefactos de Python y del sistema; `uv.lock` queda versionado a propósito.
- **Normalización de la especificación — SUJETA A APROBACIÓN y operación futura de la creación del proyecto, no de esta fase.** El contenido documental —`README.md`, `AGENTS.md` y los cuatro documentos de especificación— pasaría de la anidación actual `book-text-rag-spec-v0.1/book-text-rag-spec/` a la raíz: `README.md`, `AGENTS.md` y `docs/spec/001 … 004`. La anidación es un artefacto de empaquetado de la versión 0.1 de la especificación y hoy es incoherente con el repositorio: `data/README.md` ya referencia `docs/spec/004-decisions.md`, ruta que solo existe dentro de la anidación. El directorio anidado se retiraría tras la copia, sin duplicar contenido; si el propietario quiere conservar la instantánea original, se guardaría una copia **fuera** del repositorio. **Esta fase documental no mueve, borra ni duplica nada**; la mudanza nunca ha estado aprobada y lo sigue sin estar.
- El directorio de herramienta `.atl/` no forma parte del proyecto: se retira o se excluye en `.gitignore` al crear el repositorio.

**2. Estructura lógica de directorios y módulos.** *(Aprobado como dirección documental; la adopción de `deploy/` está sujeta a aprobación; ver §3.)* Refleja exactamente las capas de `001 §4`, sin capas nuevas:

```
book-text-rag/
├── AGENTS.md  README.md  .gitignore  pyproject.toml  uv.lock
├── docs/
│   └── spec/                 # 001-architecture … 004-decisions
├── data/                     # fuentes originales, sin modificaciones (excluida de git)
├── src/
│   └── book_text_rag/
│       ├── domain/           # entidades y reglas (001 §4)
│       ├── application/      # casos de uso y contratos de entrada/salida
│       ├── ports/            # catálogo, extracción, fragmentación, recuperación, embeddings
│       ├── adapters/
│       │   ├── storage/      # SQLite + FTS5 + sqlite-vec (D-02)
│       │   ├── extraction/   # pdftotext -layout (D-04)
│       │   ├── cli/          # operaciones administrativas (001 §7)
│       │   ├── http/         # Fase 3: FastAPI (001 §7)
│       │   ├── mcp/          # Fase 3: Streamable HTTP (D-06, D-08)
│       │   └── embeddings/   # Fase 2, diferida (D-03)
│       └── evaluation/       # datasets y métricas, fuera del camino de consulta
├── tests/
│   ├── unit/                 # dominio y casos de uso con puertos falsos
│   ├── contract/             # CLI, HTTP y MCP (001 §9)
│   └── integration/          # almacenamiento e índice
└── deploy/                   # (sujeto a aprobación) plantilla de book-text-rag-mcp.service (D-08)
```

- `data/` conserva su regla vigente: una fuente por libro candidato, sin artefactos derivados; el texto extraído, los fragmentos y los vectores van a `data/extracted/` y `data/derived/`, excluidos de git.
- Los adaptadores `http/`, `mcp/` y `embeddings/` se crean **cuando llegue su fase** (Fase 3 y Fase 2 respectivamente). El MVP de Fase 1 solo necesita dominio, aplicación, puertos, storage, extraction y cli.
- La dirección de dependencias es la de `001 §4`: adaptadores → aplicación → dominio; dominio y aplicación no importan FastAPI, el SDK de MCP, el SDK de embeddings ni la biblioteca de almacenamiento.

**3. `deploy/` — plantilla de despliegue versionada · SUJETA A APROBACIÓN.** Propuesta separada de la estructura general, con justificación propia:

- **Por qué versionar la plantilla.** D-08 (OD-3) exige **recomprobar el estado del puerto y de la unit antes de desplegar**; ese recomparado necesita una referencia versionada contra la cual comparar. La evidencia observada en este host justifica la referencia: la documentación operativa de bookgraph **divergió de su código** —su runbook (`docs/ops/mcp-service.md` §7) documenta solo `/sse` mientras su código expone `/mcp`— y su propio runbook advierte *"never assume the repo copy describes the running unit"*; además, la clase de fallo `Restart=on-failure` + recurso ausente que motivó **RP-01** nació de un estado de despliegue no reflejado en el repositorio. La plantilla versionada es la única forma de que ese recomparado sea verificable.
- **Alcance exacto.** Es una **plantilla** de referencia: la unit real vive en `/etc/systemd/system/` del host; instalarla, modificarla o recargarla son operaciones de despliegue futuras, con autorización expresa, fuera de esta fase y de la creación del proyecto.
- **Estado:** **no aprobada**. No hay decisión previa que fije dónde vive la plantilla; sin su aprobación, la unit se documenta solo en la especificación y el recomparado pierde su referencia versionada.

**4. Empaquetado y punto de entrada.** *(Aprobado como dirección documental, salvo el rango de `requires-python`, sujeto a aprobación.)*

- **Paquete único `book_text_rag`**, en layout `src/` (`src/book_text_rag/`). El layout `src/` evita importar accidentalmente el paquete desde el directorio de trabajo y es el layout estándar de `uv`.
- `pyproject.toml` (PEP 621) en la raíz, con el rango propuesto `requires-python = ">=3.13"`. **Coherencia con la regla vigente:** `AGENTS.md` fija, textualmente, «Python 3.13; usar `uv` exclusivamente para dependencias, entorno, ejecución y lockfile. No usar `pip` como flujo de proyecto.». La regla fija la **serie 3.13** como intérprete del proyecto y no declara un tope; por eso el rango propuesto es un **piso** (`>=3.13`) —un intérprete anterior queda rechazado por `uv`, coherente con la regla— y **no se acota por arriba**: no existe hoy evidencia técnica que exija una cota, y una cota sin evidencia excluiría intérpretes futuros sin beneficio. La versión **efectiva** del intérprete de producción queda anclada por el lockfile y por el entorno `uv` propio (D-08). **Estado:** el piso `">=3.13"` está **sujeto a aprobación expresa del propietario**: hasta esa aprobación es texto de propuesta, no configuración decidida. **Compatibilidad a comprobar durante la implementación** antes de adoptar cualquier serie posterior: (a) que exista wheel de `sqlite-vec` 0.1.9 para el intérprete y la plataforma del host (VAL-04); (b) que el SQLite del intérprete del host traiga FTS5 (VAL-03); (c) que el lock resuelto con `uv` sea reproducible y sin `pip`; (d) que un cambio de serie del intérprete se trate como cambio documental registrado aquí.
- La configuración de las herramientas —ruff, mypy estricto, pytest— va en el mismo `pyproject.toml`, conforme a `AGENTS.md`. El lockfile se versiona. `uv` es el único gestor; `pip` no es flujo del proyecto.
- **Un único console script: `book-text-rag`.** Subcomandos para las operaciones administrativas de `001 §7` —ingesta, reindexado explícito, auditoría, estado, evaluación— y `serve` para el servidor MCP. La unit de D-08 lanza `uv run book-text-rag serve`. La CLI funciona sin levantar HTTP ni MCP. Los nombres exactos de los subcomandos y la firma de la función de entrada son detalle de implementación.
- Configuración en ejecución: variables de entorno **tipadas** (`001 §8`); secretos fuera del repositorio, en archivo externo con permisos 0600 (D-09); nada de configuración sensible versionada ni impresa en logs.

**5. Licencia · PENDIENTE DE DECISIÓN DEL PROPIETARIO.** El proyecto es un repositorio privado sin distribución y ninguna decisión anterior declara una licencia —la única mención en toda la especificación es la de la dependencia `sqlite-vec` (MIT/Apache-2.0)—. Propuesta: **sin archivo `LICENSE`** mientras no se publique nada; si se decide publicar, la licencia se elige **antes** de la primera publicación y se registra aquí.

**6. Relación con `AGENTS.md` y `uv`.** *(Aprobado como dirección documental.)* Esta decisión no introduce reglas nuevas: les asigna ubicaciones. Python 3.13, `uv` exclusivo, lockfile versionado, Pydantic v2, FastAPI, ruff + mypy estricto + pytest, separación de capas sin imports hacia frameworks y prohibición de secretos en el repositorio ya están en `AGENTS.md`; la estructura física los materializa. Toda discrepancia futura entre la estructura y `AGENTS.md` se resuelve a favor de `AGENTS.md` y se registra.

**Pendientes por fase, no cerrados aquí.** Requieren **implementación**: nombres exactos de subcomandos y firma de la función de entrada. Requieren **evidencia**: las compatibilidades de intérprete de §4 (VAL-03, VAL-04) y el residual de VAL-D06-01/02. Requieren **autorización de despliegue**: instalación y mantenimiento de la unit real en el host.

**Aprobación:** propietario en lo sustancial (estructura documental), 2026-10-11; sujetas a aprobación: normalización de la especificación, `deploy/` y el piso `requires-python = ">=3.13"`; pendiente de decisión: la licencia.
### D-13 — Identidad de documento: asignación de `document_id` y catálogo de fuentes · CERRADA

**Qué decide.** La regla de asignación del identificador de documento y el comportamiento de la ingesta ante reingestas, renombrados, sustituciones de edición, reutilización de nombres y peticiones de identificador explícito, **distinguiendo explícitamente** identidad lógica, huella de bytes, alias, ubicación y datos descriptivos, y la semántica de las decisiones persistidas cuando la ingesta falla. Complementa la frase de `001 §6.1` («slug estable asignado en la ingesta») y `001 §5` («versión opcional» de `get_document`), sin alterar D-11, D-10 ni D-07.

**Conceptos que esta decisión separa.**

- **Identidad lógica del documento — `document_id`:** identifica la **obra**; es estable entre versiones; su valor lo fija la asignación registrada, nunca lo deducen los datos de la fuente por sí solos.
- **Huella de bytes — `document_version`** (D-11 §1): SHA-256 de los bytes originales de la fuente; identifica el **contenido** de una edición concreta. **No prueba identidad de obra**: bytes idénticos no demuestran, por sí solos, que dos registros representen la misma obra — lo que vincula unos bytes con una identidad es la **referencia registrada** del catálogo, nunca la inferencia automática a partir de la igualdad de bytes.
- **Referencia de fuente registrada:** la entrada operativa del catálogo que permite reutilizar una identidad. Por documento, cada referencia consta de: el **alias** (nombre de fuente normalizado, convención de `data/README.md`), la(s) `document_version` incorporadas desde esa fuente, el **tipo de asignación** (por defecto, deliberada, resuelta de una discrepancia), el **estado de ingesta** (sección siguiente) y la fecha. Una referencia de fuente registrada es, por construcción, **una decisión de identidad ya tomada y persistida**.
- **Alias:** el componente de nombre de una referencia de fuente. Puede haber varios por documento (renombrados). Su alta es un registro que **no decide identidades**.
- **Fuente, ubicación y datos descriptivos:** cada archivo físico, su ubicación observada y los registros descriptivos de reingesta. Los datos descriptivos son **información operativa del catálogo**: no son parte del contrato público, no deciden identidades y se rigen por la Regla 6 y por «Comportamiento seguro ante discrepancias».

**Decisión propuesta: catálogo duradero de fuentes con asignación explícita y persistente**, en el que la reutilización de identidad exige una **referencia de fuente registrada**, no la mera igualdad de bytes. El `document_id` por defecto en una primera ingesta sin discrepancia es el slug del nombre normalizado, y el catálogo deja constancia de que fue **por defecto**. El catálogo ya está anticipado por `001 §4` (puerto de «catálogo documental») y es **insumo durable**, no artefacto derivado del índice: regenerar el índice (D-02) no lo altera.

**Reglas propuestas.**

1. **Reingesta de una fuente registrada — el único camino automático, por referencia y no por inferencia.** La identidad se reutiliza **solo si el catálogo contiene la referencia de fuente**: el alias coincide con una referencia registrada y los bytes coinciden con la `document_version` que el catálogo tiene registrada **para esa referencia**. Lo que permite reutilizar es esa asignación previa persistida; la igualdad de bytes es, aparte, una comprobación de que no hubo mutación. La reingesta reconocida **no duplica** (criterio de aceptación de `002` Fase 1) y **actualiza y persiste automáticamente** — dentro de la misma transacción de la reingesta aceptada, sin aprobación manual por cambio y sin efecto de decisión de identidad — **solo los datos descriptivos permitidos por la Regla 6**: la ubicación observada y la fecha del reingesto.
2. **Referencia registrada con bytes distintos — se detiene, no decide.** Un cambio de contenido bajo una referencia registrada puede ser una **nueva edición del mismo documento** o una **obra distinta** que reutiliza el alias. No hay señal técnica que resuelva la intención: la ingesta **se detiene antes de escribir**, presenta las dos lecturas con la evidencia disponible — bytes distintos bajo el mismo alias, `document_version` nuevo y, si existen, los metadatos del PDF como **señal auxiliar, nunca decisora** — y la decisión del operador (nueva versión del mismo `document_id`, o documento nuevo con la identidad que corresponda) queda registrada en el catálogo.
3. **Fuente nueva.**
   - **3a. Bytes ya conocidos sin referencia suficiente:** si los bytes coinciden con una `document_version` registrada pero **ninguna referencia de fuente los invoca** —materialmente: un archivo con nombre no registrado—, **no hay asignación automática y ambigua**; la ingesta se detiene. Bytes idénticos por sí solos no resuelven el caso: solo la decisión registrada del operador —vincular explícitamente esa referencia al `document_id` existente, o crear identidad nueva (respetando la Regla 5)—.
   - **3b. Bytes y alias desconocidos:** propuesta de documento nuevo con `document_id` por defecto = slug del nombre normalizado. Si el slug ya existe como `document_id`, el caso vuelve a la Regla 2 que detiene.
   - **Modo no interactivo** (scripts, tests): toda situación de las Reglas 2–3 sin decisión pre-registrada **falla de forma explícita**; la automatización posible es suministrar antes la decisión en el catálogo o el `document_id` como parámetro explícito (Regla 4).
4. **`document_id` explícito por la CLI — orden contractual, sin fusiones ni reasignaciones silenciosas.** La secuencia es, por documento, **transaccional**: **(1)** validar las asociaciones existentes del catálogo — referencia de fuente, asociación previa de los bytes, colisión de slug; **(2)** si la validación es correcta, registrar en el catálogo la **decisión deliberada** que el parámetro constituye; **(3)** solo entonces aceptar la operación de ingesta. Cualquier error o rechazo aborta la secuencia **sin cambios parciales** en catálogo ni índice. Con un identificador solicitado:
   - **no existe:** tras validar que no hay asociación previa de esos bytes ni colisión de slug, se crea el documento con ese id y se registra la asignación **deliberada** —paso (2)— y luego se ingesta —paso (3)—.
   - **existe y es la fuente registrada** (referencia registrada con los mismos bytes): reingesta idempotente conforme a la Regla 1; solo se aplican los datos descriptivos permitidos.
   - **existe y su referencia de fuente tiene bytes distintos:** el parámetro explícito **constituye la decisión deliberada** de incorporar una versión nueva del mismo documento —paso (2), informado por el comando— y luego se ingesta —paso (3)—. Sin parámetro, rige la Regla 2 (detención).
   - **existen los bytes bajo OTRO `document_id`:** **rechazo explícito en el paso (1), antes de registrar nada** — el parámetro explícito **no** permite fusionar ni reasignar identidades, ni reclamar bytes ya asociados a otra. Una corrección de una asignación errónea sería una **operación de corrección de catálogo** distinta, fuera del flujo de ingesta y sujeta a decisión.
   - **la fuente es nueva y se la asocia a un id existente:** la asociación procede **solo como parte de la decisión deliberada** del paso (2), trazada en el catálogo con su tipo, y la ingesta solo se acepta en el paso (3).
5. **Ninguna fusión silenciosa.** La misma `document_version` no se registra bajo dos `document_id` distintos; cualquier excepción requiere decisión del propietario. La identidad de un documento nunca cambia ni se fusiona automáticamente: solo por decisiones registradas en el catálogo.
6. **Datos descriptivos y altas que no deciden.** Son datos descriptivos permitidos —se persisten **automáticamente** en una reingesta aceptada, **sin aprobación manual por cambio**—: la observación de ubicación, la fecha del reingesto y cualquier metadato descriptivo equivalente. Son **altas descriptivas** el registro de un alias nuevo y de una observación de ubicación: jamás alteran la identidad, no introducen versiones, no fusionan documentos y son reversibles sin efecto sobre el índice. Ningún dato descriptivo es contenido del contrato ni insumo de `document_id`; su persistencia nunca sustituye una decisión de identidad.

**Estados de identidad e ingesta en el catálogo.** Cada referencia de fuente lleva un **estado de ingesta** nominal, con exactamente tres valores, que la decisión no confunde ni mezcla:

- **decisión de identidad registrada:** la asignación quedó persistida en el catálogo. **Su existencia no implica que el documento esté indexado, disponible para consulta ni completo**; significa únicamente que la identidad quedó fijada y que la incorporación está autorizada a proseguir.
- **ingesta incompleta:** registrada la decisión, la incorporación al índice falló o quedó interrumpida. **No hay contenido parcial publicado**; el trabajo pendiente queda identificado por la propia referencia para la reejecución, y el comando informa el fallo.
- **ingesta completada e índice disponible para consulta:** la ingesta y la actualización del índice concluyeron correctamente. **Solo este estado habilita la consulta del documento** y sus resultados.

**Relación con la superficie pública.** Estos estados son internos del catálogo y **no alteran el vocabulario público que D-07 fija —`indexed`/`not_indexed`—, ni introducen estados públicos nuevos (PD-11 queda como está)**. Mientras la incorporación de una versión esté en «decisión de identidad registrada» o «ingesta incompleta», esa versión se presenta ante las superficies públicas como **no incorporada**: `get_document` la reporta con `status: not_indexed` y `search` no puede devolverla, porque el índice no contiene sus fragmentos; **esta exclusión se refiere únicamente a esa versión** y no excluye a una versión anterior que continúe disponible conforme al contrato vigente. **Ningún estado interno de identidad o de ingesta puede hacer que `get_document` o `search` presenten esa versión como disponible antes de tiempo**; el paso a `indexed` se produce **únicamente** cuando la versión está completa y el índice la expone de forma coherente — estado «ingesta completada e índice disponible para consulta» —.

*Esta relación rige hasta que la versión completa concluye y no decide la retención de versiones anteriores («Pregunta abierta declarada 2»).*

**Garantías de recuperación.** Sobre esos estados:
- la reejecución de una referencia en estado «ingesta incompleta» **completa el trabajo pendiente de forma idempotente**: recalcula lo necesario y escribe solo lo que falta;
- **no duplica chunks**: la identidad de cada fragmento es determinista (`chunk_id`, `001 §6.1`), de modo que la reescritura de la misma versión produce los mismos identificadores y la reejecución no genera duplicados;
- **no publica resultados parciales**: los datos de una versión pasan a ser consultables como conjunto de esa versión, no fragmento por fragmento;
- **la incorporación de una versión al índice es total o nada**: mientras no concluya, el índice no contiene fragmento alguno de esa versión, y —si el documento ya estaba indexado y disponible con una versión anterior— esta **permanece íntegra y sin alteración durante todo el fallo de la nueva**: ninguna consulta recibe una mezcla de fragmentos de distintas versiones, y el índice queda exactamente como estaba antes de intentar la incorporación;
- **una referencia pasa a «ingesta completada e índice disponible para consulta» únicamente cuando la ingesta y la actualización del índice concluyeron correctamente**; hasta entonces el documento no es consultable;
- **los errores nunca dejan catálogo ni índice presentándose falsamente como completados**: el estado registrado refleja el hecho real (decisión registrada, ingesta incompleta o completada) y los comandos lo informan tal cual es.

**Comportamiento seguro ante discrepancias — dos regímenes.**
- **Ingesta detenida o rechazada** (Reglas 2–3 y rechazos del paso 1 de la Regla 4): ocurre **antes de cualquier escritura**; **ni el catálogo ni el índice se modifican** (se quedan byte-idénticos), no hay ingesta parcial ni datos intermedios persistidos, y lo único registrado es el **informe de comando** (consola y, si procede, log operativo conforme a D-06 pt. 10, sin consultas crudas, contenido ni rutas sensibles).
- **Ingesta aceptada** (Regla 1 reconocida o Decisión registrada en el paso (2) de la Regla 4 con la ingesta aceptada en el paso (3)): puede actualizar **únicamente los datos descriptivos permitidos** por la Regla 6 —ubicación, fecha— y las escrituras propias de la decisión registrada (referencia de fuente / versión, con su estado de ingesta). Esas actualizaciones descriptivas **se persisten automáticamente**, sin aprobación manual por cambio, porque no deciden identidades; toda escritura sigue siendo de la CLI (D-08), y el índice solo incorpora lo que la decisión registrada autorice.
- **Coherencia transaccional:** el estado de la referencia manifiesta siempre el hecho real — decidida, incompleta o completa —; **nunca queda en catálogo ni índice un estado falsamente presentado como completo**, ni catálogo con una decisión que declare el documento indexado: la decisión de identidad y la disponibilidad para consulta son cosas distintas y quedan registradas por separado.

**Registro del catálogo — semántica, no formato.** Por documento: `document_id`; sus **referencias de fuente** —cada una con su alias, la(s) `document_version` incorporadas desde esa fuente, el tipo de asignación, la fecha y el **estado de ingesta** (uno de los tres valores nominales)—; y los **datos descriptivos** de reingesta. El **formato físico** en que el estado se representa es **detalle de diseño de almacenamiento (D-02/D-08)**; lo contractual es la **semántica de los tres estados** y las garantías de recuperación. Lo restante fijado aquí es la semántica de la asignación, el orden de matching (referencia de fuente primero), la secuencia transaccional de la Regla 4 y el deber de tratamiento explícito de toda discrepancia.

**Pregunta abierta declarada.** Si el propietario quisiera que el sistema **sugiera** automáticamente si un cambio de contenido es una edición del mismo documento u una obra nueva (por ejemplo, con metadatos del título del PDF o heurísticas de comparación), eso es una **decisión adicional suya**: no existe hoy criterio suficiente para resolverla sin decisión humana y esta decisión no lo presupone. La fiabilidad de esa señal, si algún día se decide usarla, tendría que verificarse por separado (análoga a las VAL). En esta decisión, esa distinción es **siempre del operador**.

**Pregunta abierta declarada 2 — retención de versiones anteriores en el índice.** Esta decisión garantiza la coherencia por versión **mientras la incorporación de la nueva está incompleta**; pero, una vez que una versión nueva del mismo `document_id` queda «ingesta completada e índice disponible para consulta», **el contrato actual no fija qué se hace con la versión anterior del índice**: no hay decisión registrada de retención —conservar ambas, que la consulta use solo la última, o una regla por contexto— y las reglas de esta decisión no la resuelven. Es una **decisión del propietario**, para el registro de pendientes; **no bloquea** la aprobación de esta decisión, porque la garantía P10 vale antes de que la nueva concluya, sea cual sea la política que se adopte después.

**Casos de prueba documentales.** Un test por caso y por garantía; las detenciones, rechazos y fallas se verifican con **catálogo e índice invariantes** (cero mutaciones; ninguna ingesta parcial), y las reingestas aceptadas solo con los datos descriptivos permitidos actualizados:
- **P1 — referencia conservada y descriptivos automáticos:** reingesta de una fuente registrada (alias + versión registrada por él) reutiliza su `document_id`, es idempotente, y persiste automáticamente **solo** la ubicación y la fecha permitidas; no requiere aprobación manual y no cambia la identidad.
- **P2 — bytes idénticos sin referencia suficiente:** archivo con nombre **no** registrado cuyo contenido coincide con una `document_version` existente **se detiene** en la validación (Regla 4 paso 1): sin asignación automática, catálogo e índice byte-idénticos.
- **P3 — asignación explícita incompatible, rechazo en el paso (1):** `--document-id` sobre bytes ya asociados a otro id es **rechazado antes de registrar nada**; catálogo e índice intactos.
- **P4 — secuencia de decisión registrada:** `--document-id` existente con bytes nuevos de su propia referencia sigue el **orden contractual** —validación → decisión deliberada registrada e informada → aceptación de la ingesta—; la misma situación sin parámetro **se detiene** en la validación.
- **P5 — sin cambios parciales:** en todas las detenciones, rechazos y en una ingesta que no completa tras una decisión registrada, catálogo e índice quedan coherentes — sin contenido parcial — y el estado registrado manifiesta el hecho real (decisión registrada / ingesta incompleta), jamás presentado como completado.
- **P6 — alias y bytes nuevos:** alias coincidente con contenido distinto **se detiene**; el slug repetido con contenido distinto recibe el mismo tratamiento; en modo no interactivo ambos fallan de forma explícita.
- **P7 — trazabilidad del tipo de asignación:** la primera ingesta sin discrepancia queda registrada como asignación **por defecto**; con parámetro explícito, como **deliberada**.
- **P8 — reconstrucción:** regenerar el índice (D-02) conserva el catálogo y todas las identidades.
- **P9 — estados, idempotencia y disponibilidad:** una referencia cuyo procesamiento falla queda en estado «ingesta incompleta» — no «completada» —; su **reejecución completa el trabajo pendiente de forma idempotente**, recalculando sin **duplicar chunks** (los mismos `chunk_id` deterministas) y **sin publicar resultados parciales**; el documento pasa a consultable **únicamente** cuando la ingesta y la actualización del índice concluyeron correctamente — estado «ingesta completada e índice disponible para consulta», coherente con el `status` que la superficie pública expone según D-07 (`indexed`/`not_indexed`), sin abrir ni reabrir **PD-11**.

- **P10 — versión anterior íntegra ante el fallo de la nueva:** la incorporación incompleta de una versión nueva de un documento ya indexado deja el índice **sin fragmento alguno de la nueva** y con la versión anterior **byte-idéntica** y consultable; la versión nueva figura ante las superficies públicas como **`not_indexed`** (D-07) durante todo el fallo; ninguna consulta mezcla versiones; la garantía vale **sea cual sea la política futura de retención** («Pregunta abierta declarada 2»).

**Aprobación:** propietario, 2026-10-11.

### D-14 — Política de arranque sin índice disponible · CERRADA (cierre documental)

**Qué cierra y qué no.** Cierra **RP-01**. Fija el comportamiento observable del servicio cuando el índice no está disponible: la política de arranque, la condición que decide la disponibilidad, el diagnóstico, la recuperación y la distinción frente al índice **válido y vacío**. **No** declara implementado ni verificado ese comportamiento, **no** agrega códigos de error, **no** abre estados públicos nuevos en `get_document` (**PD-11** queda como está), **no** altera `002` ni `003`, y **no** decide la plantilla de despliegue, la reserva del puerto ni la unit (`deploy/` sigue sujeto a aprobación en **D-12**; **D-08** sigue sin autorizar cambios operativos). **No** introduce ninguna capacidad de vigilancia ni de recarga. **No** decide el diseño físico de almacenamiento —si el catálogo y el índice comparten archivo, cómo se abren los almacenes auxiliares ni cómo se reemplaza un índice con el servicio en marcha—: esos asuntos quedan como residuales del Bloque 4.

**Contexto.** RP-01 nace de una clase de fallo ya observada en este host: `Restart=on-failure` combinado con un recurso ausente produce un ciclo de reinicio sin explicación (el incidente de 43.558 reinicios). El requisito no era «no fallar», sino **fallar de forma clara y diagnóstica**. Las piezas ya existentes son: el código `index_unavailable` y la capacidad `health` (**D-07**), el contrato de **solo lectura** del índice y la ingesta reservada a la CLI (**D-08**), y los vocabularios de `health.status` y `health.dependencies`, que D-07 **no** fija; **qué convierte un almacén en «válido y utilizable» no está fijado en ningún documento**.

**Opciones consideradas.**

- **A — Fallo explícito al arranque (fail-fast) con causa registrada y límite de reintentos en la unit.** El proceso termina con código distinto de cero; la unit, con límite de reintentos, queda en `failed`. *Contra:* la garantía anti-ciclo queda delegada a la **correctitud de la unit** —el artefacto cuya desactualización produjo el incidente—; el diagnóstico sólo es visible en el host y no para el consumidor MCP; y `index_unavailable` quedaría reservado sólo a una pérdida en caliente.
- **B — Estado degradado: el proceso arranca y permanece en ejecución (RECOMENDADA).** El servicio no termina por esta causa; `health` reporta el estado y las consultas responden `index_unavailable`. *Contra:* systemd lo ve `active` aunque no pueda servir; el sondeo debe usar `health`, nunca `is-active`.
- **C — Híbrida: fail-fast para configuración inválida, degradado para recurso ausente.** *Contra:* dos políticas, dos superficies y una distinción operativa que el MVP no necesita demostrar; y conserva la dependencia de la unit en su mitad fail-fast.
- **Recuperación (subdecisión).** **R1** — resolución en la ruta de consulta (**adoptada por el propietario**) · **R2** — reinicio deliberado como único mecanismo (descartada: obliga a una acción manual para un caso que el camino normal resuelve sin coste) · **R3** — supervisión o recarga activa (descartada: capacidad **no definida** en la arquitectura; no se introduce).

**Decisión adoptada — política única: estado degradado, proceso siempre en ejecución (opción B).**

1. **Sin terminación por índice no disponible.** Si el índice no es válido y utilizable, el servicio **arranca y permanece en ejecución** en estado degradado. No hay fallo de proceso que reiniciar: `Restart=on-failure` **no puede** dispararse por esta clase, de modo que el ciclo de reinicio queda descartado **por construcción**, no por configuración.
2. **El servicio nunca crea ni modifica el índice.** Abre el almacén en **solo lectura** y **no requiere permisos de escritura sobre él** (D-08). Crear un almacén vacío al arrancar convertiría «no disponible» en «válido y vacío» y borraría la distinción que esta decisión fija. El **registro operativo** es un permiso **distinto y separado**: escribe en el **destino de logging configurado** —no sobre el índice ni sobre datos persistentes del proyecto— y se acota a **D-06 pto. 10** y a `001 §8`. Esta decisión **no amplía ni exceptúa** la política de solo lectura de **D-08**, que sigue gobernando el índice y los datos persistentes del proyecto; la ubicación, el destino y los permisos del registro pertenecen al **diseño operativo**.
3. **Condición de disponibilidad: todo lo que la operación necesita debe ser válido y utilizable en modo de solo lectura.** La disponibilidad **no** se decide comprobando que un archivo existe o que puede abrirse. Se decide **validando todos los almacenes y capacidades que la operación requiere** —el índice y, si el diseño los separa, el catálogo y los almacenes auxiliares— y estableciendo que son **reconocibles por este proyecto** y **utilizables para los modos que el MVP declara disponibles**: (i) cada almacén requerido puede abrirse y consultarse **sin requerir permisos de escritura sobre el índice**; (ii) su **estructura y sus metadatos son los esperados** —las tablas y el registro de versiones que el contrato necesita para responder, conforme a **D-11**, `001 §6` y **D-13**—; (iii) están presentes las **capacidades del motor** que los modos disponibles requieren. La comprobación debe ser **de bajo coste y no crecer con el tamaño del corpus**: **no** es una verificación de integridad completa del almacén ni sustituye a las validaciones pendientes. La validación **no crea ni modifica ningún archivo** y **no declara implementada ni verificada ninguna capacidad**. El **mecanismo de apertura y de sonda**, el **diseño físico** —si catálogo e índice comparten archivo y cómo se abren los auxiliares— y el **tratamiento de la integridad** pertenecen al **diseño operativo** y quedan como **residuales del Bloque 4**: esta decisión fija la **propiedad a satisfacer**, no la técnica. La **misma** validación decide la disponibilidad en la **ruta de consulta** y en **`health`**, para que ambos caminos no puedan discrepar.

   **Clases de causa — cinco, y sólo la última no es degradación:** (a) **ausente** —no existe—; (b) **inaccesible** —existe pero no puede abrirse o consultarse en solo lectura: permisos, bloqueo, archivo ilegible—; (c) **incompatible** —se abre, pero su estructura, esquema o metadatos no son los esperados por esta versión del contrato—; (d) **capacidad o extensión del motor ausente** —la característica o extensión que un modo disponible requiere no está presente; **hoy** el único modo disponible es `lexical` y su capacidad es **FTS5 compilado**, cuya verificación sigue **pendiente** (**VAL-03**)—; (e) **válido y vacío** —reconocible y utilizable, sin documento alguno: **no es causa de indisponibilidad**. La indisponibilidad de **cualquier** almacén o capacidad requerido —incluido uno auxiliar— se clasifica en (a)–(d) según corresponda y produce el **mismo** `index_unavailable`: **no** se agregan clases ni códigos. Las cuatro clases de degradación comparten efecto observable y difieren sólo en **el detalle registrado** (ítem 5).

4. **Diagnóstico: el detalle vive en el registro; `health` expone el resumen.** El **registro operativo** anota, en lenguaje legible, la clase de causa de la indisponibilidad. `health` expone **sólo el resumen** y **sólo los campos que D-07 ya autoriza**: `status` = `degraded`; `dependencies` con `index` entre las no satisfechas; `capabilities.available_modes` = `[]`. **No** se agregan campos a `health`, **no** se agregan claves a `details` más allá de las que D-07 fija, y la **causa concreta no se publica como vocabulario de contrato**: el consumidor recibe el estado resumido, el operador recibe el detalle por el registro.
5. **Registro de transiciones: una entrada por cambio de estado, ninguna por consulta.** El servicio mantiene el **estado de disponibilidad** con su clase de causa y **no reescribe el registro mientras el par (disponibilidad, causa) no cambie**: las consultas repetidas que fallan durante una misma indisponibilidad **no generan una entrada cada una**. Se registra **una sola vez**: (i) el **arranque** en estado degradado, con su clase de causa; (ii) el **cambio de causa** sin recuperación —por ejemplo, de `ausente` a `incompatible` tras una reparación fallida—; y (iii) la **recuperación** —transición a disponible—, identificando la causa que **se resolvió** y **marcándola como resuelta**, nunca como una causa que continúe vigente. Una **misma transición se registra una sola vez, aunque varias consultas concurrentes detecten la condición al mismo tiempo**: la garantía es de **unicidad de la entrada**, y **cómo** se asegura —sincronización, punto único de decisión o cualquier otro medio— pertenece al **diseño operativo**; esta decisión **no impone ningún mecanismo ni detalle de implementación**. Invocar `health` tampoco agrega entradas: **informa, no registra.** El destino de ese registro es el **destino de logging configurado** (ítem 2) y su contenido se acota a **D-06 pto. 10** y a `001 §8`: **sin texto de consultas, sin contenido, sin secretos y sin rutas sensibles**.
6. **`search` y `get_document` responden `index_unavailable`** —el código ya definido en D-07 y `001 §6.2`— para toda solicitud **ya autenticada** que requiera el almacén indisponible. **Una sola política** cubre la indisponibilidad de arranque y la que ocurre con el proceso en marcha. La indisponibilidad **nunca** se reporta con `mode_not_available` —que en el MVP describe `vector` y `hybrid`, modos no implementados, sobre un índice sano— ni con `not_indexed` —que describe una **versión** no incorporada sobre un índice sano (**D-13**)—. `index_unavailable` es el **único** código de esta condición; y la autenticación de **D-09 precede** al contrato de aplicación, de modo que una solicitud sin credencial válida no recibe `index_unavailable`.
7. **Recuperación: se resuelve en la ruta de consulta, sin supervisión ni recarga (R1).** La indisponibilidad **no se cachea como un hecho permanente**: se **re-valida** con el criterio del **ítem 3** —todos los almacenes y capacidades que la operación requiere— cuando una operación los necesita y cuando se invoca `health`. Si la CLI crea o repara el índice después de un arranque degradado, la **primera consulta posterior lo resuelve y se sirve con normalidad**, y `health` deja de reportar `degraded`; el registro anota la causa **resuelta** (ítem 5). El intento de resolución **no crea ni modifica ningún archivo** y **no requiere permisos de escritura sobre el índice**; el modo de apertura y el tratamiento de los **almacenes auxiliares** quedan en el **diseño operativo** (D-08) y **no se deciden aquí**. El servicio **no** se reinicia, y esta decisión **no introduce ninguna capacidad nueva**: no hay proceso de vigilancia, no hay sondeo periódico, no hay señales de recarga y no hay punto de recarga. Un **reinicio deliberado** sigue siendo admisible y también resuelve el caso; lo que la política fija es que **no es necesario** para recuperarse.
8. **Un índice válido y vacío no es un índice degradado.** Si el almacén es reconocible y utilizable pero no contiene documento alguno: `health.status` = `ok` y `dependencies` vacía; `search` responde con la lista de resultados vacía —no con un error— y `get_document` aplica el contrato ya vigente (`document_not_found` para un identificador desconocido; `not_indexed` para una versión registrada sin incorporar, D-13). Un índice vacío no ofrece `index_version` que reportar: el contrato de D-07 ya resuelve ese caso con `null`, **sin cambios**. **Cero documentos no es una falla de configuración ni de inicialización.**

**Distinción exigida entre condiciones.**

| Condición | `health` | `search` | `get_document` |
| --- | --- | --- | --- |
| Algún almacén o capacidad requerido no disponible (ausente / inaccesible / incompatible / capacidad o extensión del motor ausente) | `status: degraded`; `dependencies` incluye **`index`**; `available_modes: []` | `index_unavailable` | `index_unavailable` |
| Índice válido, sin documentos | `status: ok`; `dependencies: []`; `available_modes: ["lexical"]` | lista de resultados vacía | `document_not_found` / `not_indexed` (D-13) |
| Índice válido con documentos | `status: ok`; `dependencies: []`; `available_modes: ["lexical"]` | resultados | contrato de D-07 y D-13 |

**Motivo.** Es la política **mínima** que cumple RP-01 con piezas que el contrato ya tiene: `index_unavailable`, `health` y el contrato de solo lectura de D-08. La propiedad anti-ciclo se satisface **por construcción** —el proceso no falla— y no depende de la correctitud de la unit. Expone el diagnóstico al consumidor MCP sin ampliar la superficie (D-06 pto. 7) y no toca D-07 ni **PD-11**.

**Consecuencias y residuales.**

- **Sondeo.** Con esta política el proceso figura `active` para systemd aunque el índice no esté disponible: el sondeo de salud debe usar `health` y **no** debe mapearse `health.status != ok` a un reinicio del servicio. La frase «health check útil para el orquestador» de `001 §8` queda sujeta a esta regla.
- **Residual fuera de alcance.** Un ciclo de reinicio por **otra** causa —un fallo de proceso distinto de la indisponibilidad del índice— pertenece a la política de `Restart`, a la plantilla `deploy/` (sujeta a aprobación, D-12) y a la recomprobación de puerto y unit de **D-08 (OD-3)**. **D-14 no decide la plantilla de la unit.**
- **Fuera de alcance — reemplazo con el servicio sano.** El **reemplazo del índice mientras el servicio está sano** —una reindexación completa que produce un `index_version` nuevo con un manejador de lectura ya abierto— es una cuestión de **diseño de la ruta de lectura**, no de RP-01: esta decisión sólo fija la transición **degradado → disponible**. Queda registrado como **pendiente para el Bloque 4**.
- **Fuera de alcance — almacenes auxiliares y diseño físico.** Esta decisión **no** decide el modo de apertura, los **archivos auxiliares** que el motor pudiera necesitar (ni sus requisitos de permiso) ni si el catálogo y el índice comparten archivo. **D-08 ya exige declararlos explícitamente en el diseño operativo** si fueran necesarios, y esa declaración **sigue pendiente**. Lo único que D-14 exige es que la validación **no cree ni modifique archivos** y **no requiera permisos de escritura sobre el índice**; si un almacén auxiliar requerido resulta indisponible, el comportamiento es el mismo —**`index_unavailable`**, sin códigos nuevos— (ítem 3 y su tabla).
- **No verificado.** Ninguna parte de esta política fue implementada ni verificada; su verificación corresponde a las pruebas de contrato de la Fase 3 (`002`) y no se ejecuta en esta etapa.
- **RP-02 no se toca por esta decisión** y queda fuera de su alcance. **Actualización posterior:** el cierre documental de RP-02 está en **`D-17`**.

**Aprobación:** propietario, 2026-10-12.

### D-15 — Publicación, fidelidad y reconstrucción de generaciones · CERRADA (cierre documental del marco normativo y del Protocolo B; propuestas técnicas y validaciones sujetas a condiciones de aprobación y verificación pendientes)

**Qué cierra y qué no.** Cierra documentalmente el marco normativo de publicación, fidelidad y reconstrucción de generaciones (Protocolo B, invariantes de fidelidad y niveles de disponibilidad). **No** implementa ni verifica el protocolo; **no** decide el esquema físico (D-12 §2); **no** cierra la especificación reproducible de serialización de la huella (**P-1b**, determinaciones **D-a…D-f**); **no** define la identidad lógica de construcción, su registro durable ni el bloque de identidad (**P-2**); **no** decide la cláusula residual **C-1**; **no** adopta el séptimo insumo de `index_version` (**Q-1/Q-2**); **no** altera el conjunto de seis insumos de D-11 §4 ni los contratos públicos de D-07; **no** resuelve **M7 / CD-01**; y **no** declara ejecutada ninguna de las validaciones operativas (**M-01…M-18**).

#### Directivas del propietario que orientan la decisión (no son aprobación técnica de sus componentes abiertos)
1. **B** como dirección: generaciones inmutables + puntero actualizado en **una transacción del catálogo**.
2. **C-1** como dirección: la huella cubre todos los campos persistidos no recomputables.
3. Proponer la **revisión de código** como séptimo insumo de `index_version`, resolviendo antes el caso «Git no disponible».
4. **Rechazar la ingesta** cuando no pueda verificarse una revisión limpia.
5. **No retirar automáticamente** generaciones durante el prototipo.
6. **FTS5**: documentar los límites de integridad **sin** especificar todavía una comprobación completa de consistencia.
7. **M7** se mantiene separado; no inventar identidad de corpus.

#### §1 Objetivo y alcance
Fijar cómo se publica el índice, cómo se reconstruye conservando la construcción publicada de cada versión disponible y cómo se comprueba esa fidelidad, sobre el almacenamiento en dos artefactos (catálogo + índice). **No** implementa ni verifica; **no** decide el esquema físico ([D] D-12 §2); **no** modifica D-02/05/07/11/13/14; **no** altera el contrato público MCP; **no** resuelve M7; **no** especifica la comprobación de consistencia de FTS5. Justificación: [D] D-02 pt.3 (índice «derivado y desechable»; «se registran las fuentes canónicas, las versiones y los parámetros necesarios para reconstruirlo») + [I] si los parámetros vivieran dentro del índice desechable, borrarlo destruiría lo necesario para reconstruirlo.

#### §2 Definiciones (nueve términos, no sinónimos)
`document_version` (identidad de la fuente, SHA-256 de los bytes, [D] D-11 §1) · construcción de una versión · `index_version` (derivado, seis insumos, truncado 12) · generación física · generación publicada · puntero del catálogo · huella de fidelidad · identidad del pipeline · bloque de identidad de generación.

##### §2.1 Identidad de elementos, identidad de construcción y conjuntos
- **Identidad de un elemento:** `e = ( document_id , document_version , identidad de la construcción )`.
- **Justificación (alcance literal de D-13):** [D] D-11 §1; [D] D-13 «bytes idénticos **no demuestran** por sí solos que dos registros representen la misma obra… **nunca la inferencia automática** a partir de la igualdad de bytes»; [D] **D-13 Regla 5** «la misma `document_version` **no se registra** bajo dos `document_id` distintos; **cualquier excepción requiere decisión del propietario**»; [D] **D-13 P3** rechazo en el paso (1) de `--document-id` sobre bytes ya asociados a otro id; [I] → la identidad lógica **no se deduce de los bytes**, `document_id` debe formar parte de la identidad; **[P] la co-registración es una excepción del propietario, no un caso ordinario: esta sección no la autoriza ni la presupone.**
- **Tres nociones separadas [P]:** identidad lógica de la construcción (criterio; **valores NO definidos**) · atributos y datos de los fragmentos (resultado; presencia fijada por [D] D-07 y `001` §6; **no son** la identidad) · valores de procedencia y configuración registrados (insumos **candidatos**; no decidido cuáles la constituyen). No se inventa tupla, clave ni lista cerrada.
- **`index_version` no es identificador único de construcción [P]:** es derivado y hoy **no distingue un cambio que sólo afecte al código** (§8.1). Dos construcciones **no** deben considerarse idénticas por compartirlo; **toda** comparación se hace sobre la identidad de construcción, **nunca** sobre `index_version`.
- **Alcance del bloqueo por P-2:** bloquea **`R = W`**, la **uniformidad de construcción por versión** (§4.1 paso 2), la **igualdad en reconstrucción ordinaria** (P2) y la **detección de un cambio de construcción** (lo que distingue P2 de P3). **Los principios documentales están expresados; lo bloqueado es su implementación verificable.**
- **Conjuntos:** `E` = estado lógico esperado (del catálogo, **sólo estado publicado**; no depende de que exista índice) · `W` = estado objetivo de la operación · `R` = resultado físico de la generación nueva · `O` = contenido físico observado de la generación **publicada** (sólo para detectar/reportar, **nunca** para construir `W`).
- **`W` por operación (sin `P_inv`):** **P1** `W = E ∪ { e_new }` (incorpora; si `e_new ∈ E` es idempotente, [D] D-13 P1/P9) · **P2** `W = E` (no incorpora ni sustituye; **conserva la identidad lógica de cada construcción registrada**; la regeneración física **no** es por sí misma un cambio de construcción) · **P3** `W = (E \ {e_old}) ∪ {e_new}` con `e_old=(d,v,K_old)` y `e_new=(d,v,K_new)` (sustituye **la construcción** de la misma pareja; **nunca** cambia `document_id` ni `document_version`). **P2 no absorbe cambios de construcción**: si cambian los parámetros o valores determinantes, **no** se clasifica automáticamente como P2; corresponde el tratamiento de cambio de construcción ([D] D-10 reevaluación), sin decidir aquí reglas nuevas de ingesta.

#### §3 Invariantes de la huella
**§3.1 Orientación — insuficiente para implementar:** SHA-256 hex minúsculas **64 caracteres sin truncar**; versión de esquema en cabecera; cabecera con identidad completa (document_id + document_version), construcción registrada y `N`; registros en orden de ordinal 1..N ([D] `001` §6.1); sin circularidad (la huella no cubre su propio valor; el bloque de identidad no entra en ninguna huella de versión; sin digest a nivel de archivo); cálculo al construir y verificación en reconstrucción, **nunca** en consulta.
**§3.2 Determinaciones pendientes D-a…D-f (bloqueantes):** D-a codificación de la cabecera · D-b separación cabecera/registros · D-c orden exacto de campos · D-d terminación del flujo (salto final) · D-e **NFC: normalizar al persistir o sólo al serializar** (si sólo al serializar, dos valores persistidos distintos de un mismo campo producen la misma representación canónica y la huella no los distingue; **`content` no está expuesto a esto porque `content_hash` cubre el contenido persistido**; el riesgo alcanza a `section_path` y demás campos de texto) · D-f qué campos/valores se normalizan. **Relación:** `D-a…D-f` = determinaciones individuales; **`P-1b`** = ítem de aprobación que las **agrupa**; **`P-1a`** = principio general, no cubre ninguna determinación. No se renombran.
**§3.3 Cobertura — tres grupos + fuera:**
- **A · incluidos directamente:** `document_id` y `document_version` (cabecera, completos); `section_path`; `pdf_page_start`/`pdf_page_end` (**`null` admitido**, [D] `001` §6); procedencia de construcción en **cabecera una sola vez** (C-2): extractor y versión, tokenizer y opciones, `chunking_config_version`, versiones del motor —y la revisión del pipeline **si el séptimo insumo se aprobara**—; + **cláusula residual C-1**: todo campo persistido y no recomputable no enumerado.
- **B · valores derivados, recalculados y contrastados:** **`content_hash`** — se recalcula desde la **representación UTF-8 del contenido lógico definitivo persistido** ([D] D-11 §3: «antes de cualquier operación de almacenamiento», «no añade BOM y no se aplica normalización posterior», «pueda **comprobarse contra él**», SHA-256 hex minúsculas 64 sin truncar); se compara con el almacenado; **el valor verificado entra como ancla del contenido, en una sola vía**; si no coincide, falla y no se publica. **Nada queda pendiente en D-11 §3 para esta huella**; lo pendiente pertenece a **P-1b**. · **`chunk_id`** recomputado y contrastado (**no** se incorpora) · **`index_version`** recomputado y contrastado (**no** se incorpora; no es identificador de construcción).
- **C · validación estructural, no por huella:** orden y ordinal (contigüidad 1..N sin huecos ni duplicados) y `N`.
- **D · fuera:** `rank` y `score` (**no persistidos**, calculados en consulta, [D] D-07) · estructuras **FTS5** y **`sqlite-vec`** (cuestiones distintas, §7.1).
- **Reglas:** **C-1** ningún campo persistido y no recomputable queda excluido; la regla de no duplicar cobertura **no excluye campos obligatorios** · **C-2** procedencia de generación en cabecera, una vez. **Pendiente y bloqueante:** la enumeración completa de la cláusula residual depende del esquema físico ([D] D-12 §2).

#### §4 Protocolo (B)
**§4.1 Secuencia:** 1 construir en ubicación no canónica y no referenciada, con bloque de identidad · 2 validar (identidad del bloque, contigüidad, **uniformidad** y **`R = W`** —**estos dos bloqueados por P-2**—) · 3 calcular y validar la huella · 4 comprobar condiciones de fidelidad de la operación · 5 **hacer durables el archivo y su entrada de directorio antes de referenciarlo** · 6 **actualizar en una sola transacción del catálogo** puntero + construcción publicada + huella esperada + estado · 7 conservar generaciones anteriores.
**§4.2 [I]** una transacción del catálogo es atómica **dentro del catálogo** y **no** vuelve atómicas la escritura/sincronización/creación de la generación en el sistema de archivos. **[V]** durabilidad del contenido, de la **entrada de directorio**, atomicidad y durabilidad del commit y comportamiento del FS del host: **ninguna verificada**.
**§4.3 Condiciones por operación:** **remite a las definiciones de §2.1** —no las repite ni usa notación alternativa; eliminada la notación `(v, K_old)`/`(v, K_new)` que omitía `document_id`—. Validación adicional: P1 estructural + huella propia (no consultable hasta el commit, [D] D-13); P2 **igualdad de huella** con la huella esperada como condición de fidelidad de contenido conforme al contrato de huella (discrepancia ⇒ **aborto**); la existencia, estructura y soporte durable de cualquier registro que vincule dicha huella con la identidad lógica siguen pendientes de P-2, y la igualdad de huellas **no demuestra por sí sola identidad lógica de construcción**; P3 sólo corrección propia de la nueva construcción (la diferencia es deliberada y no se compara), con **decisión explícita y autorización**. Reglas sin excepción: en reconstrucción ordinaria una discrepancia de huella **nunca** reemplaza la huella esperada; en cambio deliberado, la nueva construcción y su huella pasan a ser las esperadas **dentro del mismo acto de publicación transaccional**.

#### §5 Estados de fallo y recuperación
**§5.1** estado lógico del catálogo ≠ disponibilidad física: un catálogo intacto **no** implica índice disponible. **§5.2** E1 válida/operativo · E2 ausente/incompleta/incompatible ⇒ **degradado** ([D] D-14) · E3 reconstrucción fallida con la anterior válida ⇒ **sin efecto** · E4 reconstrucción fallida ya degradado ⇒ **sigue degradado** (no empeora ni mejora).
**§5.3 «operativo» = identidad física NECESARIA, no suficiente:** requiere **nivel 1 (requisito conceptual de identificación física de la generación publicada en O(1); su mecanismo concreto no se da por materializado al depender del esquema físico pendiente)** **y nivel 3 (compuerta de disponibilidad de D-14**: apertura en solo lectura, estructura y metadatos esperados, capacidades requeridas por la operación). **La disponibilidad física operativa no deduce la identidad lógica de construcción a partir de `index_version`, de la igualdad de huellas ni de la identidad física de una generación.** **No** se verifica la integridad completa de fragmentos en cada consulta (nivel 2 es O(N)).
**§5.4 Tipos de interrupción:** terminación del proceso · caída del sistema (se pierde lo no sincronizado: razón del paso 5) · resultado incierto del commit.
**§5.5** leer el catálogo tras recuperarse determina el **estado lógico**; **no** demuestra que el archivo nombrado sobrevivió — eso depende de garantías físicas **[V]** y de la validación posterior. Las comprobaciones de disponibilidad, publicación y recuperación **no deducen la identidad lógica de construcción** únicamente de `index_version`, de la igualdad de huellas ni de la identidad física de una generación; la disponibilidad física simplemente **se comprueba** (niveles 1 y 3), no se deduce del commit.
**§5.6** caída antes del commit · durante el commit (resultado incierto, determinado leyendo) · después de publicación confirmada (nada que recuperar, queda la retención).
**§5.7 Invariantes:** I-1 intentos previos no cambian puntero/construcción publicada/huella esperada · I-2 no se publica antes de validar y hacer durable · I-3 un intento fallido no cambia la construcción esperada · I-4 una discrepancia de huella en reconstrucción ordinaria **jamás** reemplaza la huella esperada · I-5 el MCP no reconstruye, no publica, no escribe el catálogo, no retira generaciones · I-6 la CLI es responsable · I-7 la disponibilidad exige niveles 1 y 3 · I-8 un fallo de reconstrucción no convierte por sí mismo un estado degradado en operativo · I-9 nada se nombra antes de existir completo y durable.

#### §6 Responsabilidades
CLI: construir, validar, calcular huella, publicar (commit del puntero), reconstruir, retirar (sólo por operación explícita autorizada), escribe índice y catálogo. MCP: **solo lectura** de ambos, informa degradación ([D] D-14), **nunca** repara ([D] D-14 ítem 2). [D] D-08 reserva ingesta y reindexación a la CLI y exige que el proceso de consulta **no requiera permiso de escritura sobre el archivo del índice**; [D] AGENTS.md prohíbe borrados y reindexaciones destructivas sin autorización explícita.

#### §7 Integridad y disponibilidad (tres niveles)
**Nivel 1** identidad de generación (O(1), en cada consulta) · **Nivel 3** validez funcional (O(1), resolución): apertura en solo lectura, estructura y metadatos, capacidades requeridas · **Nivel 2** integridad de fragmentos por huella (O(N), **sólo** construcción y reconstrucción). **§7.1 FTS5:** la huella **no** detecta su corrupción; **la regenerabilidad no equivale a una prueba de integridad**; **no se especifica** una comprobación completa de consistencia (fuera de alcance); [V] regeneración determinista de FTS5 desde fragmentos y tokenizer. **§7.2 `sqlite-vec`:** [D] D-02 lo fija en 0.1.9, pre-v1; [D] `001` §5 declara `vector`/`hybrid` fuera del MVP; ninguna garantía depende de él.

#### §8 Identidad del pipeline e `index_version`
**§8.1** [D] D-11 §4 fija **seis** insumos y prohíbe agregar o quitar; [D] `001` §6 exige «identidad y versión del pipeline de extracción» como procedencia **por fragmento**; [D] `003` exige registrar la «**versión de código**» junto a los resultados. **[I] el defecto:** un cambio de código que no altere ningún valor declarado (caso inminente: **RP-02**, con `heading_start = true` mientras cambia el anclaje) produce fragmentos distintos **con el mismo `index_version`**.
**§8.2** separar (1) **revisión del árbol de fuentes asociada a la operación de ingesta** de (2) **identidad del código efectivamente ejecutado**. Registrar el commit de un árbol limpio identifica una revisión de las fuentes, **no demuestra** qué código se ejecutó. No lo cubren: paquete instalado (editable vs construido), dependencias resueltas (salvo lock rastreado y limpio), **archivos ignorados**, entorno (intérprete y plataforma). **No existe hoy mecanismo verificado; el borrador no inventa uno.**
**§8.3 Dos lecturas — decisión del propietario (Q-1):** **A** = revisión del árbol de fuentes de la operación (alcanzable, con límites declarados) · **B** = identidad del código ejecutado (no alcanzable hoy; **el insumo no puede cerrarse**). Bajo A: valor = revisión del árbol de fuentes asociada a la operación; limpieza = sin modificaciones en archivos rastreados ni no rastreados no ignorados; árbol sucio o sin Git ⇒ **la ingesta falla explícitamente** y —con el séptimo insumo— `index_version` **no se calcula** ([D] D-11 §4, valores ausentes). **La directiva de rechazo se conserva en ambas lecturas y NO se presenta como garantía de identidad del código ejecutado.**
**§8.4 Bloqueantes:** Q-1 (decidir la lectura) · bajo B, falta de mecanismo · e independiente de A/B: la guarda **no cubre archivos ignorados**. Adopción del séptimo insumo (Q-2) exigiría editar **D-11 §4** y **`001` §6.1** —**no aplicado**.
**§8.5 M7** pendiente y separado: `index_version` identifica una construcción **de una versión de documento** (su primer insumo es el hash del documento), no el índice completo; [D] D-07 devuelve **un solo** valor por respuesta de `search`; M7 no se decide en D-15 y la huella **no** es sustituto de la identidad de búsqueda.

#### §9 Retención y concurrencia
[P] directiva: **no retirar automáticamente generaciones durante el prototipo**. [I] carrera: un lector lee el puntero y, antes de abrir, la CLI publica y borra la anterior ⇒ el `open` falla. [P] **tolerancia del lector (P-4, propuesta adicional, NO requisito del núcleo)**: fallo de apertura ⇒ releer el puntero y reintentar una vez; si falla, degradar ([D] D-14). **La tolerancia no sustituye** (i) la comprobación de identidad de la generación que finalmente se abre, contra el puntero **recién leído**, ni (ii) la **exclusión entre escritores** (problema distinto; mecanismo por definir o validar). **No se diseña primitiva de bloqueo.** [P] retirada futura: operación explícita y autorizada ([D] AGENTS.md); [V] comportamiento de retirada/renombrado con descriptores abiertos, sin presuponer equivalencia entre SO. [D] VAL-07 mide recursos. **No se especifica ningún recolector de basura.**

#### §10 Garantías, límites y pendientes
**§10.1 [P]:** (1) sólo se publica generación validada y durable; publicar es **un solo commit** (2) toda versión publicada tiene huella registrada antes (3) la reconstrucción ordinaria conserva la construcción publicada y la coincidencia se verifica (4) discrepancia ⇒ aborto sin cambiar estado ni reemplazar la huella esperada (5) ninguna respuesta devuelve versiones no declaradas ni informa `indexed` sin índice (6) índice inutilizable ⇒ degrada e informa, no repara (7) los intentos fallidos no alteran puntero/construcción/huella (8) **una construcción activa por versión** — **propuesta con motivación acotada**: `chunk_id` ([D] `001` §6.1) no incorpora la construcción, así que la ambigüedad aparece **si dos construcciones coexisten en el conjunto consultable**, y **no se deduce de conservar generaciones físicas antiguas** (el protocolo ya propone **una generación publicada a la vez** y valida uniformidad por versión).
**§10.2 Límites:** la huella no prueba corrección de extracción ni fragmentación; **no demuestra qué código se ejecutó**; no detecta corrupción de FTS5 ni `sqlite-vec`; la identidad de generación es O(1) y **necesaria, no suficiente**, para la disponibilidad; el catálogo es la única fuente de `E` ([D] `001` §8 sitúa los backups fuera del prototipo); la guarda de árbol limpio no cubre ignorados; la especificación de bytes de la huella no está determinada; durabilidad, concurrencia y SO son **[V]**.

#### §11 Dependencias documentales (CD-01…CD-05, ninguna resuelta)
- **CD-01** M7: `index_version` en respuestas que mezclan construcciones → **D-07** (salida de `search`).
- **CD-02** «completada» en D-13 se predica hoy de una versión; D-15 necesita versión **y** construcción publicada → **D-13** (precisión mínima).
- **CD-03** D-05 pto.8 afirma que los nombres públicos de `nivel`, `tipo de bloque` y `captions asociados` quedaron fijados en D-07, que **no los contiene**; `001` §6 tampoco los enumera como internos → **D-05 pto.8** y/o **D-07**. La **parte interna** quedó resuelta en **`D-20`** §3.1: los nombres `level`, `block_type` y `captions` se adoptan como procedencia interna y su enumeración se incorpora a `001` §6; la **parte pública** de CD-03 sigue abierta.
- **CD-04** lista de reconstrucción de **D-02**: **PARCIALMENTE CERRADA.** La lista quedó completada —incluye el **analizador léxico** (`tokenizer`, insumo separado, [D] `D-10`/PD-13), la **configuración efectiva** del extractor ([D] `D-19` §2) y la **revisión del código** ([D] `003`)— y se retiró la referencia muerta **`(P-01/P-02)`** (cerrados por D-10) sustituyéndola por el manifiesto de `D-10` y su `chunking_config_version`. **No se declara cerrada del todo:** queda pendiente la **forma** de la revisión del código (**Q-1/Q-2**), declarada como tal en la propia lista.
- **CD-05** una construcción activa por versión: **propuesta de D-15**, no hecho aprobado; si se quisiera más de una, habría que tocar **`001` §6.1** y **D-07**.

#### §12 Decisiones pendientes
**§12.1 Directivas recibidas** (las siete de arriba), incorporadas como **dirección**, no como aprobación documental. **§12.2 Propuestas técnicas pendientes:** **P-1a** principio general de la huella (aprobado con el límite de §12.4) · **P-1b** especificación reproducible de bytes = determinaciones **D-a…D-f** (no aprobable como cerrada; bloquea implementar la huella) · **P-2** materialización de la identidad de construcción + registro durable + bloque de identidad (bloquea `R = W`, uniformidad y toda comparación de construcción) · **P-3** una construcción activa por versión (política) · **P-4** tolerancia del lector (no requisito).
**§12.4 Alcance de la aprobación (cuatro categorías):** (1) **qué se aprueba y qué no**, propuesta por propuesta, con su condición; **límite explícito de P-1a**: aprueba **sólo** el principio general de una huella SHA-256 determinista — **no** cierra la serialización concreta, **no** determina la enumeración de C-1, **no** autoriza implementar mientras P-1b, P-2 y los demás bloqueantes sigan abiertos. (2) **Autorizaciones documentales derivadas** (D-11 §4 + `001` §6.1 sólo si Q-1⇒A; D-13; D-02; D-05/D-07; D-07 para M7 **fuera** de este acto), **no aplicadas**. (3) **Decisiones abiertas:** M7 · Q-1 · Q-2 · P-1b (D-a…D-f) · **P-2** y esquema físico —cuyo bloqueo alcanza `R = W`, uniformidad por versión y detección de cambio de construcción— · cláusula residual de C-1 · Q-4/CD-02 · CD-03 · **CD-04** (parcialmente cerrada: queda pendiente la forma de la revisión del código, **Q-1/Q-2**). (4) **Validaciones [V]**. **Declaración: aprobar una decisión documental no demuestra su corrección técnica ni autoriza a afirmar que las validaciones se ejecutaron.**

#### §13 Matriz de validación futura (M-01…M-18)
M-01 determinismo de reconstrucción · M-02 durabilidad de archivo y entrada de directorio antes del commit · M-03 atomicidad, durabilidad y determinación del resultado del commit · M-04 retirada/renombrado con descriptores abiertos · M-05 Git disponible donde corre la ingesta y semántica exacta de árbol limpio (rastreados y no rastreados no ignorados) — **bloquea cerrar el séptimo insumo** · M-06 SQLite/FTS5/`sqlite-vec` ([D] VAL-03/04/05) · M-07 extractor ARM64 ([D] VAL-01) · M-08 exclusión entre escritores · M-09 coste de la huella · M-10 recursos del host ([D] VAL-07) · M-11 regeneración determinista de FTS5 (**no** integridad) · M-12 tolerancia del lector con comprobación de identidad (propuesta, no requisito) · M-13 **M7: bloquea cerrar un contrato** (D-07, aparte) · M-14 «completada» en D-13: bloquea cerrar un contrato · **M-15** registro durable y materialización de la identidad (**P-2**; bloquea `R = W`, uniformidad y toda comparación). **Aprobaciones independientes:** la aprobación documental de D-15 y la definición y aprobación de P-2 y del esquema físico son actos distintos. Aprobar D-15 no aprueba implícitamente P-2, no completa la definición de la identidad lógica de construcción y no autoriza por sí sola la implementación de esos elementos. M-15 solo puede cerrarse cuando P-2 y los elementos correspondientes del esquema físico hayan sido definidos y aprobados expresamente, además de cumplirse los demás requisitos de cierre que establece el documento · M-16 protocolo B y huella con C-1 [P] · M-17 identidad del pipeline: bloquea cerrar el séptimo insumo (Q-1) · **M-18** especificación de bytes (D-a…D-f, **P-1b**): requisito que bloquea la implementación del núcleo; **no aprobable hoy como cerrada**.

**Aprobación:** propietario, 2026-10-12.

### D-16 — Configuración del extractor, anclaje del encabezado y política de cola · INCORPORADA — SUS TRES PROPUESTAS CERRADAS EN D-17, D-18 Y D-19

**Qué contiene y qué no cierra.** Esta entrada **propone**, a partir de la evidencia del Experimento 3, tres cosas: (1) un **criterio de anclaje en dos niveles** para **RP-02**; (2) **B** como **candidata** de política de cola; (3) el **registro de la configuración del extractor** —herramienta, versión y flags— como identidad de construcción. **No** es una decisión aprobada: **no** cierra **RP-02** por sí misma —su cierre documental es posterior, en `D-17`—, **no** adopta ninguna política de cola, **no** modifica **D-04**, **D-05**, **D-10**, **D-11**, **D-12**, **D-13**, **D-14** ni **D-15** —en particular **no** toca las cuatro huellas de D-11 ni los **seis insumos** de `index_version`—, **no** re-mide las métricas de D-04/D-05 y **no** autoriza implementación alguna. Sus afirmaciones son `[P]` propuestas, `[I]` inferencias o `[V]` pendientes; ninguna es `[D]`. **Estado posterior:** el **criterio de anclaje** quedó cerrado documentalmente en **`D-17`**, la **política de cola** en **`D-18`** y la **configuración del extractor** y su representación en la identidad en **`D-19`**. Esta entrada se conserva como el registro de las propuestas que los originaron.

**§1 Evidencia registrada (Experimento 3).** Artefactos en el directorio temporal del experimento, **fuera del repositorio**: `informe-exp3.md`, `exp3-report.json` (`09c071cc…`), `exp3.py` (`0f4ba9d0…`) y la corrida defectuosa conservada como evidencia. Entradas verificadas por hash: PDF `0cd2fc84…`, extracción `-layout -enc UTF-8` `281f2f23…`, extracción sin `-enc` `324a4511…`. El diagnóstico usó PyMuPDF 1.26.7 / MuPDF 1.26.12, **de uso transitorio fuera del proyecto** y con licencia AGPL-3.0: **no** se propone adoptarlo como dependencia.

- **E1.** Los **11 encabezados** que la medición previa clasificó como aproximados existen como **bloque de encabezado** en la página declarada por el outline: **3 con evidencia posicional** (desvío ≤ 0,5 pt respecto del calibrado) y **8 sólo con página + tipografía** —las aperturas de capítulo, cuyo destino tiene `y` = 0,0—.
- **E2.** El destino XYZ del outline apunta **+72 pt (1 pulgada) por encima** de la primera línea del encabezado (5/5 controles; dispersión 0,75 pt): es el *viewport*, no el glifo.
- **E3.** Tipografía medida: capítulos en negrita **30,0 pt** (26,11 en el capítulo 3); secciones en negrita **19,37 pt**; cuerpo **15,0 pt** (13,06 en el capítulo 3). El tamaño **relativo al cuerpo no es constante** entre capítulos.
- **E4.** De las **30 colas** con figura o tabla: **30/30** tienen el rótulo **encima** del encabezado; **30/30** coinciden en capítulo con su unidad; **30/30** tienen objeto gráfico presente; **26/30** con la figura arriba del rótulo; distancia rótulo↔figura ≈ 6,2 pt; 28 `Figure` + 2 `Table`.
- **E5.** **28/30** rótulos aparecen **referenciados en la prosa de la sección previa**; **0/30** en la ventana posterior al encabezado (≤ 8 páginas, acotada).
- **E6.** El outline tiene **off-by-one en 3 entradas** del front matter: declara p8/p11/p13 y el encabezado está en p9/p12/p14.
- **E7.** Codificación: la salida por omisión de Xpdf **no es UTF-8 válido** (151 bytes altos, todos ≥ 0xA0 ⇒ Latin-1; 151 reemplazos al decodificar). Con `-enc UTF-8`: válida, sin reemplazos, **4.052 caracteres** fuera de Latin-1 recuperados. Palabras **170.917** con `-layout -enc UTF-8` frente a **170.887** con la salida por omisión; 13 páginas con recuento distinto.
- **E8.** La primera corrida del Experimento 3 fue **defectuosa** —candidatos de coincidencia espurios que volvían vacío el umbral tipográfico— y quedó **descartada y conservada como evidencia**; E1 proviene del método corregido.

**§2 `[P]` Criterio de anclaje en dos niveles (RP-02).** `[I]` El outline aporta posición sólo en parte de los casos —140 de 178 entradas con `y` utilizable, y 0 de 11 en las aperturas de capítulo— y su destino está desplazado +72 pt; por eso el anclaje **no puede depender sólo de la coordenada**.

Los dos niveles **no son equivalentes** y no deben leerse como un único criterio: `posicional` combina **dos fuentes independientes de posición** —la página declarada y la coordenada del destino del outline— con la tipografía; `pagina+tipografia` dispone de **una sola** fuente de posición —la página declarada— más la tipografía, y por eso se registra y se marca como **evidencia más débil**. Un caso de nivel `pagina+tipografia` **no** satisface el mismo estándar de evidencia que uno de nivel `posicional`.

- **CA-1 · nivel `posicional`.** Página del outline = página declarada **y** bloque de encabezado (negrita, tamaño ≥ umbral del nivel) cuyo texto cubre el título de la unidad —tolerante a título envuelto y a la forma ordinal (`1.` frente a `Chapter 1.`)— **y** `y_destino > 0` con `|(y_encabezado − y_destino) − Δ| ≤ tolerancia`. En el piloto: **p26, p34 y p348**, con Δ = 72 pt y tolerancia = 2 pt. Ambos valores son **provisionales y específicos de este PDF**, no universales.
- **CA-2 · nivel `pagina+tipografia`.** Sin coordenada utilizable: página declarada **y** bloque de encabezado dentro de la **banda superior** (y ≤ 200 pt, **provisional y específica de este PDF**) cuyo texto cubre el título. En el piloto: **los 8 capítulos**. Se registra como evidencia **más débil**: no hay segunda fuente independiente de posición.
- **CA-3 · sin anclaje.** Si en la página declarada no hay bloque de encabezado que cubra el título, la unidad **no se ancla**: no se inventa posición ni se acepta una coincidencia **sólo textual**. `[I]` Es el comportamiento explícito que RP-02 ítem (d) exige y que sigue sin implementarse.
- **CA-4 · precedencia.** El matcher textual **propone**; la tipografía y la página **disponen**. Una coincidencia en una línea de cuerpo **no** ancla, aunque el texto coincida exactamente. `[I]` Es el modo de fallo que E8 documentó.
- **CA-5 · metadato.** Se registra por unidad `anclaje ∈ {posicional, pagina+tipografia, no_verificado}` y el fragmento arranca en la **primera línea del bloque de encabezado**, no en la línea que eligió el matcher textual.

`[D]` **Cerrado documentalmente en `D-17`**: allí quedan fijados el criterio en dos niveles, la **calibración documental** (§4 de D-17) y el **comportamiento ante el fallo** (§5 de D-17), incluida la decisión de que el nivel `pagina+tipografia` **ancla** registrándose como evidencia más débil. Esta sección se conserva como el registro de la propuesta que lo originó; **RP-02 no se declara verificado ni implementado**.

**§3 `[P]` Política de cola — B como candidata, no aprobada.** Efecto medido sobre el corpus del piloto: **130 unidades** con cola, **14.731 palabras** y **30 bloques** con rótulo (28 `Figure` + 2 `Table`).

| Opción | Contenido perdido | Contenido duplicado | Contenido reasignado | Evidencia disponible |
| --- | --- | --- | --- | --- |
| **A — descartar** | 14.731 palabras + 30 rótulos | 0 | 0 | `[I]` En contra: 28/30 rótulos están referenciados en la prosa previa (E5) ⇒ referencias huérfanas |
| **B — asignar a la unidad anterior** | 0 | 0 | 14.731 palabras en 130 unidades | `[I]` A favor: 30/30 rótulos encima del encabezado (E4) y 28/30 referenciados en la prosa previa (E5) |
| **C — solapar** | 0 | 14.731 palabras + 30 rótulos | 0 | `[I]` Recupera la referencia huérfana a costa de duplicar texto y rótulos en el índice |

**B era la candidata recomendada** —conserva sin duplicar—, **no aprobada por esta entrada**: esta entrada **no** aprueba B ni cierra ninguna de sus excepciones. `[D]` **Cerrado documentalmente en `D-18`**, que adopta **B**, fija su mecanismo, resuelve las excepciones de abajo y añade la exclusión del mobiliario de página. `[I]` La evidencia sostiene que el material gráfico de la cola pertenece al **contenido anterior**; la pertenencia **semántica por sección** no queda demostrada y la decide el propietario. Excepciones pendientes, ninguna resuelta aquí: (1) **unidad sin predecesor** en el corpus —0 casos activados en este PDF, pero la regla debe definirlo: la cola no asignada se **declara**, nunca se descarta en silencio—; (2) **predecesor de tipo padre** —no se decide si la cola va al padre o a su última hoja—; (3) **cola sin prosa** (3 casos medidos): se propone asignar prosa y rótulo, y se recuerda que la **imagen no es texto indexable**; (4) **pertenencia a una unidad excluida del corpus** —si el texto previo viniera de una unidad fuera del corpus, B lo atribuiría a la última unidad incluida: límite a declarar—. `[D]` El corte del fragmento ya no depende de un criterio abierto: **dónde empieza** lo fija **`D-17`** §2 y **dónde termina**, **`D-18`** §2.

**§4 `[P]` Configuración del extractor y codificación.** Se propone **registrar** como configuración de construcción —la que D-02 exige registrar para reconstruir el índice— la terna **herramienta + versión + flags**: `pdftotext` (Xpdf) **4.00** con **`-layout -enc UTF-8`**. D-04 aprueba **`-layout`** y **no** aprueba `-enc UTF-8`: la combinación completa `-layout -enc UTF-8` **no puede citarse como configuración vigente de D-04** ni como configuración aprobada, y en esta entrada se la nombra como **la configuración usada en los experimentos**. Lo que agrega esta propuesta es la **versión explícita**, la **codificación explícita** y el registro de la **política de decodificación** aplicada al texto extraído antes de definir el contenido lógico. `[I]` Sin esa política, el mismo PDF produce contenidos lógicos distintos (E7) y `content_hash` deja de estar determinado. Esta propuesta es **documental**: no adopta dependencias, no modifica `pyproject.toml` ni el lockfile, no inicia implementación y **no** aprueba ninguna incorporación al código. `[D]` **Cerrado documentalmente en `D-19`**: allí se fija la configuración efectiva —`pdftotext` (Xpdf) **4.00** con **`-layout -enc UTF-8`** y decodificación **UTF-8 estricta**—, su representación en la identidad —el campo `extractor` pasa a llevar la configuración efectiva— y las tres reglas del fragmentador en el manifiesto v2 de D-10. `[V]` **VAL-01** sigue abierta: la configuración registrada será la **efectiva de cada ingesta**, no la esperada, y un extractor distinto cambia `index_version` por diseño.

**§5 Aclaraciones sobre hashes y versiones (sin cambios normativos).** (i) **`document_version`** sigue siendo SHA-256 de los **bytes del PDF** (D-11 §1): no depende del extractor ni de la codificación y **no cambia** por esta propuesta. (ii) **`content_hash`** cubre la representación UTF-8 del **contenido lógico definitivo** (D-11 §3); dos decodificaciones distintas del mismo extracto producen contenidos lógicos distintos (E7), de modo que la huella **no es comparable** entre ellas y sólo queda determinada si la **política de decodificación** está declarada —que es lo que propone §4—. (iii) **`index_version`**: los **seis insumos** de D-11 §4 quedan **intactos**; si la revisión del pipeline o la política de codificación debieran entrar como **séptimo** insumo es **Q-1/Q-2** (D-15 §8), **abierto**, y esta entrada **no** lo decide ni modifica D-11. (iv) Nada de esta entrada cambia las **cuatro definiciones de D-11** ni el vocabulario de D-07.

**§6 Métricas históricas: no comparables, no recalculadas.** `[I]` Las cifras documentadas de **D-04** y **D-05** —y con ellas el «**12 de 178**» del ítem (c) de RP-02— provienen de una extracción en **modo plano**: el Experimento 1 verificó que el artefacto de referencia de esa medición es **byte-idéntico** a una corrida **sin `-layout`**. Esas cifras **no son directamente comparables** con las obtenidas con `-layout -enc UTF-8` (E7). Medir el anclaje con la configuración `-layout -enc UTF-8` —la usada en los experimentos; **no** una configuración aprobada en D-04— arrojó, sobre el corpus del piloto, **0 de 166** unidades sin encabezado localizable y **3 referencias del front matter** explicadas por el **off-by-one** del outline (E1, E6). **Esos recuentos son resultados experimentales obtenidos con umbrales experimentales y no constituyen validación normativa de los 166 anclajes**: no satisfacen el criterio de verificación de RP-02 —que sigue pendiente— ni convierten evidencia en decisión. **No se recalcula ninguna métrica histórica** aquí y **no se autoriza** hacerlo: queda como decisión aparte del propietario.

**§7 Lo que esta propuesta NO cierra.** La **re-medición** de D-04/D-05 · **D-11**, sus cuatro huellas y sus seis insumos · **Q-1/Q-2** y el séptimo insumo de `index_version` · **M7/CD-01** · **P-1b, P-2, la cláusula residual C-1 y el esquema físico** que D-15 deja pendientes, junto con las autorizaciones documentales de **D-15 §12.4** · **D-12 §1** (normalización de la especificación), **D-12 §3** (`deploy/`) y **D-12 §4** (`requires-python`), que siguen sujetos a aprobación · la **licencia** del proyecto (D-12 §5) · la **retención de versiones anteriores** (D-13, pregunta abierta declarada 2) · **VAL-01 … VAL-07** y **VAL-D06-01 … VAL-D06-05** · **T-1 … T-7** · `git init`, `pyproject.toml`, estructura física y dependencias. **RP-02**, la **política de cola** y el **registro del extractor** ya no figuran en esta lista: quedaron **cerrados documentalmente** en **`D-17`**, **`D-18`** y **`D-19`**, respectivamente.

**§8 `[V]` Identificador de esta entrada — comprobación documental.** Se verificó la documentación vigente **antes** de etiquetar: el identificador **`D-16` no está reservado en ningún documento** de la especificación (`README.md`, `AGENTS.md`, `001`, `002`, `003`, `004`): `D-16` y `D-17` no aparecen en ninguna parte, no existe declaración de reserva ni convención de numeración, y los pendientes de **esquema físico, P-1b, P-2, C-1 y Protocolo B** están registrados **dentro de D-15** (§12 y §13), bajo su propio identificador. Por eso esta entrada se numera **D-16**. **Advertencia declarada, fuera de la documentación vigente:** en el trabajo de sesión previo —borradores y anclas de memoria, **no incorporados al repositorio**— esos mismos pendientes se etiquetaron conversacionalmente como «D-16». El propietario **mantuvo `D-16`**: no reserva un identificador por su uso conversacional previo. Si más adelante decidiera reservarlo, la renumeración a otro identificador libre son cuatro sustituciones localizadas —título del bloque, esta sección, la referencia interna del párrafo de RP-02 y la frase de «Estado de Fase 0»— sin efecto sobre el resto del contenido.

**Incorporación:** propietario — aprobación conceptual del **contenido** y autorización expresa de aplicación, 2026-10-15. La aprobación se refiere al contenido descrito en el informe de revisión y **no** certifica de forma independiente los bytes del parche ni sus hashes; **no** autoriza implementación y **no** cierra ninguno de los pendientes de §7.

**Estado:** **entrada incorporada** al documento con **aprobación conceptual del propietario sobre su contenido** y **autorización expresa de aplicación**; el incremento a **v0.19** quedó aplicado. Sus **§2, §3 y §4 no son decisiones cerradas**: los niveles de evidencia, la política de cola —B candidata, sin excepciones resueltas— y el registro del extractor siguen **abiertos**, y **no** se declara verificado ningún comportamiento. Los pendientes de §7 siguen vigentes.

### D-17 — Anclaje del encabezado: criterio definitivo · CERRADA (cierre documental de RP-02)

**Qué cierra y qué no.** Cierra **documentalmente** **RP-02**: fija el criterio con el que un fragmento arranca en su encabezado, la calibración documental que lo hace operativo, el comportamiento exigido cuando no puede anclarse y el criterio de verificación. **No** declara implementado ni verificado ningún comportamiento, **no** habilita la implementación, **no** altera **D-05** (ptos. 1, 2 y 8), **D-10**, **D-11** —cuyos **seis insumos** de `index_version` quedan intactos—, **D-13**, **D-14** ni **D-16**, y **no** decide la política de cola (D-16 §3) ni la representación del extractor en la identidad de construcción. Los parámetros que cita son **calibración medida sobre el piloto** y **no** son universales.

**Puntos resueltos por el propietario que este criterio fija** (`[D]`): **P1** = fallo con **exclusión explícita registrada** (§5); **P2** = el nivel `pagina+tipografia` **ancla** y se registra como evidencia más débil (§3); **P3** = la calibración del anclaje vive como **función determinista del documento y del procedimiento declarado, registrada en la traza de ingesta** (§4.5, con su límite declarado en §4.6).

#### §1 Definición operativa

1. La unidad es el nodo de la jerarquía (hoja más profunda disponible; [D] D-05 pto. 1) y el anclaje se resuelve **por unidad**, sobre su **página declarada** (la del bookmark; [D] D-01 fija la página física del PDF).
2. El fragmento **arranca en la primera línea del bloque de encabezado** de su unidad. Ninguna línea anterior forma parte del fragmento.
3. `heading_start = true` ([D] D-10) declara la regla; esta decisión fija **cómo se localiza** el encabezado y **cómo se verifica**.
4. Dónde termina el material anterior al anclaje —la cola previa— lo fija la política de cola (**`D-18`**): esta decisión fija dónde **empieza** el fragmento, no qué se hace con la cola.

#### §2 Localización — bloque de encabezado y comparación

1. **Bloque de encabezado:** run maximal de líneas **consecutivas** de la página declarada con fuente **negrita** y tamaño ≥ umbral calibrado (§4), acumulado **hasta cubrir el título**. El run se corta en la primera línea no negrita o de tamaño inferior y no puede exceder **4 líneas** ni **300 caracteres**; si al alcanzar esos topes no cubre el título, **no hay bloque** (§5).
2. **Cobertura del título:** el texto acumulado, normalizado, **contiene** el título normalizado **o** sus **primeras 4 palabras** son **prefijo** del texto acumulado. No se admite una coincidencia en cualquier parte de una línea de cuerpo.
3. **Normalización de comparación** (válida sólo para comparar; **no** altera el contenido indexado): minúsculas; espacios y saltos colapsados; guion de corte al final de línea unido sin espacio; guion suave eliminado; **forma ordinal normalizada** (`N.` ↔ `Chapter N.` / `Capítulo N.`), que es la causa medida de que la coincidencia exacta fallara en los 8 capítulos del piloto. **No** se quitan diacríticos: el índice los normaliza para el léxico ([D] D-10, `unicode61 remove_diacritics=2`), mientras el anclaje compara texto literal; son ámbitos distintos y no se mezclan.
4. **Desempate:** si más de un run de la página cubre el título, se elige por nivel (§3): el de `y` más próximo al destino, o el de menor `y` dentro de la banda. Si dos runs empatan en el criterio aplicable, el caso es **no concluyente** y rige §5.
5. **Prohibiciones:** no se busca en otras páginas —una discrepancia de página del outline **no** se compensa en silencio: se reporta como anomalía (§7)—; no se acepta una coincidencia en línea de cuerpo (no negrita o tamaño < umbral); no se recorta el título para forzar la coincidencia.

#### §3 Dos niveles de evidencia, no equivalentes

- **`posicional`:** página declarada y bloque que cubre el título, con `y_destino > 0` y `|(y0 − y_destino) − Δ| ≤ tol`.
- **`pagina+tipografia`:** sin `y` utilizable (aperturas de capítulo): página declarada y bloque dentro de la **banda superior**.
- El nivel **se registra por unidad** y un caso de nivel 2 **no** se presenta como nivel 1. `[D]` **El nivel 2 ancla** —no es sólo una marca—: su diferencia es la **fuerza de la evidencia** (una sola fuente de posición frente a dos), no la validez del corte.

#### §4 Calibración documental: función determinista, registrada

1. Al ingerir se calibra **por documento**: `Δ` = mediana de (y0 del bloque − y_destino) sobre las entradas del outline con `y` utilizable y bloque localizable; `tol` = max(2 pt, 1,5 × dispersión observada); banda superior declarada; umbral de tamaño de encabezado derivado de los bloques de calibración.
2. **Condiciones de aceptación:** al menos **20** entradas de calibración y dispersión ≤ **3 pt**. Si no se cumplen, la calibración **falla explícitamente** y la ingesta no produce fragmentos: no se ancla contra una referencia no fiable. **No** hay parámetros ajustados por caso.
3. **Valores del piloto (calibrados, no universales):** `Δ` = **72,57 pt** con dispersión **0,75 pt** ⇒ `tol` = 2 pt; banda **200 pt**; encabezados de capítulo **30,0 pt** (26,11 en el capítulo 3) y de sección **19,37 pt** frente a cuerpo **15,0 pt** (13,06 en el capítulo 3).
4. `[I]` Los umbrales del punto 2 (**20** entradas, **3 pt**) **no** provienen de una medición: son elecciones de diseño declaradas como tales.
5. `[D]` **Dónde vive la calibración (P3):** se **recalcula de forma determinista** a partir del documento y del procedimiento declarado, y se **registra en la traza de ingesta**; **no** se incorpora a `index_version` —cuyos **seis insumos** quedan intactos ([D] D-11 §4)— ni al manifiesto de **D-10**.
6. **Límite declarado del punto 5:** al no entrar en `index_version` ni en `chunking_config_version`, dos ingestas con **procedimientos de anclaje distintos** podrían producir fragmentos distintos compartiendo `index_version`. **Mitigación exigida:** la ingesta **registra** el procedimiento y su versión en la traza, y un **cambio de procedimiento obliga a reingesta y reevaluación**, por analogía con la regla de revisión de [D] D-10. El defecto de identidad quedó **declarado como residual**. `[D]` **Resuelto en `D-19`**: el procedimiento de anclaje entra al manifiesto v2 de D-10 como `anchoring_procedure`, con la regla de que **todo cambio en sus umbrales obliga a una nueva versión del procedimiento**, de modo que `chunking_config_version` y `index_version` ya lo distinguen.
7. **Artefacto de escala del outline — separación de implementación, medición y decisión.** `[I]` **Implementación observada** (sin validación propia todavía): la calibración separa las entradas del outline en un **núcleo** y un **resto**; si el resto es consistente con un **factor único** `k` tal que `y_destino ≈ k · (y0 − Δ)`, el destino se corrige a `y_destino / k` **antes** de anclar y la decisión se registra por entrada; si no hay factor único, el destino **no se usa** y la unidad se ancla por el segundo nivel de §3. **Medido** (un solo documento —el PDF piloto—; Experimento 3 sobre el capítulo 3 y la corrida de la unidad 1, ver §7): **17** entradas corregidas, factor **1,148827**, residuo máximo **≤ 0,751 pt**, **0** destinos inutilizables, concentradas en el capítulo 3 (páginas 184–229), donde el mismo factor explica los tamaños de fuente —encabezados de sección **16,9 pt** frente a **19,37 pt** fuera de él y cuerpo **13,06 pt** frente a **15,0 pt**, ambos conforme a §4.3—. `[P]` **Regla que se propone documentar:** detección determinista de un factor único sobre las entradas fuera del núcleo; corrección `y_destino / k` aplicada **antes** de anclar; **registro obligatorio** de la corrección o de la inutilidad —nunca compensación en silencio (§2.5)—; y, mientras no se decidan los valores del punto siguiente, los datos que hoy se registran: entradas corregidas, factor, **residuo máximo observado** y destinos inutilizables, en la traza de ingesta (D-20 §3.2). `[I]` **Umbrales — valores iniciales de diseño (D-21):** los tres valores implementados —residuo máximo aceptado **1,0 pt**, ventana que define el núcleo **2,0 pt** y fracción mínima de núcleo **2/3**— **no provienen de una medición**: son **elecciones de diseño** declaradas como tales, con el mismo patrón del punto 4, y quedan **aprobados como valores iniciales de diseño** por `D-21`, revisables mediante una nueva versión del procedimiento; **no** se presentan como umbrales universalmente validados. `[D]` **Consecuencia de cambiarlos:** rige la regla del punto 6 ([D] `D-19` §3) y los **seis** insumos de `index_version` **no** se alteran ([D] `D-11` §4). **No se afirma** que la reconstrucción exacta de `anchor_evidence` esté demostrada: aprobar estos valores **no** la demuestra y sigue pendiente el experimento que la comprobaría (D-20 §3.1); hasta entonces, del artefacto solo queda registrado el **agregado** de la traza (D-20 §3.2).

#### §5 Cuando no puede anclarse (condición (d) de RP-02)

`[D]` **P1 = fallo con exclusión explícita registrada.**

1. Si **cualquier** unidad del corpus no puede anclarse —no hay bloque que cubra el título (§2.1 y §2.2), o el desempate es no concluyente (§2.4)—, la ingesta **falla de forma explícita** y **no publica fragmentos**: ni catálogo ni índice se presentan como completados ([D] D-13).
2. El fallo **informa las unidades afectadas** con la evidencia disponible: página, texto esperado, runs encontrados y nivel intentado.
3. Indexar queda habilitado **sólo** si el propietario autoriza una **exclusión explícita y registrada** de esas unidades: la exclusión se persiste (unidad, motivo, fecha) y se **reporta**; las unidades excluidas no aparecen en el índice ni en los resultados.
4. **Prohibido** el corte silencioso al inicio de la página: no existe un modo «anclar al inicio de página» como reserva automática.
5. Si la **calibración** del §4 falla, rige lo mismo: la ingesta no produce fragmentos.

#### §6 Verificación (condición (e) de RP-02)

`[D]` El anclaje debe ser verificable **sin inspeccionar el interior del pipeline**, con propiedades observables:

1. **Por fragmento:** la primera línea de `content` coincide, bajo la normalización de §2.3, con la primera línea del **bloque de encabezado registrado** para su unidad; el registro de anclaje incluye página, `y0`, nivel y `y_destino` cuando exista.
2. **Agregado por documento:** `unidades_ancladas` = `unidades_del_corpus`, con desglose por nivel, y **ninguna** unidad sin anclar y sin registrar —ni excluida sin su registro—.
3. **Negativo:** ninguna primera línea de fragmento proviene de una línea de cuerpo (no negrita o tamaño < umbral) ni del inicio de página por defecto.
4. **Estado:** la verificación **no** se ejecuta ni se declara hecha en esta etapa; es un procedimiento que la implementación deberá ejecutar. Este cierre es **documental**, como [D] D-14 y D-15.

#### §7 Evidencia y límites

- **Medido** (Experimentos 2 y 3, configuración `-layout -enc UTF-8`, **un solo PDF**; ver D-16 §1): **166/166** unidades del corpus localizadas —155 por coincidencia exacta y 11 tolerantes—; las **11** verificadas como bloque de encabezado (**3** `posicional`, **8** `pagina+tipografia`); **3** anomalías del front matter por **off-by-one** del outline, **fuera del corpus** y no compensadas en silencio (§2.5); `Δ` y dispersión según §4.3.
- **No medido:** el **nivel** de las 155 localizadas por coincidencia exacta —no se verificaron una por una—; la calibración con otro extractor (**VAL-01**); el comportamiento con otro documento.
- **Cifra histórica:** el «**12 de 178**» de la medición previa en **modo plano** no se reproduce con la configuración usada en los experimentos; se conserva como criterio de verificación pendiente y **no** como resultado alcanzado.
- Los conteos anteriores son **evidencia experimental**, **no** validación normativa del anclaje.

#### §8 Pendientes que esta decisión NO cierra

La **representación del extractor y del anclaje en la identidad de construcción** (§4.6) —la **política de cola** quedó cerrada documentalmente en **`D-18`**— · la **implementación y verificación** de este criterio · **VAL-01** y las demás validaciones · **P-1b, P-2, C-1 y el esquema físico** de D-15 · **Q-1/Q-2** y el séptimo insumo de `index_version` · los demás pendientes de D-16 §7.

**Aprobación:** propietario, 2026-10-15 — con el criterio definitivo y los tres puntos P1–P3 resueltos; el cierre es **documental** y no declara verificado ningún comportamiento.

### D-18 — Política de cola y contenido del fragmento · CERRADA (cierre documental del pendiente de D-16 §3)

**Qué cierra y qué no.** Cierra **documentalmente** el pendiente de **política de cola** que D-16 §3 registraba como propuesta: adopta **B**, fija su mecanismo, sus casos límite y su invariante de verificación, y establece la **exclusión del mobiliario de página** del contenido del fragmento. **No** implementa ni verifica, **no** habilita la implementación, **no** altera **D-05** (ptos. 1–3, 5, 6 y 7), **D-10**, **D-11** —cuyos **seis insumos** y cuyas cuatro definiciones quedan intactos—, **D-13**, **D-14**, **D-16** ni **D-17**, y **no** decide la pertenencia semántica de las figuras ni la representación de fin de contenido en el manifiesto (§6.1, residual declarado).

**Puntos resueltos por el propietario** (`[D]`): **Q1** = se adopta **B** con el mecanismo de §2; **Q2** = la cola se **fusiona** en el contenido del predecesor (§2.3); **Q3** = la **exclusión del mobiliario de página** se incorpora en esta decisión (§3).

#### §1 La cola es contenido del predecesor, no texto huérfano

La «cola previa» es el texto que queda **sobre el encabezado** de una unidad en su página de inicio. Bajo [D] D-05 pto. 2 —el fragmento arranca en su encabezado— el texto que está **entre dos encabezados pertenece a la unidad anterior**. Por lo tanto:

1. **A — descartarla** no pierde «cola»: pierde **contenido del predecesor**. En los **10 casos medidos** en que el predecesor empieza en esa misma página, descartar el texto sobre el encabezado borraría el **encabezado y el texto del propio predecesor** (1.777 palabras): el corte por página es **incoherente**, no sólo costoso.
2. **C — solaparla** exigiría duplicar texto **entre unidades**, y [D] D-10 fija `overlap_scope = "same_unit"`, con el solapamiento dentro de la misma unidad ([D] D-05 pto. 7): C requeriría **abrir D-10**.
3. **B** es la lectura directa de D-05 + D-10: el contenido de una unidad **corre hasta el encabezado de su sucesora**. No es una preferencia entre opciones equivalentes: es la **única compatible con el texto normativo vigente**.

#### §2 Mecanismo adoptado (B)

1. **Fin de contenido.** El contenido de una unidad es el texto que va **desde la primera línea de su bloque de encabezado** ([D] D-17 §2) **hasta la primera línea del bloque de encabezado de su sucesora**; para la última unidad del corpus, hasta el final de su rango declarado. **Sin cortes por página.**
2. **Una sola vez.** La cola de U(i) es, por construcción, la **parte final del contenido de U(i−1)**: se incluye **una sola vez**, dentro de los fragmentos de U(i−1). No hay reasignación ni duplicación.
3. **Materialización por fusión.** La cola se **fusiona en el contenido del predecesor** y **participa del tope y del corte por párrafo**: se aplican las reglas vigentes de [D] D-10 sin cambiarlas (`segmentation_unit = hierarchy_leaf`, `split_boundary = paragraph_within_unit`, `max_words = 1500`, `overlap_words = 0`, `table_blocks = atomic`).
4. **Procedencia.** El `pdf_page_end` del último fragmento de U(i−1) **se extiende** a la página donde aparece la cola, y el primer fragmento de U(i) arranca en esa misma página. Dos unidades pueden compartir página; ya ocurre en el corpus (**12 páginas** con más de un arranque, de 166).
5. **Invariante — criterio de verificación.** *Cobertura contigua y sin solape*: la concatenación de los fragmentos de U(i−1) y de U(i) cubre el texto de la página **sin hueco y sin repetición**, y el primer fragmento de U(i) empieza exactamente donde termina el último de U(i−1). Es verificable sobre los fragmentos producidos, **sin inspeccionar el interior del pipeline**.

#### §3 Exclusión del mobiliario de página

1. **Regla.** Se excluye del contenido del fragmento la **línea del número impreso de página**, identificada de forma determinista: la **última línea de texto** de una página cuando, ya recortada, satisface `^\d{1,4}$` **y** su valor es **`pdf_page − 1`** ([D] D-01 fija que la numeración impresa equivale a `pdf_page − 1`).
2. **Evidencia del piloto.** Corpus (páginas 25–716): **692 de 692** páginas cumplen la regla, con **0 excepciones** y **0 páginas sin número**; fuera del corpus, 91 de 92 páginas del front y back matter. **Ninguna cola** contiene la línea (el número va debajo del encabezado).
3. **Alcance.** Es una regla de **definición del contenido lógico**: afecta a `content` y a `content_hash`, conforme a [D] D-11 §3, que ya distingue el **texto extraído** del **contenido lógico definitivo**. **No** afecta a `document_version`, que sigue siendo el SHA-256 de los bytes del PDF ([D] D-11 §1), y **no** modifica el artefacto de extracción.
4. **Límites de la regla.** No se excluye ninguna otra línea numérica: sólo la que cumple **las dos** condiciones del punto 1. Si la última línea de una página fuera un número **distinto** de `pdf_page − 1`, se **conserva** y se **registra como anomalía**; nunca se descarta en silencio.
5. **Motivo medido.** Sin esta regla, todo fragmento que atraviesa páginas arrastra el número impreso **dentro de su `content`** —una línea por página cubierta—, y el texto servido al consumidor lo muestra.
6. **Verificación.** Observable: en cada fragmento, ninguna de sus líneas coincide con el número esperado de las páginas de su rango; y en el agregado, **páginas cubiertas − líneas excluidas = 0**. **No se declara ejecutada** en esta etapa.

#### §4 Casos límite (con la medición que los respalda)

| Caso | Medición (Experimentos 2 y 3) | Resolución |
|---|---|---|
| El predecesor arranca en la **misma** página | **10 unidades / 1.777 palabras** de 130 / 14.731; en las 10, la región contiene el título de otra unidad | **No es un caso especial**: es texto cuyo encabezado está ahí. Se incluye en el predecesor y se registra |
| Predecesor de tipo `parent_own` | **40 pares** «texto propio del padre → su primer hijo» | La regla «entrada inmediatamente anterior en orden de lectura» lo cubre: la cola del primer hijo entra en el texto propio del padre. **Sin caso especial** |
| Cola **sin prosa** (sólo rótulo) | **3 unidades** (`Step 5` 0 palabras; `Step 3` y `Monitoring` 1 palabra) | El rótulo es contenido del predecesor y se incluye; **la imagen no es texto indexable** |
| Material de una **región excluida** | **0 casos activados** | [D] D-05 pto. 6 obliga a excluirlo: se **excluye y se registra**, nunca se atribuye a una unidad del corpus |
| **Bloques de tabla/figura** en la cola | **30** (28 `Figure` + 2 `Table`) | Atómicos y etiquetados ([D] D-05 pto. 5 y `table_blocks = atomic` de D-10); no se parten |
| Tamaño de las colas | n=130: mín 9 · p25 56 · **mediana 106,5** · p75 170 · máx 271 palabras | El tope de 1.500 palabras no se alcanza por la cola sola |

#### §5 Corrección de la cuantificación (auto-auditoría)

El Experimento 2 contó «palabras sobre el encabezado» **sin distinguir** los 10 casos en que el predecesor arranca en esa misma página. Por eso: **14.731 palabras** es la exposición total ante un corte por página; **12.954** es la cola estricta —continuación del predecesor en una página donde no arranca otra unidad—; y **1.777** (10 unidades) son contenido propio del predecesor, sin reasignación alguna. La afirmación «B reasigna 14.731 palabras» es **imprecisa** y no debe citarse así.

#### §6 Pendientes que esta decisión NO cierra

1. **Reglas de contenido sin campo en el manifiesto.** El manifiesto de [D] D-10 declara `heading_start = true` —dónde **arranca** el fragmento— pero **no** dónde **termina**, ni contempla la exclusión del mobiliario de página. La regla de fin de contenido (§2.1) y la exclusión (§3) **no tienen campo propio**. Se declaran **residuales** y se resuelven al fijar la representación del extractor y del anclaje en la identidad de construcción; **no se abre D-10 por inferencia**. Hasta `D-19`, `chunking_config_version` **no distinguía** una implementación con corte por página de la estructural, ni una con mobiliario de página incluido de una que lo excluye: `[D]` **Resuelto en `D-19`**, que incorpora el fin de contenido y la exclusión del mobiliario al manifiesto v2 como `content_end` y `page_furniture`.
2. **Pertenencia semántica de las figuras:** sin decidir. La evidencia —30/30 rótulos sobre el encabezado y 28/30 referenciados en la prosa previa (D-16 §1)— es **evidencia**, no prueba.
3. **Implementación y verificación** de esta política: pendientes, no declaradas.
4. **Mobiliario fuera del corpus:** los 91 de 92 páginas del front y back matter quedan fuera por [D] D-05 pto. 6; la regla de §3 se limita al contenido del corpus.
5. Los demás pendientes de D-16 §7 y de D-17 §8.

**Aprobación:** propietario, 2026-10-15 — con Q1 (B), Q2 (fusión en el predecesor) y Q3 (exclusión del mobiliario de página) resueltos; el cierre es **documental** y no declara verificado ningún comportamiento.

### D-19 — Configuración efectiva del extractor y su representación en la identidad de construcción · CERRADA

**Qué cierra y qué no.** Cierra **documentalmente** la configuración efectiva del extractor y su representación en la identidad de construcción, y con ello los **tres residuales** declarados en `D-16` §4, `D-17` §4.6 y `D-18` §6.1. **No** implementa ni verifica, **no** habilita la implementación, **no** agrega ni quita insumos de `index_version` —**los seis de D-11 §4 se conservan, en su orden**—, **no** resuelve **Q-1/Q-2** (la revisión de código como séptimo insumo, que sigue abierta), **no** decide el esquema físico ni P-1b/P-2/C-1, y **no** altera el resto de D-10 ni de D-11.

**Puntos resueltos por el propietario** (`[D]`): **Q1** = se fija la configuración efectiva del extractor (§1); **Q2** = el campo `extractor` de `index_version` **lleva la configuración efectiva** (§2); **Q3** = las tres reglas del fragmentador entran al **manifiesto v2** de D-10 (§3).

#### §1 Configuración efectiva del extractor

1. **Herramienta, versión y flags.** `pdftotext` (**Xpdf**) **4.00** con **`-layout -enc UTF-8`**. D-04 aprueba `-layout` y **no** aprueba la codificación: esta decisión **completa** la configuración efectiva y **no modifica D-04**; la combinación completa **no** puede citarse como enmienda de D-04.
2. **Política de decodificación.** Decodificación **UTF-8 estricta**: sin `errors="replace"`, sin BOM y sin normalización posterior. Se declara porque una política permisiva **oculta** los errores de decodificación: en el Experimento 3 una sustitución silenciosa escondió primero el problema de codificación (defecto propio, conservado como evidencia).
   **Enmienda aprobada por el propietario el 2026-10-23 — excepción CESU-8.** Un PDF puede traer un carácter astral codificado como **dos surrogates UTF-8** (CESU-8) en lugar de la secuencia UTF-8 de cuatro bytes; es el caso de `libro_Agentic_Architectural_Patterns.pdf`, que falla en la posición 61.225 con los bytes `ED A0 BE ED B7 A0` (U+1F9E0). Esos **pares se recomponen** en el carácter que el autor escribió, de modo que el contenido extraído queda íntegro. La excepción es **acotada**: un surrogate **no emparejado** —o cualquier otra secuencia irreparable— sigue siendo `decode_error` y la extracción falla; no se introduce `errors="replace"` ni ninguna sustitución silenciosa. La estrictez frente a bytes inválidos no cambia.
3. **Regla de registro.** Se registra la configuración **efectiva de cada ingesta**, no la esperada. `[V]` **VAL-01** sigue abierta: si el host ARM64 usa otro extractor —Poppler, por ejemplo—, se registra **ese** y, al cambiar el valor, **cambia `index_version`**, que es el comportamiento exigido.
4. **Evidencia medida del piloto.** PDF `0cd2fc84…`. Con `-layout -enc UTF-8`: `281f2f23…`, 1.214.721 B, **170.917 palabras**, 0 reemplazos. Sin `-enc`: `324a4511…`, 1.206.781 B, **170.887 palabras**, 151 bytes altos —todos ≥ 0xA0 ⇒ Latin-1— y 151 reemplazos al decodificar como UTF-8; 13 páginas con recuento distinto. La línea base documentada de D-04/D-05 provino del **modo plano**.
5. **Alcance sobre otros registros.** Esta decisión precisa el elemento «Extractor y su versión» de la lista de fuentes canónicas de **D-02**: comprende también su **configuración efectiva**. **No** modifica D-02, cuya lista ya es objeto de la dependencia declarada **CD-04**.

#### §2 Representación del extractor en `index_version`

1. **Se amplía el valor, no el conjunto.** El insumo 2 de D-11 §4 conserva su lugar y su nombre (`extractor`) y el conjunto **sigue siendo de seis insumos**; cambia el **valor** del campo: pasa de un arreglo ordenado de **dos** cadenas a uno de **tres** —`["pdftotext","4.00","-layout -enc UTF-8"]`—, donde la tercera es la **configuración efectiva** y es **obligatoria**.
2. **Valores ausentes o inválidos.** Rige D-11 §4 sin cambios: ningún insumo admite sustitutos; si falta cualquiera de las tres cadenas, el campo no es válido y **`index_version` no se calcula**.
3. **Sin migración.** No existen valores históricos de `index_version` que migrar; el cambio afecta a los índices construidos en adelante. `document_version` y `content_hash` **no** cambian por esta decisión.
4. **Efecto exigido.** Dos **configuraciones efectivas distintas** del mismo extractor y versión **no pueden** producir el mismo `index_version`.

#### §3 Las tres reglas del fragmentador en el manifiesto

1. **Manifiesto v2.** El manifiesto de D-10 pasa a tener **catorce campos**: los once adoptados, **en su orden**, más tres **al final** —`content_end`, `page_furniture`, `anchoring_procedure`— con valores `"next_heading"`, `"excluded"` y `"anchoring/v1"`. `schema` pasa a **`"chunking_config/v2"`**, conforme a la regla de D-10 según la cual el `schema` versiona la **estructura** del manifiesto: campos, tipos y orden. **Actualización posterior (paso 5):** el propietario autorizó la segunda herramienta de geometría y el manifiesto pasa a **quince** campos con `geometry_tool` —la herramienta de geometría **efectiva**, registrada por corrida— y `schema` = **`"chunking_config/v3"`**; el resto de esta sección no cambia.
2. **Por qué así.** Las tres reglas **son reglas del fragmentador** —fin de contenido (`D-18` §2.1), exclusión del mobiliario de página (`D-18` §3) y procedimiento de anclaje (`D-17` §2 a §5)— y el manifiesto es, por definición de D-10, **declarativo**: enuncia qué reglas se aplicaron. Entran por el **tercer insumo ya existente** (`chunking_config_version`), de modo que **no se agrega ningún insumo**.
3. **Umbrales del anclaje.** Los umbrales de calibración de `D-17` §4.2 y §4.3 —número mínimo de entradas, tope de dispersión, banda superior y `tol` mínimo— son **parámetros de diseño del procedimiento**: **todo cambio en ellos obliga a una nueva versión del procedimiento de anclaje**, que cambia el manifiesto y por tanto `chunking_config_version` e `index_version`.
4. **Los valores calibrados no entran.** `Δ`, la dispersión observada y el umbral de tamaño **no** forman parte del manifiesto: son **función determinista** del documento y del procedimiento declarado (`D-17` §4.5) y se registran en la traza de ingesta.
5. **Efecto exigido.** Dos conjuntos distintos de reglas declaradas **no pueden** producir el mismo `chunking_config_version`; y la **reconstrucción** del índice desde las fuentes registradas reproduce el mismo `index_version`.

#### §4 Verificación (observable), no ejecutada

1. Dos configuraciones efectivas distintas del extractor **no pueden** compartir `index_version`.
2. Dos conjuntos distintos de reglas declaradas **no pueden** compartir `chunking_config_version`.
3. La **reconstrucción** desde las fuentes registradas reproduce el mismo `index_version`.
4. Todo cambio de valor del manifiesto v2 produce una **entrada canónica distinta** (regla ya fijada por D-10).

**No se declara ejecutada**: el cierre es **documental**.

#### §5 Lo que esta decisión NO cierra

**Q-1/Q-2** (revisión de código como séptimo insumo) y la **revisión del código ejecutado** (D-15 §8.2) · **M7/CD-01** · **P-1b, P-2, C-1 y el esquema físico** · **VAL-01** y las demás validaciones · el **contrato del fragmentador** en su forma completa · la **implementación** de estas reglas · y dos anotaciones **no** realizadas, que quedan como decisión aparte del propietario: el texto de **D-04** («extractor principal `pdftotext -layout`») y la referencia «se verifica según **RP-02**» del bullet de correspondencia de **D-10**, ambas dentro de decisiones cerradas.

**Aprobación:** propietario, 2026-10-15 — con Q1 (configuración efectiva), Q2 (campo `extractor` con tres cadenas) y Q3 (manifiesto v2) resueltos; el cierre es **documental**, los seis insumos de `index_version` se conservan y no se declara verificado ningún comportamiento.

### D-20 — Contrato mínimo de la unidad 1 (prototipo en memoria) · CERRADA (cierre documental de O-3, O-4 y O-5 y de la parte interna de CD-03)

**Qué cierra y qué no.** Cierra **documentalmente** el contrato mínimo de la **unidad 1** —extracción → anclaje → fragmentación **en memoria**— y con él las tres omisiones de la auditoría del paso 4 (**O-3** registro del fragmento, **O-4** traza de ingesta, **O-5** errores del camino de ingesta) y la **parte interna** de **CD-03**. **No** autoriza ni inicia implementación —eso es un acto separado del propietario—, **no** crea persistencia, **no** calcula ni publica `index_version`, **no** altera los **seis insumos** de `D-11` §4, **no** cierra **Q-1/Q-2**, **M7/CD-01**, **P-1b**, **P-2**, **C-1** ni el esquema físico, y **no** expone nada en el contrato público de `D-07` ni de `001` §5 y §6.2.

**Puntos resueltos por el propietario** (`[D]`): se incorpora el contrato (Q2) con los nombres internos `level`, `block_type` y `captions` confirmados (Q3).

#### §1 Alcance y no-alcance

1. La unidad recibe una fuente y una configuración y produce **registros de fragmento** y una **traza de ingesta**; debe ser **determinista, auditable y verificable**.
2. Quedan **fuera**: persistencia (SQLite, FTS5, `sqlite-vec`), `index_version`, embeddings, catálogo de fuentes de `D-13`, publicación y generaciones de `D-15`, contratos públicos de `D-07` (CLI, HTTP, MCP), evaluación de `003`, retención, validaciones del host y toda decisión abierta (Q-1/Q-2, M7/CD-01, P-1b, P-2, C-1, esquema físico).
3. La unidad **no** decide identidades: recibe el `document_id` ya decidido.

#### §2 Entradas

| # | Entrada | Regla |
|---|---|---|
| 1 | Ruta al **PDF fuente** | Se leen sus **bytes** sin normalización, para `document_version` ([D] `D-11` §1; `001` §6.1 L97) |
| 2 | `document_id` | **Parámetro explícito** de la corrida; el catálogo es persistencia y queda fuera (`001` §6.1 L96) |
| 3 | Extractor efectivo | `pdftotext` (**Xpdf**) **4.00** con **`-layout -enc UTF-8`** y decodificación **UTF-8 estricta** ([D] `D-19` §1); se registra la configuración **efectiva observada** |
| 4 | **Manifiesto** | Los **quince campos** con sus valores y `schema` = `"chunking_config/v3"` ([D] `D-10` L251-255; `D-19` §3.1); `chunking_config_version` se calcula sobre sus bytes canónicos ([D] `D-10` L250-251) |

#### §3 Salidas

**§3.1 Registro de fragmento** — lista ordenada por lectura, con `ordinal` 1..N:

| Campo | Contenido | Fuente |
|---|---|---|
| `document_id`, `document_version`, `document_version_short`, `chunk_id` | Identidad; `chunk_id` = `{document_id}:{document_version_short}:{ordinal}` | `001` §6.1 L96-98 |
| `section_path`, `level` | Camino capítulo → sección → subsección y **nivel jerárquico** | [D] `D-05` pto. 8 (L62) |
| `block_type` ∈ {`prose`,`table`}, `captions` | Tipo de bloque y rótulos asociados | [D] `D-05` ptos. 5 y 8 (L59, L62) |
| `pdf_page_start`, `pdf_page_end` | Página **física** del PDF; `null` si no es determinable | `001` §6 L92 |
| `content` | Contenido lógico definitivo, con el número de página excluido | [D] `D-11` §3; `D-18` §3 |
| `word_count` `[P]` | Derivado de `content`, para verificar el tope | [D] `D-10` L251 |
| `content_hash` | SHA-256 hex minúsculas 64 sobre la representación UTF-8 de `content`, sin BOM | [D] `D-11` §3 |
| `anchor_level` ∈ {`posicional`,`pagina+tipografia`} | Nivel de evidencia del anclaje, registrado por unidad | [D] `D-17` §3 (L659-664) |
| `anchor_evidence` `[P]` | Página, `y0` del bloque de encabezado y `y_destino` cuando exista | [D] `D-17` §6.1 (L689) |

**`anchor_evidence` es caché derivada, no autoridad (decisión del propietario).** No participa en la identidad, en la huella de la generación, en `index_version`, en `chunk_id` ni en la publicación: su **ausencia, descarte o regeneración no determina** la identidad, la validez ni la publicación de una generación. Es una **caché de auditoría**, reconstruible y descartable. Límites declarados: en el camino de anclaje por **página y tipografía**, `y_destino` **no se registra** (solo `y0` y la decisión); y la reconstrucción de `y0` y de `destination_use` **no está plenamente demostrada** —depende del procedimiento y de parámetros que `D-17` §4 deja pendientes—. La traza agregada de §3.2 **no sustituye** esta evidencia por fragmento: perder la caché no invalida la generación, pero **limita la auditoría detallada**.

**§3.2 Registro de ingesta (traza) — resuelve O-4.** `document_version`; del extractor, nombre, versión y **configuración efectiva**; la **herramienta de geometría efectiva** (marcadores, tipografía y coordenadas); **bytes canónicos del manifiesto** y `chunking_config_version`; **registro de calibración** —procedimiento `anchoring/v1`, número de entradas, `Δ` mediana, dispersión, tolerancia, banda superior y umbral de tamaño de encabezado ([D] `D-17` §4.3 L669 y §4.5 L671) y **artefacto de escala**: entradas corregidas, factor, residuo máximo observado y destinos inutilizables ([D] `D-17` §4, punto 7)—; y **recuentos**: unidades del corpus, unidades ancladas por nivel, fragmentos totales, bloques de tabla, líneas de número excluidas **y anomalías de numeración de página** —`recuento_anomalias_pagina` y `paginas_anomalas`, con la semántica y la representación que fija **`D-23`**— ([D] `D-17` §6.2 L689; `D-18` §3.4 L734 y §3.6 L735). Es **registro operativo**, no artefacto derivado del índice.

**§3.3 `index_version` queda fuera de la unidad.** **No se calcula**: sus seis insumos incluyen versiones del motor ([D] `D-11` §4 L289-290) que pertenecen a la construcción del índice, y `D-11` §4 **no admite sustitutos** (L301). Calcularlo aquí exigiría inventar valores.

#### §4 Invariantes verificables

| ID | Invariante | Fuente |
|---|---|---|
| I1 | Cobertura **contigua y sin solape** entre unidades consecutivas | [D] `D-18` §2.5 (L727) |
| I2 | Todo fragmento arranca en la **primera línea del bloque de encabezado** de su unidad | [D] `D-17` §1.2 (L647) y §6.1 (L689) |
| I3 | Ningún fragmento cruza el límite de su unidad | [D] `D-05` pto. 3 (L57); `D-10` (L256) |
| I4 | Los bloques de tabla son **atómicos** y etiquetados | [D] `D-05` pto. 5 (L59); `D-18` §4 (L746) |
| I5 | Ninguna línea del contenido es un **número de página** | [D] `D-18` §3.6 (L736) |
| I6 | Nada proviene del front matter, del back matter ni del Index | [D] `D-05` pto. 6 (L60); `D-10` (L251) |
| I7 | El **único** fragmento que puede superar `max_words` es un bloque de tabla atómico | [D] `D-10` (L256) |
| I8 | `chunk_id` determinista, sin huecos ni duplicados en 1..N | `001` §6.1 L98; [D] `D-13` P9 (L446) |
| I9 | `content_hash` recomputable desde `content` | [D] `D-11` §3 |

#### §5 Errores del camino de ingesta — resuelve O-5

Códigos **internos** de la ingesta. **No** se agregan al enum público de `001` §6.2 (enum en L107) ni de `D-07`.

| Código | Condición | Efecto |
|---|---|---|
| `source_unreadable` | El PDF no puede leerse | Fallo explícito, sin salida parcial |
| `extractor_unavailable` | El extractor no está disponible | Fallo explícito |
| `extraction_failed` | El extractor devuelve error | Fallo explícito |
| `decode_error` | La salida no decodifica en UTF-8 estricto | Fallo explícito; **no** se sustituyen caracteres ([D] `D-19` §1.2) |
| `outline_unavailable` | Sin outline utilizable para calibrar | Fallo explícito |
| `calibration_failed` | No se cumplen los umbrales de [D] `D-17` §4.2 (L668) | Fallo explícito; **no** hay fragmentos |
| `unit_not_anchored` | Una unidad del corpus sin bloque de encabezado que cubra su título, o desempate no concluyente ([D] `D-17` §5, L675-683) | Fallo explícito; se informan las unidades afectadas ([D] `D-18` §5) |
| `config_invalid` | Manifiesto incompleto o valor inválido ([D] `D-10`; `D-11` §4 L301) | Fallo explícito |

Todo error **detiene la corrida antes de producir salida**, ni total ni parcial, informa la causa y —cuando corresponda— las unidades afectadas ([D] `D-13` P5 L442; `D-18` §5; `002` Fase 1).

#### §6 Determinismo

Misma fuente + misma configuración + mismo `document_id` ⇒ **registros idénticos**: mismo orden, mismos `chunk_id`, mismo `content` y mismos `content_hash`. La traza también es idéntica **salvo marcas temporales**, que se declaran **fuera** de la comparación (`001` §3 pto. 2; [D] `D-13` P9 L446).

#### §7 Criterios de aceptación (pruebas deterministas)

1. **Una prueba por invariante** (I1…I9) y **una por error** (§5), con entrada, salida esperada y código o invariante verificado; los errores se prueban comprobando que **no hay salida**.
2. **Determinismo:** dos corridas sobre la misma entrada ⇒ registros **byte-idénticos**, excluyendo marcas temporales.
3. **Cifras esperadas del piloto** (evidencia de los Experimentos 2 y 3 con la misma configuración; **a confirmar por la corrida, y una diferencia se reporta como hallazgo**): **166** unidades del corpus, **166 ancladas** y **0** sin anclar; **30** bloques con rótulo (**28** `Figure` + **2** `Table`); cola total **14.731** palabras, de las cuales **1.777** pertenecen a predecesores que arrancan en la misma página ([D] `D-17` §7 L694-700; `D-18` §5 L749-752).
4. **No** se fija el reparto `posicional`/`pagina+tipografia` de las 155 unidades localizadas por coincidencia exacta: ese nivel **no fue medido** ([D] `D-17` §7).

#### §8 Relación con la auditoría del paso 4

O-3 → §3.1 · O-4 → §3.2 · O-5 → §5 · **CD-03 (parte interna)** → los nombres `level`, `block_type` y `captions` se adoptan como **procedencia interna** y se enumeran en `001` §6; la **parte pública** de CD-03 **sigue abierta** (no se exponen en `D-07`). A-1…A-4 y R-3 no se tocan en esta decisión.

#### §9 Lo que esta decisión NO cierra

La **implementación** de la unidad —autorización separada del propietario— · **Q-1/Q-2** · **M7/CD-01** · **P-1b, P-2, C-1 y el esquema físico** · **CD-02, CD-04 y CD-05** · **VAL-01 … VAL-07**, **VAL-D06-01 … VAL-D06-05** y **T-1 … T-7** · los pendientes de `D-16` §7, `D-17` §8 y `D-19` §5 · la parte **pública** de CD-03.

**Aprobación:** propietario, 2026-10-16 — con la incorporación del contrato (Q2) y los nombres internos confirmados (Q3); el cierre es **documental**, **no** autoriza implementación y no declara verificado ningún comportamiento.

### D-21 — Umbrales del artefacto de escala: valores iniciales de diseño · APROBADA (opción (b): valores iniciales, **no** umbrales universalmente validados)

**Contexto.** `D-17` §4 punto 7 declara tres valores implementados —residuo máximo aceptado **1,0 pt**, ventana que define el núcleo **2,0 pt** y fracción mínima de núcleo **2/3**— como decisiones de diseño **propuestas, no aprobadas**, sin respaldo documental previo.

**Opciones consideradas.** (a) Dejarlos como detalle de implementación, sin registrarlos. (b) Aprobarlos como **valores iniciales de diseño explícitos**, provisionales y revisables por decisión versionada. (c) Aprobarlos como umbrales validados.

**Recomendación y motivo — opción (b) aprobada.** La evidencia del piloto —un solo documento— los respalda **como valores de trabajo**, no como umbrales validados: la corrida no falló; el residuo observado (**0,751 pt**) queda bajo el admitido con un margen del **25 %**; el núcleo cubrió **116** de **133** entradas medidas, un **30 %** por encima del mínimo exigido (89); y la ventana de 2,0 pt no resultó limitante (dispersión del núcleo 0,75 pt). (c) **no es sostenible**: no hay análisis de sensibilidad ni un segundo documento. (a) pierde la trazabilidad de por qué estos valores y no otros.

**Consecuencias.** Quedan fijados como **valores iniciales del método `anchoring/v1`**, calibrados para el método y el corpus piloto y **no universales**. Todo cambio exige una **nueva versión del procedimiento** (`D-17` §4 punto 6; `D-19` §3), de modo que `chunking_config_version` la distinga; **no** altera los **seis** insumos de `index_version` (`D-11` §4). **Riesgo aceptado:** en la dirección permisiva el único guardián es el propio ajuste —un factor único con residuo ≤ 1,0 pt sobre todas las entradas fuera del núcleo—, de modo que un espacio escalado consistente pero distinto se aceptaría y se registraría como `scale_corrected`; el registro permite auditarlo, no impedirlo.

**Evidencia.** Traza del piloto: `entries` 116 · `outline_scale_anomalies` 17 · `outline_scale_factor` 1,148827 · `outline_scale_residual_max_pt` 0,751 · `destinations_unusable` 0 · `dispersion_pt` 0,75 · `tolerance_pt` 2,0. El **factor** se ajusta por documento; los **umbrales** son constantes del método y **no** se ajustan.

**Evidencia adicional, no ejecutada.** El análisis de **sensibilidad** de los tres umbrales y la verificación sobre un **segundo documento** quedan como **trabajo futuro**: esta decisión no los declara ejecutados ni los necesita para aprobar un valor inicial.

**Aprobación:** propietario, 2026-10-17 — opción (b) elegida expresamente; los valores **no** se aprueban como umbrales universalmente validados. `D-17` §4 punto 7 queda actualizado conforme a esta decisión.

### D-22 — Contrato lógico de persistencia · APROBADA (contrato lógico; **no** aprueba esquema físico, ejecución ni publicación)

**Contexto.** La unidad 1 termina **en memoria** (`D-20`). Persistir exige un contrato que fije **qué se persiste**, con qué **identidades**, **claves** e **invariantes**, y con qué **límites**. El motor y el índice están decididos (`D-02`: SQLite + FTS5 + `sqlite-vec`, índice reconstruible y desechable); las identidades, en `D-11`; la procedencia por fragmento, en `D-20` §3.1 y `001` §6; el catálogo de fuentes, en `D-13`; el marco de publicación, en `D-15`.

**§1 Alcance.** Se aprueba el **contrato lógico**. **No** se aprueba el **esquema físico** ni el DDL, ni la **ejecución** de la persistencia, ni la **publicación** de generaciones (`D-15`), ni implementación alguna, ni ninguna validación experimental.

**§2 Autoridad y derivados.** **Autoridad persistida:** catálogo de fuentes (`D-13`), versiones de documento, **fragmentos** (`D-20` §3.1) y **traza de ingesta** (`D-20` §3.2). **Derivados:** el índice FTS5 y `vec0` (`D-02`: reconstruible), `chunk_id` e `index_version` —recalculados y contrastados, **no** incorporados a la huella (`D-15` §3.3)—. **`content_hash` es distinto:** se recalcula desde el contenido persistido y se contrasta, y **el valor verificado entra como ancla del contenido, en una sola vía** (`D-15` §3.3; `D-11` §3); si no coincide, **falla y no se publica**. Los **bytes del PDF no se persisten**: la fuente es canónica y externa (`D-02`). **Sobre los insumos de `index_version`:** deben existir cuando se calcule la etiqueta —`D-11` §4 **no admite sustitutos**: si falta uno, **no se calcula** y la indexación falla—, pero **este contrato no afirma dónde se persisten** ni que una sola entidad los contenga: `D-20` §3.2 enumera la traza de ingesta y **no incluye** el `tokenizer` ni las versiones del motor, que pertenecen a la **construcción del índice** (`D-20` §3.3). **Tampoco afirma** que esos seis insumos sean los valores que componen la **identidad de construcción**: esos valores **no están definidos** y son **P-2** (§4). Embeddings y `vec0`: fuera de este acto.

**§3 Identidades.** `document_id` (slug asignado por el catálogo, `D-13`) · `document_version` = SHA-256 de los bytes originales, 64 hex sin normalización (`D-11` §1) · `document_version_short` = los 12 primeros caracteres · `chunk_id` = `{document_id}:{document_version_short}:{ordinal}` (`001` §6.1) · `chunking_config_version` = huella del manifiesto de quince campos (`D-10`) · `content_hash` = SHA-256 hex de `content` en UTF-8, **sin truncar** (`D-11` §3) · `index_version` = SHA-256 sobre los **seis insumos** de `D-11` §4, **sin agregar ni quitar ninguno**; **no se calcula en la unidad 1** (`D-20` §3.3) y se calcula al construir el índice.

**§4 Entidades y claves.** `FUENTE` (`document_id`) · `REFERENCIA_FUENTE` (`document_id`, `alias`) · `VERSION_DOCUMENTO` (`document_id`, `document_version`) · `FRAGMENTO` (`document_id`, `document_version`, `ordinal`) con `chunk_id` único · `CONSTRUCCIÓN` —la traza de ingesta (§2), con los insumos declarados en ella—. **Claves naturales**; los identificadores de almacenamiento (`rowid`) **nunca** en el contrato público (`001` §6.1). Se admiten **N** construcciones por versión: la unicidad es política abierta (`CD-05`, P-3).

**Aptitud para distinguir N construcciones (relación con `index_version` y con P-2).** **No reside en `index_version`**: es una etiqueta derivada, truncada a 12 hex, que **no identifica unívocamente una construcción** ni distingue un cambio que sólo afecte al código (`D-15` §2.1, §8.1), y que `D-07` devuelve como **un solo** valor por respuesta (`D-15` §8.5). **Tampoco reside en sus seis insumos**: que existan es condición para **calcular la etiqueta** (`D-11` §4), no definición de la identidad de construcción —`D-15` §2.1 declara esa identidad como un **criterio cuyos valores NO están definidos**, y su materialización, su registro durable, la **uniformidad** por versión y **`R = W`** dependen de **P-2** (`D-15` §12.2; M-15)—. Consecuencia que este contrato asume: `chunk_id` **no** incorpora la construcción (`001` §6.1), de modo que la ambigüedad aparece **si dos construcciones coexisten en el conjunto consultable** y **no** se deduce de conservar generaciones físicas antiguas (`D-15` §10.1 (8)); **toda** comparación se hace sobre la **identidad de construcción**, **nunca** sobre `index_version` (`D-15` §2.1). Por eso este contrato admite N construcciones **lógicamente** y **no** afirma su materialización ni su registro durable: **P-2** queda **diferido**, con los principios expresados y su implementación verificable pendiente (`D-15` §2.1).

**§5 Invariantes de la persistencia.** Unicidad de claves naturales · integridad referencial `FRAGMENTO → VERSION_DOCUMENTO → FUENTE` · ordinales `1..N` contiguos y sin duplicados (`D-20` I8) · `content_hash` verificado **antes** de publicar (`D-15` §3.3) · **ningún valor inventado**: `null` se conserva `null` (`001` §6) · **atomicidad «total o nada»** por versión, con el alcance declarado en `D-15` §4.2 (la transacción del catálogo es atómica **dentro** del catálogo) · sin retirada automática de generaciones (`D-15` §9) · el índice se reconstruye desde la autoridad persistida.

**§6 Integridad y durabilidad: lo documentado y lo que no.** Documentado: atomicidad lógica acotada, integridad de conjunto —sin duplicados, sin publicación parcial, versión anterior intacta, estado honesto— e idempotencia de recuperación (`D-13`). **No documentado y no dado por garantizado:** **durabilidad** del contenido, de la entrada de directorio y del commit (`D-15` §4.2: «ninguna verificada»); la integridad de fragmentos por huella (niveles 1/2/3, `D-15` §7); la huella **no** detecta corrupción de FTS5 (`D-15` §7.1).

**§7 Reconstrucción.** El conjunto normativo es la **lista de reconstrucción de `D-02`**, completada por el cierre parcial de **CD-04**: documento fuente y hash · extractor con su **configuración efectiva** (`D-19` §2) · **analizador léxico** (`tokenizer` y opciones, insumo separado, `D-10`/PD-13) · outline y jerarquía · reglas de exclusión · **manifiesto de `D-10`** y `chunking_config_version` · **revisión del código** —forma **pendiente de Q-1/Q-2**, que si no se adopta como insumo se registra junto a los resultados (`003`)— · modelo de embeddings cuando se decida · versión de SQLite y de `sqlite-vec`.

**§8 Completitud.** La condición para considerar una versión completa y válida —fragmentos completos con `content_hash` verificado; traza con sus insumos; índice léxico construido y consultable; `index_version` calculada y registrada; escritura atómica sin estado parcial; proceso sin error— se registra como **criterio de aceptación de la implementación**, **no** como norma de publicación, hasta cerrar **CD-02/M-14** (`D-15` §13).

**Registro del descriptor de embeddings.** Cuando existan construcciones vectoriales, el descriptor de `D-11 §4.1` —y, si corresponde, el texto exacto de la plantilla— **deben persistirse** junto a la construcción, porque sin ellos la etiqueta no es recomputable. Esa persistencia exige una versión de esquema posterior (`SCHEMA_VERSION` 3), **pospuesta** hasta el incremento vectorial y **sin migraciones**: un almacén de la versión anterior se rechaza. Hasta entonces no se registra ninguna construcción vectorial, de modo que la etiqueta vectorial es **calculable pero no persistible**, y esta carencia queda declarada, no resuelta.

**§9 Responsabilidades y límites.** **Aplicación:** asigna identidad, extrae, ancla, fragmenta, calcula huellas, verifica `content_hash`, decide persistir y exige atomicidad. **Almacenamiento:** transacción, unicidad, integridad referencial e índices derivados; **no** inventa valores, **no** normaliza contenido, **no** calcula identidades, **no** expone `rowid` ni rutas, **no** decide publicación. **Catálogo:** semántica de `D-13`; el formato físico es detalle de diseño. **Publicación:** `D-15`, fuera de este acto.

**§10 Cobertura de la huella (declaración).** La huella cubre **una construcción publicada de una versión** —cabecera con `document_id` y `document_version` completos, procedencia de construcción **una sola vez** (C-2) y `N`, más los registros en orden `1..N`—. **No** cubre el **catálogo**, ni `rank`/`score`, ni las estructuras FTS5 y `sqlite-vec`, ni su propio valor, ni el bloque de identidad. **Residual C-1:** `level`, `block_type`, `captions` y `anchor_level`. `anchor_evidence` **queda fuera**: caché derivada de auditoría, reconstruible y descartable, cuya ausencia no invalida una generación (`D-20` §3.1). Los campos **no recomputables del catálogo** (fecha, estado de ingesta) **no** entran en C-1: su control pertenece a las garantías del catálogo (`D-13`); si el propietario prefiriera incluirlos, se registraría aquí.

**§11 Criterios de aceptación de la implementación (ocho).** Reingesta idéntica sin duplicados · integridad por fragmento (`content_hash`, `chunk_id`, ordinales) · insumos incompletos ⇒ **rechazo sin escritura parcial** · borrar derivados y reconstruir ⇒ misma `index_version` y mismos resultados · ningún valor inventado · sin `rowid` ni rutas en el contrato público · fallo inyectado ⇒ versión no visible y base utilizable · dos corridas ⇒ conjuntos de fragmentos idénticos.

**§12 Pendientes que esta decisión NO cierra.** **Q-1/Q-2** · **C-1** (enumeración; depende del esquema físico) · **P-1b** · **P-2** · **P-3/CD-05** · **CD-02/M-14** · **M7/CD-01** · retención de versiones (`D-13`) · **D-12** §1/§3/§4/§5 · **VAL-01…07**, **VAL-D06-01…05**, **T-1…T-7**, **M-01…M-18** · la conversión de las citas `L###` a referencias de sección · la reconciliación del resumen **«Estado de Fase 0»** (que no menciona D-21 ni mencionará D-22) · y la **demostración experimental** de que `anchor_evidence` se reconstruye. Ninguna se resuelve aquí.

**Aprobación:** propietario, 2026-10-17 — contrato **lógico** únicamente; **no** aprueba esquema físico, ejecución, publicación ni implementación.

### D-23 — Registro de anomalías de numeración de página (enmienda de `D-20` §3.2) · APROBADA (E-2)

**Contexto.** `D-18` §3.4 exige que, si la última línea de una página es un número **distinto** de `pdf_page − 1`, la línea **se conserve** y **se registre como anomalía**. `D-20` §3.2 enumeraba los recuentos de la traza **sin** incluirla y el esquema físico aprobado **no tenía destino** para ella. **La línea conservada en `content` no satisface el registro:** no la distingue de contenido ordinario ni señala su página.

**Opciones consideradas.** (a) No registrar y re-derivar —rechazada: `D-18` pide **registrar**, y re-derivar exigiría re-ejecutar la extracción—. (b) Registrar solo el recuento. (c) Registrar **recuento y páginas**. (d) Un mecanismo alternativo ya autorizado: **no existe** —no cabe en la caché de anclaje (descartable y de otra naturaleza), **no** es un error de `D-20` §5 (la anomalía **no** detiene la corrida: la línea se conserva) y el informe de comando o el log de `D-06` pt. 10 **no son durables** ni están autorizados para esto—.

**Decisión (c).** La traza de `D-20` §3.2 incorpora **`recuento_anomalias_pagina`** (entero) y **`paginas_anomalas`** (arreglo **JSON canónico** de los números de página **físicos**, ordenados de menor a mayor, sin duplicados). **Semántica de detección:** la última línea de texto no vacía de la página satisface `^\d{1,4}$` y su valor **no** es `pdf_page − 1`; la **línea original se conserva** en el contenido lógico y **nunca** se descarta en silencio. **Consistencia exigida:** `recuento_anomalias_pagina` **es igual** a la longitud de `paginas_anomalas`; una discrepancia es un **fallo**, no un valor tolerado. En el piloto ambos valen **0**.

**Consecuencias.** `D-20` §3.2 queda **enmendada** en su enumeración de recuentos. El **esquema físico** aprobado requiere **dos columnas nuevas** en `construccion` —y por tanto el incremento de `SCHEMA_VERSION`— en un **acto propio**: **no** se aplica aquí y **no** forma parte del esquema aprobado.

**Qué cierra y qué no.** Cierra **documentalmente** el registro que `D-18` §3.4 exige. **No** modifica el esquema físico, **no** incrementa `SCHEMA_VERSION`, **no** implementa nada, **no** altera `D-18` ni el resto de `D-20` y **no** cierra ningún otro pendiente. *(Estado en el momento de la aprobación. La **materialización física**, entonces pendiente, quedó **aplicada**: véase «Materialización».)*

**Materialización (2026-10-17).** Aplicada en el **esquema SQLite versión 2**: `construccion` incorpora **`recuento_anomalias_pagina INTEGER NOT NULL`** con `CHECK (recuento_anomalias_pagina = json_array_length(paginas_anomalas))` y **`paginas_anomalas TEXT NOT NULL`** con `CHECK (json_type(paginas_anomalas) = 'array')`; `SCHEMA_VERSION` pasa de **1** a **2**, **sin migraciones** —un almacén con la versión o la estructura anteriores **se rechaza**—. **Límites que se conservan expresamente:** el **orden ascendente** del arreglo **no** lo impone el esquema —debe garantizarlo el **escritor** y **verificarse en `D-25`**—, y los dos `CHECK` dependen de **JSON1**, cuya disponibilidad en el entorno de despliegue **sigue sujeta a `VAL-03`**. Esta materialización **no** cierra `VAL-03`, `P-2` ni ningún otro pendiente.

**Aprobación:** propietario, 2026-10-17 — decisión **documental**; la materialización física, entonces **pendiente**, quedó **aplicada** en el esquema **versión 2** (2026-10-17).

### D-24 — Mecanismo de verificación de la versión de `sqlite-vec` y código `version_no_coincide` · APROBADA (E-1c)

**Contexto.** `D-11` §4 fija como insumo la **versión fijada** de `sqlite-vec`; `D-02` la fija en **0.1.9** con **pin obligatorio** y trata una actualización como un cambio que exige reindexado y re-evaluación. El **mecanismo concreto de lectura** figuraba como **reserva abierta** en el acta del diseño físico aprobado.

**Tres nociones, no confundir.** **Pin esperado:** `"0.1.9"`, el valor declarado por `D-02` y el que la identidad debe llevar. **Versión instalada:** la del artefacto presente —la distribución `sqlite-vec` informa **0.1.9**; la extensión cargada responde `vec_version()` = `"v0.1.9"`, **cadena distinta**—. **Mecanismo de lectura:** cómo se obtiene y se **verifica** el valor.

**Decisión.** (1) El valor de la identidad es el **pin**. (2) Si la distribución `sqlite-vec` está instalada, se lee su versión por metadatos y se compara **literalmente** con el pin. (3) **Discrepancia ⇒ fallo explícito antes de T1**, sin escritura: `D-11` §4 **no admite sustitutos** y `D-02` exige reindexado y re-evaluación. (4) **Distribución ausente ⇒** se usa el pin y se **declara explícitamente que la versión efectiva no se verificó** —limitación declarada, nunca silenciosa—; el incremento 2 **no** usa `vec0` y **no** depende de instalar la extensión. **No se usa ni se normaliza `vec_version()`:** devuelve `"v0.1.9"` y `D-11` §4 pide cadenas **sin reformatear**.

**Código de error.** Se registra como **decisión de diseño** el código interno **`version_no_coincide`** para `ports/storage.py`, que mantiene este fallo **separado** de `incompatible`, `no_es_base`, `destino_cambiado` y `error_sqlite`. **No se implementa.**

**Estado de implementación (2026-10-17).** El **mecanismo** de lectura y verificación del pin quedó **implementado** en el incremento 2 (`D-25`): el valor de la identidad es el pin, la versión de la distribución instalada se compara **literalmente** con él y su ausencia se **declara** como no verificada. **Limitación provisional declarada:** mientras **`version_no_coincide`** siga sin implementar, la **discrepancia** se informa con **`error_sqlite`** —el código del motor—, de modo que ese camino **no** distingue todavía una discrepancia de versión de un fallo inesperado de SQLite. Es **provisional** y **no** sustituye a `version_no_coincide`, que sigue **pendiente de autorización expresa**.

**Qué cierra y qué no.** Cierra la **reserva del mecanismo de lectura del pin** registrada en el acta del diseño físico. **No** implementa el mecanismo ni el código, **no** cambia `D-02` ni los **seis insumos** de `D-11` §4, **no** declara dependencia nueva, **no** toca `pyproject.toml` y **no** sustituye `VAL-04`.

**Aprobación:** propietario, 2026-10-17 — cierre **documental** de la reserva; implementación **no autorizada**. *(El **mecanismo** de lectura y verificación quedó **implementado** después, en el incremento 2 (`D-25`); el **código** `version_no_coincide` **sigue sin implementar**: véase «Estado de implementación».)*

### D-25 — Contrato de escritura del incremento 2: secuencia de estados y política de reintentos · APROBADA (diseño; no autoriza implementación)

**Contexto.** El contrato lógico (`D-22`) y el esquema físico están aprobados; el incremento 2 persiste la salida de la unidad 1. `D-13` fija tres estados y su `P9` exige que una referencia cuyo procesamiento falla quede en «ingesta incompleta».

**Decisión.**

1. **Secuencia.** **T1** registra o confirma la referencia con estado **«decisión de identidad registrada»**; **T2** marca **«ingesta incompleta»**; **T3** escribe en **una transacción atómica** versión, fragmentos, caché de anclaje, traza y la estructura derivada FTS5, y fija **«ingesta completada»**. Referencia y estado **durables antes de T3**.
2. **Reintentos.** Misma identidad **y mismo** `content_hash` por ordinal ⇒ **completar sin duplicar** (se escribe solo lo que falta); misma identidad **y distinto** `content_hash` ⇒ **fallo explícito**, nunca sobrescritura silenciosa. **No** se comparan construcciones y **no** hay publicación.
3. **Traza.** **Una fila de `construccion` por operación aceptada** (**`D-1`**), sin deduplicar ni comparar.
4. **Fallo en T1.** **No** altera el estado previo de una referencia existente: un reintento fallido de una versión ya completada **no degrada** «completada».
5. **Fallo en T2.** La referencia queda en «decisión de identidad registrada»; el **reintento debe detectar ese estado y volver a intentar T2 antes de T3**.
6. **Fallo en T3.** **No** queda nada de la unidad y el estado permanece en **«incompleta»**; el reintento reescribe el conjunto completo, y la omisión por `content_hash` igual cubre el caso residual en que el `ROLLBACK` fallara.

**Qué cierra y qué no.** Registra **documentalmente** el contrato de escritura decidido. **No** autoriza implementación, **no** modifica el esquema físico, **no** cierra `P-2` ni ningún otro pendiente y **no** introduce publicación de generaciones. *(Estado en el momento de la aprobación. La **implementación**, entonces pendiente, quedó **aplicada**: véase «Materialización».)*

**Materialización (2026-10-17).** Implementado sobre el **esquema versión 2**. Precondiciones, efectos persistentes, atomicidad, idempotencia y comportamiento ante fallos, tal como quedaron:

- **T1 — registro o confirmación de la referencia.** *Precondición:* ninguna. *Efecto persistente:* `INSERT OR IGNORE` en `fuente` y en `referencia_fuente`, con `tipo_asignacion = "deliberada"` y estado **«decisión de identidad registrada»**. *Ante fallo:* no altera una referencia existente, de modo que un reintento fallido **no** degrada «completada». La conexión se abre en **autocommit**, así que sus dos `INSERT` **no** forman una unidad atómica: una interrupción entre ambos deja `fuente` **sin** referencia, y ese estado intermedio es el que detecta la precondición de T3.
- **T2 — «ingesta incompleta» durable.** *Precondición:* la referencia de T1. *Efecto persistente:* el estado queda en **«ingesta incompleta»** antes de T3. *Ante fallo:* si la referencia **no existe**, se rechaza con **`referencia_ausente`** sin escribir nada. *Idempotencia:* repetir T2 sobre una referencia ya en «incompleta» **no** falla —el recuento de filas del `UPDATE` cuenta **coincidencias**, no valores modificados—, de modo que el reintento del punto 5 no se confunde con una ausencia.
- **T3 — escritura atómica y estado completado.** *Precondición:* la referencia de T1, verificada **dentro** de la transacción, para que el hecho se informe igual exista o no la fila de `fuente`. *Efectos persistentes, en **una** transacción `BEGIN IMMEDIATE`:* `version_documento` si falta; los fragmentos y su caché de anclaje ausentes; la estructura derivada **FTS5** de la versión, borrada y reinsertada en la misma transacción; y **una** fila de `construccion`; al final, el estado **«ingesta completada»**. *Atomicidad:* cualquier fallo revierte la transacción completa —con el `ROLLBACK` protegido para conservar la excepción original—, de modo que **no** queda nada de la unidad y el estado permanece en **«incompleta»**. *Idempotencia:* los ordinales ya persistidos con el **mismo** `content_hash` se omiten; con **distinto** `content_hash` la operación se rechaza con **`contenido_divergente`**, sin sobrescritura silenciosa. *Ante fallo:* el reintento reescribe el conjunto completo y la omisión por `content_hash` cubre el caso residual en que el `ROLLBACK` fallara.
- **Contrastes previos a escribir.** Por fragmento, antes de abrir la transacción: el `content_hash` corresponde a `content` y el `chunk_id` es reconstruible; si no, se rechaza con **`contenido_divergente`**.
- **Códigos internos de implementación.** **`referencia_ausente`** —la operación exigía una referencia registrada por T1 y no la encontró: incumplimiento de la precondición de §1— y **`contenido_divergente`** —el contenido bajo una identidad ya registrada difiere, o el `chunk_id` no es reconstruible—. Son **internos** de `ports/storage.py` y **no** se incorporan al **vocabulario público de errores de `001 §6.2`**: califican a la **operación de escritura**, mientras `incompatible` y `no_es_base` califican al **destino** y `error_sqlite` queda reservado a los fallos del motor.
- **Al persistir.** `section_path` y `captions` se normalizan **NFC** y `content` se conserva **sin** normalizar; los arreglos y objetos se serializan en **JSON canónico**; `paginas_anomalas` se persiste en orden ascendente, garantizado por el **escritor** y **no** por el esquema (`D-23`). No se persisten `heading_min_ratio`, las métricas de cola, `temporal_mark`, `word_count` ni `document_version_short`; **no** se calcula `index_version` y los **seis insumos** de `D-11` §4 quedan **intactos**.
- **Verificación observada.** **109** pruebas en verde —atomicidad, idempotencia, recuperación tras fallo en T1, T2 y T3, rechazo de contenido divergente y precondición de referencia ausente—, Ruff y formato limpios y MyPy estricto sin errores; en el piloto: 1 fuente, 1 referencia, 1 versión, 1 traza, **583** fragmentos, **583** entradas de caché de anclaje y **583** filas FTS5.
- **Limitación provisional que se conserva.** La **discrepancia** entre la versión instalada de `sqlite-vec` y el pin `"0.1.9"` de `D-02` se informa hoy con **`error_sqlite`**, porque **`version_no_coincide` sigue sin implementar** (`D-24`): es **provisional** y **declarada**, no el mecanismo definitivo.
- **Límites que esta materialización no cierra.** **No** implementa publicación de generaciones, API de lectura, embeddings, ANN, `vec0` ni cálculo de `index_version`; **no** migra esquemas; **no** afirma exclusión completa entre escritores concurrentes; y **no** cierra `P-1b`, `P-2`, `P-3/CD-05`, `VAL-03` ni ningún otro pendiente.

**Aprobación:** propietario, 2026-10-17 — diseño aprobado; la implementación, entonces **pendiente de autorización expresa**, quedó **aplicada** sobre el esquema **versión 2** (2026-10-17).

### D-26 — Reconciliación de los recuentos y ordinales de `index_version` entre D-11 §4/§4.1, D-15 y D-16 · CERRADA (reconciliación documental; no aprueba Q-2)

**Contexto.** D-15 (2026-10-12) y D-16 (entrada no decisoria) describen `index_version` con **seis insumos**, porque ese era el contrato entonces vigente. **D-11 §4.1** (aprobación del 2026-10-19) añadió el **descriptor de `embeddings`** como séptimo insumo, y la corrección documental de **v0.28** alineó D-11 §4 con §4.1. Quedaron así dos ambigüedades: el recuento que D-15 y D-16 atribuyen a `index_version`, y el ordinal que D-15 usa para la **revisión del código**, que hoy designa otro insumo.

**Qué cierra y qué no.** Cierra **documentalmente** esas dos ambigüedades. **No** aprueba **Q-1/Q-2**, **no** incorpora la revisión del código como insumo, **no** altera el diseño de `index_version` fijado en D-11 §4/§4.1 y en `001 §6.1`, **no** reescribe D-15 ni D-16, **no** toca D-19 §2.1 ni D-20 §3.3 y **no** declara verificado ningún comportamiento.

**1. Contrato vigente.** `index_version` se calcula sobre **siete insumos**, conforme a **D-11 §4**, **D-11 §4.1** y **`001 §6.1`**: los **seis originales** de `001 §6.1`, en su orden —hash del documento; extractor, su versión y su configuración efectiva; `chunking_config_version`; tokenizer del análisis léxico; versión de SQLite; versión fijada de `sqlite-vec`— y el **descriptor de `embeddings`** como **séptimo y último**. En una construcción léxica el séptimo insumo es el arreglo vacío `[]`: es un valor declarado, no un sustituto.

**2. Alcance de las referencias de D-15.** Las menciones de **D-15** a **seis insumos** (§2 y §8.1) describen el **contrato existente cuando D-15 fue aprobada**, no un contrato propio. **No** constituyen una **prohibición independiente** frente a la enmienda posterior de D-11: D-15 §1 declara que no modifica D-11, y D-15 §8.4 prevé, para incorporar el insumo de Q-2, la edición de **D-11 §4** y de **`001` §6.1**. Esa vía quedó ejercida por **D-11 §4.1**, que no requirió tocar D-15.

**3. Colisión de ordinales resuelta sin aprobar Q-2.** El **séptimo insumo vigente** es el **descriptor de `embeddings`** de D-11 §4.1. La **revisión del código** —Q-1/Q-2— **sigue siendo una propuesta pendiente**: no se adopta en este acto, y **si se aprobara** posteriormente exigiría incorporarse como **octavo insumo**, después de `embeddings`. El ordinal «séptimo» que D-15 usa para la revisión del código (§3.3, §8.3, §8.4, §13 M-05/M-17 y su declaración de alcance) se lee como **ordinal histórico de esa propuesta**, no como descripción del contrato vigente. Este acto **no renumera** esos pasajes.

**4. Sustancia de D-15 preservada.** Sigue vigente el diagnóstico de **D-15 §8.1**: un cambio de código que no altere ningún valor declarado puede producir fragmentos distintos con el mismo `index_version`. El descriptor de `embeddings` **no** cubre la revisión del código, de modo que su incorporación en D-11 §4.1 **no** cierra esa brecha; su cierre sigue dependiendo de **Q-1/Q-2**. Por eso la referencia de **D-22** a **D-15 §2.1 y §8.1** conserva su sentido: `index_version` sigue sin distinguir un cambio que sólo afecte al código.

**5. D-16 como registro histórico.** Las menciones de **D-16** a los seis insumos y al séptimo (apertura y §7) son el **registro histórico de una propuesta** `[P]/[I]/[V]` que declaró no modificar D-11 y que nunca fue decisión aprobada. Este acto **no las reescribe**: se conservan como evidencia de lo propuesto y no restringen actos posteriores.

**6. Límites de este acto.** No modifica D-15, D-16, D-19 ni D-20; no reescribe sus menciones a seis insumos; no corrige otras referencias obsoletas del árbol documental; no aprueba Q-2; no autoriza implementación; no altera `001 §6.1`, D-03 ni D-07.

**Aprobación:** propietario, 2026-10-19 — reconciliación **documental**; Q-1/Q-2 permanecen **abiertos**.

## Decisiones diferidas del contrato (D-07) — no decididas

- **PD-02 — `filters`.** Fuera del MVP. El conjunto de filtros permitidos no está definido en ningún documento; se introducirá solo cuando exista una necesidad real.
- **PD-11 (parcial) — Estados adicionales de `get_document`.** Más allá de `indexed` y `not_indexed`, cualquier estado nuevo debe justificarse con transiciones reales del pipeline.

## Decisiones diferidas de embeddings (D-03) — no decididas

- **PE-01 — Proveedor y modelo de embeddings.** Entre `voyage-4` y `text-embedding-3-small`, decidido por medición sobre el conjunto etiquetado; el precio no es el criterio.
- **PE-02 — Dimensión efectiva.** La más pequeña que cumpla la calidad requerida (Matryoshka), medida y no asumida.
- **PE-03 — Embedding en tiempo de consulta.** Es una decisión de arquitectura (latencia y dependencia de un proveedor externo en el camino de lectura), no de facturación; se resuelve con la fase vectorial.

## Pruebas pendientes de embeddings (D-03) — ninguna ejecutada

Ninguna de estas pruebas se ejecutó. Las que requieren contacto con un proveedor o consumo de cuota quedan **diferidas** y no se ejecutan sin autorización explícita.

- **T-1 — Llamada real de embedding por candidato** (confirmar la dimensión devuelta). **DIFERIDA · efecto externo** (llamada a proveedor).
- **T-2 — Confirmar que el pool de 200M tokens gratuitos aplica a la cuenta.** **DIFERIDA · efecto externo** (cuenta/API del proveedor).
- **T-3 — Confirmar el requisito de tier pago en Gemini para uso no-entrenamiento.** **DIFERIDA · verificación de términos** (sin efecto externo).
- **T-4 — Comportamiento de `cosine` en sqlite-vec 0.1.9 con vectores unitarios, en la Orange Pi.** **DIFERIDA · local**, depende de VAL-04.
- **T-5 — Soporte y límites de auxiliary columns en 0.1.9.** **DIFERIDA · local**, depende de VAL-04.
- **T-6 — Cláusula de uso de datos del ToS de Voyage.** **DIFERIDA · verificación de términos** (sin efecto externo; no se confirmó en fuentes primarias).
- **T-7 — Construir las 30–50 preguntas etiquetadas y congelar la línea base BM25.** **PENDIENTE · trabajo local de etiquetado**; prerequisito de cualquier comparación y no requiere proveedores.

## Decisiones diferidas de despliegue (D-06) — no decididas

- **TLS.** Elegir entre `tailscale serve` (HTTPS en 443) y HTTP restringido a la interfaz Tailscale, considerando permisos necesarios en el host, ACL del tailnet, protección del tráfico y complejidad operativa. La exposición pública **no** es una alternativa. Debe quedar documentada antes del despliegue operativo.

## Decisiones abiertas de la interfaz MCP (D-06)

OD-1 (ciclo de vida) y OD-3 (puerto y unidad) quedaron cerradas en **D-08**; OD-5 (token) quedó cerrada **en el plano documental** en **D-09**.

**Sin otras decisiones documentales abiertas en esta sección.** Las decisiones operativas que D-09 deja **explícitamente pendientes** —mecanismo de inyección, momento de carga o relectura del secreto, orden y ventana de rotación, ubicación del archivo y exclusión de copias, mecanismo de entrega al consumidor, comportamiento frente a un token revocado y la confirmación de una rotación sin interrupción— se consultan en la propia **D-09**.

## Requisitos previos a la implementación — pendientes, no implementados

- **RP-01 — Política de arranque sin índice disponible. Cerrada documentalmente en `D-14`**, que fija el comportamiento observable (estado degradado, `health` como superficie de diagnóstico, `index_unavailable` en `search` y `get_document`, sin creación del índice y sin ciclo de reinicio). Su **implementación y verificación permanecen pendientes** y no se declaran hechas.
- **RP-02 — Anclaje del encabezado dentro de la página. Cerrada documentalmente en `D-17`**, que fija el criterio definitivo de anclaje, su calibración documental, el comportamiento ante el fallo —con **exclusión explícita registrada**— y el criterio de verificación. Su **implementación y verificación permanecen pendientes** y no se declaran hechas. Reclasificado desde P-03: es una **técnica de implementación con requisito de verificación**. Se conservan íntegras sus condiciones: (a) el fragmento debe **arrancar en su propio encabezado** (D-05 pto. 2); (b) el método debe localizar el encabezado en las unidades cuyo bookmark tiene destino válido —**178 de 178** según la medición del outline—, cifra que opera como **criterio de verificación**, no como resultado ya obtenido; (c) debe resolver los **12 de 178** encabezados que esa medición **no** localizó por coincidencia textual: evidencia medida del problema y **criterio de verificación pendiente**, no un resultado alcanzado; (d) cuando no pueda localizarse con fiabilidad, el comportamiento debe ser **explícito y documentado**, nunca un corte silencioso al inicio de la página; (e) el resultado debe ser **verificable**: que cada fragmento comience en su encabezado de sección.
  **Evidencia del Experimento 3 — recogida y usada por `D-17` §7.** Sobre la configuración `-layout -enc UTF-8` el Experimento 3 localizó el encabezado en las **166 unidades del corpus** —155 por coincidencia exacta y 11 por coincidencia tolerante, las 11 confirmadas como bloque de encabezado en su página declarada— y encontró **3 referencias del front matter** cuyo encabezado está en la **página siguiente** a la declarada por el outline, es decir un **off-by-one del outline**, no un fallo del matcher. En consecuencia, la cifra «**12 de 178**» de este ítem, medida en **modo plano**, **no se reproduce** con la configuración `-layout -enc UTF-8` usada en el Experimento 3 —cuya codificación explícita **no** está aprobada en D-04 y que aquí se registra sólo como configuración experimental—; **no se declara resuelta** y (c) sigue siendo un criterio de verificación pendiente. Los recuentos del experimento **no** son validación normativa del anclaje. Criterio definitivo y advertencia sobre las métricas históricas: **D-17** (§3, §4, §5 y §6) y **D-16 §1**. **RP-02 queda cerrado documentalmente en `D-17`**; su **implementación y verificación siguen pendientes** y sus condiciones (a)–(e) permanecen íntegras.

## Validaciones pendientes antes de declarar la ingesta validada

- **VAL-01 — extractor real en ARM64.** El desarrollo usó **Xpdf 4.00**; el host ARM64 probablemente use **Poppler** (`poppler-utils`). Xpdf `-layout` y Poppler `-layout` no son necesariamente equivalentes. Antes de validar la ingesta: ejecutar el extractor real en la Orange Pi y comprobar que los fragmentos y sus referencias (página física, capítulos/secciones) coinciden. Registrar nombre y versión del extractor es necesario pero **no suficiente**.
- **VAL-02 — cobertura de tablas.** La comparación analizó una muestra de las 76 páginas con tablas. Jaccard 1,000 demuestra similitud del contenido léxico, **no** equivalencia semántica ni que cada valor quede asociado a su columna correcta. Si la evaluación de recuperación muestra fallos atribuibles a tablas, reevaluar (candidatos: pdfplumber o un extractor de tabla dedicado).
- **VAL-03 — FTS5 en la Orange Pi.** Confirmar que el SQLite del intérprete del host trae FTS5 compilado (Debian/Ubuntu suelen traerlo; no asumirlo).
- **VAL-04 — carga de la extensión `sqlite-vec` en la Orange Pi.** Instalar el wheel `manylinux_2_17_aarch64` y verificar que el build de Python del host permite `enable_load_extension`. Si ese build lo tiene deshabilitado, la opción cambia y hay que revisarla.
- **VAL-05 — semántica de escritura de `vec0` (0.1.9).** Comprobar INSERT/DELETE/UPDATE y las columnas de metadata de la versión fijada, antes de diseñar la sincronización con FTS5.
- **VAL-06 — latencia brute-force medida** al tamaño real del corpus en el CPU del host. No asumirla.
- **VAL-07 — recursos del host.** RAM y disco libres junto a Neo4j, que ya está en ejecución.
- **VAL-D06-01 — Endpoint de referencia · evidencia parcial recopilada; verificación funcional pendiente.**
  - **Observado en el host** —siete consultas de solo lectura, sin conexión al servicio, en la auditoría (2026-10-11); esta revisión no realizó consultas nuevas—: `ss -ltnp` muestra `LISTEN 100.106.85.109:8003` ocupado por el proceso `book-graph-rag-…` (pid 3663899), sin bind comodín; la unit viva `mcp-server` coincide con la copia del repositorio (`WorkingDirectory` del proyecto, `ExecStart` vía `uv run`, `MCP_BIND_HOST=100.106.85.109` declarado en la propia unit, `Restart=on-failure` / `RestartSec=5`); el árbol desplegado (commit `69c2d7e`) contiene `http_transport_dispatch.py`.
  - **Demostrado por inspección de código** (lectura local del repositorio, sin host): el despachador enruta `/mcp` (y `/mcp/…`) a la aplicación Streamable HTTP, `/sse` y `/messages/` a la aplicación SSE, y el resto a 404; todo sobre el mismo servidor FastMCP y el mismo puerto. El despachador fue añadido por `5c9ed12` y existe en el árbol desplegado desde `046954f`; es byte-idéntico entre `69c2d7e` y el HEAD local. El `README` de bookgraph documenta `/mcp`; su runbook (`docs/ops/mcp-service.md` §7) documenta solo `/sse`: la desactualización es del runbook, no del código.
  - **Sin demostrar:** que el proceso en ejecución ejecute ese código —la identidad se **infiere** de `WorkingDirectory` + `ExecStart` + socket, no se probó vía `/proc`—; y que `/mcp` **responda correctamente a una solicitud MCP real**: no se hizo ningún intercambio de protocolo (ni handshake ni herramienta). **No se afirma que el endpoint responda ni que el handshake esté validado.**
  - **Residual exacto:** una solicitud MCP real por `/mcp` (por ejemplo el `initialize` del handshake) y, si se quiere probar la identidad del proceso, la lectura de `/proc/<pid>`. Ambas requieren autorización expresa y permanecen sin ejecutar.
  - **Efecto provisional:** no contradice D-06; lo apoya — existe una implementación Streamable HTTP en el mismo SDK y el mismo host, con verificación de bearer en todos los transportes. La desactualización del runbook pertenece a **otro proyecto** y no se corrige aquí.
- **VAL-D06-02 — SDK y runtime · evidencia parcial recopilada; verificación funcional pendiente.**
  - **Observado:** el `.venv` del host es `python3.13` y contiene la distribución instalada `mcp-1.28.0` (`mcp-1.28.0.dist-info`); el `pyproject.toml` del repositorio declara `requires-python = ">=3.12"` y `"mcp>=1.27,<2"`, con el lock resuelto en `mcp 1.28.0`.
  - **Demostrado por inspección de código:** `mcp` 1.28.0 provee `StreamableHTTPSessionManager`, que el código desplegado utiliza; el transporte está cubierto por tests del repositorio de bookgraph. El SDK con Streamable HTTP está presente y en uso en el árbol desplegado de este host.
  - **Sin demostrar:** el comportamiento en ejecución del handshake con esa versión concreta —mismo residual que VAL-D06-01—. Nota de método: la consulta del lock (Q5) quedó truncada por un filtro de salida propio; la versión efectiva quedó confirmada por la distribución instalada (Q7), no por esa consulta.
  - **Residual exacto:** la misma solicitud MCP real de VAL-D06-01.
- **VAL-D06-03 — Tailscale.** Comprobar las ACL aplicables al puerto elegido y que el consumidor autorizado alcance el servicio sin exposición a otras redes.
- **VAL-D06-04 — TLS.** Verificar disponibilidad de `tailscale serve`, requisitos de permisos y consecuencias operativas antes de decidir entre HTTPS y HTTP restringido a Tailscale.
- **VAL-D06-05 — Configuración del consumidor.** Determinar el mecanismo apropiado para registrar el servidor en Pi y almacenar el token fuera del repositorio, sin introducir configuración global o por proyecto hasta justificar su alcance. **Advertencia observada en este entorno:** una variable de entorno exportada en una shell **no llega** a un Pi lanzado desde el menú, y el síntoma resultante es **401**, no un error de conexión.

## Estado de Fase 0

**Decisiones del alcance documental de Fase 0: cerradas.** D-01, D-02, D-04, D-05 (estrategia estructural), D-06 (dirección arquitectónica), D-07, D-08 (topología y despliegue), D-09 (política de autenticación, cierre documental), D-10 (configuración de indexación léxica, con valores provisionales), D-11 (huellas del proyecto: alcance, algoritmo y serialización canónica), D-12 (estructura física del proyecto, aprobada como dirección documental; con la normalización, `deploy/` y `requires-python` sujetos a aprobación y la licencia pendiente), D-13 (identidad de documento: asignación de `document_id` y catálogo de fuentes; la **retención de versiones anteriores** queda como pregunta abierta del propietario), **D-14** (política de arranque sin índice disponible; cierre **documental**, no implementada ni verificada) **D-15** (publicación, fidelidad y reconstrucción de generaciones; cierre **documental** del marco normativo y del Protocolo B, sin implementación ni verificación, con P-1b, P-2, esquema físico y validaciones pendientes) **D-17** (anclaje del encabezado: criterio definitivo; **cierre documental de RP-02**, sin implementación ni verificación) **D-18** (política de cola y contenido del fragmento; **cierre documental** del pendiente de D-16 §3, sin implementación ni verificación) y **D-19** (configuración efectiva del extractor y su representación en la identidad de construcción; **cierre documental** de los tres residuales de D-16 §4, D-17 §4.6 y D-18 §6.1, sin agregar ni quitar insumos de `index_version`) y **D-20** (contrato mínimo de la unidad 1 en memoria; **cierre documental** de O-3, O-4 y O-5 y de la parte interna de CD-03, **sin autorizar implementación**). **Ninguna de ellas implica implementación ni verificación.**

**Propuesta incorporada y cerrada.** **D-16** (configuración del extractor, anclaje del encabezado y política de cola) quedó **incorporada** al documento con la **aprobación conceptual del propietario sobre su contenido**: **no** cierra RP-02 —su cierre documental es `D-17`—, **no** adopta política de cola, **no** re-mide métricas históricas y **no** modifica ninguna decisión cerrada.

**Decisiones diferidas.** **D-03 (embeddings) permanece parcialmente cerrada**: **PE-01** (proveedor y modelo), **PE-02** (dimensión efectiva) y **PE-03** (embedding en tiempo de consulta) siguen diferidas. Del contrato (D-07) siguen diferidas **PD-02** (`filters`) y **PD-11 (parcial)** (estados adicionales de `get_document`). De despliegue (D-06) sigue diferida **TLS**, con su registro propio en la sección correspondiente. De la estructura física (D-12) quedan **sujetos a aprobación** del propietario la normalización de la especificación, la adopción de `deploy/` y el piso `requires-python = ">=3.13"`, y **pendiente de decisión** la **licencia**. De la identidad de documento (D-13) queda abierta para decisión del propietario la **política de retención de versiones anteriores** («Pregunta abierta declarada 2»).

**Verificaciones y operaciones pendientes.** **VAL-01 … VAL-07** y **VAL-D06-01 … VAL-D06-05**; **RP-02** (cerrado documentalmente en **D-17**; su implementación y verificación siguen pendientes); el **contrato del fragmentador** —cuya representación en el manifiesto quedó fijada en **`D-19`** §3, con el contrato completo aún pendiente—; las **siete decisiones operativas** que D-09 deja explícitamente pendientes; y **T-1 … T-7**, ninguna ejecutada, con las marcadas como diferidas en ese estado.

## Formato para cerrar una decisión

Cada decisión debe registrar: contexto, opciones consideradas, recomendación, motivo, consecuencias y aprobación del propietario. Evitar ADRs extensos para decisiones reversibles y de bajo impacto.
