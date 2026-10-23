"""Atribución de `index_version` a una respuesta de recuperación (decisión F; M7/CD-01).

`D-07` expone **un solo** `index_version` por respuesta de `search`; `D-15` §8.5 y `CD-01` dejan abierto
qué hacer cuando la respuesta mezcla construcciones. La regla adoptada es la mínima que no amplía el
contrato:

- se emite el valor solo si los resultados pertenecen a **un único par** `(document_id, document_version)`
  y esa versión tiene **exactamente una** construcción con todos sus insumos válidos;
- en cualquier otro caso —resultados vacíos, varias versiones o varias construcciones para la misma
  versión— se emite `None`, que es el valor que `D-07` ya define para «genuinamente desconocido».

No se rechazan consultas mixtas, no se altera el orden ni los resultados, y no se elige una construcción
entre varias: `CD-05` («una construcción activa por versión») sigue abierto y esta regla no lo decide.
"""

from __future__ import annotations

from collections.abc import Iterable

from book_text_rag.ports.storage import SearchResult, StoreReader


def index_version_de_resultados(store: StoreReader, resultados: Iterable[SearchResult]) -> str | None:
    """Devuelve el `index_version` atribuible a la respuesta, o `None` si no hay una única construcción."""
    pares = {(resultado.document_id, resultado.document_version) for resultado in resultados}
    if len(pares) != 1:
        return None
    document_id, document_version = next(iter(pares))
    return store.index_version_for(document_id, document_version)
