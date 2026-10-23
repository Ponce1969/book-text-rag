"""CLI administrativa para inicializar, ingerir, reconstruir, verificar, consultar y auditar la salud.

Referencias: `001` §5 y §7; D-07, D-08, D-12, D-13, D-14, D-15, D-22 §5 y D-25.
La CLI funciona sin HTTP ni MCP. La ingesta persistente ejecuta T1 → T2 → T3; `rebuild` reconstruye el
índice léxico derivado de una versión desde la autoridad; `verify` sólo informa y `search`/`show`
sólo leen: ninguna operación repara ni inicializa automáticamente el almacén. `health` informa la
disponibilidad del almacén (`D-14`) y, cuando no está disponible, `search` y `show` responden
`index_unavailable`.

Códigos de salida:
- `0`: operación correcta (incluye una búsqueda sin resultados y un `health` degradado, que informa).
- `1`: la auditoría se ejecutó, pero la versión no está verificada (`VerifyOutcome.ok is False`).
- `2`: error operativo o de uso: almacén incorrecto o ajeno, índice no disponible, versión no
  encontrada, referencia ausente, fallo de extracción, consulta o límites inválidos, o argumento
  requerido ausente.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.application.health import exigir_disponible, health
from book_text_rag.application.index_version import index_version_de_resultados
from book_text_rag.application.ingest_persistent import ingest_persistent
from book_text_rag.application.search_lexical import search_lexical
from book_text_rag.domain.models import IngestError, IngestResult
from book_text_rag.ports.storage import FragmentRead, SearchResult, StoreError, StoreErrorCode


class _AnalizadorArgumentos(argparse.ArgumentParser):
    """Parser con diagnóstico explícito en español para errores de uso."""

    def error(self, message: str) -> NoReturn:
        """Termina con el código de uso y conserva el detalle del argumento rechazado."""
        prefijo_requeridos = "the following arguments are required: "
        if message.startswith(prefijo_requeridos):
            message = f"faltan argumentos requeridos: {message.removeprefix(prefijo_requeridos)}"
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error [uso]: {message}\n")

    def format_usage(self) -> str:
        """Devuelve la línea de uso con el rótulo en español."""
        return super().format_usage().replace("usage: ", "Uso: ", 1)

    def format_help(self) -> str:
        """Devuelve la ayuda con la línea de uso en español."""
        return super().format_help().replace("usage: ", "Uso: ", 1)


_CODIGOS_SALIDA = (
    "Códigos de salida:\n"
    "  0 = operación correcta;\n"
    "  1 = auditoría ejecutada y versión no verificada;\n"
    "  2 = error operativo o de uso (almacén incorrecto o ajeno, versión o referencia ausente, "
    "fallo de extracción o argumento requerido ausente)."
)

_CODIGOS_SALIDA_CONSULTA = (
    "Códigos de salida:\n"
    "  0 = operación correcta, incluso cuando la consulta no devuelve resultados;\n"
    "  2 = error operativo o de uso (almacén incorrecto o ajeno, índice no disponible, versión o "
    "referencia ausente, consulta o límites inválidos o argumento requerido ausente)."
)

_CODIGOS_SALIDA_CATALOGO = (
    "Códigos de salida:\n"
    "  0 = catálogo informado, incluso cuando el almacén no contiene documentos;\n"
    "  2 = error operativo o de uso (almacén incorrecto o ajeno, índice no disponible o argumento "
    "requerido ausente)."
)

_CODIGOS_SALIDA_SALUD = (
    "Códigos de salida:\n"
    "  0 = estado informado, disponible o degradado (health informa y no falla por indisponibilidad);\n"
    "  2 = error de uso (argumento requerido ausente)."
)

_CODIGOS_SALIDA_RECONSTRUCCION = (
    "Códigos de salida:\n"
    "  0 = reconstrucción completada;\n"
    "  2 = error operativo o de uso (almacén incorrecto o ajeno, versión o referencia ausente "
    "o argumento requerido ausente)."
)


def _agregar_ayuda(parser: argparse.ArgumentParser) -> None:
    """Añade la opción de ayuda con los rótulos en español."""
    parser._positionals.title = "argumentos posicionales"
    parser._optionals.title = "opciones"
    parser.add_argument("-h", "--help", action="help", help="mostrar esta ayuda y salir")


def _summarize(result: IngestResult) -> str:
    """Resume la traza existente del pipeline, sin alterar sus datos."""
    counts = result.trace.counts
    calibration = result.trace.calibration
    levels = ", ".join(f"{name}={value}" for name, value in sorted(counts.anchored_by_level.items()))
    return "\n".join(
        [
            f"document_version      : {result.trace.document_version}",
            f"extractor             : {' '.join(result.trace.extractor)}",
            f"geometry_tool         : {result.trace.geometry_tool}",
            f"chunking_config_version: {result.trace.chunking_config_version}",
            f"calibracion           : delta={calibration.delta_pt} pt, dispersion={calibration.dispersion_pt} pt, "
            f"tolerancia={calibration.tolerance_pt} pt, entradas={calibration.entries}",
            f"unidades del corpus   : {counts.corpus_units} ({levels})",
            f"fragmentos            : {counts.fragments} (bloques de tabla: {counts.table_blocks})",
            f"cola previa           : {counts.tail_words_total} palabras "
            f"({counts.tail_words_predecessor_same_page} con predecesor en la misma pagina)",
            f"mobiliario excluido   : {counts.page_number_lines_excluded} lineas "
            f"(anomalias: {counts.page_number_anomalies})",
        ]
    )


def _formatear_paginas(inicio: int | None, fin: int | None) -> str:
    """Representa las páginas declaradas sin inventar los extremos ausentes."""
    if inicio is None and fin is None:
        return "no declaradas"
    if inicio is None:
        return f"hasta {fin}"
    if fin is None:
        return f"desde {inicio}"
    return str(inicio) if inicio == fin else f"{inicio}-{fin}"


def _recorte(texto: str, limite: int = 120) -> str:
    """Primera línea del contenido, recortada a una sola línea legible y sin saltos."""
    plano = " ".join(texto.split())
    return plano if len(plano) <= limite else plano[:limite] + "…"


def _formatear_resultado(posicion: int, resultado: SearchResult) -> list[str]:
    """Proyecta un resultado de recuperación con la procedencia que expone el almacén."""
    ruta = " > ".join(resultado.section_path) if resultado.section_path else "(sin secciones)"
    return [
        f"[{posicion}]",
        f"rank: {resultado.rank}",
        f"score: {resultado.score:.6f}",
        f"document_id: {resultado.document_id}",
        f"document_version: {resultado.document_version}",
        f"chunk_id: {resultado.chunk_id}",
        f"section_path: {ruta}",
        f"paginas: {_formatear_paginas(resultado.pdf_page_start, resultado.pdf_page_end)}",
        "content:",
        resultado.content,
    ]


def _formatear_resultado_breve(resultado: SearchResult) -> str:
    """Línea única con la procedencia del resultado, sin contenido (`search --brief`)."""
    ruta = " > ".join(resultado.section_path) if resultado.section_path else "(sin secciones)"
    paginas = _formatear_paginas(resultado.pdf_page_start, resultado.pdf_page_end)
    return (
        f"[{resultado.rank}] score={resultado.score:.6f} document_id={resultado.document_id} "
        f"chunk_id={resultado.chunk_id} "
        f"version={resultado.document_version[:12]} paginas={paginas} seccion={ruta}"
    )


def _formatear_fragmento(fragmento: FragmentRead) -> str:
    """Línea única de un fragmento de la versión, con el inicio del texto (`show --fragments`)."""
    ruta = " > ".join(fragmento.section_path) if fragmento.section_path else "(sin secciones)"
    paginas = _formatear_paginas(fragmento.pdf_page_start, fragmento.pdf_page_end)
    return f"{fragmento.ordinal:>4} | {fragmento.chunk_id} | {paginas} | {ruta} | {_recorte(fragmento.content)}"


def _formatear_fragmento_completo(fragmento: FragmentRead) -> list[str]:
    """Detalle de un fragmento concreto, con su contenido completo (`show --orden`)."""
    ruta = " > ".join(fragmento.section_path) if fragmento.section_path else "(sin secciones)"
    return [
        f"ordinal: {fragmento.ordinal}",
        f"chunk_id: {fragmento.chunk_id}",
        f"section_path: {ruta}",
        f"nivel: {fragmento.level}",
        f"block_type: {fragmento.block_type.value}",
        f"captions: {len(fragmento.captions)}",
        f"paginas: {_formatear_paginas(fragmento.pdf_page_start, fragmento.pdf_page_end)}",
        f"anchor_level: {fragmento.anchor_level.value}",
        f"content_hash: {fragmento.content_hash}",
        "content:",
        fragmento.content,
    ]


def _resolver_version_solicitada(versiones: tuple[str, ...], solicitada: str) -> str:
    """Resuelve la versión pedida: completa o **prefijo único**, sin elegir entre candidatas.

    Devuelve la versión registrada que corresponde. Un prefijo ambiguo es un **error de uso** con los
    candidatos completos —nunca se elige una— y un valor que no coincide con ninguna registrada conserva
    `version_no_encontrada`, el código que ya existía.
    """
    if not solicitada.strip():
        raise ValueError("--document-version no puede estar vacía")
    if solicitada in versiones:
        return solicitada
    candidatas = tuple(version for version in versiones if version.startswith(solicitada))
    if len(candidatas) == 1:
        return candidatas[0]
    if candidatas:
        raise ValueError(
            f"el prefijo «{solicitada}» coincide con {len(candidatas)} versiones: " + ", ".join(candidatas)
        )
    raise StoreError(
        StoreErrorCode.VERSION_NO_ENCONTRADA,
        "la versión no está registrada",
        document_version=solicitada,
    )


def _mostrar_fragmentos(
    fragmentos: tuple[FragmentRead, ...],
    *,
    orden: int | None,
    listar: bool,
    limite: int,
    todos: bool,
) -> None:
    """Extiende la ficha de la versión con el detalle de sus fragmentos (`show --fragments`/`--orden`).

    Sin `--fragments` ni `--orden` la salida de `show` no cambia. `--orden` inspecciona un fragmento
    concreto con su contenido completo; `--fragments` lista como máximo `limite` fragmentos, salvo `--all`.
    """
    if orden is not None:
        if orden < 1:
            raise ValueError("--orden debe ser un ordinal >= 1")
        seleccionado = next((fragmento for fragmento in fragmentos if fragmento.ordinal == orden), None)
        if seleccionado is None:
            raise ValueError(f"la versión no tiene un fragmento con ordinal {orden}")
        print()
        print(f"fragmento {orden}:")
        print("\n".join(_formatear_fragmento_completo(seleccionado)))
        return
    if not listar:
        return
    if limite < 1:
        raise ValueError("--limit debe ser un entero >= 1")
    visibles = fragmentos if todos else fragmentos[:limite]
    print()
    print(f"listado: {len(visibles)} de {len(fragmentos)}")
    for fragmento in visibles:
        print(_formatear_fragmento(fragmento))
    if len(visibles) < len(fragmentos):
        print(f"  … {len(fragmentos) - len(visibles)} fragmentos más; use --all o --limit N")


def _reportar_error(error: StoreError | IngestError) -> None:
    """Imprime el código, el mensaje y los detalles de un error previsto."""
    print(f"error [{error.code.value}]: {error.message}", file=sys.stderr)
    for key, value in sorted(error.details.items()):
        print(f"  {key}: {value}", file=sys.stderr)


def _exigir_almacen_inicializado(store: SqliteStore, document_id: str) -> None:
    """Rechaza destinos ajenos sin escribir ni inicializar automáticamente."""
    if store.is_initialized():
        return
    # Esta lectura clasifica el destino como `no_es_base` o `incompatible` y no crea el esquema.
    store.verify_version(document_id, "0" * 64)
    raise StoreError(
        StoreErrorCode.INCOMPATIBLE,
        "el almacén no está inicializado; ejecute `init` antes de la ingesta",
        ruta=str(store.path),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada del console script `book-text-rag`."""
    parser = _AnalizadorArgumentos(
        prog="book-text-rag",
        description=(
            "Operaciones administrativas de inicialización, ingesta persistente, reconstrucción del índice "
            "derivado, auditoría, catálogo y salud del almacén."
        ),
        epilog=_CODIGOS_SALIDA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    _agregar_ayuda(parser)
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=_AnalizadorArgumentos)

    inicializar = subparsers.add_parser(
        "init",
        help="crear o verificar el esquema SQLite sin migrar almacenes ajenos",
        description="Crea el esquema o verifica que el almacén ya sea compatible e inicializado.",
        epilog=_CODIGOS_SALIDA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    _agregar_ayuda(inicializar)
    inicializar.add_argument("--store", required=True, help="ruta explícita del almacén SQLite")

    ingest = subparsers.add_parser(
        "ingest",
        help="extraer, anclar, fragmentar y persistir una fuente",
        description="Ejecuta la ingesta persistente T1 → T2 → T3 sobre un PDF y un almacén inicializado.",
        epilog=_CODIGOS_SALIDA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    _agregar_ayuda(ingest)
    ingest.add_argument("pdf", help="ruta al PDF fuente")
    ingest.add_argument("--document-id", required=True, help="identificador explícito del documento")
    ingest.add_argument("--alias", required=True, help="alias explícito de la referencia")
    ingest.add_argument("--fecha", required=True, help="fecha explícita de la referencia")
    ingest.add_argument("--store", required=True, help="ruta explícita del almacén SQLite")
    ingest.add_argument("--source-format", help="formato declarado de la fuente")

    verificar = subparsers.add_parser(
        "verify",
        help="auditar una versión sin modificar ni reparar el almacén",
        description="Verifica los indicadores disponibles de una versión persistida; nunca repara el índice.",
        epilog=_CODIGOS_SALIDA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    _agregar_ayuda(verificar)
    verificar.add_argument("--store", required=True, help="ruta explícita del almacén SQLite")
    verificar.add_argument("--document-id", required=True, help="identificador explícito del documento")
    verificar.add_argument("--document-version", required=True, help="document_version completa que se audita")

    reconstruir = subparsers.add_parser(
        "rebuild",
        help="reconstruir el índice léxico derivado de una versión desde la autoridad",
        description=(
            "Reconstruye fragmento_fts de una versión desde la autoridad persistida, en una transacción; "
            "no toca el contenido, el estado de ingesta ni index_version."
        ),
        epilog=_CODIGOS_SALIDA_RECONSTRUCCION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    _agregar_ayuda(reconstruir)
    reconstruir.add_argument("--store", required=True, help="ruta explícita del almacén SQLite")
    reconstruir.add_argument("--document-id", required=True, help="identificador explícito del documento")
    reconstruir.add_argument(
        "--document-version", required=True, help="document_version completa cuyo índice derivado se reconstruye"
    )

    buscar = subparsers.add_parser(
        "search",
        help="consultar el índice léxico y devolver evidencia con procedencia",
        description="Ejecuta una consulta léxica BM25 de solo lectura sobre un almacén inicializado.",
        epilog=_CODIGOS_SALIDA_CONSULTA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    _agregar_ayuda(buscar)
    buscar.add_argument("query", help="texto de la consulta léxica (máximo 1000 caracteres)")
    buscar.add_argument("--store", required=True, help="ruta explícita del almacén SQLite")
    buscar.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="número máximo de resultados, entre 1 y 50 (por defecto 10)",
    )
    buscar.add_argument(
        "--document-id",
        action="append",
        dest="document_ids",
        metavar="ID",
        help="filtra por documento; puede repetirse para consultar más de uno",
    )

    buscar.add_argument(
        "--brief",
        action="store_true",
        help="mostrar una línea de procedencia por resultado, sin el contenido",
    )

    mostrar = subparsers.add_parser(
        "show",
        help="mostrar metadatos, estados y fragmentos de una versión",
        description="Lee la autoridad persistida de una versión registrada, sin escribir ni reparar.",
        epilog=_CODIGOS_SALIDA_CONSULTA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    _agregar_ayuda(mostrar)
    mostrar.add_argument("--store", required=True, help="ruta explícita del almacén SQLite")
    mostrar.add_argument("--document-id", required=True, help="identificador explícito del documento")
    mostrar.add_argument(
        "--document-version",
        required=True,
        help="document_version completa o un prefijo único entre las versiones registradas",
    )
    mostrar.add_argument(
        "--fragments",
        action="store_true",
        help="listar los fragmentos de la versión (20 por defecto; ver --limit y --all)",
    )
    mostrar.add_argument(
        "--limit",
        type=int,
        default=20,
        help="cuántos fragmentos listar con --fragments (por defecto 20)",
    )
    mostrar.add_argument(
        "--all",
        action="store_true",
        help="listar todos los fragmentos de la versión con --fragments",
    )
    mostrar.add_argument(
        "--orden",
        type=int,
        help="mostrar un fragmento concreto por su ordinal, con su contenido completo",
    )

    catalogo = subparsers.add_parser(
        "documents",
        help="listar los documentos del almacén sin modificarlo",
        description=(
            "Enumera el catálogo del almacén: cada documento con sus alias y estados de ingesta, sus "
            "metadatos de fuente y sus versiones registradas. `consultable` indica si la búsqueda puede "
            "devolver fragmentos de ese documento (referencias presentes y todas completadas); es un "
            "indicador del documento, no de cada versión. No muestra fragmentos, contenido ni rutas."
        ),
        epilog=_CODIGOS_SALIDA_CATALOGO,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    _agregar_ayuda(catalogo)
    catalogo.add_argument("--store", required=True, help="ruta explícita del almacén SQLite")

    salud = subparsers.add_parser(
        "health",
        help="informar la disponibilidad del almacén sin modificarlo",
        description=(
            "Informa el estado de disponibilidad del almacén conforme a D-14: `status`, `dependencies` y "
            "`available_modes`. Es de solo lectura: no crea el almacén ausente, no escribe y no repara."
        ),
        epilog=_CODIGOS_SALIDA_SALUD,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    _agregar_ayuda(salud)
    salud.add_argument("--store", required=True, help="ruta explícita del almacén SQLite")

    args = parser.parse_args(list(argv) if argv is not None else None)
    store = SqliteStore(Path(args.store))

    try:
        if args.command == "init":
            resultado_init = store.initialize()
            print(f"almacen: {store.path}")
            print(f"resultado: {resultado_init.value}")
            return 0

        if args.command == "ingest":
            document_id = str(args.document_id)
            _exigir_almacen_inicializado(store, document_id)
            resultado_ingesta, escritura = ingest_persistent(
                Path(str(args.pdf)),
                document_id,
                str(args.alias),
                fecha=str(args.fecha),
                store=store,
                source_format=None if args.source_format is None else str(args.source_format),
            )
            print(_summarize(resultado_ingesta))
            print(f"almacen: {store.path}")
            print(f"document_id: {document_id}")
            print(f"document_version: {resultado_ingesta.trace.document_version}")
            print(f"fragmentos_escritos: {escritura.fragmentos_escritos}")
            print(f"fragmentos_existentes: {escritura.fragmentos_existentes}")
            print(f"sqlite_vec_verificado: {escritura.sqlite_vec_verificado}")
            return 0

        if args.command == "documents":
            exigir_disponible(store)
            documentos = store.list_documents()
            lineas = [f"documentos: {len(documentos)}"]
            for posicion, documento in enumerate(documentos, start=1):
                lineas.extend(
                    [
                        "",
                        f"[{posicion}]",
                        f"document_id: {documento.document_id}",
                        f"source_format: {documento.source_format or '(no declarado)'}",
                        f"page_count: {documento.page_count if documento.page_count is not None else '(no declarado)'}",
                        f"referencias: {len(documento.references)}",
                    ]
                )
                if documento.references:
                    for referencia in documento.references:
                        lineas.append(f"  alias: {referencia.alias} | estado: {referencia.estado.value}")
                else:
                    lineas.append("  (sin referencias)")
                lineas.append(f"versiones: {len(documento.versions)}")
                for identificador in documento.versions:
                    lineas.append(f"  - {identificador}")
                lineas.append(f"consultable: {'sí' if documento.consultable else 'no'}")
            print("\n".join(lineas))
            return 0

        if args.command == "health":
            resumen = health(store)
            print(f"status: {resumen.status}")
            print(f"dependencies: {json.dumps(list(resumen.dependencies))}")
            print(f"available_modes: {json.dumps(list(resumen.available_modes))}")
            return 0

        if args.command == "rebuild":
            resultado_reconstruccion = store.rebuild_lexical_index(str(args.document_id), str(args.document_version))
            print(f"almacen: {store.path}")
            print(f"document_id: {resultado_reconstruccion.document_id}")
            print(f"document_version: {resultado_reconstruccion.document_version}")
            print(f"filas_previas: {resultado_reconstruccion.filas_previas}")
            print(f"filas_reconstruidas: {resultado_reconstruccion.filas_reconstruidas}")
            return 0

        if args.command == "verify":
            resultado_verificacion = store.verify_version(str(args.document_id), str(args.document_version))
            print(f"fragmentos: {resultado_verificacion.fragmentos}")
            print(f"ordinales_ok: {resultado_verificacion.ordinales_ok}")
            print(f"content_hash_ok: {resultado_verificacion.content_hash_ok}")
            print(f"chunk_id_ok: {resultado_verificacion.chunk_id_ok}")
            print(f"fts5_ok: {resultado_verificacion.fts5_ok}")
            print(f"estado_ok: {resultado_verificacion.estado_ok}")
            print(f"traza_presente: {resultado_verificacion.traza_presente}")
            print(f"fuente_presente: {resultado_verificacion.fuente_presente}")
            print(f"ok: {resultado_verificacion.ok}")
            print(f"no_verificado: {resultado_verificacion.no_verificado}")
            return 0 if resultado_verificacion.ok else 1

        if args.command == "search":
            filtros = (
                None if args.document_ids is None else tuple(str(identificador) for identificador in args.document_ids)
            )
            exigir_disponible(store)
            resultados = search_lexical(store, query=str(args.query), top_k=int(args.top_k), document_ids=filtros)
            identidad = index_version_de_resultados(store, resultados)
            lineas = [
                f"consulta: {args.query}",
                "modo: lexical",
                f"index_version: {'null' if identidad is None else identidad}",
                f"resultados: {len(resultados)}",
            ]
            if args.brief:
                lineas.extend(_formatear_resultado_breve(resultado) for resultado in resultados)
                print("\n".join(lineas))
                return 0
            for posicion, resultado in enumerate(resultados, start=1):
                lineas.append("")
                lineas.extend(_formatear_resultado(posicion, resultado))
            print("\n".join(lineas))
            return 0

        if args.command == "show":
            exigir_disponible(store)
            version_resuelta = _resolver_version_solicitada(
                store.read_document(str(args.document_id)).versions, str(args.document_version)
            )
            version = store.read_version(str(args.document_id), version_resuelta)
            identidad = store.index_version_for(str(args.document_id), version_resuelta)
            print(f"document_id: {version.document_id}")
            print(f"document_version: {version.document_version}")
            print(f"index_version: {'null' if identidad is None else identidad}")
            print(f"estados: {', '.join(estado.value for estado in version.estados)}")
            print(f"source_format: {version.source_format if version.source_format is not None else '(no declarado)'}")
            print(f"page_count: {version.page_count if version.page_count is not None else '(no declarado)'}")
            print(f"fragmentos: {len(version.fragments)}")
            _mostrar_fragmentos(
                version.fragments, orden=args.orden, listar=args.fragments, limite=args.limit, todos=args.all
            )
            return 0

        parser.error("comando no soportado")  # pragma: no cover - argparse lo impide
    except ValueError as error:
        print(f"error [uso]: {error}", file=sys.stderr)
        return 2
    except (StoreError, IngestError) as error:
        _reportar_error(error)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
