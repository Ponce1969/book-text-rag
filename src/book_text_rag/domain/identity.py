"""Identidades y huellas de la unidad 1 (D-11 §§1-4, `001` §6.1, D-20 §§3.1, 3.3).

La unidad 1 en memoria no calcula `index_version`: sus versiones del motor pertenecen a la construcción
del índice (D-20 §3.3). Este módulo sí calcula la etiqueta a partir de los seis insumos de D-11 §4.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Sequence
from typing import cast

__all__ = ["chunk_id", "content_hash", "document_version", "document_version_short", "index_version"]


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def document_version(pdf_bytes: bytes) -> str:
    """`document_version` = SHA-256 de los **bytes originales** de la fuente, sin normalización (D-11 §1)."""
    return _sha256_hex(pdf_bytes)


def document_version_short(version: str) -> str:
    """`document_version_short` = primeros 12 caracteres de `document_version` (D-11 §2)."""
    return version[:12]


def _texto_requerido(valor: object, nombre: str) -> str:
    if not isinstance(valor, str):
        raise ValueError(f"{nombre} debe ser una cadena")
    if not valor:
        raise ValueError(f"{nombre} no puede ser una cadena vacía")
    try:
        valor.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{nombre} debe poder codificarse en UTF-8") from error
    return unicodedata.normalize("NFC", valor)


def _extractor_requerido(valor: object) -> tuple[str, str, str]:
    if not isinstance(valor, Sequence) or isinstance(valor, (str, bytes)):
        raise ValueError("extractor debe ser una secuencia ordenada de exactamente tres cadenas")
    if len(valor) != 3:
        raise ValueError("extractor debe contener exactamente tres cadenas")
    return (
        _texto_requerido(valor[0], "extractor[0]"),
        _texto_requerido(valor[1], "extractor[1]"),
        _texto_requerido(valor[2], "extractor[2]"),
    )


def _escapar_cadena_json(texto: str) -> str:
    caracteres: list[str] = ['"']
    for caracter in texto:
        codigo = ord(caracter)
        if caracter == '"':
            caracteres.append('\\"')
        elif caracter == "\\":
            caracteres.append("\\\\")
        elif codigo <= 0x1F:
            caracteres.append(f"\\u00{codigo:02x}")
        else:
            caracteres.append(caracter)
    caracteres.append('"')
    return "".join(caracteres)


def _embeddings_requerido(valor: object) -> None:
    """Valida el séptimo insumo (`D-11` §4.1): arreglo de descriptores, **cero** en una construcción léxica.

    Esta unidad sólo puede producir construcciones léxicas —no hay almacén de vectores ni arm vectorial
    autorizado—, de modo que el arreglo debe estar vacío. Uno o más descriptores se rechazan en lugar de
    aceptarse sin validar la gramática de ocho campos de §4.1: no se completa ni se inventa ninguno.
    """
    if isinstance(valor, (str, bytes)) or not isinstance(valor, Sequence):
        raise ValueError("embeddings debe ser una secuencia de descriptores")
    if tuple(cast(Sequence[object], valor)):
        raise ValueError(
            "embeddings sólo admite el arreglo vacío: el descriptor de ocho campos de D-11 §4.1 no está "
            "implementado mientras el arm vectorial no esté autorizado"
        )


def _bytes_canonicos(
    *,
    document_version: object,
    extractor: object,
    chunking_config_version: object,
    tokenizer: object,
    sqlite_version: object,
    sqlite_vec_version: object,
    embeddings: object,
) -> bytes:
    version_documento = _texto_requerido(document_version, "document_version")
    version_extractor = _extractor_requerido(extractor)
    version_troceado = _texto_requerido(chunking_config_version, "chunking_config_version")
    declaracion_tokenizador = _texto_requerido(tokenizer, "tokenizer")
    version_sqlite = _texto_requerido(sqlite_version, "sqlite_version")
    version_sqlite_vec = _texto_requerido(sqlite_vec_version, "sqlite_vec_version")
    _embeddings_requerido(embeddings)

    campos = (
        '"document_version":' + _escapar_cadena_json(version_documento),
        '"extractor":[' + ",".join(_escapar_cadena_json(valor) for valor in version_extractor) + "]",
        '"chunking_config_version":' + _escapar_cadena_json(version_troceado),
        '"tokenizer":' + _escapar_cadena_json(declaracion_tokenizador),
        '"sqlite_version":' + _escapar_cadena_json(version_sqlite),
        '"sqlite_vec_version":' + _escapar_cadena_json(version_sqlite_vec),
        # Séptimo y último campo (D-11 §4.1). Con cero descriptores el arreglo se emite como `[]`: es el
        # resultado natural de la emisión de arreglos, sin caso especial. Los seis campos anteriores
        # conservan exactamente sus bytes canónicos.
        '"embeddings":[]',
    )
    return ("{" + ",".join(campos) + "}").encode("utf-8")


def index_version(
    *,
    document_version: str,
    extractor: Sequence[str],
    chunking_config_version: str,
    tokenizer: str,
    sqlite_version: str,
    sqlite_vec_version: str,
    embeddings: Sequence[object],
) -> str:
    """Calcula el prefijo SHA-256 de 12 caracteres de los **siete** insumos de `D-11` §4/§4.1.

    `extractor` es una secuencia ordenada de **exactamente tres** cadenas válidas: nombre, versión y
    configuración efectiva del extractor (D-19 §2). `embeddings` es el séptimo insumo, al final: el
    arreglo de descriptores de §4.1, con **cero** elementos en una construcción léxica. No se persiste
    ningún dato; cualquier insumo ausente o inválido falla explícitamente, sin sustitutos. La firma no
    admite valores por defecto: omitir `embeddings` es un error de llamada, no un valor implícito.

    Añadir el séptimo insumo es el **cambio de época declarado** en §4.1: cambia el valor de todas las
    construcciones, incluidas las léxicas, aunque sus seis primeros insumos no cambien. Esta función no
    decide si persistir o recalcular (D-22 §8) ni cuál construcción elegir (CD-05).

    El descriptor de ocho campos de §4.1 **no se implementa aquí**: hoy no existe arm vectorial autorizado
    ni almacén de vectores, así que un arreglo no vacío se rechaza en lugar de aceptarse sin validar su
    gramática. No se completa ni se inventa ningún descriptor.
    """
    datos = _bytes_canonicos(
        document_version=document_version,
        extractor=extractor,
        chunking_config_version=chunking_config_version,
        tokenizer=tokenizer,
        sqlite_version=sqlite_version,
        sqlite_vec_version=sqlite_vec_version,
        embeddings=embeddings,
    )
    return hashlib.sha256(datos).hexdigest()[:12]


def content_hash(content: str) -> str:
    """`content_hash` = SHA-256 sobre la representación UTF-8 del contenido lógico definitivo (D-11 §3)."""
    return _sha256_hex(content.encode("utf-8"))


def chunk_id(document_id: str, version_short: str, ordinal: int) -> str:
    """`chunk_id` = `{document_id}:{document_version_short}:{ordinal}`, ordinal 1-based (D-07, `001` §6.1)."""
    return f"{document_id}:{version_short}:{ordinal}"
