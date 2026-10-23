"""Adaptador de outline, tipografía y coordenadas con PyMuPDF (herramienta autorizada para geometría).

No extrae contenido: D-19 §1 fija `pdftotext` como extractor. PyMuPDF aporta **sólo** los marcadores
con sus destinos, el tamaño/peso por línea y las coordenadas que D-17 §2 y §4 exigen.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from book_text_rag.domain.models import ErrorCode, IngestError, Line, TocEntry


class PyMuPdfGeometry:
    """Implementa el puerto de geometría leyendo el PDF con PyMuPDF."""

    def __init__(self, pdf_path: Path) -> None:
        self._pdf_path = pdf_path
        if not pdf_path.exists():
            raise IngestError(ErrorCode.SOURCE_UNREADABLE, "la fuente no existe", ruta=str(pdf_path))
        try:
            self._doc = fitz.open(str(pdf_path))
        except Exception as error:  # pragma: no cover - depende del archivo
            raise IngestError(ErrorCode.SOURCE_UNREADABLE, "no se pudo abrir la fuente") from error
        self._cache: dict[int, list[Line]] = {}

    def tool(self) -> str:
        """Identificación de la herramienta y su versión, para el manifiesto y la traza."""
        return f"PyMuPDF {fitz.VersionBind}"

    def toc(self) -> list[TocEntry]:
        """Marcadores del PDF con página física y coordenada del destino cuando existe."""
        entries: list[TocEntry] = []
        for level, title, page, dest in self._doc.get_toc(simple=False):
            y_dest: float | None = None
            if isinstance(dest, dict):
                point = dest.get("to")
                if point is not None:
                    y_dest = round(float(point.y), 3)
            entries.append(TocEntry(level=int(level), title=str(title), page=int(page), y_dest=y_dest))
        return entries

    def lines(self, page: int) -> list[Line]:
        """Líneas de la página física 1-based con texto, `y0`, `y1`, tamaño, fuente y negrita."""
        cached = self._cache.get(page)
        if cached is not None:
            return cached
        if page < 1 or page > self._doc.page_count:
            raise IngestError(ErrorCode.OUTLINE_UNAVAILABLE, "página fuera del documento", pagina=page)

        collected: list[Line] = []
        raw = self._doc[page - 1].get_text("dict")
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(str(span.get("text", "")) for span in spans)
                if not text.strip():
                    continue
                sizes = [float(span.get("size", 0.0)) for span in spans]
                font = str(spans[0].get("font", "")) if spans else ""
                collected.append(
                    Line(
                        text=text,
                        y0=round(float(line["bbox"][1]), 3),
                        y1=round(float(line["bbox"][3]), 3),
                        size=round(max(sizes), 3),
                        font=font,
                        bold="Bold" in font,
                    )
                )
        collected.sort(key=lambda item: item.y0)
        self._cache[page] = collected
        return collected
