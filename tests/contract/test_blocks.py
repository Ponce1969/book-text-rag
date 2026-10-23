"""Bloques de tabla, regiones excluidas y colas sin prosa (D-05 ptos. 5 y 6, D-18 §3 y §4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.application.ingest_persistent import ingest_persistent
from book_text_rag.domain.models import (
    AnchorLevel,
    BlockType,
    DestinationUse,
    ErrorCode,
    IngestError,
    IngestResult,
    TocEntry,
)
from tests.conftest import (
    BODY_SIZE,
    HEADING_SIZE,
    HEADING_Y0,
    DocumentBuilder,
    FakeGeometry,
    FakeTextExtractor,
    Line,
)


def _run(
    tmp_path: Path, text: FakeTextExtractor, geometry: FakeGeometry, *, end_page: int | None = None
) -> IngestResult:
    pdf = tmp_path / "sintetico.pdf"
    pdf.write_bytes(b"bytes sinteticos")
    return ingest_in_memory(
        pdf,
        "sintetico",
        text_extractor=text,
        geometry=geometry,
        corpus_start_page=25,
        corpus_end_page=end_page if end_page is not None else len(text.pages()) + 1,
    )


def _filled_document(last_page: int = 50) -> tuple[FakeTextExtractor, FakeGeometry]:
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler text"]])
    return builder.build(last_page)


def test_tabla_atomica_y_etiquetada(tmp_path: Path) -> None:
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler text"]])
    builder.add_unit(
        46,
        "Beta",
        [["prose before"]],
        table=["Table 3-2. Resumen", "clave  valor", "uno  1", "dos  2"],
    )
    text, geometry = builder.build(50)

    result = _run(tmp_path, text, geometry)
    tables = [f for f in result.fragments if f.block_type is BlockType.TABLE]
    assert len(tables) == 1
    table = tables[0]
    assert table.captions == ["Table 3-2. Resumen"]
    assert table.content.splitlines() == ["Table 3-2. Resumen", "clave  valor", "uno  1", "dos  2"]
    assert table.section_path[-1] == "Beta"

    prose = [f for f in result.fragments if f.section_path[-1] == "Beta" and f.block_type is BlockType.PROSE]
    assert len(prose) == 1
    assert "Table 3-2." not in prose[0].content


def test_regiones_excluidas(tmp_path: Path) -> None:
    text, geometry = _filled_document(last_page=730)
    text.pages_list[19] = "MATERIAL DE PORTADA"
    text.pages_list[729] = "MATERIAL DE CIERRE"
    # Frontera explícita 25..716, la del piloto: el material de la página 730 queda fuera del corpus.
    result = _run(tmp_path, text, geometry, end_page=717)
    for fragment in result.fragments:
        assert "MATERIAL DE PORTADA" not in fragment.content
        assert "MATERIAL DE CIERRE" not in fragment.content
    assert all(fragment.pdf_page_start is not None and fragment.pdf_page_start >= 25 for fragment in result.fragments)
    assert all(fragment.pdf_page_end is not None and fragment.pdf_page_end <= 716 for fragment in result.fragments)


def test_cola_sin_prosa_solo_rotulo(tmp_path: Path) -> None:
    """La cola puede ser sólo el rótulo de una figura: pertenece al predecesor (D-18 §4)."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler text"]])
    builder.add_unit(46, "WithFigure", [["body after figure"]], y0=200.0)
    text, geometry = builder.build(50)

    geometry.page_lines[46] = [
        Line(
            text="Figure 9-9. Un rótulo",
            y0=120.0,
            y1=120.0 + BODY_SIZE,
            size=BODY_SIZE,
            font="Fake",
            bold=False,
        ),
        *geometry.page_lines[46],
    ]
    page_lines = text.pages_list[45].split("\n")
    number = page_lines[-1]
    text.pages_list[45] = "\n".join(["Figure 9-9. Un rótulo", *page_lines[:-1], number])

    result = _run(tmp_path, text, geometry)
    predecessor = [f for f in result.fragments if f.section_path[-1] == "Filler 45"]
    successor = [f for f in result.fragments if f.section_path[-1] == "WithFigure"]
    assert any("Figure 9-9." in fragment.content for fragment in predecessor)
    assert all("Figure 9-9." not in fragment.content for fragment in successor)
    assert successor[0].content.splitlines()[0].strip() == "WithFigure"
    assert result.trace.counts.tail_words_total == 4


def test_encabezado_con_mismo_texto_en_cuerpo(tmp_path: Path) -> None:
    """La alineación es monótona: el encabezado no se confunde con una línea de cuerpo idéntica."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler text"]])
    builder.add_unit(46, "Beta", [["beta"]])
    text, geometry = builder.build(50)

    result = _run(tmp_path, text, geometry)
    beta = [f for f in result.fragments if f.section_path[-1] == "Beta"]
    assert beta
    lines = beta[0].content.splitlines()
    assert lines[0].strip() == "Beta"
    assert "beta" in [line.strip() for line in lines]
    assert HEADING_SIZE > BODY_SIZE


def _contar(ruta: Path, tabla: str) -> int:
    """Cuenta filas de una tabla del esquema vigente."""
    conexion = sqlite3.connect(ruta)
    try:
        fila = conexion.execute(f"SELECT count(*) FROM {tabla}").fetchone()
    finally:
        conexion.close()
    assert fila is not None
    return int(fila[0])


TABLAS_PERSISTIDAS = (
    "fuente",
    "referencia_fuente",
    "version_documento",
    "fragmento",
    "fragmento_fts",
    "construccion",
    "anclaje_cache",
)


def _editorial_document() -> tuple[FakeTextExtractor, FakeGeometry]:
    """Dos unidades con marcas de parte: prefijo desnudo y sufijo entre paréntesis."""
    builder = DocumentBuilder()
    builder.add_unit(
        25,
        "I. Foundations of Graph-Based Systems",
        [["alpha body"]],
        heading_text="Part I. Foundations of Graph-",
    )
    tail = Line(text="Based Systems", y0=118.0, y1=138.0, size=HEADING_SIZE, font="Fake-Bold", bold=True)
    builder.geometry[25].insert(1, tail)
    builder.text[25].insert(1, "Based Systems")
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "Beta (Part II)", [["beta content"]], heading_text="Part II. Beta")
    return builder.build(50)


def _mismatched_part_document() -> tuple[FakeTextExtractor, FakeGeometry]:
    """Unidad cuyo título y encabezado declaran números de parte distintos."""
    builder = DocumentBuilder()
    builder.add_unit(25, "I. Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "II. Beta", [["beta"]], heading_text="Part III. Beta")
    return builder.build(50)


def _cross_page_document() -> tuple[FakeTextExtractor, FakeGeometry]:
    """El título solo existe como encabezado en la página siguiente."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]], heading_text="Otro encabezado")
    for page in range(26, 51):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.geometry[26][0] = Line(
        text="Alpha", y0=HEADING_Y0, y1=HEADING_Y0 + HEADING_SIZE, size=HEADING_SIZE, font="Fake-Bold", bold=True
    )
    builder.text[26][0] = "Alpha"
    return builder.build(50)


def test_variantes_editoriales_anclan_en_el_bloque_correcto(tmp_path: Path) -> None:
    """La marca de parte y el guion de corte no impiden anclar el encabezado real."""
    text, geometry = _editorial_document()

    result = _run(tmp_path, text, geometry)
    inicial = next(f for f in result.fragments if f.section_path[-1] == "I. Foundations of Graph-Based Systems")
    assert inicial.anchor_level is AnchorLevel.POSITIONAL
    assert inicial.anchor_evidence.page == 25
    assert inicial.anchor_evidence.y0 == HEADING_Y0
    assert inicial.anchor_evidence.destination_use is DestinationUse.VALID
    assert inicial.content.splitlines()[0].strip() == "Part I. Foundations of Graph-"

    final = next(f for f in result.fragments if f.section_path[-1] == "Beta (Part II)")
    assert final.anchor_level is AnchorLevel.POSITIONAL
    assert final.anchor_evidence.page == 46
    assert final.content.splitlines()[0].strip() == "Part II. Beta"


def test_parte_no_coincidente_falla_antes_de_t1_y_no_persiste(tmp_path: Path) -> None:
    """Una marca de parte distinta no ancla y la ingesta no deja estado parcial."""
    text, geometry = _mismatched_part_document()
    pdf = tmp_path / "sintetico.pdf"
    pdf.write_bytes(b"bytes sinteticos")
    ruta = tmp_path / "almacen.sqlite"
    SqliteStore(ruta).initialize()

    with pytest.raises(IngestError) as info:
        ingest_persistent(
            pdf,
            "sintetico",
            "alias",
            fecha="2026-10-20",
            store=SqliteStore(ruta),
            text_extractor=text,
            geometry=geometry,
            corpus_start_page=25,
            corpus_end_page=len(text.pages()) + 1,
        )

    assert info.value.code is ErrorCode.UNIT_NOT_ANCHORED
    for tabla in TABLAS_PERSISTIDAS:
        assert _contar(ruta, tabla) == 0


def test_no_busca_el_encabezado_en_la_pagina_siguiente(tmp_path: Path) -> None:
    """El anclaje sigue limitado a la página declarada: no toma el encabezado de la siguiente."""
    text, geometry = _cross_page_document()

    with pytest.raises(IngestError) as info:
        _run(tmp_path, text, geometry)

    assert info.value.code is ErrorCode.UNIT_NOT_ANCHORED


def _append_line(
    builder: DocumentBuilder,
    page: int,
    text: str,
    *,
    y0: float,
    bold: bool = False,
    size: float = BODY_SIZE,
) -> None:
    """Agrega una línea tipográfica y su texto extraído a una página del documento sintético."""
    builder.geometry.setdefault(page, []).append(
        Line(text=text, y0=y0, y1=y0 + size, size=size, font="Fake-Bold" if bold else "Fake", bold=bold)
    )
    builder.text.setdefault(page, []).append(text)


def _move_heading_to_next_page(builder: DocumentBuilder, page: int, *, y0: float = HEADING_Y0) -> None:
    """Simula un destino con una página de atraso: el encabezado real vive en `page + 1`."""
    heading = builder.geometry[page].pop(0)
    builder.text[page].pop(0)
    moved = Line(text=heading.text, y0=y0, y1=y0 + HEADING_SIZE, size=heading.size, font=heading.font, bold=True)
    builder.geometry.setdefault(page + 1, []).insert(0, moved)
    builder.text.setdefault(page + 1, []).insert(0, heading.text)


def _shifted_document() -> tuple[FakeTextExtractor, FakeGeometry]:
    """Unidad declarada en 46 con su encabezado real en 47 y cuerpo en ambas páginas."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "I. Shifted", [["body on declared page"]], heading_text="Part I. Shifted")
    _move_heading_to_next_page(builder, 46)
    _append_line(builder, 47, "shifted body", y0=136.0)
    builder.add_unit(48, "Beta", [["beta body"]])
    builder.add_unit(49, "Gamma", [["gamma body"]])
    return builder.build(50)


def test_fallback_de_pagina_ancla_y_conserva_los_limites_entre_unidades(tmp_path: Path) -> None:
    """La unidad desplazada empieza en la página real; anterior y siguiente no se pisan."""
    text, geometry = _shifted_document()

    result = _run(tmp_path, text, geometry)
    previo = next(f for f in result.fragments if f.section_path[-1] == "Filler 45")
    desplazado = next(f for f in result.fragments if f.section_path[-1] == "I. Shifted")
    siguiente = next(f for f in result.fragments if f.section_path[-1] == "Beta")

    assert previo.pdf_page_start == 45
    assert previo.pdf_page_end == 46
    assert "body on declared page" in previo.content
    assert "Part I. Shifted" not in previo.content
    assert "shifted body" not in previo.content

    assert desplazado.anchor_level is AnchorLevel.PAGE_TYPOGRAPHY
    assert desplazado.anchor_evidence.page == 47
    assert desplazado.anchor_evidence.y0 == HEADING_Y0
    assert desplazado.anchor_evidence.y_dest is None
    assert desplazado.anchor_evidence.destination_use is DestinationUse.UNUSABLE
    assert desplazado.pdf_page_start == 47
    assert desplazado.pdf_page_end == 47
    assert desplazado.content.splitlines()[0].strip() == "Part I. Shifted"
    assert "shifted body" in desplazado.content
    assert "body on declared page" not in desplazado.content
    assert "beta body" not in desplazado.content

    assert siguiente.pdf_page_start == 48
    assert siguiente.pdf_page_end == 48
    assert "beta body" in siguiente.content
    assert "shifted body" not in siguiente.content

    gamma = next(f for f in result.fragments if f.section_path[-1] == "Gamma")
    assert gamma.pdf_page_start == 49

    todo = "\n".join(fragment.content for fragment in result.fragments)
    assert todo.count("body on declared page") == 1
    assert todo.count("shifted body") == 1
    assert todo.count("beta body") == 1
    assert todo.count("gamma body") == 1


def test_fallback_persistido_verifica_y_registra_la_evidencia(tmp_path: Path) -> None:
    """El almacén conserva página real, `y_dest` nulo y destino inutilizable; `verify` da ok."""
    text, geometry = _shifted_document()
    pdf = tmp_path / "sintetico.pdf"
    pdf.write_bytes(b"bytes sinteticos")
    ruta = tmp_path / "almacen.sqlite"
    store = SqliteStore(ruta)
    store.initialize()

    resultado, _ = ingest_persistent(
        pdf,
        "sintetico",
        "alias",
        fecha="2026-10-20",
        store=store,
        text_extractor=text,
        geometry=geometry,
        corpus_start_page=25,
        corpus_end_page=len(text.pages()) + 1,
    )
    desplazado = next(f for f in resultado.fragments if f.section_path[-1] == "I. Shifted")
    assert store.verify_version("sintetico", resultado.trace.document_version).ok is True

    conexion = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    try:
        fila = conexion.execute(
            "SELECT page, y0, y_dest, destination_use FROM anclaje_cache WHERE ordinal = ?",
            (desplazado.ordinal,),
        ).fetchone()
    finally:
        conexion.close()
    assert fila == (47, HEADING_Y0, None, "unusable")


def test_fallback_no_se_activa_si_la_pagina_declarada_tiene_candidato(tmp_path: Path) -> None:
    """Con candidato en la página declarada, el anclaje no se desplaza aunque el título se repita."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "I. Shifted", [["declared body"]], heading_text="Part I. Shifted")
    _append_line(builder, 47, "Part I. Shifted", y0=HEADING_Y0, bold=True, size=HEADING_SIZE)
    builder.add_unit(48, "Beta", [["beta body"]])
    builder.add_unit(49, "Gamma", [["gamma body"]])
    text, geometry = builder.build(50)

    result = _run(tmp_path, text, geometry)
    desplazado = next(f for f in result.fragments if f.section_path[-1] == "I. Shifted")
    assert desplazado.anchor_evidence.page == 46
    assert desplazado.pdf_page_start == 46


def _shifted_ambiguous_document() -> tuple[FakeTextExtractor, FakeGeometry]:
    """Dos encabezados exactos en la página siguiente: ambigüedad."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "I. Shifted", [["declared body"]], heading_text="Part I. Shifted")
    _move_heading_to_next_page(builder, 46)
    _append_line(builder, 47, "Part I. Shifted", y0=160.0, bold=True, size=HEADING_SIZE)
    builder.add_unit(48, "Beta", [["beta body"]])
    builder.add_unit(49, "Gamma", [["gamma body"]])
    return builder.build(50)


def test_fallback_ambiguo_falla_sin_persistir(tmp_path: Path) -> None:
    """Dos encabezados exactos en la página siguiente: rechazo explícito y almacén vacío."""
    text, geometry = _shifted_ambiguous_document()
    pdf = tmp_path / "sintetico.pdf"
    pdf.write_bytes(b"bytes sinteticos")
    ruta = tmp_path / "almacen.sqlite"
    SqliteStore(ruta).initialize()

    with pytest.raises(IngestError) as info:
        ingest_persistent(
            pdf,
            "sintetico",
            "alias",
            fecha="2026-10-20",
            store=SqliteStore(ruta),
            text_extractor=text,
            geometry=geometry,
            corpus_start_page=25,
            corpus_end_page=len(text.pages()) + 1,
        )

    assert info.value.code is ErrorCode.UNIT_NOT_ANCHORED
    for tabla in TABLAS_PERSISTIDAS:
        assert _contar(ruta, tabla) == 0


def _shifted_below_band_document() -> tuple[FakeTextExtractor, FakeGeometry]:
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "I. Shifted", [["declared body"]], heading_text="Part I. Shifted")
    _move_heading_to_next_page(builder, 46, y0=300.0)
    builder.add_unit(48, "Beta", [["beta body"]])
    builder.add_unit(49, "Gamma", [["gamma body"]])
    return builder.build(50)


def _shifted_part_mismatch_document() -> tuple[FakeTextExtractor, FakeGeometry]:
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "II. Beta", [["declared body"]], heading_text="Part III. Beta")
    _move_heading_to_next_page(builder, 46)
    builder.add_unit(48, "Gamma", [["gamma body"]])
    builder.add_unit(49, "Delta", [["delta body"]])
    return builder.build(50)


def _shifted_weak_prefix_document() -> tuple[FakeTextExtractor, FakeGeometry]:
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(
        46,
        "I. Foundations of Graph-Based Systems",
        [["declared body"]],
        heading_text="Part I. Foundations of Graph-Based Systems",
    )
    _move_heading_to_next_page(builder, 46)
    builder.geometry[47][0] = Line(
        text="Part I. Foundations of Vector-Based Systems",
        y0=HEADING_Y0,
        y1=HEADING_Y0 + HEADING_SIZE,
        size=HEADING_SIZE,
        font="Fake-Bold",
        bold=True,
    )
    builder.text[47][0] = "Part I. Foundations of Vector-Based Systems"
    builder.add_unit(48, "Beta", [["beta body"]])
    builder.add_unit(49, "Gamma", [["gamma body"]])
    return builder.build(50)


@pytest.mark.parametrize(
    "documento",
    [
        _shifted_below_band_document,
        _shifted_part_mismatch_document,
        _shifted_weak_prefix_document,
    ],
)
def test_fallback_con_candidato_no_valido_se_rechaza(tmp_path: Path, documento) -> None:
    """Fuera de banda, parte distinta o coincidencia débil: no hay anclaje en la página siguiente."""
    text, geometry = documento()

    with pytest.raises(IngestError) as info:
        _run(tmp_path, text, geometry)

    assert info.value.code is ErrorCode.UNIT_NOT_ANCHORED


def test_fallback_no_toma_la_unidad_siguiente(tmp_path: Path) -> None:
    """Si la unidad siguiente empieza en `page + 1`, su encabezado no se usa como fallback."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "I. Shifted", [["declared body"]], heading_text="Not the heading")
    builder.add_unit(47, "Filler 47", [["filler 47 body"]], heading_text="Part I. Shifted")
    builder.add_unit(48, "Beta", [["beta body"]])
    text, geometry = builder.build(50)

    with pytest.raises(IngestError) as info:
        _run(tmp_path, text, geometry)

    assert info.value.code is ErrorCode.UNIT_NOT_ANCHORED
    assert info.value.details["titulo"] == "I. Shifted"


def test_fallback_no_sale_de_la_ultima_pagina(tmp_path: Path) -> None:
    """En la última página no hay `page + 1`: el fallback no se evalúa."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 50):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(50, "Last", [["last body"]], heading_text="Nothing")
    text, geometry = builder.build(50)

    with pytest.raises(IngestError) as info:
        _run(tmp_path, text, geometry)

    assert info.value.code is ErrorCode.UNIT_NOT_ANCHORED
    assert info.value.details["titulo"] == "Last"


def test_fallback_con_dos_unidades_desplazadas_conserva_los_limites(tmp_path: Path) -> None:
    """Dos desplazamientos consecutivos: el fin de cada tramo usa la página real de la siguiente."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "I. One", [["body one declared"]], heading_text="Part I. One")
    _move_heading_to_next_page(builder, 46)
    _append_line(builder, 47, "body one real", y0=136.0)
    builder.add_unit(48, "II. Two", [["body two declared"]], heading_text="Part II. Two")
    _move_heading_to_next_page(builder, 48)
    _append_line(builder, 49, "body two real", y0=136.0)
    builder.add_unit(50, "Three", [["body three"]])
    text, geometry = builder.build(52)

    result = _run(tmp_path, text, geometry)
    uno = next(f for f in result.fragments if f.section_path[-1] == "I. One")
    dos = next(f for f in result.fragments if f.section_path[-1] == "II. Two")
    tres = next(f for f in result.fragments if f.section_path[-1] == "Three")

    assert uno.pdf_page_start == 47
    assert uno.pdf_page_end == 48
    assert "body one real" in uno.content
    assert "body one declared" not in uno.content
    assert "body two declared" in uno.content
    assert "body two real" not in uno.content

    assert dos.pdf_page_start == 49
    assert dos.pdf_page_end == 49
    assert "body two real" in dos.content
    assert "body two declared" not in dos.content
    assert "body three" not in dos.content

    assert tres.pdf_page_start == 50
    assert "body three" in tres.content

    todo = "\n".join(fragment.content for fragment in result.fragments)
    for marca in ("body one declared", "body one real", "body two declared", "body two real", "body three"):
        assert todo.count(marca) == 1


def _window_document(
    *,
    extra_heading: bool = False,
    heading_text: str = "Agents as Tools: A Powerful Pattern",
    dest_offset: float = 50.95,
) -> tuple[FakeTextExtractor, FakeGeometry]:
    """Dos unidades en la misma página: la segunda con destino inutilizable bajo la banda."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "Top Section", [["top body"]], y0=72.0)
    footer = builder.geometry[46].pop()
    footer_text = builder.text[46].pop()
    builder.toc.append(
        TocEntry(
            level=3,
            title="Agents as Tools: A Powerful Pattern",
            page=46,
            y_dest=386.3 + dest_offset,
        )
    )
    _append_line(builder, 46, heading_text, y0=386.3, bold=True, size=HEADING_SIZE)
    if extra_heading:
        _append_line(builder, 46, "separator line", y0=404.0)
        _append_line(builder, 46, "Agents as Tools: A Powerful Pattern", y0=420.0, bold=True, size=HEADING_SIZE)
    _append_line(builder, 46, "window body", y0=430.0)
    builder.geometry[46].append(footer)
    builder.text[46].append(footer_text)
    builder.add_unit(47, "Upper Outlier", [["upper body"]], y0=150.0)
    outlier = builder.toc[-1]
    builder.toc[-1] = TocEntry(level=outlier.level, title=outlier.title, page=outlier.page, y_dest=100.0)
    builder.add_unit(48, "Beta", [["beta body"]])
    return builder.build(50)


def test_ventana_local_ancla_fuera_de_banda_y_conserva_los_limites(tmp_path: Path) -> None:
    """La segunda unidad de la página ancla con ventana local; la anterior termina en su encabezado."""
    text, geometry = _window_document()

    result = _run(tmp_path, text, geometry)
    superior = next(f for f in result.fragments if f.section_path[-1] == "Top Section")
    ventana = next(f for f in result.fragments if f.section_path[-1] == "Agents as Tools: A Powerful Pattern")
    outlier = next(f for f in result.fragments if f.section_path[-1] == "Upper Outlier")
    beta = next(f for f in result.fragments if f.section_path[-1] == "Beta")

    assert superior.pdf_page_start == 46
    assert superior.pdf_page_end == 46
    assert "top body" in superior.content
    assert "Agents as Tools: A Powerful Pattern" not in superior.content

    assert ventana.anchor_level is AnchorLevel.PAGE_TYPOGRAPHY
    assert ventana.anchor_evidence.page == 46
    assert ventana.anchor_evidence.y0 == 386.3
    assert ventana.anchor_evidence.y_dest is None
    assert ventana.anchor_evidence.destination_use is DestinationUse.UNUSABLE
    assert ventana.pdf_page_start == 46
    assert ventana.pdf_page_end == 46
    assert ventana.content.splitlines()[0].strip() == "Agents as Tools: A Powerful Pattern"
    assert "window body" in ventana.content
    assert "top body" not in ventana.content
    assert "upper body" not in ventana.content

    assert outlier.pdf_page_start == 47
    assert "upper body" in outlier.content
    assert beta.pdf_page_start == 48

    todo = "\n".join(fragment.content for fragment in result.fragments)
    for marca in ("top body", "window body", "upper body", "beta body"):
        assert todo.count(marca) == 1


def test_ventana_local_persistida_verifica_y_registra_evidencia(tmp_path: Path) -> None:
    """La evidencia persistida conserva página, y0, destino nulo y uso inutilizable."""
    text, geometry = _window_document()
    pdf = tmp_path / "sintetico.pdf"
    pdf.write_bytes(b"bytes sinteticos")
    ruta = tmp_path / "almacen.sqlite"
    store = SqliteStore(ruta)
    store.initialize()

    resultado, _ = ingest_persistent(
        pdf,
        "sintetico",
        "alias",
        fecha="2026-10-20",
        store=store,
        text_extractor=text,
        geometry=geometry,
        corpus_start_page=25,
        corpus_end_page=len(text.pages()) + 1,
    )
    ventana = next(f for f in resultado.fragments if f.section_path[-1] == "Agents as Tools: A Powerful Pattern")
    assert store.verify_version("sintetico", resultado.trace.document_version).ok is True

    conexion = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    try:
        fila = conexion.execute(
            "SELECT page, y0, y_dest, destination_use FROM anclaje_cache WHERE ordinal = ?",
            (ventana.ordinal,),
        ).fetchone()
    finally:
        conexion.close()
    assert fila == (46, 386.3, None, "unusable")


def test_ventana_local_ambigua_falla_sin_persistir(tmp_path: Path) -> None:
    """Dos coincidencias fuertes en la ventana: rechazo explícito y almacén vacío."""
    text, geometry = _window_document(extra_heading=True)
    pdf = tmp_path / "sintetico.pdf"
    pdf.write_bytes(b"bytes sinteticos")
    ruta = tmp_path / "almacen.sqlite"
    SqliteStore(ruta).initialize()

    with pytest.raises(IngestError) as info:
        ingest_persistent(
            pdf,
            "sintetico",
            "alias",
            fecha="2026-10-20",
            store=SqliteStore(ruta),
            text_extractor=text,
            geometry=geometry,
            corpus_start_page=25,
            corpus_end_page=len(text.pages()) + 1,
        )

    assert info.value.code is ErrorCode.UNIT_NOT_ANCHORED
    for tabla in TABLAS_PERSISTIDAS:
        assert _contar(ruta, tabla) == 0


def test_ventana_local_rechaza_divergencia_semantica(tmp_path: Path) -> None:
    """Compartir las primeras cuatro palabras no basta: la divergencia posterior se rechaza."""
    text, geometry = _window_document(heading_text="Agents as Tools: A Very Different Pattern")

    with pytest.raises(IngestError) as info:
        _run(tmp_path, text, geometry)

    assert info.value.code is ErrorCode.UNIT_NOT_ANCHORED


def test_ventana_local_rechaza_distancia_mayor_a_120(tmp_path: Path) -> None:
    """Un destino a 120.01 pt del encabezado queda fuera de la ventana local."""
    text, geometry = _window_document(dest_offset=120.01)

    with pytest.raises(IngestError) as info:
        _run(tmp_path, text, geometry)

    assert info.value.code is ErrorCode.UNIT_NOT_ANCHORED


def _preamble_document() -> tuple[FakeTextExtractor, FakeGeometry]:
    """Unidad superior cuyo encabezado no está en el índice 0 de la página."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler", "text"]])
    builder.add_unit(46, "Top Section", [["top body"]], y0=200.0)
    footer = builder.geometry[46].pop()
    footer_text = builder.text[46].pop()
    builder.geometry[46].insert(
        0, Line(text="preamble line", y0=40.0, y1=52.0, size=BODY_SIZE, font="Fake", bold=False)
    )
    builder.text[46].insert(0, "preamble line")
    builder.toc.append(TocEntry(level=3, title="Second Section", page=46, y_dest=464.0))
    _append_line(builder, 46, "Second Section", y0=500.0, bold=True, size=HEADING_SIZE)
    _append_line(builder, 46, "second body", y0=536.0)
    builder.geometry[46].append(footer)
    builder.text[46].append(footer_text)
    builder.add_unit(47, "Beta", [["beta body"]])
    return builder.build(50)


def test_corte_de_misma_pagina_no_duplica_la_unidad_siguiente(tmp_path: Path) -> None:
    """Con índice inicial no nulo, el tramo anterior termina antes del encabezado siguiente."""
    text, geometry = _preamble_document()

    result = _run(tmp_path, text, geometry)
    superior = next(f for f in result.fragments if f.section_path[-1] == "Top Section")
    siguiente = next(f for f in result.fragments if f.section_path[-1] == "Second Section")

    assert superior.content.splitlines()[0].strip() == "Top Section"
    assert "top body" in superior.content
    assert "Second Section" not in superior.content
    assert "second body" not in superior.content

    assert siguiente.content.splitlines()[0].strip() == "Second Section"
    assert "second body" in siguiente.content
    assert "top body" not in siguiente.content

    todo = "\n".join(fragment.content for fragment in result.fragments)
    for marca in ("preamble line", "top body", "second body"):
        assert todo.count(marca) == 1
