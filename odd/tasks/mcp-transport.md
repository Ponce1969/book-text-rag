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
