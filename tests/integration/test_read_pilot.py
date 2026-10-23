"""Lectura, verificación y consulta léxica sobre el piloto persistido (incremento 3).

Un almacén **temporal** por prueba y **una** extracción del piloto por módulo. Comprueba el round-trip
de los 583 fragmentos, los invariantes de `D-22` §5, la detección de alteraciones **sin reparación**, la
consulta léxica interna y que todo el camino de lectura deja el archivo intacto.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from book_text_rag.adapters.extraction.geometry import PyMuPdfGeometry
from book_text_rag.adapters.extraction.pdftotext import PdftotextExtractor
from book_text_rag.adapters.storage import sqlite_write as sqlite_write_module
from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.application.ingest_persistent import persist_unit
from book_text_rag.ports.storage import (
    NO_VERIFICADO,
    EstadoIngesta,
    FragmentRead,
    StoreError,
    StoreErrorCode,
    UnitWrite,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT = REPO_ROOT / "data" / "Ingeniería de IA - Chip Huyen (EN).pdf"
DOCUMENT_ID = "huyen-ai-engineering"
ALIAS = "huyen"
FECHA = "2026-10-18"
FRAGMENTOS_ESPERADOS = 583

pytestmark = pytest.mark.skipif(not PILOT.exists(), reason="falta el PDF piloto en data/")


@pytest.fixture(scope="module")
def unidad() -> UnitWrite:
    resultado = ingest_in_memory(
        PILOT, DOCUMENT_ID, text_extractor=PdftotextExtractor(PILOT), geometry=PyMuPdfGeometry(PILOT)
    )
    return UnitWrite(
        document_id=DOCUMENT_ID,
        alias=ALIAS,
        fecha=FECHA,
        fragments=tuple(resultado.fragments),
        trace=resultado.trace,
        source_format="pdf",
        page_count=784,
    )


@pytest.fixture
def almacen(tmp_path: Path, unidad: UnitWrite) -> Path:
    ruta = tmp_path / "almacen.sqlite"
    SqliteStore(ruta).initialize()
    persist_unit(unidad, store=SqliteStore(ruta))
    return ruta


def _version(unidad: UnitWrite) -> str:
    return unidad.trace.document_version


def _proyeccion(unidad: UnitWrite) -> tuple[FragmentRead, ...]:
    """Campos persistidos de la unidad, en la forma en que el lector debe devolverlos."""
    return tuple(
        FragmentRead(
            ordinal=fragmento.ordinal,
            chunk_id=fragmento.chunk_id,
            section_path=tuple(fragmento.section_path),
            level=fragmento.level,
            block_type=fragmento.block_type,
            captions=tuple(fragmento.captions),
            pdf_page_start=fragmento.pdf_page_start,
            pdf_page_end=fragmento.pdf_page_end,
            content=fragmento.content,
            content_hash=fragmento.content_hash,
            anchor_level=fragmento.anchor_level,
        )
        for fragmento in unidad.fragments
    )


def _ejecutar(ruta: Path, sentencias: tuple[str, ...]) -> None:
    conexion = sqlite3.connect(ruta)
    try:
        for sql in sentencias:
            conexion.execute(sql)
        conexion.commit()
    finally:
        conexion.close()


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _contar(ruta: Path, tabla: str) -> int:
    conexion = sqlite3.connect(ruta)
    try:
        fila = conexion.execute(f"SELECT count(*) FROM {tabla}").fetchone()
    finally:
        conexion.close()
    assert fila is not None
    return int(fila[0])


def _laterales(ruta: Path) -> list[str]:
    return sorted(p.name for p in ruta.parent.glob(f"{ruta.name}-*"))


def test_round_trip_de_los_583_fragmentos(almacen: Path, unidad: UnitWrite) -> None:
    leido = SqliteStore(almacen).read_version(DOCUMENT_ID, _version(unidad))
    assert len(leido.fragments) == FRAGMENTOS_ESPERADOS
    assert [fragmento.ordinal for fragmento in leido.fragments] == list(range(1, FRAGMENTOS_ESPERADOS + 1))
    assert leido.fragments == _proyeccion(unidad)
    assert leido.estados == (EstadoIngesta.COMPLETADA,)
    assert leido.source_format == "pdf"
    assert leido.page_count == 784


def test_verificacion_del_piloto_recien_persistido(almacen: Path, unidad: UnitWrite) -> None:
    verificacion = SqliteStore(almacen).verify_version(DOCUMENT_ID, _version(unidad))
    assert verificacion.fragmentos == FRAGMENTOS_ESPERADOS
    assert verificacion.ordinales_ok is True
    assert verificacion.content_hash_ok is True
    assert verificacion.chunk_id_ok is True
    assert verificacion.fts5_ok is True
    assert verificacion.estado_ok is True
    assert verificacion.traza_presente is True
    assert verificacion.fuente_presente is True
    assert verificacion.ok is True
    assert verificacion.no_verificado == NO_VERIFICADO
    assert set(verificacion.no_verificado) == {
        "traza_insumos",
        "index_version",
        "reconstruccion_indice",
        "consultabilidad_indice",
    }


def test_busqueda_lexica_encuentra_y_no_inventa(almacen: Path, unidad: UnitWrite) -> None:
    almacen_obj = SqliteStore(almacen)
    fragmento = unidad.fragments[10]
    tokens = [token for token in fragmento.content.split() if len(token) >= 10 and token.isalpha()]
    assert tokens, "el fragmento elegido no tiene un token distintivo"
    aciertos = almacen_obj.search_lexical(tokens[0].lower(), limit=5)
    assert aciertos
    assert fragmento.ordinal in {acierto.ordinal for acierto in aciertos}
    assert fragmento.chunk_id in {acierto.chunk_id for acierto in aciertos}
    assert all(acierto.document_id == DOCUMENT_ID for acierto in aciertos)
    assert almacen_obj.search_lexical("zzzzqqqqxxxx") == ()


def test_busqueda_lexica_acotada_por_documento(almacen: Path, unidad: UnitWrite) -> None:
    almacen_obj = SqliteStore(almacen)
    token = next(token for fragmento in unidad.fragments for token in fragmento.content.split() if len(token) >= 12)
    acotado = almacen_obj.search_lexical(token.lower(), document_id=DOCUMENT_ID, limit=3)
    assert len(acotado) <= 3
    assert all(acierto.document_id == DOCUMENT_ID for acierto in acotado)
    assert almacen_obj.search_lexical(token.lower(), document_id="otro-documento") == ()


def test_lectura_verificacion_y_busqueda_no_alteran_el_almacen(almacen: Path, unidad: UnitWrite) -> None:
    antes = _huella(almacen)
    almacen_obj = SqliteStore(almacen)
    almacen_obj.read_version(DOCUMENT_ID, _version(unidad))
    almacen_obj.verify_version(DOCUMENT_ID, _version(unidad))
    almacen_obj.search_lexical("multimodal", limit=5)
    assert _huella(almacen) == antes
    assert _laterales(almacen) == []


def test_contenido_alterado_se_detecta_y_no_se_repara(almacen: Path, unidad: UnitWrite) -> None:
    _ejecutar(almacen, ("UPDATE fragmento SET content = 'alterado' WHERE ordinal = 1",))
    almacen_obj = SqliteStore(almacen)
    verificacion = almacen_obj.verify_version(DOCUMENT_ID, _version(unidad))
    assert verificacion.content_hash_ok is False
    assert verificacion.ok is False
    assert verificacion.fragmentos == FRAGMENTOS_ESPERADOS
    leido = almacen_obj.read_version(DOCUMENT_ID, _version(unidad))
    assert leido.fragments[0].content == "alterado"


def test_ordinal_faltante_se_detecta(almacen: Path, unidad: UnitWrite) -> None:
    _ejecutar(almacen, ("DELETE FROM fragmento WHERE ordinal = 2",))
    verificacion = SqliteStore(almacen).verify_version(DOCUMENT_ID, _version(unidad))
    assert verificacion.ordinales_ok is False
    assert verificacion.ok is False
    assert verificacion.fragmentos == FRAGMENTOS_ESPERADOS - 1


def test_indice_lexico_incoherente_se_detecta(almacen: Path, unidad: UnitWrite) -> None:
    _ejecutar(almacen, ("DELETE FROM fragmento_fts WHERE ordinal = 5",))
    verificacion = SqliteStore(almacen).verify_version(DOCUMENT_ID, _version(unidad))
    assert verificacion.fts5_ok is False
    assert verificacion.ok is False
    assert verificacion.ordinales_ok is True
    assert verificacion.content_hash_ok is True


def test_estado_no_completado_con_fragmentos_se_detecta(almacen: Path, unidad: UnitWrite) -> None:
    _ejecutar(almacen, (f"UPDATE referencia_fuente SET estado_ingesta = '{EstadoIngesta.INCOMPLETA.value}'",))
    almacen_obj = SqliteStore(almacen)
    verificacion = almacen_obj.verify_version(DOCUMENT_ID, _version(unidad))
    assert verificacion.estado_ok is False
    assert verificacion.ok is False
    assert almacen_obj.read_version(DOCUMENT_ID, _version(unidad)).estados == (EstadoIngesta.INCOMPLETA,)


def test_fallo_en_t3_deja_la_version_no_legible(
    tmp_path: Path, unidad: UnitWrite, monkeypatch: pytest.MonkeyPatch
) -> None:
    ruta = tmp_path / "parcial.sqlite"
    almacen_obj = SqliteStore(ruta)
    almacen_obj.initialize()

    def fallar(conexion: sqlite3.Connection, unit: UnitWrite, fragmento: object) -> None:
        raise StoreError(StoreErrorCode.ERROR_SQLITE, "fallo inyectado en T3")

    monkeypatch.setattr(sqlite_write_module, "_insertar_fts", fallar)
    with pytest.raises(StoreError):
        persist_unit(unidad, store=almacen_obj)
    monkeypatch.undo()

    with pytest.raises(StoreError) as info:
        almacen_obj.read_version(DOCUMENT_ID, _version(unidad))
    assert info.value.code is StoreErrorCode.VERSION_NO_ENCONTRADA
    with pytest.raises(StoreError) as info_verify:
        almacen_obj.verify_version(DOCUMENT_ID, _version(unidad))
    assert info_verify.value.code is StoreErrorCode.VERSION_NO_ENCONTRADA
    assert _laterales(ruta) == []


def test_fuente_ausente_se_detecta_y_no_se_repara(almacen: Path, unidad: UnitWrite) -> None:
    """Integridad referencial `VERSION_DOCUMENTO → FUENTE`: falta la fuente de una versión registrada.

    La lectura **no** lo convierte en «versión inexistente»: sigue devolviendo la autoridad. La
    verificación lo refleja con `fuente_presente=False` y deja `ok` en `False`, sin reparar nada.
    """
    _ejecutar(almacen, (f"DELETE FROM fuente WHERE document_id = '{DOCUMENT_ID}'",))
    antes = _huella(almacen)
    almacen_obj = SqliteStore(almacen)
    leido = almacen_obj.read_version(DOCUMENT_ID, _version(unidad))
    assert len(leido.fragments) == FRAGMENTOS_ESPERADOS
    assert leido.source_format is None
    verificacion = almacen_obj.verify_version(DOCUMENT_ID, _version(unidad))
    assert verificacion.fuente_presente is False
    assert verificacion.ok is False
    assert verificacion.ordinales_ok is True
    assert verificacion.content_hash_ok is True
    assert verificacion.traza_presente is True
    assert _huella(almacen) == antes
    assert _laterales(almacen) == []
    assert _contar(almacen, "fuente") == 0


def test_indice_invertido_danado_escapa_a_fts5_ok(almacen: Path, unidad: UnitWrite) -> None:
    """`fts5_ok` comprueba recuento y `content` almacenado: **no** la coherencia del índice invertido.

    Con el índice invertido dañado el fragmento deja de ser recuperable y, aun así, la verificación
    sigue diciendo `fts5_ok=True` y `ok=True`. Es la limitación declarada en `consultabilidad_indice`;
    el incremento **no** repara ni reconstruye el índice.
    """
    almacen_obj = SqliteStore(almacen)
    token = next(token for fragmento in unidad.fragments for token in fragmento.content.split() if len(token) >= 12)
    antes = {acierto.ordinal for acierto in almacen_obj.search_lexical(token.lower(), limit=50)}
    assert antes, "el token elegido debe recuperar algo antes del daño"
    _ejecutar(almacen, ("DELETE FROM fragmento_fts_idx",))
    verificacion = almacen_obj.verify_version(DOCUMENT_ID, _version(unidad))
    assert verificacion.fts5_ok is True
    assert verificacion.ok is True
    try:
        despues = {acierto.ordinal for acierto in almacen_obj.search_lexical(token.lower(), limit=50)}
    except StoreError:
        despues = set()
    assert not (antes & despues), "el fragmento ya no debe ser recuperable: la limitación es real"


def test_dos_lecturas_son_identicas(almacen: Path, unidad: UnitWrite) -> None:
    almacen_obj = SqliteStore(almacen)
    primera = almacen_obj.read_version(DOCUMENT_ID, _version(unidad))
    segunda = almacen_obj.read_version(DOCUMENT_ID, _version(unidad))
    assert primera == segunda
    assert almacen_obj.verify_version(DOCUMENT_ID, _version(unidad)) == almacen_obj.verify_version(
        DOCUMENT_ID, _version(unidad)
    )


def test_par_compensado_se_detecta_y_la_busqueda_lo_evidencia(almacen: Path, unidad: UnitWrite) -> None:
    """Duplicar un ordinal y borrar otro **conserva el total**: antes escapaba; ahora se detecta.

    Se demuestra sobre el piloto (583 fragmentos) y se comprueba en la búsqueda real: el ordinal duplicado
    aparece **dos** veces y el ausente **ninguna**. La verificación es de solo lectura: el archivo no
    cambia y la autoridad queda intacta.
    """
    duplicado, ausente = 5, 6
    almacen_obj = SqliteStore(almacen)

    def token(ordinal: int) -> str:
        contenido = unidad.fragments[ordinal - 1].content
        return next(t.lower() for t in contenido.split() if len(t) >= 10 and t.isalpha())

    token_duplicado, token_ausente = token(duplicado), token(ausente)

    def veces(token_buscado: str, ordinal: int) -> int:
        aciertos = almacen_obj.search_lexical(token_buscado, document_id=DOCUMENT_ID, limit=50)
        return sum(1 for acierto in aciertos if acierto.ordinal == ordinal)

    assert veces(token_duplicado, duplicado) == 1
    assert veces(token_ausente, ausente) >= 1

    _ejecutar(
        almacen,
        (
            f"DELETE FROM fragmento_fts WHERE document_id = '{DOCUMENT_ID}' AND ordinal = {ausente}",
            "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) "
            f"SELECT document_id, document_version, ordinal, content FROM fragmento_fts WHERE ordinal = {duplicado}",
        ),
    )
    assert _contar(almacen, "fragmento_fts") == FRAGMENTOS_ESPERADOS, "el total se conserva"
    antes = _huella(almacen)

    verificacion = almacen_obj.verify_version(DOCUMENT_ID, _version(unidad))
    assert verificacion.fts5_ok is False
    assert verificacion.ok is False
    assert verificacion.ordinales_ok is True
    assert verificacion.content_hash_ok is True
    assert veces(token_duplicado, duplicado) == 2
    assert veces(token_ausente, ausente) == 0

    assert _huella(almacen) == antes
    assert _laterales(almacen) == []
    assert _contar(almacen, "fragmento") == FRAGMENTOS_ESPERADOS
