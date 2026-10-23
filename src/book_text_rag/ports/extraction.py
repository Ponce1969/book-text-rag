"""Puertos del camino de ingesta (D-20 §2; `001` §4: puertos en el núcleo).

Son `Protocol`s inyectables: permiten probar los ocho códigos de error con dobles deterministas,
sin depender del PDF ni de las herramientas externas.
"""

from __future__ import annotations

from typing import Protocol

from book_text_rag.domain.models import Line, TocEntry


class TextExtractor(Protocol):
    """Extractor de texto aprobado (D-19 §1): una cadena por página, en orden físico."""

    def pages(self) -> list[str]:
        """Páginas del PDF ya decodificadas en UTF-8 estricto, separadas por salto de página."""
        ...

    def effective_config(self) -> tuple[str, str, str]:
        """`(nombre, versión, flags)` de la configuración **efectiva** observada (D-19 §1.3)."""
        ...


class GeometryProvider(Protocol):
    """Herramienta autorizada para outline, tipografía y coordenadas (decisión del propietario)."""

    def toc(self) -> list[TocEntry]:
        """Entradas del outline: nivel, título, página física y coordenada del destino si existe."""
        ...

    def lines(self, page: int) -> list[Line]:
        """Líneas de la página física 1-based con su tipografía y su coordenada vertical."""
        ...

    def tool(self) -> str:
        """Identificación de la herramienta y su versión, para el manifiesto y la traza."""
        ...
