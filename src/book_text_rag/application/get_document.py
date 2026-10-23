"""Caso de uso `get_document` (`D-07`, `D-13`), en el alcance mínimo decidido.

Alcance implementado (**B1, B2, B4**):

- **Cero versiones registradas (`B4`):** `status: not_indexed`; `document_version`, `index_version` y
  `title` en `null`; `source_format` y `page_count` conservan los valores de `fuente` si existen.
  La ausencia de versiones **no** es `document_not_found`.
- **Una versión (`D-13`):** `status: indexed` solo si **todos** los estados observados del documento son
  «ingesta completada e índice disponible para consulta»; cualquier otro estado produce `not_indexed`
  («nunca antes de tiempo»). El `index_version` se recalcula con la regla de F.
- **Versión omitida (`B2`):** con una sola versión se resuelve; con varias se responde `invalid_request`
  con `details.field = "document_version"`; nunca se elige por orden, fecha ni valor lexicográfico.
- **`title` (`B1`):** siempre `null` mientras no exista un origen aprobado; no se deriva de rutas,
  nombres de archivo ni títulos del outline.

**Fuera de alcance declarado.** Con **dos o más versiones** y una versión explícita, el `status` por
versión no es derivable del almacén: el estado de ingesta vive en `referencia_fuente` (por documento) y
las versiones no están vinculadas a ninguna referencia, de modo que aplicarlo a cada versión sería
inventar la correspondencia que `CD-02/M-14` debe decidir. En ese caso el caso de uso lanza
`EstadoPorVersionNoDefinido` **antes** de construir `DocumentView`: no hay respuesta pública, no se
fabrica ningún `status` y **no se mapea a ningún código** de `D-07` hasta que esa decisión exista.
"""

from __future__ import annotations

from book_text_rag.application.health import exigir_disponible
from book_text_rag.ports.storage import (
    DocumentIndex,
    DocumentStatus,
    DocumentView,
    EstadoIngesta,
    StoreError,
    StoreErrorCode,
    StoreReadService,
)


class EstadoPorVersionNoDefinido(Exception):
    """El `status` por versión no es derivable: requiere `CD-02/M-14`.

    No es un código público ni se mapea a uno: `D-07` no ofrece un error que describa «el documento
    existe, tiene varias versiones y su estado por versión no está definido». Se lanza **antes** de
    construir la respuesta para no fabricar un `status`. Hoy ninguna superficie puede alcanzarlo: no hay
    transporte ni verbo de CLI, y `show` no lo usa.
    """


def get_document(store: StoreReadService, document_id: str, document_version: str | None = None) -> DocumentView:
    """Proyecta los siete campos de `D-07` para el documento y la versión resueltos."""
    exigir_disponible(store)  # D-14: almacén no disponible ⇒ `index_unavailable`
    try:
        indice = store.read_document(document_id)  # sin referencia ⇒ `referencia_ausente`
    except StoreError as error:
        if error.code is StoreErrorCode.REFERENCIA_AUSENTE:
            # `D-07`/`D-13`: un identificador no registrado en el catálogo es `document_not_found`.
            raise StoreError(
                StoreErrorCode.DOCUMENT_NOT_FOUND,
                "el documento no está registrado en el catálogo",
                document_id=document_id,
            ) from error
        raise

    version = _resolver_version(indice, document_version)
    if len(indice.versions) >= 2:
        raise EstadoPorVersionNoDefinido(
            "el estado por versión de un documento con varias versiones requiere CD-02/M-14; "
            f"document_id={document_id!r} tiene {len(indice.versions)} versiones registradas"
        )

    if version is None:
        return DocumentView(
            document_id=document_id,
            document_version=None,
            title=None,
            source_format=indice.source_format,
            page_count=indice.page_count,
            index_version=None,
            status=DocumentStatus.NOT_INDEXED,
        )

    return DocumentView(
        document_id=document_id,
        document_version=version,
        title=None,
        source_format=indice.source_format,
        page_count=indice.page_count,
        index_version=store.index_version_for(document_id, version),
        status=_estado_publico(indice.estados),
    )


def _resolver_version(indice: DocumentIndex, document_version: str | None) -> str | None:
    """Resuelve la versión pedida u omitida (`B2`). No elige entre varias ni por orden alguno."""
    if document_version is not None:
        if document_version not in indice.versions:
            raise StoreError(
                StoreErrorCode.DOCUMENT_NOT_FOUND,
                "la versión no está registrada para el documento",
                document_id=indice.document_id,
                document_version=document_version,
            )
        return document_version
    if not indice.versions:
        return None
    if len(indice.versions) == 1:
        return indice.versions[0]
    raise StoreError(
        StoreErrorCode.INVALID_REQUEST,
        "el documento tiene varias versiones: indique document_version",
        field="document_version",
    )


def _estado_publico(estados: tuple[EstadoIngesta, ...]) -> DocumentStatus:
    """`indexed` solo si **todos** los estados observados son «ingesta completada» (`D-13`)."""
    if estados and all(estado is EstadoIngesta.COMPLETADA for estado in estados):
        return DocumentStatus.INDEXED
    return DocumentStatus.NOT_INDEXED


__all__ = ["EstadoPorVersionNoDefinido", "get_document"]
