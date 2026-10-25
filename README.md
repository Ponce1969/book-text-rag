# book-text-rag

Lexical book retrieval with verifiable provenance: ingest technical PDFs, catalog them, search
with BM25, and inspect every hit down to its page with full provenance. No silent fallbacks —
a failed anchor, an unreadable source, or a missing version fails explicitly.

Part of a three-project agent knowledge stack: **book-text-rag** (this repo, verbatim evidence
from books) feeds **agentic-book-graph** (Neo4j knowledge graph of patterns and relations) and
**agentic-memory** (SQLite answer cache with citations), so agents never pay twice for the same
question.

## Status

Working MVP, validated end to end on three real books (583 + 290 + 730 fragments):
ingest → catalog → search → inspect → verify, all from the CLI.

- Ingestion derives each book's corpus boundaries from its own outline (no hardcoded pages),
  anchors headings with geometric and textual evidence, and strips running headers and back matter.
- Search is lexical BM25 with provenance on every hit (`document_id`, `chunk_id`, short version,
  pages, section path).
- Provenance, integrity (`verify`), and health checks are read-only: they report, never repair.
- Roadmap: vector/hybrid search (`002`, `D-03`), HTTP/MCP transports, multi-version status
  (`CD-02/M-14`).

## Requirements

- Python **3.13** and [`uv`](https://docs.astral.sh/uv/) for the environment and dependencies.
- **`pdftotext` (Xpdf 4.00)** on the `PATH`: the effective extractor recorded in the trace
  (`-layout -enc UTF-8`, strict UTF-8 decoding).
- `PyMuPDF` (installed with the project) for outline and typography.

```bash
uv sync
```

> On Ubuntu ARM64 (e.g. Orange Pi 5 Plus) the same steps apply: install `uv`, install the
> `poppler-utils` package for `pdftotext`, then `uv sync`. No Windows-only dependency exists.

## Quickstart

```bash
# 1. Create the store (schema v2; never migrates nor overwrites)
uv run book-text-rag init --store ./store.sqlite

# 2. Ingest a book (T1 -> T2 -> T3, transactional)
uv run book-text-rag ingest "data/Ingeniería de IA - Chip Huyen (EN).pdf" \
    --document-id huyen-ai-engineering --alias huyen --fecha 2026-10-23 \
    --store ./store.sqlite --source-format pdf

# 3. See what the store holds
uv run book-text-rag documents --store ./store.sqlite

# 4. Search (compact provenance with --brief, full content without it)
uv run book-text-rag search "evaluation pipeline" --store ./store.sqlite --top-k 5 --brief

# 5. Read one fragment with its full provenance
uv run book-text-rag show --store ./store.sqlite \
    --document-id huyen-ai-engineering --document-version <prefix-or-version> \
    --orden 245

# 6. Audit the version and check store health
uv run book-text-rag verify --store ./store.sqlite \
    --document-id huyen-ai-engineering --document-version <version>
uv run book-text-rag health --store ./store.sqlite
```

All commands are **read-only** except `init`, `ingest`, and `rebuild`. None repairs or creates
the store on its own, and none requires write permission to query.

## Commands

| Command | What it does |
|---|---|
| `init` | Creates the v2 schema or verifies compatibility. Never migrates. |
| `ingest` | Extracts, anchors, chunks, and persists the book (T1 → T2 → T3). |
| `documents` | Catalog: documents, aliases, ingest states, metadata, and versions. |
| `document` | Public document card (`D-07`): resolved version, metadata, `index_version`, status. No fragments or content. |
| `search` | Lexical BM25 query; `--brief` gives one provenance line per hit. |
| `show` | Version card; `--fragments`, `--limit`, `--all`, and `--orden N`. Accepts a unique version prefix. |
| `verify` | Version invariant audit. Reports, never repairs. |
| `rebuild` | Rebuilds the derived lexical index from the authority. |
| `health` | Store availability (`ok` / `degraded`) per `D-14`. |

Exit codes: `0` success (includes empty search and reported degraded store),
`1` audit run with unverified version, `2` operational or usage error.

## Quality gates

Four checks, configured in `pyproject.toml`:

```bash
uv run python scripts/check_architecture.py   # hexagonal layer direction
uv run ruff check .                           # lint
uv run ruff format --check .                  # format
uv run mypy                                   # strict typing (files = ["src"])
```

`scripts/check_architecture.py` enforces the hexagonal direction: `domain` imports nothing from
the project; `ports` imports `domain`; `adapters` and `application` import `domain` and `ports`;
`cli` is the composition root and may import all four. It fails with `file:line` and the rule.

### Pre-commit hook

The hook lives versioned in `.githooks/pre-commit` and runs all four checks; a failing check
aborts the commit. Enable once per clone:

```bash
# Linux / macOS / Git Bash on Windows
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit
```

```powershell
# PowerShell on Windows
git config core.hooksPath .githooks
```

The interpreter resolves from the environment: `BTRAG_PYTHON` if set, then `.venv/Scripts/python.exe`
(Windows), `.venv/bin/python` (POSIX), finally `python`. To skip once:
`git commit --no-verify`.

## Layout

```
src/book_text_rag/
  domain/        pure rules: identity, anchoring, chunking, availability
  ports/         extraction and storage contracts
  adapters/      pdftotext, PyMuPDF, SQLite (schema, T1/T2/T3 writes, reads)
  application/   use cases: ingest, search, health, index_version, get_document
  cli.py         administrative surface
tests/           unit, contract, integration
```

## Ecosystem

```
                            ┌────────────────────────┐
                            │  Agent (pi-dev, CLI)   │
                            └───────────┬────────────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
        ┌─────────────────────┐               ┌─────────────────────┐
        │   book-text-rag     │               │ agentic-book-graph  │
        │   (this repo)       │               │ (Neo4j graph)       │
        │ verbatim evidence   │               │ patterns, relations │
        └─────────┬───────────┘               └─────────┬───────────┘
                  │         both feed                   │
                  └──────────────┬──────────────────────┘
                                 ▼
                    ┌─────────────────────┐
                    │   agentic-memory    │
                    │ (SQLite cache)      │
                    │ verified answers   │
                    └─────────────────────┘
```

- **book-text-rag** answers "what does the book actually say, and where?" — fragments with
  page-level provenance.
- **agentic-book-graph** answers "how do the ideas connect?" — entities and relations in Neo4j.
- **agentic-memory** answers "did we already solve this?" — a deterministic SQLite cache so
  agents never pay twice for the same question.

## Known limits and roadmap

- **Lexical search only.** Vector and hybrid stay out of the MVP (`002`, `D-03`).
- **`title` always `null`** in `get_document`: no approved source and no column to persist it.
- **`document` exposes `get_document`** via CLI (no transport yet). Without `--document-version` it
  resolves the single version; with **two or more versions** and no version it requires
  `document_version`, and with an explicit version it builds no card: per-version `status` needs
  `CD-02/M-14`.
- **`index_version` is recomputed**, not persisted; emitted only when the answer maps to a single
  document and version with a single build.
- **An invalid source fails instead of degrading**: strict UTF-8 decoding by decision (`D-19` §1.2),
  so a PDF whose text carries CESU-8 surrogate pairs is rejected with `decode_error` instead of
  being ingested with altered characters.
- Books under `data/` are **not** versioned (size and rights); see `data/README.md`.

## Reproducibility across platforms

The corpus payload is the text a PDF carries, not the platform that extracts it, so ingestion
normalizes the three artifacts an extractor leaves in the output:

| Artifact | Why it differs across platforms | Normalization |
| --- | --- | --- |
| Line endings | Windows writes `CRLF` | `CRLF` and `CR` become `LF` |
| `U+200B`, `U+2060` | Xpdf places zero-width marks by platform | both are dropped |
| `idx_<8 hex>` | hidden text layer named per glyph | dropped, even chained or glued to a word |

The first two live in `_normalizar_fin_de_linea` and `_descartar_formato_invisible`; the third in
`_descartar_identificadores_ocultos`, all at the extraction port (`adapters/extraction/pdftotext.py`).

**Verified corpus** (three books, 1,602 fragments), identical between Windows/MSYS2 and
Ubuntu/aarch64, both running Xpdf 4.00:

| Book | Fragments | `content_hash` digest |
| --- | ---: | --- |
| Lexical pilot | 583 | `a20fbea8` |
| Agentic GraphRAG | 290 | `accfdd23` |
| Agentic Architectural Patterns | 729 | `3106762f` |

**One documented residual**: fragment 169 of the pilot book carries a mathematical formula whose
glyphs `∏` and an italic `n` are recovered by the MSYS2 build and not by the self-compiled ARM64
build of the same Xpdf 4.00. Ordinal, page, `chunk_id` and the rest of the text match, so a citation
still resolves to the same place on both machines. Accepted on 2026-10-24 rather than chased through
compiler differences.

`index_version` is **not** meant to be comparable across machines: `D-11` §4 makes it a hash of seven
inputs, and one of them is the SQLite library version. Same corpus, same `document_version`, two
stores: Windows with SQLite 3.50.4 gives `814639169f9e` and Ubuntu/aarch64 with SQLite 3.47.1 gives
`6902c6191388` for the same GraphRAG construction. The identifiers that *are* comparable are
`chunk_id` and `content_hash`, which is what a cached citation needs.

On Linux, `pdftotext` must be **Xpdf 4.00**, not poppler: poppler fragments the same PDFs
differently (292 fragments and 32 table blocks instead of 290 and 31 for GraphRAG) and breaks
`chunk_id` comparability.
