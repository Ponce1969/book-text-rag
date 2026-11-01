# MCP transport (Fase 3)

Servicio MCP de solo lectura para `search`, `get_document` y `health`, sobre el corpus de la Orange Pi.
Requirement source: `004-decisions.md` D-06 (transporte y acceso) y D-08 (topología y despliegue),
aprobadas por el propietario el 2026-10-10. Límites de `D-07`.

## Specs

**S1 — Transporte.** «**Transporte: Streamable HTTP.** El SSE heredado queda descartado: Pi no lo
admite y la especificación MCP lo marca como deprecado.»

**S2 — Ubicación y red.** «el servidor MCP se ejecuta en la Orange Pi, junto al índice SQLite, conforme
a D-02.» · «el servicio escucha **exclusivamente** en la interfaz Tailscale de la Orange Pi. No se
permite enlazar a `0.0.0.0`, publicar el servicio en Internet ni configurar redirecciones de puerto en
el router.»

**S3 — Autenticación.** «bearer token **independiente** para este servicio. El secreto se almacena
fuera del repositorio y se entrega al consumidor mediante configuración local protegida. **No** se
reutiliza automáticamente el token de otro servicio MCP.»

**S4 — Aislamiento operativo.** «el servicio tiene **nombre de unit y puerto propios**, distintos de
`mcp-server.service` y del puerto `:8003` del servicio de bookgraph. **Nunca** se ejecuta una instancia
manual junto al servicio». · «**Puerto objetivo: `8020`.**» · «**Unidad systemd:
`book-text-rag-mcp.service`.**» · «El **puerto debe comprobarse nuevamente antes del despliegue.**»
(Comprobado el 2026-10-24: libre.)

**S5 — Superficie.** «únicamente las operaciones de lectura de D-07 — `search`, `get_document` y
`health`. La ingesta, la reconstrucción del índice y cualquier operación administrativa quedan fuera de
la interfaz MCP de consulta.»

**S6 — Proceso separado.** «El MCP es un **proceso independiente**, con **unidad systemd propia** y
**entorno `uv` propio**.» · «El proceso MCP abre el índice SQLite en **modo de solo lectura**.» · «La
integración del MCP en una **única aplicación** junto con la API HTTP queda **descartada para el
MVP**.»

**S7 — Límites.** «Consulta máxima 1000 caracteres; `top_k` máximo 50; timeout por defecto 5 s. Todos
configurables; los valores por defecto no son constantes universales.» · «`mode` (por defecto
`lexical`; en el MVP **solo se acepta `lexical`**)».

**S8 — Observabilidad.** «los logs no registran texto crudo de consultas, contenido recuperado,
secretos ni rutas sensibles. Se usan metadatos mínimos y, cuando corresponda, fingerprints protegidos.»

**S9 — Registro en el consumidor.** «se acepta el ámbito **user-level** de
`~/.pi/agent/mcp-adapter.json`». Verificado el 2026-10-24: el archivo existe y ya registra tres
servidores.

**S10 — Arquitectura.** «No permitir que dominio/aplicación importen FastAPI, SDK de MCP, SDK de
embeddings ni bibliotecas concretas de almacenamiento.» El guardián `scripts/check_architecture.py`
debe seguir en verde sin excepciones nuevas.

## Tasks

| ID | Spec | Route | Qué |
| --- | --- | --- | --- |
| T1 | S1 S5 S10 | inline | Adaptador MCP: servidor Streamable HTTP con las tres herramientas sobre los casos de uso existentes. |
| T2 | S2 S3 | inline | Bind fail-closed a la IP de Tailscale y bearer token obligatorio, secreto fuera del repo. |
| T3 | S7 | inline | Límites de `D-07` aplicados en el borde: query ≤1000, `top_k` ≤50, `mode` solo `lexical`, timeout 5 s. |
| T4 | S5 S8 | inline | Solo lectura: SQLite abierto `mode=ro`, sin ingesta, logs sin texto crudo. |
| T5 | S7 S10 | inline | Pruebas de contrato: las tres herramientas, cada límite rechazado, y el guardián de arquitectura. |
| T6 | S4 S6 | inline | Unidad `book-text-rag-mcp.service` y despliegue documentado. |
| T7 | S9 | inline | Registro en el consumidor y verificación end-to-end desde Windows. |

## Log

**L1.** «bueno seguimos? dime que paso a paso debo dar en el servidor para hacer lo que sigue»

**L2.** Reconocimiento del host (2026-10-24): Tailscale `100.106.85.109`; puerto `8020` libre; existe
`mcp-server.service` (bookgraph) escuchando en `100.106.85.109:8003`, que no se toca; almacén
`/home/gonzalo/datos/book-text-rag/corpus.sqlite` (13.5 MB, `gonzalo:gonzalo`, 644); `uv 0.7.8` en
`/home/gonzalo/.local/bin/uv`.

**L3 — Validación end-to-end (pasos 1 y 2, más comprobaciones 1, 3 y 4).** Evidencia recogida desde
Windows contra `http://100.106.85.109:8020/mcp`.

Registro en el consumidor: se agregó **una** clave (`book-text-rag`) a `~/.pi/agent/mcp-adapter.json`,
con respaldo `mcp-adapter.json.bak-2026-10-25`. Las **seis entradas anteriores quedaron idénticas**,
verificado por igualdad profunda de las estructuras y no por inspección visual. El token vive en la
variable de usuario de Windows `BOOK_TEXT_RAG_MCP_TOKEN` (64 caracteres): no está en el JSON, ni en
scripts, ni en registros.

Protocolo: `initialize` HTTP 200 con `Mcp-Session-Id`, `notifications/initialized` HTTP 202,
`tools/list` HTTP 200 con **exactamente** `search`, `get_document` y `health`. `health` devuelve
`status: ok`, `dependencies: []`, `available_modes: ["lexical"]`. `get_document` de
`graphrag-agentico` devuelve los **siete** campos de `D-07` con `page_count: 692` e
`index_version: 6902c6191388`.

Comparación MCP vs CLI con `search "vector database"`, idénticos **y en el mismo orden**:
`graphrag-agentico:0f31856f5415:13`, `huyen-ai-engineering:0cd2fc8424e5:324`,
`agentic-architectural-patterns:425c95335234:466`.

Solo lectura sobre el almacén real: SHA-256 `92e68755f97822d332ee33212c8a9494d4c21ad366cf689dd985022635c849f8`
y `mtime` `2026-10-25 01:33:54.621` idénticos antes y después de las tres llamadas; el directorio
contiene solo `corpus.sqlite`, sin `-wal` ni `-shm` nuevos.

Red: `http://192.168.1.100:8020/mcp` (IP de LAN de la propia Pi) rechaza la conexión; la dirección
Tailscale responde `401` sin credenciales. El enlace no es amplio.

Registros: 31 líneas en total, **0** apariciones del token, **0** de la consulta, **0** de la ruta del
almacén y **0** de `Bearer`. Lo único que se registra es metadato: `herramienta=search resultado=ok
duracion_ms=8`.

Corrección de expectativa, no defecto: `get_document` no expone un conteo de fragmentos porque
`DocumentView` tiene los siete campos de `D-07` y la decisión dice «sin fragmentos ni rutas».

Pendiente para cerrar T7: el **reinicio controlado** (requiere `sudo` con contraseña, que no está
disponible de forma no interactiva) y el **consumidor Pi en sesión nueva**.

**L4 — Causa raíz del 401 en el cliente de Pi, y cierre del consumidor.** Diagnóstico de solo lectura,
sin tocar configuración, servicio, caché ni token.

Síntoma: Pi descubría `book-text-rag` pero la conexión fallaba con `{"error":"unauthorized"}`,
`mcp-cache.json` quedaba con `discoveryFailed: true`, y el journal registraba tres `POST /mcp` → 401 a
las 22:52 sin intentos posteriores.

Causa raíz demostrada — **la variable nunca estuvo en el proceso de Pi**:
- `herdr.exe` PID 15776 arrancó 21:52:22; el pane `pwsh.exe` 22152 a las 21:52:23; el proceso de Pi
  `node.exe` 5540 a las **21:52:24**. La variable de usuario se creó mucho después (después de las
  22:35). Windows entrega el entorno al crear el proceso, así que nada nacido a las 21:52 podía verla.
- Las tres instancias de Pi vivas arrancaron **todas a las 21:52:24**, cada una bajo un `pwsh.exe`
  distinto: son panes del mismo Herdr. Cerrar y reabrir Pi dentro de Herdr reutiliza esos intérpretes
  de larga vida, así que el entorno nuevo no entraba nunca en la cadena.
- Punto exacto de la pérdida: `pi-mcp-adapter` expande los `headers` **en cada intento de conexión**
  con `process.env` del proceso de Pi (`server-manager.ts:1703` → `utils.ts:138`); si la variable falta,
  `utils.ts:142` produce cadena vacía y el encabezado sale como `Bearer ` sin valor. La `url` falla
  cerrado (`utils.ts:270`), los `headers` no: de ahí el 401 silencioso en lugar de un error legible.
- Silencio posterior: `init.ts:388` aparta del arranque las entradas con `discoveryFailed` cuyo
  `configHash` coincide, y como `computeServerHash` (`metadata-cache.ts:147-157`) hashea los encabezados
  **ya expandidos**, un proceso con el entorno vacío reproduce el mismo hash. No hubo un cuarto
  intento, no un cuarto fallo.

Resolución (2026-10-31, por el propietario): reinicio de **Herdr**. Cadena nueva: `pwsh.exe` 22472 y Pi
`node.exe` 12800, ambos de 23:17:09; la variable está **presente con 64 caracteres** en el entorno de
Pi. Sin cambios en el repositorio, en el servicio, en el caché ni en el token.

Cierre del consumidor, ejercido **con el cliente propio de Pi**, no con un cliente externo:
- `tools/list`: `search`, `get_document`, `health`, con instrucciones del servidor.
- `health` → `status: ok`, `dependencies: []`, `available_modes: ["lexical"]`, 11 ms.
- `search "vector database" top_k=3` → los tres `chunk_id` de referencia, **en orden**, con contenido
  real y `section_path` completo: `graphrag-agentico:0f31856f5415:13`,
  `huyen-ai-engineering:0cd2fc8424e5:324`, `agentic-architectural-patterns:425c95335234:466`.
- `get_document graphrag-agentico` → siete campos, `page_count: 692`, `index_version: 6902c6191388`,
  `status: indexed`.
- Journal: `herramienta=health|search|get_document resultado=ok` (11, 24 y 24 ms). Los 401 totales
  siguen en 5 y **ninguno es posterior** al reinicio: no hay credencial rechazada desde entonces.
- `mcp-cache.json`: `discoveryFailed` ya **no** está presente para `book-text-rag`.

Queda pendiente, fuera del alcance del agente: el **reinicio controlado** del servicio en la Pi, que
requiere `sudo` con contraseña.
