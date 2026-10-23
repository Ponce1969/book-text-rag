# book-text-rag

Recuperación de evidencia textual con procedencia verificable sobre libros técnicos en PDF.
Prototipo de la Fase 1 de `docs/spec/002-mvp.md`: ingesta reproducible, persistencia SQLite,
búsqueda léxica BM25 y una CLI administrativa.

## Requisitos

- Python **3.13** y [`uv`](https://docs.astral.sh/uv/) para el entorno y las dependencias.
- **`pdftotext` (Xpdf 4.00)** en el `PATH`: es el extractor efectivo registrado en la traza
  (`-layout -enc UTF-8`, decodificación UTF-8 estricta).
- `PyMuPDF` (se instala con el proyecto) para outline y tipografía.

```bash
uv sync
```

## Flujo de uso

```bash
# 1. Crear el almacén (esquema v2; nunca migra ni sobrescribe)
uv run book-text-rag init --store ./store.sqlite

# 2. Ingerir un libro (T1 -> T2 -> T3, transaccional)
uv run book-text-rag ingest "data/Ingeniería de IA - Chip Huyen (EN).pdf" \
    --document-id huyen-ai-engineering --alias huyen --fecha 2026-10-23 \
    --store ./store.sqlite --source-format pdf

# 3. Ver qué contiene el almacén
uv run book-text-rag documents --store ./store.sqlite

# 4. Buscar (procedencia compacta con --brief, o contenido completo sin él)
uv run book-text-rag search "evaluation pipeline" --store ./store.sqlite --top-k 5 --brief

# 5. Leer un fragmento concreto con su procedencia completa
uv run book-text-rag show --store ./store.sqlite \
    --document-id huyen-ai-engineering --document-version <prefijo-o-versión> \
    --orden 245

# 6. Auditar la versión y consultar la salud del almacén
uv run book-text-rag verify --store ./store.sqlite \
    --document-id huyen-ai-engineering --document-version <versión>
uv run book-text-rag health --store ./store.sqlite
```

Todos los comandos son de **solo lectura** salvo `init`, `ingest` y `rebuild`. Ninguno repara ni
crea el almacén por su cuenta, y ninguno requiere permisos de escritura para consultar.

## Comandos

| Comando | Qué hace |
|---|---|
| `init` | Crea el esquema v2 o verifica que ya sea compatible. Nunca migra. |
| `ingest` | Extrae, ancla, fragmenta y persiste el libro (T1 → T2 → T3). |
| `documents` | Catálogo: documentos, alias, estados de ingesta, metadatos y versiones. |
| `search` | Consulta léxica BM25; `--brief` da una línea de procedencia por resultado. |
| `show` | Ficha de la versión; `--fragments`, `--limit`, `--all` y `--orden N`. Acepta prefijo único de versión. |
| `verify` | Auditoría de invariantes de la versión. Informa, nunca repara. |
| `rebuild` | Reconstruye el índice léxico derivado desde la autoridad. |
| `health` | Disponibilidad del almacén (`ok` / `degraded`) según `D-14`. |

Códigos de salida: `0` correcto (incluye búsqueda sin resultados y almacén degradado informado),
`1` auditoría ejecutada con la versión no verificada, `2` error operativo o de uso.

## Estructura

```
src/book_text_rag/
  domain/        reglas puras: identidad, anclaje, fragmentación, disponibilidad
  ports/         contratos de extracción y de almacén
  adapters/      pdftotext, PyMuPDF y SQLite (esquema, escritura T1/T2/T3, lectura)
  application/   casos de uso: ingesta, búsqueda, salud, index_version, get_document
  cli.py         superficie administrativa
tests/           unidad, contrato e integración
```

## Estado y límites conocidos

- **Búsqueda sólo léxica.** Vectorial e híbrida quedan fuera del MVP (`002`, `D-03`).
- **`title` siempre `null`** en `get_document`: no hay origen aprobado ni columna donde persistirlo.
- **`get_document` no está expuesto** por ninguna superficie (no hay transporte ni verbo de CLI).
  Con **dos o más versiones** de un documento su `status` no es derivable y queda bloqueado por
  `CD-02/M-14`.
- **`index_version` se recalcula**, no se persiste; se emite sólo cuando la respuesta corresponde a
  un único documento y versión con una sola construcción.
- **Una fuente con bytes inválidos falla en vez de degradarse**: la decodificación es UTF-8 estricta
  por decisión (`D-19 §1.2`), así que un PDF cuyo texto traiga pares sustitutos en CESU-8 se rechaza
  con `decode_error` en lugar de ingerirse con caracteres alterados.
- Los libros de `data/` **no** se versionan (tamaño y derechos); ver `data/README.md`.
