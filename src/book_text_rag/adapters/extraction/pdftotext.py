"""Adaptador del extractor de texto aprobado: `pdftotext` (Xpdf) con `-layout -enc UTF-8` (D-19 §1).

La salida se lee en memoria por `stdout` y se decodifica en **UTF-8 estricto**: sin
`errors="replace"`, sin BOM y sin normalización posterior (D-19 §1.2). Cualquier fallo es explícito
y no produce salida parcial (D-20 §5).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from book_text_rag.domain.models import ErrorCode, IngestError

FLAGS = ("-layout", "-enc", "UTF-8")
FLAGS_TEXT = "-layout -enc UTF-8"
_VERSION_RE = re.compile(r"version\s+(\S+)", re.IGNORECASE)


def decode_output(blob: bytes) -> str:
    """Decodifica la salida del extractor en UTF-8 **estricto**, con una excepción declarada.

    Sin `errors="replace"`, sin BOM y sin normalización posterior: los errores se manifiestan en vez
    de ocultarse (D-20 §5, `decode_error`).

    **Excepción aprobada (D-19 §1.2, enmienda 2026-10-23).** Algunos PDF traen caracteres astrales
    codificados en **CESU-8**: dos surrogates UTF-8 consecutivos (p. ej. `ED A0 BE ED B7 A0` para
    U+1F9E0) en lugar de la secuencia UTF-8 de cuatro bytes. Esos pares **se recomponen** en el carácter
    real, que es lo que el autor escribió; no se sustituye nada. Un surrogate **no emparejado** o cualquier
    otra secuencia irreparable sigue siendo `decode_error`: la política no se vuelve permisiva.
    """
    try:
        text = blob.decode("utf-8", errors="surrogatepass")
    except UnicodeDecodeError as error:
        raise IngestError(
            ErrorCode.DECODE_ERROR,
            "la salida del extractor no decodifica en UTF-8 estricto",
            posicion=error.start,
        ) from error
    text = _recomponer_pares_cesu8(text)
    if text.startswith("\ufeff"):
        raise IngestError(ErrorCode.DECODE_ERROR, "la salida del extractor trae BOM")
    return text


def _recomponer_pares_cesu8(texto: str) -> str:
    """Combina pares de surrogates (CESU-8) en su carácter astral; rechaza los no emparejados.

    `surrogatepass` deja los surrogates tal cual. Aquí se valida que **cada** uno forme parte de un par
    alto+bajo y se recompone con la fórmula UTF-16; cualquier surrogate suelto es un error explícito, no
    un reemplazo.
    """
    if not any("\ud800" <= caracter <= "\udfff" for caracter in texto):
        return texto
    resultado: list[str] = []
    indice = 0
    while indice < len(texto):
        caracter = texto[indice]
        if "\ud800" <= caracter <= "\udbff":
            siguiente = texto[indice + 1] if indice + 1 < len(texto) else ""
            if not "\udc00" <= siguiente <= "\udfff":
                raise IngestError(
                    ErrorCode.DECODE_ERROR,
                    "la salida trae un surrogate alto no emparejado",
                    posicion=indice,
                )
            codigo = 0x10000 + ((ord(caracter) - 0xD800) << 10) + (ord(siguiente) - 0xDC00)
            resultado.append(chr(codigo))
            indice += 2
            continue
        if "\udc00" <= caracter <= "\udfff":
            raise IngestError(
                ErrorCode.DECODE_ERROR,
                "la salida trae un surrogate bajo no emparejado",
                posicion=indice,
            )
        resultado.append(caracter)
        indice += 1
    return "".join(resultado)


class PdftotextExtractor:
    """Extrae el texto del PDF con la configuración efectiva de D-19 §1."""

    def __init__(self, pdf_path: Path, binary: Path | None = None) -> None:
        self._pdf_path = pdf_path
        self._binary = binary
        self._version: str | None = None

    def _resolve_binary(self) -> Path:
        if self._binary is not None:
            if not self._binary.exists():
                raise IngestError(ErrorCode.EXTRACTOR_UNAVAILABLE, "extractor no disponible", binario=str(self._binary))
            return self._binary
        found = shutil.which("pdftotext")
        if found is None:
            raise IngestError(ErrorCode.EXTRACTOR_UNAVAILABLE, "extractor no disponible", binario="pdftotext")
        return Path(found)

    def _detect_version(self, binary: Path) -> str:
        if self._version is not None:
            return self._version
        try:
            result = subprocess.run([str(binary), "-v"], capture_output=True, check=False, timeout=60)
        except OSError as error:  # pragma: no cover - depende del sistema
            raise IngestError(ErrorCode.EXTRACTOR_UNAVAILABLE, "no se pudo ejecutar el extractor") from error
        blob = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        match = _VERSION_RE.search(blob)
        self._version = match.group(1) if match else "desconocida"
        return self._version

    def pages(self) -> list[str]:
        """Devuelve las páginas del PDF decodificadas en UTF-8 estricto."""
        if not self._pdf_path.exists():
            raise IngestError(ErrorCode.SOURCE_UNREADABLE, "la fuente no existe", ruta=str(self._pdf_path))
        binary = self._resolve_binary()
        try:
            result = subprocess.run(
                [str(binary), *FLAGS, str(self._pdf_path), "-"],
                capture_output=True,
                check=False,
                timeout=900,
            )
        except OSError as error:
            raise IngestError(ErrorCode.EXTRACTOR_UNAVAILABLE, "no se pudo ejecutar el extractor") from error
        if result.returncode != 0:
            raise IngestError(
                ErrorCode.EXTRACTION_FAILED,
                "el extractor devolvió un error",
                codigo=result.returncode,
                detalle=result.stderr.decode("utf-8", errors="replace")[:400],
            )
        try:
            text = decode_output(result.stdout)
        except UnicodeDecodeError as error:  # pragma: no cover - decode_output ya la convierte
            raise IngestError(ErrorCode.DECODE_ERROR, "la salida del extractor no decodifica") from error
        pages = text.split("\f")
        if pages and not pages[-1].strip():
            pages = pages[:-1]
        return pages

    def effective_config(self) -> tuple[str, str, str]:
        """Configuración efectiva observada (D-19 §1.3): nombre, versión y flags."""
        binary = self._resolve_binary()
        return ("pdftotext", self._detect_version(binary), FLAGS_TEXT)
