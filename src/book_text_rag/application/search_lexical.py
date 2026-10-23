"""Proyección interna de resultados de recuperación léxica de `D-07`.

Construye una expresión MATCH segura a partir del texto del usuario: extrae tokens alfanuméricos y
los combina con `OR`, cada uno entre comillas para neutralizar la sintaxis de FTS5. Sin lista de
stopwords en esta versión. No implementa la búsqueda pública: no crea sobre, no acepta `mode` y no
calcula ni persiste `index_version`. La capa de almacenamiento determina el orden y `rank`, y esta
aplicación los devuelve intactos. El mapeo público de errores (`invalid_request`, etc.) pertenece a
una superficie futura y no se implementa aquí.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from book_text_rag.ports.storage import SearchResult, StoreReader

TOP_K_POR_DEFECTO = 10
TOP_K_MAXIMO = 50
LONGITUD_MAXIMA_CONSULTA = 1000


def _tokens_alfanumericos(consulta: str) -> tuple[str, ...]:
    """Máximas secuencias alfanuméricas de la consulta, sin repetidos (comparación sin mayúsculas).

    Cualquier otro carácter —guion, apóstrofo, signo de interrogación, comillas o un operador de
    FTS5— actúa como separador. Se conserva la forma de la primera aparición de cada token para que
    la expresión sea legible; FTS5 no distingue mayúsculas al buscar.
    """
    tokens: list[str] = []
    actual: list[str] = []
    for caracter in consulta:
        if caracter.isalnum():
            actual.append(caracter)
            continue
        if actual:
            tokens.append("".join(actual))
            actual.clear()
    if actual:
        tokens.append("".join(actual))

    vistos: set[str] = set()
    unicos: list[str] = []
    for token in tokens:
        clave = token.casefold()
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(token)
    return tuple(unicos)


def _expresion_lexica(consulta: str) -> str:
    """Expresión MATCH con un `OR` por token, segura frente a la sintaxis de FTS5.

    Cada token va entre comillas: los tokens son alfanuméricos, de modo que no hace falta escapar
    nada dentro de ellas, y así palabras como `AND`, `OR`, `NOT` o `NEAR` se tratan como términos y
    no como operadores. Un token único entre comillas produce los mismos aciertos y puntuaciones
    que el token desnudo.
    """
    tokens = _tokens_alfanumericos(consulta)
    if not tokens:
        raise ValueError("la consulta léxica no contiene tokens alfanuméricos utilizables")
    return " OR ".join(f'"{token}"' for token in tokens)


def _validar_document_ids(document_ids: tuple[str, ...] | None) -> tuple[str, ...] | None:
    """Valida los identificadores sin convertir cadenas en secuencias de caracteres."""
    crudo: object = document_ids
    if crudo is None:
        return None
    if isinstance(crudo, (str, bytes)):
        raise ValueError("document_ids no puede ser str ni bytes")
    if not isinstance(crudo, Iterable):
        raise ValueError("document_ids debe ser una colección de identificadores str")

    identificadores = tuple(crudo)
    for elemento in identificadores:
        if not isinstance(elemento, str):
            raise ValueError("cada elemento de document_ids debe ser str")
    return cast(tuple[str, ...], identificadores)


def search_lexical(
    store: StoreReader,
    *,
    query: str,
    top_k: int = TOP_K_POR_DEFECTO,
    document_ids: tuple[str, ...] | None = None,
) -> tuple[SearchResult, ...]:
    """Valida la entrada, construye la expresión léxica y devuelve la secuencia del almacén.

    La consulta del usuario se convierte en `"t1" OR "t2" OR …` con sus tokens alfanuméricos: eso
    elimina los errores de sintaxis de FTS5 (guiones, apóstrofos, signos de interrogación, operadores)
    y evita la conjunción implícita `AND`, que devolvía cero resultados en consultas de varias
    palabras. Sin lista de stopwords en esta versión.

    Es una capacidad **interna**, no la búsqueda pública `search`: no hay sobre, `mode` ni
    `index_version`. No calcula ni persiste `index_version`; el orden y `rank` vienen del almacén y se
    devuelven intactos. El mapeo público de errores (`invalid_request`, etc.) corresponde a la futura
    superficie pública y no se implementa aquí.
    """
    consulta: object = query
    if not isinstance(consulta, str):
        raise ValueError("query debe ser str")
    if not query.strip():
        raise ValueError("la consulta léxica no puede estar vacía")
    if len(query) > LONGITUD_MAXIMA_CONSULTA:
        raise ValueError(f"la consulta léxica supera el máximo de {LONGITUD_MAXIMA_CONSULTA} caracteres")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= TOP_K_MAXIMO:
        raise ValueError(f"top_k debe ser un entero entre 1 y {TOP_K_MAXIMO}")

    expresion = _expresion_lexica(query)
    ids = _validar_document_ids(document_ids)
    if ids == ():
        return ()
    return store.search_results(expresion, document_ids=ids, top_k=top_k)
