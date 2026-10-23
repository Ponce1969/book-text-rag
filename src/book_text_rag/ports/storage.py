"""Contrato del almacén persistente (diseño físico aprobado; `001` §4 y §9).

Puerto de **inicialización** (incremento 1), de **escritura** (incremento 2) y de **lectura**
(incremento 3). **No** calcula `index_version`, **no** publica generaciones, **no** migra, **no** borra
nada preexistente y **no** expone detalles físicos del almacén (`rowid`, rutas).

Los códigos son internos y mantienen separados los **rechazos explícitos** (`incompatible`,
`no_es_base`, `destino_cambiado`, `referencia_ausente`, `version_no_encontrada`,
`contenido_divergente`) de los **errores inesperados del motor** (`error_sqlite`). Ninguno de ellos se
reclasifica como otro. `incompatible` y `no_es_base` califican al **destino**; `referencia_ausente`,
`version_no_encontrada` y `contenido_divergente` califican a la **operación** (`D-25`).

`index_unavailable` es la excepción declarada: es el código **público** que `D-14` ítem 6 y `001` §6.2
fijan para el índice no disponible, y se declara aquí porque es el borde de la CLI quien debe emitirlo.
No introduce vocabulario nuevo ni reclasifica un fallo del motor. `document_not_found` e
`invalid_request` siguen el mismo criterio: son los códigos que `D-07` y `001` §6.2 ya fijan, y se
declaran para que la capa de aplicación pueda emitirlos al proyectar `get_document`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from book_text_rag.domain.availability import Availability
from book_text_rag.domain.models import AnchorLevel, BlockType, FragmentRecord, IngestTrace


class StoreErrorCode(StrEnum):
    """Códigos internos del camino de almacén. **No** son el enum público de `001` §6.2."""

    INCOMPATIBLE = "incompatible"
    NO_ES_BASE = "no_es_base"
    DESTINO_CAMBIADO = "destino_cambiado"
    REFERENCIA_AUSENTE = "referencia_ausente"
    VERSION_NO_ENCONTRADA = "version_no_encontrada"
    ERROR_SQLITE = "error_sqlite"
    CONTENIDO_DIVERGENTE = "contenido_divergente"
    INDEX_UNAVAILABLE = "index_unavailable"
    DOCUMENT_NOT_FOUND = "document_not_found"
    INVALID_REQUEST = "invalid_request"


class StoreError(Exception):
    """Fallo explícito del almacén: no sobrescribe, no borra y no migra nada preexistente."""

    def __init__(self, code: StoreErrorCode, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details)

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"


class InitOutcome(StrEnum):
    """Resultado de una inicialización (estados E1, E2a/E2b y E3 del plan del incremento 1)."""

    CREADO = "creado"
    INICIALIZADO = "inicializado"
    YA_INICIALIZADO = "ya_inicializado"


class StoreHealth(Protocol):
    """Sonda de disponibilidad del almacén (`D-14` ítem 3): de solo lectura y sin crear nada."""

    def probe_availability(self) -> Availability:
        """Clasifica el almacén en las cinco causas de `D-14` sin escribir en él."""
        ...


class StoreInitializer(Protocol):
    """Contrato mínimo del almacén: crear o verificar el esquema físico, sin migrar."""

    def initialize(self) -> InitOutcome:
        """Crea o verifica el esquema. Es idempotente y **rechaza** lo incompatible sin modificarlo."""
        ...

    def is_initialized(self) -> bool:
        """`True` solo si el marcador **y** las estructuras físicas coinciden con el esquema vigente."""
        ...


class EstadoIngesta(StrEnum):
    """Los tres valores nominales de `estado_ingesta`, **literales** de `D-13` (004:410-412)."""

    DECISION_REGISTRADA = "decisión de identidad registrada"
    INCOMPLETA = "ingesta incompleta"
    COMPLETADA = "ingesta completada e índice disponible para consulta"


@dataclass(frozen=True)
class UnitWrite:
    """Entrada de la escritura de la unidad 1: identidad, referencia, metadatos y registros."""

    document_id: str
    alias: str
    fecha: str
    fragments: tuple[FragmentRecord, ...]
    trace: IngestTrace
    source_format: str | None = None
    page_count: int | None = None


@dataclass(frozen=True)
class WriteOutcome:
    """Resultado de `write_unit`: recuentos y si la versión del pin se pudo verificar (`D-24`)."""

    fragmentos_escritos: int = 0
    fragmentos_existentes: int = 0
    sqlite_vec_verificado: bool = field(default=False)


class StoreWriter(Protocol):
    """Contrato de escritura del incremento 2 (`D-25`): tres transacciones, sin publicación."""

    def register_reference(self, unit: UnitWrite) -> None:
        """**T1:** registra o confirma la referencia **sin** degradar el estado previo."""
        ...

    def mark_incomplete(self, document_id: str, alias: str) -> None:
        """**T2:** deja durable «ingesta incompleta» antes de escribir la unidad."""
        ...

    def write_unit(self, unit: UnitWrite) -> WriteOutcome:
        """**T3:** persiste la unidad de forma atómica y fija «ingesta completada»."""
        ...


@dataclass(frozen=True)
class FragmentRead:
    """Fragmento **leído** de la autoridad persistida (`D-22` §2), sin detalles físicos del almacén.

    Contiene **exactamente** los campos persistidos y recomputables. **No** incluye `word_count` —su
    regla de conteo sigue sin definir y sin versionar (`I7`), y no se persiste: incluirla obligaría a
    inventarla— ni `anchor_evidence` —caché descartable, `D-22` §10—. **Nunca** expone `rowid` ni rutas
    (`D-22` §9); `section_path` es el camino jerárquico lógico del fragmento, no una ruta de archivo.
    """

    ordinal: int
    chunk_id: str
    section_path: tuple[str, ...]
    level: int
    block_type: BlockType
    captions: tuple[str, ...]
    pdf_page_start: int | None
    pdf_page_end: int | None
    content: str
    content_hash: str
    anchor_level: AnchorLevel


@dataclass(frozen=True)
class VersionRead:
    """Autoridad persistida de una versión: referencias, metadatos de fuente y fragmentos.

    `estados` son los estados de ingesta **distintos** observados en las referencias del documento,
    ordenados. El lector **no elige** uno: la relación entre el estado de ingesta y la versión es
    `CD-02/M-14`, que sigue abierta, y elegir sería inventar. Los fragmentos vienen en orden de ordinal.

    `source_format` y `page_count` son **nullable** en el esquema: un `None` significa «ausente o no
    declarado» y **no** distingue por sí solo una fila de `fuente` que falta. Esa distinción la informa
    `verify_version` con `fuente_presente`; `read_version` no la convierte en error.
    """

    document_id: str
    document_version: str
    estados: tuple[EstadoIngesta, ...]
    source_format: str | None
    page_count: int | None
    fragments: tuple[FragmentRead, ...]


class DocumentStatus(StrEnum):
    """Los dos estados públicos de `get_document` (`D-07`). `PD-11` mantiene el vocabulario cerrado."""

    INDEXED = "indexed"
    NOT_INDEXED = "not_indexed"


@dataclass(frozen=True)
class DocumentIndex:
    """Índice documental mínimo para resolver `get_document`, **sin exigir versión** (`D-07` la admite omitida).

    `estados` son los estados de ingesta **distintos** de las referencias del documento, ordenados: el
    lector no elige uno entre varios (`CD-02/M-14` sigue abierta). `versions` va ordenado solo para que
    el valor sea determinista; ese orden **nunca** se usa para elegir una versión.
    """

    document_id: str
    source_format: str | None
    page_count: int | None
    estados: tuple[EstadoIngesta, ...]
    versions: tuple[str, ...]


@dataclass(frozen=True)
class DocumentView:
    """Proyección pública de `get_document` (`D-07`): siete campos, sin fragmentos ni rutas."""

    document_id: str
    document_version: str | None
    title: str | None
    source_format: str | None
    page_count: int | None
    index_version: str | None
    status: DocumentStatus


@dataclass(frozen=True)
class DocumentReference:
    """Una referencia de fuente del catálogo (`D-13`): alias y estado de ingesta."""

    alias: str
    estado: EstadoIngesta


@dataclass(frozen=True)
class DocumentSummary:
    """Entrada del catálogo para listar el almacén, sin fragmentos, contenido ni rutas.

    `consultable` es un indicador **del documento**, no de cada versión: responde exactamente a «¿`search`
    puede devolver fragmentos de este documento?» y sigue la regla conservadora de `D-13` (hay referencias
    y **todas** están en «ingesta completada»). Con varias versiones no se afirma nada por versión: esa
    atribución es `CD-02/M-14` y sigue abierta.
    """

    document_id: str
    source_format: str | None
    page_count: int | None
    references: tuple[DocumentReference, ...]
    versions: tuple[str, ...]

    @property
    def consultable(self) -> bool:
        """`True` solo si hay referencias y todas están completadas (`D-13`, regla de `search`)."""
        return bool(self.references) and all(
            referencia.estado is EstadoIngesta.COMPLETADA for referencia in self.references
        )


NO_VERIFICADO: tuple[str, ...] = (
    "traza_insumos",
    "index_version",
    "reconstruccion_indice",
    "consultabilidad_indice",
)
"""Lo que `verify_version` **no** verifica en el incremento 3, declarado para no sobreentender `ok`.

- `traza_insumos`: la condición de completitud de `D-22` §8 exige «traza con sus insumos», pero **no**
  es un invariante de `D-22` §5 y comprobarla exige reconstruir la traza completa y contrastarla; el
  incremento **no** la declara satisfecha.
- `index_version`: **no se calcula** (`D-11` §4 exige sus seis insumos, que pertenecen a la construcción
  del índice; `D-20` §3.3).
- `reconstruccion_indice`: borrar los derivados y reconstruir el índice léxico pertenece al incremento
  siguiente, no a este.
- `consultabilidad_indice`: **no** se comprueba que una consulta léxica recupere todo lo esperado, ni la
  coherencia del índice invertido. `ok=True` **no** garantiza que la búsqueda encuentre los documentos
  esperados ni satisface la condición de completitud de `D-22` §8 («índice léxico construido y
  **consultable**»).
"""


@dataclass(frozen=True)
class VerifyOutcome:
    """Resultado de verificar los invariantes **comprobables** de `D-22` §5 sobre una versión.

    `ok` significa que **todos** los indicadores pasaron. **No** afirma la condición de completitud de
    `D-22` §8 ni nada de lo enumerado en `no_verificado`; en particular **no** garantiza que una consulta
    léxica recupere todo lo esperado ni que el índice invertido sea coherente.

    Alcance exacto de cada indicador:

    - `ordinales_ok`: los ordinales leídos son `1..N` contiguos.
    - `content_hash_ok`: `content_hash(content)` coincide con el persistido, **por fragmento**.
    - `chunk_id_ok`: el `chunk_id` reconstruido coincide con el persistido, **por fragmento**.
    - `fts5_ok`: correspondencia **por filas almacenadas** con el índice derivado: cardinalidad total,
      **ausencia de ordinales repetidos** y `content` por ordinal. Las tres juntas equivalen a que el
      multiset de pares `(ordinal, content)` sea idéntico al de la autoridad, de modo que detecta una fila
      ausente, una duplicada, el patrón **compensado** —duplicar un ordinal y borrar otro, que conserva el
      total— y un `content` divergente. **No** comprueba la coherencia del índice **invertido** ni la
      **consultabilidad** (`integrity-check` de FTS5 es una operación de escritura y no se usa): compara
      filas almacenadas, **no** la estructura interna del índice.
    - `estado_ok`: **todos** los estados de referencia del documento son «ingesta completada…». Es una
      condición sobre el **documento**, no sobre la versión (`CD-02/M-14` sigue abierta).
    - `traza_presente`: existe **al menos una** fila de traza (`D-22` §2; `§4` admite **N** por versión).
      Sólo presencia: **no** afirma que la traza tenga todos sus insumos.
    - `fuente_presente`: existe la fila de `fuente` de la que la versión depende
      (`VERSION_DOCUMENTO → FUENTE`, `D-22` §5). Su ausencia es una **falta de integridad referencial**
      de una versión registrada, **no** una versión inexistente.

    **Versión con cero fragmentos.** `N = 0` es un caso legítimo (`C-14`) y **no** es un error. Con
    `fragmentos == 0` los indicadores por fragmento —`ordinales_ok`, `content_hash_ok`, `chunk_id_ok`,
    `fts5_ok`— son **vacuamente verdaderos**: afirman que «todo lo persistido cumple» y no hay nada
    persistido, de modo que **no** son prueba de que se haya verificado contenido alguno.

    La verificación **informa**; nunca repara ni escribe.
    """

    fragmentos: int
    ordinales_ok: bool
    content_hash_ok: bool
    chunk_id_ok: bool
    fts5_ok: bool
    estado_ok: bool
    traza_presente: bool
    fuente_presente: bool
    no_verificado: tuple[str, ...] = NO_VERIFICADO

    @property
    def ok(self) -> bool:
        """`True` sólo si **todos** los invariantes comprobados en este incremento pasaron."""
        return (
            self.ordinales_ok
            and self.content_hash_ok
            and self.chunk_id_ok
            and self.fts5_ok
            and self.estado_ok
            and self.traza_presente
            and self.fuente_presente
        )


@dataclass(frozen=True)
class LexicalHit:
    """Acierto léxico **interno** de `search_lexical`: sin `score`, sin `rank` y sin `index_version`.

    Es una primitiva de recuperación, **no** el contrato público de `D-07`: no fija puntuación ni orden
    contractual y no devuelve `index_version`. El orden es el que fija el motor.
    """

    document_id: str
    document_version: str
    ordinal: int
    chunk_id: str


@dataclass(frozen=True)
class SearchResult:
    """Proyección interna de resultado de recuperación léxica de `D-07`.

    `rank` es la posición 1-based en la secuencia ordenada por relevancia del motor; no es la columna
    `rank` de FTS5, que contiene la puntuación. `score` conserva el valor crudo de `bm25()`, sin
    transformar: un valor menor es mejor y no es comparable entre consultas. Sólo los dos campos de
    página son anulables. `section_path` es la ruta jerárquica decodificada, nunca una ruta del sistema
    de archivos. Se excluyen `index_version`, `rowid`, `word_count`, `anchor_evidence`, `ordinal`,
    `level`, `block_type` y `captions`.
    """

    rank: int
    score: float
    document_id: str
    document_version: str
    chunk_id: str
    content: str
    section_path: tuple[str, ...]
    pdf_page_start: int | None
    pdf_page_end: int | None


class StoreReader(Protocol):
    """Contrato de lectura del incremento 3: autoridad persistida, verificación y consulta léxica.

    Es **sólo lectura**: no escribe, no repara y no crea efectos laterales — no requiere permiso de
    escritura sobre el archivo del almacén (condición de `D-08`). Un destino que no sea un almacén de la
    versión vigente se rechaza (`no_es_base`/`incompatible`) sin modificarlo.
    """

    def read_version(self, document_id: str, document_version: str) -> VersionRead:
        """Devuelve la autoridad persistida de la versión, con los fragmentos en orden de ordinal.

        `referencia_ausente` si el documento no tiene referencia; `version_no_encontrada` si la
        referencia existe pero la **versión no está registrada**. Una versión registrada con **cero**
        fragmentos es un caso legítimo y se devuelve con `fragments` vacío.
        """
        ...

    def verify_version(self, document_id: str, document_version: str) -> VerifyOutcome:
        """Comprueba los invariantes comprobables de `D-22` §5. Informa; **nunca** repara.

        Incluye la integridad referencial `VERSION_DOCUMENTO → FUENTE` mediante `fuente_presente`: una
        versión registrada cuya fuente falta se informa como tal y **no** deja `ok` en `True`.
        """
        ...

    def index_version_for(self, document_id: str, document_version: str) -> str | None:
        """Recalcula `index_version` de la construcción de una versión (`D-11` §4/§4.1; `D-22` §2).

        Es un **derivado**: se calcula desde la traza persistida y no se persiste ni se contrasta contra
        copia alguna. Devuelve `None` cuando la versión no tiene **exactamente una** construcción o cuando
        algún insumo falta o es inválido: no se sustituye ni se inventa ningún valor.
        """
        ...

    def read_document(self, document_id: str) -> DocumentIndex:
        """Índice documental del documento, **sin exigir versión** (`D-07` la admite omitida).

        `referencia_ausente` si el documento no tiene referencia registrada. `versions` puede ser vacía:
        una identidad registrada sin versiones es un caso legítimo (`B4`) y no un error.
        """
        ...

    def list_documents(self) -> tuple[DocumentSummary, ...]:
        """Catálogo completo del almacén, en orden determinista por `document_id` y alias.

        Devuelve un resumen por documento: metadatos de `fuente`, cada referencia con su estado y las
        versiones registradas. No incluye fragmentos, contenido ni rutas. Un almacén válido y vacío
        devuelve `()`; no es un error (`D-14` ítem 8).
        """
        ...

    def search_lexical(self, query: str, *, document_id: str | None = None, limit: int = 10) -> tuple[LexicalHit, ...]:
        """Consulta el índice léxico derivado y devuelve los aciertos internos acordados.

        `query` no vacía y `limit >= 1` son responsabilidad del llamador: un valor inválido es un
        `ValueError`, no un valor tolerado.
        """
        ...

    def search_results(
        self, query: str, *, document_ids: tuple[str, ...] | None = None, top_k: int = 10
    ) -> tuple[SearchResult, ...]:
        """Lee resultados D-07 sin escribir ni reparar el almacén.

        El orden es el de relevancia del motor y ninguna capa posterior debe reordenar; `rank` es
        1..N en ese orden. La aplicación valida que `query` sea `str`, no vacía tras `strip()` y de hasta
        1000 caracteres; que `top_k` sea un entero entre 1 y 50 (no `bool`); y que `document_ids` sea
        `None` o una colección de `str`. `document_ids=None` significa sin filtro; si la colección está
        vacía, la aplicación devuelve `()` sin consultar al adaptador. El adaptador rechaza, antes de abrir
        el almacén, si los IDs junto con `MATCH` y `LIMIT` exceden el límite efectivo de variables ligadas
        del SQLite en uso. Una solicitud inválida produce `ValueError`, no se tolera. Identificadores
        desconocidos y consultas válidas sin coincidencias devuelven `()`. La atribución de
        `index_version` a la respuesta es responsabilidad de la capa de aplicación (`F`), no de esta
        proyección.
        """
        ...


@dataclass(frozen=True)
class RebuildOutcome:
    """Resultado de reconstruir el índice léxico **derivado** de una versión (incremento 3-b).

    Cuenta filas derivadas: las que había antes de reconstruir y las que quedaron tras hacerlo desde la
    autoridad. **No** transporta `index_version`: no se calcula ni se persiste en este incremento, de modo
    que el criterio de `D-22` §11 se cumple aquí en su mitad observable —«mismos resultados»— y **no** en
    la de «misma `index_version`», que sigue fuera.
    """

    document_id: str
    document_version: str
    filas_previas: int
    filas_reconstruidas: int


class LexicalIndexMaintainer(Protocol):
    """Contrato de **mantenimiento** del índice derivado (incremento 3-b). **No** es de solo lectura.

    Es un protocolo **separado** de `StoreReader` a propósito: el lector no escribe y no repara, así que
    una operación que escribe no puede formar parte de su contrato. Reconstruye `fragmento_fts` de **una**
    versión desde la autoridad persistida (`D-02` pt. 3; `D-22` §5), en una transacción, **sin** tocar la
    autoridad, **sin** cambiar el estado de ingesta, **sin** publicar generaciones y **sin** calcular
    `index_version`.
    """

    def rebuild_lexical_index(self, document_id: str, document_version: str) -> RebuildOutcome:
        """Reconstruye el índice léxico derivado de la versión tomando ordinal y contenido de `fragmento`.

        Explícito, atómico e idempotente. Rechaza con `referencia_ausente` si el documento no tiene
        referencia, con `version_no_encontrada` si la versión no está registrada y con
        `no_es_base`/`incompatible` si el destino no es un almacén de la versión vigente: **ningún**
        rechazo modifica la autoridad ni el estado previo del índice.
        """
        ...


class StoreReadService(StoreReader, StoreHealth, Protocol):
    """Almacén de lectura con sonda de disponibilidad: contrato que exige `get_document` (`D-14`)."""

    ...
