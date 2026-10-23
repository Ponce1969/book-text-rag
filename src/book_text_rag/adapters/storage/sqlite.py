"""Almacén SQLite del diseño físico aprobado: esquema mínimo e inicialización idempotente.

**Incremento 1.** Crea el esquema físico derivado del diseño aprobado (tablas de autoridad, caché de
anclaje y la estructura derivada FTS5) y verifica el contrato de inicialización. **No** persiste datos
del pipeline, **no** calcula `index_version`, **no** publica generaciones, **no** migra, **no** borra y
**no** fija parámetros de durabilidad: `D-15` §4.2 declara que la durabilidad del contenido, de la
entrada de directorio y del commit **no está verificada**, y fijar `journal_mode` o `synchronous`
afirmaría una garantía no establecida.

Estados de inicialización (plan del incremento 1):

- **E1** ruta inexistente ⇒ se crea.
- **E2a** archivo de cero bytes ⇒ se inicializa (SQLite lo trata como base vacía válida).
- **E2b** SQLite válido **sin objetos** ⇒ se inicializa.
- **E3** ya inicializado y **compatible** ⇒ no se toca nada.
- **E4** versión desconocida o esquema incompatible ⇒ **rechazo** `incompatible`, sin escribir.
- **E5** archivo que no es una base SQLite válida ⇒ **rechazo** `no_es_base`, sin escribir.

La validez **no** se deduce de que la conexión se abra —SQLite abre un archivo arbitrario sin leer el
encabezado—: se determina **leyendo** el contenido. La inspección previa se hace en **solo lectura**,
de modo que E4 y E5 no pueden escribir.

La definición del esquema —constantes, `DDL`, modelo esperado por tabla y validadores estructurales— y
las funciones de apertura y de evidencia del destino viven en `adapters/storage/sqlite_schema.py`; la
persistencia —T1/T2/T3 y sus inserciones— en `adapters/storage/sqlite_write.py`. Este módulo conserva el
puerto, la aplicación del `DDL` en `_crear`, el camino de lectura, la verificación y la búsqueda, y
reexporta los nombres que consumen las pruebas.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from book_text_rag.adapters.storage.sqlite_schema import (
    CHECK_BLOCK_TYPE,
    DDL,
    INDICES_ESPERADOS,
    PREFIJO_SOMBRA_FTS,
    SCHEMA_VERSION,
    TABLAS_ESPERADAS,
    TOKENIZE_FTS,
    _abrir_escritura,
    _abrir_lectura_valida,
    _consultar,
    _entero,
    _estado_de_ingesta,
    _Evidence,
    _evidencia_de,
    _evidencia_de_conexion,
    _referencias,
    _verificar_evidencia,
    _version_registrada,
)
from book_text_rag.adapters.storage.sqlite_write import (
    _nfc,
    _reconstruir_indice_lexico,
    _t1_registrar_referencia,
    _t2_marcar_incompleta,
    _t3_escribir_unidad,
    json_canonico,
)
from book_text_rag.domain.availability import Availability, AvailabilityCause
from book_text_rag.domain.identity import chunk_id, content_hash, document_version_short, index_version
from book_text_rag.domain.models import AnchorLevel, BlockType
from book_text_rag.ports.storage import (
    DocumentIndex,
    DocumentReference,
    DocumentSummary,
    EstadoIngesta,
    FragmentRead,
    InitOutcome,
    LexicalHit,
    RebuildOutcome,
    SearchResult,
    StoreError,
    StoreErrorCode,
    UnitWrite,
    VerifyOutcome,
    VersionRead,
    WriteOutcome,
)

__all__ = [
    "CHECK_BLOCK_TYPE",
    "DDL",
    "INDICES_ESPERADOS",
    "PREFIJO_SOMBRA_FTS",
    "SCHEMA_VERSION",
    "TABLAS_ESPERADAS",
    "TOKENIZE_FTS",
    "SqliteStore",
    "_Evidence",
    "_evidencia_de_conexion",
    "_nfc",
    "_verificar_evidencia",
    "json_canonico",
]

VARIABLES_SQLITE_SONDEO = 32766
"""Cota superior de sondeo (valor medido en el entorno de desarrollo). **No** es el límite efectivo: lo mide
`_limite_variables_sqlite()`. Una compilación con un límite menor queda cubierta porque la guarda usa el valor
medido, no este supuesto.
"""


def _acepta_variables(conexion: sqlite3.Connection, cantidad: int) -> bool:
    """`True` si el motor acepta una sentencia con `cantidad` variables ligadas.

    Cualquier rechazo del motor se interpreta como «no admitido»: la medición queda como cota inferior, que es
    la dirección segura para una guarda.
    """
    marcadores = ",".join("?" for _ in range(cantidad))
    try:
        conexion.execute(f"SELECT 1 WHERE 1 IN ({marcadores})", [0] * cantidad).fetchall()
    except sqlite3.Error:
        return False
    return True


@lru_cache(maxsize=1)
def _limite_variables_sqlite() -> int:
    """Límite **efectivo** de variables ligadas del SQLite en uso, medido **sin abrir ningún almacén**.

    `SQLITE_MAX_VARIABLE_NUMBER` es una constante de compilación que SQLite no expone por PRAGMA ni por la API
    de `sqlite3` de Python, así que se sondea por bisección sobre una base **en memoria** (`IN ()` es aceptado y
    sirve de extremo inferior). La medición se memoriza: una vez por proceso.
    """
    conexion = sqlite3.connect(":memory:")
    try:
        if _acepta_variables(conexion, VARIABLES_SQLITE_SONDEO):
            return VARIABLES_SQLITE_SONDEO
        bajo, alto = 0, VARIABLES_SQLITE_SONDEO
        while bajo + 1 < alto:
            medio = (bajo + alto) // 2
            if _acepta_variables(conexion, medio):
                bajo = medio
            else:
                alto = medio
        return bajo
    finally:
        conexion.close()


class SqliteStore:
    """Almacén SQLite: esquema mínimo e inicialización idempotente. La ruta es **explícita** (D-F)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> InitOutcome:
        """Crea o verifica el esquema. Rechaza lo incompatible sin escribir y sin migrar."""
        evidencia = _evidencia_de(self._path)
        if not evidencia.existe:
            return self._crear(evidencia)
        if evidencia.user_version == SCHEMA_VERSION and evidencia.valido:
            return InitOutcome.YA_INICIALIZADO
        if evidencia.user_version == 0 and not evidencia.objetos:
            return self._crear(evidencia)
        raise StoreError(
            StoreErrorCode.INCOMPATIBLE,
            "el destino tiene una versión desconocida o un esquema incompatible",
            ruta=str(self._path),
            user_version=evidencia.user_version,
            version_esperada=SCHEMA_VERSION,
        )

    def is_initialized(self) -> bool:
        """`True` solo si el marcador **y** la estructura efectiva coinciden con el esquema vigente.

        Un destino que no es una base SQLite válida se informa como **no inicializado** (`False`); un
        fallo operativo del motor (`error_sqlite`) **se propaga**, porque no es un estado del almacén.
        """
        try:
            evidencia = _evidencia_de(self._path)
        except StoreError as error:
            if error.code is StoreErrorCode.NO_ES_BASE:
                return False
            raise
        return evidencia.existe and evidencia.user_version == SCHEMA_VERSION and evidencia.valido

    def probe_availability(self) -> Availability:
        """Clasifica la disponibilidad en las cinco causas de `D-14` ítem 3. **Solo lectura**.

        Distingue **disponibilidad estructural** —que el almacén sea reconocible y utilizable para el
        modo `lexical`— de la verificación de contenido, que es O(N) y pertenece a `verify` (`D-15` §7):
        aquí no se comprueban fragmentos, hashes ni cardinalidades. No crea el almacén ausente, no abre
        en escritura y no deja archivos laterales.

        La comprobación de existencia **no** usa `Path.exists()`: esa función **no** absorbe la denegación de
        permisos (`EACCES`/`EPERM`/`ERROR_ACCESS_DENIED` no figuran entre sus errores ignorados), así que un
        almacén existente e ilegible escaparía como excepción en lugar de informarse como `inaccesible`.
        """
        try:
            self._path.stat()
        except (FileNotFoundError, NotADirectoryError):
            # `ENOENT` y `ENOTDIR`: la ruta no designa ninguna entrada (no existe, o un componente previo
            # no es un directorio). Es `ausente`, igual que antes.
            return Availability(AvailabilityCause.AUSENTE)
        except ValueError:
            # `os.stat` rechaza con `ValueError` una ruta con byte nulo incrustado o no codificable: no
            # designa ninguna entrada posible. `Path.exists()` devolvía `False` para ese caso, de modo que
            # `ausente` conserva el comportamiento previo; no es un recurso existente inaccesible.
            return Availability(AvailabilityCause.AUSENTE)
        except OSError:
            # La ruta existe o no puede determinarse, pero el sistema impide inspeccionarla (permisos,
            # bloqueo, unidad no disponible): es la clase (b) **inaccesible** de `D-14`, no `ausente`.
            return Availability(AvailabilityCause.INACCESIBLE)
        try:
            evidencia = _evidencia_de(self._path)
        except StoreError as error:
            # Un archivo que no es una base legible y un fallo operativo al abrirlo comparten efecto
            # observable (D-14: las cuatro causas de degradación difieren solo en el detalle del registro).
            if error.code in (StoreErrorCode.NO_ES_BASE, StoreErrorCode.ERROR_SQLITE):
                return Availability(AvailabilityCause.INACCESIBLE)
            raise
        if evidencia.user_version != SCHEMA_VERSION or not evidencia.valido:
            return Availability(AvailabilityCause.INCOMPATIBLE)
        if not _fts5_disponible():
            return Availability(AvailabilityCause.CAPACIDAD_AUSENTE)
        return Availability(AvailabilityCause.DISPONIBLE)

    def _crear(self, esperada: _Evidence) -> InitOutcome:
        conexion = _abrir_escritura(self._path)
        try:
            conexion.execute("PRAGMA foreign_keys = ON")
            conexion.execute("BEGIN IMMEDIATE")
            try:
                # La guarda corre DENTRO de la transacción: reduce la ventana y detecta más cambios,
                # pero NO elimina la carrera ni excluye a quien no respete los bloqueos de SQLite.
                _verificar_evidencia(esperada, _evidencia_de_conexion(conexion, self._path), self._path)
                for sentencia in DDL:
                    conexion.execute(sentencia)
                conexion.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            except Exception:
                # Si el ROLLBACK también falla, se conserva la excepción original (su causa, no la del ROLLBACK).
                with contextlib.suppress(sqlite3.Error):
                    conexion.execute("ROLLBACK")
                raise
            conexion.execute("COMMIT")
        except StoreError:
            raise
        except sqlite3.OperationalError as error:
            raise StoreError(
                StoreErrorCode.ERROR_SQLITE, "el motor falló al escribir el esquema", ruta=str(self._path)
            ) from error
        except sqlite3.DatabaseError as error:
            raise StoreError(
                StoreErrorCode.ERROR_SQLITE, "el motor rechazó la escritura del esquema", ruta=str(self._path)
            ) from error
        finally:
            conexion.close()
        return InitOutcome.CREADO if not esperada.existe else InitOutcome.INICIALIZADO

    def register_reference(self, unit: UnitWrite) -> None:
        """**T1** (`D-25`): registra o confirma la referencia sin degradar el estado previo."""
        _t1_registrar_referencia(self._path, unit)

    def mark_incomplete(self, document_id: str, alias: str) -> None:
        """**T2** (`D-25`): deja durable «ingesta incompleta» antes de escribir la unidad."""
        _t2_marcar_incompleta(self._path, document_id, alias)

    def write_unit(self, unit: UnitWrite) -> WriteOutcome:
        """**T3** (`D-25`): persiste la unidad de forma atómica y fija «ingesta completada»."""
        return _t3_escribir_unidad(self._path, unit)

    def read_version(self, document_id: str, document_version: str) -> VersionRead:
        """Autoridad persistida de la versión, en orden de ordinal (incremento 3; `D-22` §2)."""
        return _leer_version(self._path, document_id, document_version)

    def verify_version(self, document_id: str, document_version: str) -> VerifyOutcome:
        """Invariantes comprobables de `D-22` §5. Sólo lectura: informa y **nunca** repara."""
        return _verificar_version(self._path, document_id, document_version)

    def search_lexical(self, query: str, *, document_id: str | None = None, limit: int = 10) -> tuple[LexicalHit, ...]:
        """Consulta léxica **interna**: sin puntuación, sin ranking y sin `index_version`."""
        return _buscar_lexico(self._path, query, document_id=document_id, limit=limit)

    def search_results(
        self, query: str, *, document_ids: tuple[str, ...] | None = None, top_k: int = 10
    ) -> tuple[SearchResult, ...]:
        """Proyección interna D-07, de solo lectura y sin reparación del almacén."""
        return _buscar_resultados(self._path, query, document_ids=document_ids, top_k=top_k)

    def read_document(self, document_id: str) -> DocumentIndex:
        """Índice documental sin exigir versión: `D-07` admite omitirla y `B4` la registra sin versiones."""
        return _leer_documento(self._path, document_id)

    def list_documents(self) -> tuple[DocumentSummary, ...]:
        """Catálogo del almacén, de solo lectura, sin fragmentos ni contenido."""
        return _listar_documentos(self._path)

    def index_version_for(self, document_id: str, document_version: str) -> str | None:
        """`index_version` recalculada de la construcción de una versión, o `None` (`D-11` §4/§4.1).

        Es un **derivado** (`D-22` §2): se recalcula desde la traza persistida y no se contrasta contra
        ninguna copia, porque no existe. Devuelve `None` cuando la versión no tiene **exactamente una**
        construcción o cuando algún insumo falta o es inválido: no se inventa un valor (`D-11` §4).
        """
        return _index_version_de_construccion(self._path, document_id, document_version)

    def rebuild_lexical_index(self, document_id: str, document_version: str) -> RebuildOutcome:
        """Reconstruye el índice léxico **derivado** de una versión desde la autoridad (incremento 3-b)."""
        return _reconstruir_indice_lexico(self._path, document_id, document_version)


# --- Disponibilidad (`D-14`) ------------------------------------------------------------------------


def _fts5_disponible() -> bool:
    """Sonda de capacidad FTS5 **en memoria**: no crea ni modifica ningún archivo del almacén."""
    try:
        conexion = sqlite3.connect(":memory:")
    except sqlite3.Error:
        return False
    try:
        conexion.execute("CREATE VIRTUAL TABLE sonda_fts5 USING fts5(contenido)")
    except sqlite3.Error:
        return False
    finally:
        conexion.close()
    return True


# --- Incremento 3: lectura de la autoridad, verificación y consulta léxica interna -----------------
#
# Todo el camino de lectura es de **sólo lectura**: abre el almacén con `mode=ro`, no escribe, no crea
# laterales (`-journal`/`-wal`/`-shm`) y **nunca** repara (`D-14` ítem 2). La verificación es O(N) y
# pertenece a construcción/reconstrucción, no a una consulta (`D-15` §7, nivel 2).


@contextlib.contextmanager
def _lectura(ruta: Path) -> Iterator[sqlite3.Connection]:
    """Conexión de **solo lectura** al almacén vigente, cerrada siempre."""
    conexion = _abrir_lectura_valida(ruta)
    try:
        yield conexion
    finally:
        conexion.close()


def _lista_de_texto(valor: object, columna: str) -> tuple[str, ...]:
    """Arreglo JSON canónico de cadenas; un contenido inválido falla de forma explícita."""
    try:
        decodificado = json.loads(str(valor))
    except json.JSONDecodeError as error:
        raise StoreError(StoreErrorCode.ERROR_SQLITE, "el almacén tiene JSON inválido", columna=columna) from error
    if not isinstance(decodificado, list) or not all(isinstance(elemento, str) for elemento in decodificado):
        raise StoreError(StoreErrorCode.ERROR_SQLITE, "el almacén tiene un arreglo JSON inesperado", columna=columna)
    return tuple(str(elemento) for elemento in decodificado)


def _bloque(valor: object) -> BlockType:
    try:
        return BlockType(str(valor))
    except ValueError as error:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE, "el almacén tiene un tipo de bloque desconocido", obtenido=str(valor)
        ) from error


def _nivel_de_anclaje(valor: object) -> AnchorLevel:
    try:
        return AnchorLevel(str(valor))
    except ValueError as error:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE, "el almacén tiene un nivel de anclaje desconocido", obtenido=str(valor)
        ) from error


def _fragmento_leido(fila: tuple[object, ...]) -> FragmentRead:
    """Mapeo inverso fila -> `FragmentRead`; `null` se conserva `null` (`D-22` §5)."""
    return FragmentRead(
        ordinal=_entero(fila[0], "ordinal"),
        chunk_id=str(fila[1]),
        section_path=_lista_de_texto(fila[2], "section_path"),
        level=_entero(fila[3], "level"),
        block_type=_bloque(fila[4]),
        captions=_lista_de_texto(fila[5], "captions"),
        pdf_page_start=None if fila[6] is None else _entero(fila[6], "pdf_page_start"),
        pdf_page_end=None if fila[7] is None else _entero(fila[7], "pdf_page_end"),
        content=str(fila[8]),
        content_hash=str(fila[9]),
        anchor_level=_nivel_de_anclaje(fila[10]),
    )


def _fragmentos_persistidos(
    conexion: sqlite3.Connection, document_id: str, document_version: str
) -> tuple[FragmentRead, ...]:
    """Fragmentos de la versión, en orden de ordinal: la autoridad de `D-22` §2."""
    filas = _consultar(
        conexion,
        "SELECT ordinal, chunk_id, section_path, level, block_type, captions, pdf_page_start, "
        "pdf_page_end, content, content_hash, anchor_level FROM fragmento "
        "WHERE document_id = ? AND document_version = ? ORDER BY ordinal",
        (document_id, document_version),
        "el motor falló al leer los fragmentos de la versión",
    )
    return tuple(_fragmento_leido(fila) for fila in filas)


def _estados_de(
    referencias: tuple[tuple[str, EstadoIngesta], ...],
) -> tuple[EstadoIngesta, ...]:
    """Estados **distintos** de las referencias, ordenados; el lector no elige uno (`CD-02/M-14`)."""
    return tuple(sorted({estado for _, estado in referencias}, key=lambda estado: estado.value))


def _contexto(
    conexion: sqlite3.Connection, document_id: str, document_version: str
) -> tuple[tuple[EstadoIngesta, ...], tuple[FragmentRead, ...]]:
    """Precondiciones comunes: referencia existente y versión registrada, más la autoridad leída."""
    referencias = _referencias(conexion, document_id)
    if not referencias:
        raise StoreError(
            StoreErrorCode.REFERENCIA_AUSENTE,
            "el documento no tiene referencia registrada",
            document_id=document_id,
        )
    if not _version_registrada(conexion, document_id, document_version):
        raise StoreError(
            StoreErrorCode.VERSION_NO_ENCONTRADA,
            "la versión no está registrada",
            document_id=document_id,
            document_version=document_version,
        )
    return _estados_de(referencias), _fragmentos_persistidos(conexion, document_id, document_version)


def _leer_documento(ruta: Path, document_id: str) -> DocumentIndex:
    """Índice documental del documento: metadatos de `fuente`, estados y versiones registradas.

    No exige versión, a diferencia de `read_version`: el contrato público permite omitirla (`D-07`) y una
    identidad registrada sin versiones es un caso legítimo (`B4`). Las versiones se ordenan solo para que
    el valor sea determinista; ese orden **nunca** se usa para elegir una.
    """
    with _lectura(ruta) as conexion:
        referencias = _referencias(conexion, document_id)
        if not referencias:
            raise StoreError(
                StoreErrorCode.REFERENCIA_AUSENTE,
                "el documento no tiene referencia registrada",
                document_id=document_id,
            )
        fuente = _consultar(
            conexion,
            "SELECT source_format, page_count FROM fuente WHERE document_id = ?",
            (document_id,),
            "el motor falló al leer la fuente",
        )
        versiones = _consultar(
            conexion,
            "SELECT document_version FROM version_documento WHERE document_id = ? ORDER BY document_version",
            (document_id,),
            "el motor falló al leer las versiones registradas",
        )
    formato = None if not fuente or fuente[0][0] is None else str(fuente[0][0])
    paginas = None if not fuente or fuente[0][1] is None else _entero(fuente[0][1], "page_count")
    return DocumentIndex(
        document_id=document_id,
        source_format=formato,
        page_count=paginas,
        estados=_estados_de(referencias),
        versions=tuple(str(fila[0]) for fila in versiones),
    )


def _listar_documentos(ruta: Path) -> tuple[DocumentSummary, ...]:
    """Catálogo del almacén en orden determinista (`document_id`, luego alias), en una sola lectura.

    Tres consultas independientes y agrupación en memoria: no hay JOIN que pueda multiplicar filas si un
    documento tuviera varias referencias o varias versiones. No lee fragmentos ni contenido.
    """
    with _lectura(ruta) as conexion:
        fuentes = _consultar(
            conexion,
            "SELECT document_id, source_format, page_count FROM fuente ORDER BY document_id",
            (),
            "el motor falló al leer las fuentes",
        )
        referencias = _consultar(
            conexion,
            "SELECT document_id, alias, estado_ingesta FROM referencia_fuente ORDER BY document_id, alias",
            (),
            "el motor falló al leer las referencias",
        )
        versiones = _consultar(
            conexion,
            "SELECT document_id, document_version FROM version_documento ORDER BY document_id, document_version",
            (),
            "el motor falló al leer las versiones registradas",
        )

    por_documento: dict[str, list[DocumentReference]] = {}
    for fila in referencias:
        por_documento.setdefault(str(fila[0]), []).append(
            DocumentReference(alias=str(fila[1]), estado=_estado_de_ingesta(fila[2]))
        )
    versiones_por_documento: dict[str, list[str]] = {}
    for fila in versiones:
        versiones_por_documento.setdefault(str(fila[0]), []).append(str(fila[1]))

    resumenes: list[DocumentSummary] = []
    for fila in fuentes:
        document_id = str(fila[0])
        resumenes.append(
            DocumentSummary(
                document_id=document_id,
                source_format=None if fila[1] is None else str(fila[1]),
                page_count=None if fila[2] is None else _entero(fila[2], "page_count"),
                references=tuple(por_documento.get(document_id, ())),
                versions=tuple(versiones_por_documento.get(document_id, ())),
            )
        )
    return tuple(resumenes)


def _leer_version(ruta: Path, document_id: str, document_version: str) -> VersionRead:
    """Autoridad persistida de una versión. Sólo lectura; nunca escribe ni repara.

    `source_format` y `page_count` pueden ser `None` porque el esquema los admite nulos: esta lectura
    **no** distingue «fila de `fuente` ausente» de «valor no declarado». Esa distinción la informa
    `verify_version` con `fuente_presente`, y aquí **no** se convierte en error.
    """
    with _lectura(ruta) as conexion:
        estados, fragmentos = _contexto(conexion, document_id, document_version)
        fuente = _consultar(
            conexion,
            "SELECT source_format, page_count FROM fuente WHERE document_id = ?",
            (document_id,),
            "el motor falló al leer la fuente",
        )
    formato = None if not fuente or fuente[0][0] is None else str(fuente[0][0])
    paginas = None if not fuente or fuente[0][1] is None else _entero(fuente[0][1], "page_count")
    return VersionRead(
        document_id=document_id,
        document_version=document_version,
        estados=estados,
        source_format=formato,
        page_count=paginas,
        fragments=fragmentos,
    )


def _fts5_corresponde(
    conexion: sqlite3.Connection, document_id: str, document_version: str, fragmentos: tuple[FragmentRead, ...]
) -> bool:
    """Correspondencia autoridad <-> índice derivado **por filas almacenadas**: cardinalidad total,
    ausencia de ordinales repetidos y `content` por ordinal. Nada más.

    Comprueba tres igualdades: **(1)** el número de filas de `fragmento_fts` de la versión; **(2)** que
    ningún ordinal de esa versión aparezca **más de una vez**; **(3)** el número de filas del cruce por
    ordinal cuyo `content` coincide. Las tres juntas equivalen a que el multiset de pares
    `(ordinal, content)` del derivado sea **idéntico** al de la autoridad: (2) acota la multiplicidad a
    uno, (1) fija cuántos ordinales distintos hay y (3) exige que cada fila cruce. Detecta así una fila
    **ausente**, una **duplicada**, el patrón **compensado** —duplicar un ordinal y borrar otro, que
    conserva el total— y una fila con **otro contenido**, que la detecta (3) y **no** (2).

    **No** comprueba la coherencia del **índice invertido** —una corrupción que deje intactas las filas y
    el `content` almacenado pasa inadvertida, y el índice puede quedar sin recuperar nada— ni la
    **consultabilidad**: `integrity-check` de FTS5 es una operación de **escritura** y no se usa, y `D-15`
    §7.1 deja la comprobación completa de consistencia de FTS5 **fuera de alcance**. Compara **filas
    almacenadas**; **no** audita la estructura interna del índice.
    """
    totales = _consultar(
        conexion,
        "SELECT count(*) FROM fragmento_fts WHERE document_id = ? AND document_version = ?",
        (document_id, document_version),
        "el motor falló al contar el índice léxico",
    )
    repetidos = _consultar(
        conexion,
        "SELECT count(*) FROM (SELECT ordinal FROM fragmento_fts "
        "WHERE document_id = ? AND document_version = ? GROUP BY ordinal HAVING count(*) > 1)",
        (document_id, document_version),
        "el motor falló al comprobar los ordinales repetidos del índice léxico",
    )
    coincidentes = _consultar(
        conexion,
        "SELECT count(*) FROM fragmento JOIN fragmento_fts "
        "ON fragmento_fts.document_id = fragmento.document_id "
        "AND fragmento_fts.document_version = fragmento.document_version "
        "AND fragmento_fts.ordinal = fragmento.ordinal "
        "WHERE fragmento.document_id = ? AND fragmento.document_version = ? "
        "AND fragmento_fts.content = fragmento.content",
        (document_id, document_version),
        "el motor falló al contrastar el índice léxico",
    )
    esperados = len(fragmentos)
    return (
        _entero(totales[0][0], "count") == esperados
        and _entero(repetidos[0][0], "count") == 0
        and _entero(coincidentes[0][0], "count") == esperados
    )


def _index_version_de_construccion(ruta: Path, document_id: str, document_version: str) -> str | None:
    """Recalcula `index_version` desde la traza de construcción (`D-11` §4/§4.1; `D-22` §2).

    Los seis primeros insumos se leen de la fila de `construccion`; el séptimo (`embeddings`) es el
    arreglo vacío, único valor que puede existir hoy porque no hay arm vectorial ni almacén de vectores.
    `None` significa «no atribuible»: cero o varias construcciones, o un insumo ausente o inválido. Nunca
    se sustituye un insumo ni se elige una construcción entre varias (`CD-05` sigue abierto).
    """
    with _lectura(ruta) as conexion:
        filas = _consultar(
            conexion,
            "SELECT extractor_nombre, extractor_version, extractor_config_efectiva, chunking_config_version, "
            "tokenizer, sqlite_version, sqlite_vec_version FROM construccion "
            "WHERE document_id = ? AND document_version = ?",
            (document_id, document_version),
            "el motor falló al leer la traza de construcción",
        )
    if len(filas) != 1:
        return None
    fila = filas[0]
    if len(fila) != 7 or not all(isinstance(valor, str) for valor in fila):
        return None
    nombre, version, configuracion, troceado, tokenizer, version_sqlite, version_sqlite_vec = (
        valor for valor in fila if isinstance(valor, str)
    )
    try:
        return index_version(
            document_version=document_version,
            extractor=(nombre, version, configuracion),
            chunking_config_version=troceado,
            tokenizer=tokenizer,
            sqlite_version=version_sqlite,
            sqlite_vec_version=version_sqlite_vec,
            embeddings=(),
        )
    except ValueError:
        return None


def _traza_presente(conexion: sqlite3.Connection, document_id: str, document_version: str) -> bool:
    """Presencia de **al menos una** fila de traza para la versión (`D-22` §2: es autoridad).

    **No** afirma que la traza tenga todos sus insumos: eso pertenece a la condición de completitud de
    `D-22` §8 y queda declarado fuera del incremento (`NO_VERIFICADO`). `D-22` §4 admite **N**
    construcciones por versión, así que exigir «exactamente una» sería incorrecto.
    """
    filas = _consultar(
        conexion,
        "SELECT count(*) FROM construccion WHERE document_id = ? AND document_version = ?",
        (document_id, document_version),
        "el motor falló al leer la traza",
    )
    return _entero(filas[0][0], "count") >= 1


def _fuente_presente(conexion: sqlite3.Connection, document_id: str) -> bool:
    """Integridad referencial `VERSION_DOCUMENTO → FUENTE` (`D-22` §5), comprobada en solo lectura.

    Una versión registrada cuya fila de `fuente` falta es una **falta de integridad referencial**, no una
    versión inexistente: por eso se informa con este indicador y **no** con `version_no_encontrada`.
    """
    filas = _consultar(
        conexion,
        "SELECT 1 FROM fuente WHERE document_id = ?",
        (document_id,),
        "el motor falló al comprobar la fuente",
    )
    return bool(filas)


def _verificar_version(ruta: Path, document_id: str, document_version: str) -> VerifyOutcome:
    """Invariantes comprobables de `D-22` §5. Sólo lectura: informa y **nunca** repara.

    Incluye la integridad referencial `VERSION_DOCUMENTO → FUENTE`: una versión **registrada** cuya
    fila de `fuente` falta se informa con `fuente_presente=False` y deja `ok` en `False`. Eso **no** es
    una versión inexistente: ese caso sigue siendo `version_no_encontrada` (o `referencia_ausente`).
    """
    corta = document_version_short(document_version)
    with _lectura(ruta) as conexion:
        estados, fragmentos = _contexto(conexion, document_id, document_version)
        fts5_ok = _fts5_corresponde(conexion, document_id, document_version, fragmentos)
        traza_presente = _traza_presente(conexion, document_id, document_version)
        fuente_presente = _fuente_presente(conexion, document_id)
    return VerifyOutcome(
        fragmentos=len(fragmentos),
        ordinales_ok=[fragmento.ordinal for fragmento in fragmentos] == list(range(1, len(fragmentos) + 1)),
        content_hash_ok=all(content_hash(fragmento.content) == fragmento.content_hash for fragmento in fragmentos),
        chunk_id_ok=all(
            chunk_id(document_id, corta, fragmento.ordinal) == fragmento.chunk_id for fragmento in fragmentos
        ),
        fts5_ok=fts5_ok,
        estado_ok=estados == (EstadoIngesta.COMPLETADA,),
        traza_presente=traza_presente,
        fuente_presente=fuente_presente,
    )


def _buscar_lexico(ruta: Path, query: str, *, document_id: str | None, limit: int) -> tuple[LexicalHit, ...]:
    """Consulta léxica **interna**: sin puntuación, sin ranking y sin `index_version` (`D-07` aparte)."""
    if not query.strip():
        raise ValueError("la consulta léxica no puede estar vacía")
    if limit < 1:
        raise ValueError("el límite de la consulta léxica debe ser >= 1")
    sql = (
        "SELECT fragmento_fts.document_id, fragmento_fts.document_version, fragmento_fts.ordinal, "
        "fragmento.chunk_id FROM fragmento_fts JOIN fragmento "
        "ON fragmento.document_id = fragmento_fts.document_id "
        "AND fragmento.document_version = fragmento_fts.document_version "
        "AND fragmento.ordinal = fragmento_fts.ordinal "
        "WHERE fragmento_fts MATCH ?"
    )
    parametros: list[object] = [query]
    if document_id is not None:
        sql += " AND fragmento_fts.document_id = ?"
        parametros.append(document_id)
    sql += " ORDER BY rank LIMIT ?"
    parametros.append(limit)
    with _lectura(ruta) as conexion:
        try:
            filas = [tuple(fila) for fila in conexion.execute(sql, parametros).fetchall()]
        except sqlite3.OperationalError as error:
            raise StoreError(
                StoreErrorCode.ERROR_SQLITE,
                "el motor rechazó la consulta léxica (su sintaxis pertenece a `D-07`)",
            ) from error
        except sqlite3.DatabaseError as error:
            raise StoreError(StoreErrorCode.ERROR_SQLITE, "el motor falló al consultar el índice léxico") from error
    return tuple(
        LexicalHit(
            document_id=str(fila[0]),
            document_version=str(fila[1]),
            ordinal=_entero(fila[2], "ordinal"),
            chunk_id=str(fila[3]),
        )
        for fila in filas
    )


def _buscar_resultados(
    ruta: Path,
    query: str,
    *,
    document_ids: tuple[str, ...] | None,
    top_k: int,
) -> tuple[SearchResult, ...]:
    """Proyecta resultados en una sola lectura, sin deduplicar.

    La puntuación es la cruda de `bm25()` y el orden lo fija FTS5 con `ORDER BY rank`. No deduplicar
    significa reflejar posibles duplicados del derivado; no garantiza corrección ante corrupción del índice.
    El límite de variables se mide en memoria; la guarda reserva `MATCH`, el estado de ingesta y `LIMIT`,
    rechaza el exceso antes de abrir el almacén y nunca trunca la entrada.
    """
    if not query.strip():
        raise ValueError("la consulta de resultados no puede estar vacía")
    if type(top_k) is not int or top_k < 1:
        raise ValueError("top_k debe ser un entero >= 1")
    if document_ids is not None and not document_ids:
        raise ValueError("document_ids debe contener al menos un identificador")
    if document_ids is not None:
        maximo = _limite_variables_sqlite() - 3  # variables de `MATCH`, del estado y de `LIMIT`
        if len(document_ids) > maximo:
            raise ValueError(f"document_ids excede el máximo de {maximo} identificadores del SQLite en uso")

    sql = (
        "SELECT bm25(fragmento_fts), fragmento.document_id, fragmento.document_version, fragmento.chunk_id, "
        "fragmento.content, fragmento.section_path, fragmento.pdf_page_start, fragmento.pdf_page_end "
        "FROM fragmento_fts JOIN fragmento "
        "ON fragmento.document_id = fragmento_fts.document_id "
        "AND fragmento.document_version = fragmento_fts.document_version "
        "AND fragmento.ordinal = fragmento_fts.ordinal "
        "WHERE fragmento_fts MATCH ?"
        # D-13 (004:452-455 y 525): `search` no puede devolver una versión que el catálogo no declara
        # incorporada. Se exige que el documento **tenga** referencia y que **todas** estén en «ingesta
        # completada»: el `EXISTS` impide que la ausencia de filas habilite el documento por omisión, y el
        # `NOT EXISTS` excluye cualquier estado distinto (la regla conservadora que ya aplica `get_document`).
        " AND EXISTS (SELECT 1 FROM referencia_fuente AS r WHERE r.document_id = fragmento.document_id)"
        " AND NOT EXISTS ("
        "SELECT 1 FROM referencia_fuente AS r "
        "WHERE r.document_id = fragmento.document_id AND r.estado_ingesta <> ?)"
    )
    parametros: list[object] = [query, EstadoIngesta.COMPLETADA.value]
    if document_ids is not None:
        marcadores = ",".join("?" for _ in document_ids)
        sql += f" AND fragmento.document_id IN ({marcadores})"
        parametros.extend(document_ids)
    sql += " ORDER BY rank LIMIT ?"
    parametros.append(top_k)

    with _lectura(ruta) as conexion:
        try:
            filas = [tuple(fila) for fila in conexion.execute(sql, parametros).fetchall()]
        except sqlite3.OperationalError as error:
            raise StoreError(
                StoreErrorCode.ERROR_SQLITE,
                "el motor rechazó la consulta de resultados (la sintaxis pertenece a `D-07`)",
            ) from error
        except sqlite3.DatabaseError as error:
            raise StoreError(StoreErrorCode.ERROR_SQLITE, "el motor falló al consultar el índice léxico") from error

    resultados: list[SearchResult] = []
    for posicion, fila in enumerate(filas, start=1):
        puntuacion = fila[0]
        if not isinstance(puntuacion, (int, float)):
            raise StoreError(StoreErrorCode.ERROR_SQLITE, "el almacén devolvió una puntuación no numérica")
        resultados.append(
            SearchResult(
                rank=posicion,
                score=float(puntuacion),
                document_id=str(fila[1]),
                document_version=str(fila[2]),
                chunk_id=str(fila[3]),
                content=str(fila[4]),
                section_path=_lista_de_texto(fila[5], "section_path"),
                pdf_page_start=None if fila[6] is None else _entero(fila[6], "pdf_page_start"),
                pdf_page_end=None if fila[7] is None else _entero(fila[7], "pdf_page_end"),
            )
        )
    return tuple(resultados)
