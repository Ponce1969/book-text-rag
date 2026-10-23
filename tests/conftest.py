"""Dobles deterministas y generador de documentos sintéticos para la unidad 1.

Los dobles implementan los puertos de `ports.extraction` sin tocar el PDF real ni herramientas
externas, de modo que los ocho códigos de error y los invariantes se prueban de forma enfocada
(D-20 §5 y §4). El documento sintético respeta las reglas del corpus: páginas físicas ≥ 25,
encabezados en negrita, cuerpo de tamaño menor y el número impreso como última línea de cada página.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from book_text_rag.domain.models import Line, TocEntry

HEADING_Y0 = 100.0
HALF_INCH = 72.0
HEADING_SIZE = 20.0
BODY_SIZE = 12.0


@dataclass
class FakeTextExtractor:
    """Extractor de texto en memoria: devuelve páginas ya decodificadas."""

    pages_list: list[str]

    def pages(self) -> list[str]:
        return list(self.pages_list)

    def effective_config(self) -> tuple[str, str, str]:
        return ("pdftotext", "4.00", "-layout -enc UTF-8")


@dataclass
class FakeGeometry:
    """Proveedor de geometría en memoria: outline y líneas tipográficas por página."""

    toc_entries: list[TocEntry]
    page_lines: dict[int, list[Line]]
    tool_name: str = "PyMuPDF 0.0.0-fake"
    calls: list[int] = field(default_factory=list)

    def toc(self) -> list[TocEntry]:
        return list(self.toc_entries)

    def lines(self, page: int) -> list[Line]:
        self.calls.append(page)
        return list(self.page_lines.get(page, []))

    def tool(self) -> str:
        return self.tool_name


class DocumentBuilder:
    """Construye un documento sintético coherente entre texto y geometría."""

    def __init__(self) -> None:
        self.toc: list[TocEntry] = [
            TocEntry(level=1, title="Chapter 0. Contenedor", page=20, y_dest=0.0),
        ]
        self.geometry: dict[int, list[Line]] = {}
        self.text: dict[int, list[str]] = {}

    def add_unit(
        self,
        page: int,
        title: str,
        paragraphs: list[list[str]],
        *,
        y0: float = HEADING_Y0,
        level: int = 2,
        heading: bool = True,
        heading_text: str | None = None,
        table: list[str] | None = None,
    ) -> None:
        """Agrega una unidad en su propia página, con párrafos separados por línea en blanco."""
        rendered = heading_text if heading_text is not None else title
        toc_title = title
        self.toc.append(TocEntry(level=level, title=toc_title, page=page, y_dest=y0 - HALF_INCH))

        lines: list[Line] = []
        text_lines: list[str] = []
        lines.append(
            Line(
                text=rendered,
                y0=y0,
                y1=y0 + HEADING_SIZE,
                size=HEADING_SIZE,
                font="Fake-Bold",
                bold=heading,
            )
        )
        text_lines.append(rendered)
        cursor = y0 + 36.0
        for paragraph in paragraphs:
            for row in paragraph:
                lines.append(Line(text=row, y0=cursor, y1=cursor + BODY_SIZE, size=BODY_SIZE, font="Fake", bold=False))
                text_lines.append(row)
                cursor += 18.0
            text_lines.append("")
            cursor += 18.0
        if table:
            for row in table:
                lines.append(Line(text=row, y0=cursor, y1=cursor + BODY_SIZE, size=BODY_SIZE, font="Fake", bold=False))
                text_lines.append(row)
                cursor += 18.0
        text_lines.append(str(page - 1))
        lines.append(Line(text=str(page - 1), y0=740.0, y1=752.0, size=BODY_SIZE, font="Fake", bold=False))
        self.geometry[page] = lines
        self.text[page] = text_lines

    def build(self, last_page: int) -> tuple[FakeTextExtractor, FakeGeometry]:
        pages: list[str] = []
        for page in range(1, last_page + 1):
            pages.append("\n".join(self.text.get(page, [])))
        return FakeTextExtractor(pages_list=pages), FakeGeometry(toc_entries=self.toc, page_lines=self.geometry)


def two_unit_document() -> tuple[FakeTextExtractor, FakeGeometry]:
    """Documento de dos unidades y 22 páginas de relleno para satisfacer la calibración."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [[f"alpha body word {index}" for index in range(3)]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "Beta", [["beta", "content"]], table=["Table 1-1. Datos", "a  1", "b  2"])
    return builder.build(50)


def single_unit_with_tail() -> tuple[FakeTextExtractor, FakeGeometry]:
    """Unidad cuyo encabezado tiene texto por encima: la cola pertenece al predecesor."""
    builder = DocumentBuilder()
    builder.add_unit(25, "First", [["first", "paragraph"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "Second", [["second", "paragraph"]], y0=200.0)
    text, geometry = builder.build(50)
    geometry.page_lines[46] = [
        Line(text="tail words before the heading", y0=120.0, y1=132.0, size=BODY_SIZE, font="Fake", bold=False),
        *geometry.page_lines[46],
    ]
    text.pages_list[45] = "tail words before the heading\n" + text.pages_list[45]
    return text, geometry


@pytest.fixture
def two_units() -> tuple[FakeTextExtractor, FakeGeometry]:
    """Dos unidades de interés y veinte de relleno: supera el mínimo de calibración (D-17 §4.2)."""
    return two_unit_document()


@pytest.fixture
def unit_with_tail() -> tuple[FakeTextExtractor, FakeGeometry]:
    """Documento con cola previa al encabezado de la última unidad."""
    return single_unit_with_tail()
