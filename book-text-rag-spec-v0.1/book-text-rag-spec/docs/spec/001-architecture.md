# 001 — Especificación de arquitectura

Estado: propuesta v0.1. Alcance inicial: definición de arquitectura, sin autorizar por sí sola despliegue en producción.

## 1. Objetivo

Crear `book-text-rag`, un servicio independiente que permita a agentes y herramientas recuperar pasajes relevantes de libros técnicos con procedencia verificable. La respuesta principal es **evidencia textual recuperada**, no una respuesta generada que sustituya la fuente.

Debe permitir encontrar:
- términos exactos: nombres de funciones, identificadores, acrónimos y conceptos;
- explicaciones conceptuales expresadas con vocabulario diferente;
- fragmentos cuya interpretación depende de su capítulo o sección.

## 2. No objetivos

Fuera del MVP:
- sustituir o modificar `book-graph-rag`;
- extraer entidades/relaciones, construir comunidades o mantener un grafo;
- generar respuestas finales mediante un LLM dentro del servicio;
- ejecutar modelos locales de embeddings o generación en Orange Pi;
- contextual retrieval generado por LLM, reranking, query rewriting o agentes autónomos;
- caché semántica/memoria compartida (`agent-memory`);
- sincronización distribuida, escalado horizontal o multi-tenancy avanzada;
- procesamiento especializado de toda clase de tablas, fórmulas o código;
- remediación automática o escritura libre por parte de consumidores MCP.

## 3. Principios

1. **Evidence first:** devolver texto, fuente, ubicación y puntuaciones disponibles.
2. **Reproducibilidad:** la misma fuente y configuración de ingesta deben producir resultados equivalentes.
3. **Procedencia:** no separar un fragmento de la versión documental y el proceso que lo generó.
4. **Medición antes de complejidad:** BM25 es línea base; vectorial e híbrida se comparan empíricamente.
5. **Una lógica, tres interfaces:** CLI, HTTP y MCP llaman los mismos casos de uso.
6. **Separación de responsabilidades:** este servicio recupera texto; el grafo recupera relaciones; una memoria futura reutilizará resultados validados.
7. **Privilegios mínimos:** consultas de lectura separadas de las operaciones administrativas.
8. **Evolución vertical primero:** no introducir distribución hasta que métricas reales lo requieran.

## 4. Arquitectura lógica

Capas recomendadas:

- `domain`: entidades y reglas independientes de frameworks y almacenamiento.
- `application`: casos de uso y contratos de entrada/salida.
- `ports`: interfaces para catálogo documental, extracción, fragmentación, recuperación, embeddings y reloj/configuración cuando sea necesario.
- `adapters`: persistencia/índices, extracción documental, proveedor de embeddings, API HTTP, MCP y CLI.
- `evaluation`: datasets, métricas y herramientas de evaluación, fuera del camino de consulta de producción.

Dirección de dependencias: adaptadores → aplicación → dominio. Los puertos pertenecen al núcleo de la aplicación/dominio según su responsabilidad. No permitir que dominio/aplicación importen FastAPI, SDK de MCP, SDK de embeddings ni bibliotecas concretas de almacenamiento.

No crear un microservicio por componente. Un despliegue inicial puede ser un solo servicio con una única persistencia elegida tras la decisión técnica.

## 5. Casos de uso y contratos conceptuales

### `search`
Entrada:
- `query`: texto no vacío.
- `top_k`: número positivo, con límite máximo configurable (por defecto 10, máximo 50).
- `mode`: por defecto `lexical`. En el MVP solo se acepta `lexical`; `vector` y `hybrid` devuelven el error `mode_not_available`. Los modos disponibles se publican en `health`.
- `document_ids`: lista opcional para limitar el corpus.
- `filters`: fuera del MVP. El conjunto de filtros permitidos no está definido y solo se introducirá cuando exista una necesidad real.

Salida (todos los campos están siempre presentes; un valor genuinamente desconocido es `null`, nunca se omite ni se inventa):
- `query` (eco de la consulta efectiva) y `mode` efectivo;
- `index_version`;
- lista ordenada de resultados, cada uno con `rank`, `score`, `document_id`, `document_version`, `chunk_id`, `content`, `section_path`, `pdf_page_start` y `pdf_page_end`.

Semántica de `score`: depende del recuperador y **no es comparable entre consultas distintas**; se interpreta junto con `index_version` y la configuración registrada. En la fase vectorial se agregarán campos nuevos (nunca renombres de los existentes). El orden de la lista lo fija `rank`, no la magnitud de `score`.

No incluir una respuesta inventada por un LLM. No prometer que cada fragmento es una respuesta completa.

### `get_document`
Entrada: `document_id` y versión opcional.

Salida: `document_id`, `document_version`, `title`, `source_format`, `page_count`, `index_version` y `status` ∈ {`indexed`, `not_indexed`}. No devolver el libro completo por defecto.

### `health`
Salida: `status`, `dependencies` y `capabilities.available_modes`. `status` ∈ {`ok`, `degraded`}; `dependencies` enumera los nombres de las dependencias **no satisfechas** —vacía cuando todas lo están—; con el índice no disponible, `status` es `degraded`, `dependencies` incluye `index`, `capabilities.available_modes` es `[]` y `search`/`get_document` responden `index_unavailable`, conforme a **D-14**. Un índice válido **sin documentos** no es un estado degradado. No incluir secretos, rutas privadas ni configuración sensible.

### Operaciones administrativas CLI
Como mínimo se prevén comandos para listar documentos/estado, ingestar o reindexar una fuente, auditar el índice y ejecutar evaluación. Los nombres finales se deciden en el diseño de implementación, manteniendo operaciones explícitas y no destructivas por defecto.

## 6. Procedencia del documento y del fragmento

Cada documento tiene identidad estable (`document_id`, un identificador público asignado en la ingesta) y versión de contenido (`document_version`, derivada del hash del contenido de la fuente).

Cada fragmento conserva como mínimo:
- procedencia pública: `document_id`, `document_version`, `chunk_id`, `section_path` (capítulo → sección → subsección) y `pdf_page_start`/`pdf_page_end`;
- contenido: `content`;
- procedencia interna, no expuesta en el contrato: `content_hash`, identidad y versión del pipeline de extracción, `chunking_config_version`, análisis léxico (tokenizer y sus opciones), versiones del motor, el **nivel jerárquico**, el **tipo de bloque** y los **captions** asociados (`level`, `block_type`, `captions`) y el **registro de anclaje** de la unidad a la que pertenece el fragmento —nivel de evidencia, página y coordenadas del bloque de encabezado y del destino del outline—, conforme a **D-17** §6.1 y **D-20** §3.1;
- para vectorización, cuando exista: proveedor, modelo/versión y dimensiones.

`pdf_page_start`/`pdf_page_end` son la **página física del PDF**. El número de página impreso es un dato secundario y no debe presentarse como página de la edición editorial. No inventar páginas: si la extracción no puede preservar una ubicación, el valor es `null` y se marca como desconocida.

### 6.1 Identificadores públicos

- `document_id`: slug estable asignado en la ingesta y persistido en el **catálogo de fuentes**, que registra explícitamente las decisiones de identidad, sus referencias de fuente con su estado de ingesta, y los datos descriptivos de las reingestas conforme a **D-13**; estable entre versiones del mismo documento lógico e independiente del contenido, del nombre reutilizado y de la ruta de la fuente. Nunca una ruta de archivo ni un identificador de almacenamiento.
- `document_version`: **SHA-256** de los **bytes originales del archivo fuente**, hexadecimal en minúsculas, **64 caracteres**, sin normalización y sin incluir el nombre ni la ruta.
- `chunk_id`: `{document_id}:{document_version_short}:{ordinal}`, con `ordinal` 1-based en orden de lectura y `document_version_short` = los **primeros 12 caracteres** de `document_version`. Determinista y reconstruible; no depende del almacenamiento. La sección no se codifica dentro del id porque `section_path` ya la expone: evitar dos fuentes de verdad.
- `index_version`: huella **SHA-256** sobre (hash del documento, extractor, su versión y su configuración efectiva, `chunking_config_version`, tokenizer del análisis léxico, versión de SQLite, versión fijada de `sqlite-vec` **y el descriptor de embeddings**), hexadecimal en minúsculas, truncada a 12 hex. La serialización canónica de esos **siete** insumos se especifica en **D-11**, y la forma del séptimo en **`D-11 §4.1`**. Una construcción **léxica** —sin componentes de embeddings— declara el séptimo insumo como el array vacío `[]`: es un valor declarado, no un sustituto, y significa que la construcción no tiene componentes de embeddings.

`document_version` e `index_version` son independientes: `document_version` cambia cuando cambia la fuente, mientras que `index_version` cambia cuando cambia cualquier insumo de construcción del índice (extractor, fragmentación, tokenizer o versiones del motor) aunque la fuente sea la misma.

Los identificadores de almacenamiento (`rowid` de SQLite, de FTS5 o de `vec0`) y las rutas de archivo nunca forman parte del contrato público.

### 6.2 Errores

Forma única y estable: `{ "error": { "code", "message", "details" } }`, con `code` en {`invalid_request`, `document_not_found`, `mode_not_available`, `index_unavailable`}. `message` es legible y sin detalles internos; `details` nunca incluye rutas del sistema ni secretos. `invalid_request` puede llevar `details.field` para señalar el campo inválido, y `mode_not_available` lleva `details.mode` y `details.available_modes`.

## 7. Interfaces

### CLI
Para operaciones de mantenimiento: ingesta, reindexación explícita, auditoría, estado y evaluación. Debe funcionar sin levantar HTTP ni MCP.

### API HTTP
FastAPI, con esquemas Pydantic versionados. Endpoints iniciales conceptuales: `GET /health`, `GET /v1/documents/{document_id}`, `POST /v1/search`. Los contratos definitivos deben ser compartidos conceptualmente con MCP, sin acoplarlos a transportes.

### MCP
Exponer herramientas de consulta de solo lectura, inicialmente `search`, `get_document` y `health`. Las herramientas administrativas no se publican a todos los agentes por defecto. Mantener compatibilidad con el patrón de conexión que se adopte en el servidor; no asumir que el transporte está públicamente expuesto.

## 8. Seguridad y operación

- Configuración mediante variables de entorno tipadas; secretos fuera de repositorio y fuera de logs.
- Por defecto, servicio no expuesto directamente a Internet. Acceso por la red privada/túnel autorizado según la infraestructura existente.
- Separar permisos de consulta de los de ingesta/reindexación.
- Timeouts, límites de `top_k` (por defecto 10, máximo 50), tamaño máximo de consulta (1000 caracteres) y errores seguros según §6.2.
- Health check útil para el orquestador.
- Backups y restauración se especifican antes de producción; no son requisito para el primer prototipo local.
- Registrar latencia, modo de búsqueda, número de resultados, errores y versión del índice. No registrar contenido completo de consultas/documentos por defecto.

## 9. Calidad

- Pruebas unitarias de dominio y casos de uso con puertos falsos.
- Pruebas de contrato para CLI, HTTP y MCP.
- Pruebas de integración para almacenamiento/índice seleccionado.
- Dataset de evaluación separado del corpus operativo.
- Ruff, MyPy estricto, pytest y verificación de límites arquitectónicos.
