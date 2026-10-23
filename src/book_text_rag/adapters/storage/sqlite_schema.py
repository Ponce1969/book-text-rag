"""Esquema físico del diseño aprobado: definición declarada, modelo esperado y validación del destino.

Separado de `sqlite.py` (incrementos A y B2 de la división por responsabilidades): aquí vive **todo**
lo que conoce el esquema físico —las constantes literales, el `DDL`, el modelo esperado por tabla, los
validadores estructurales y las funciones de apertura y de evidencia del destino— y, desde B2, las
**primitivas de consulta compartidas** que necesitan por igual el camino de lectura y la reconstrucción
del índice derivado, de modo que la dirección de dependencias siga siendo acíclica. **Nada** de las
operaciones del adaptador vive aquí. `sqlite.py` reexporta los nombres que consumen las pruebas.

**Compatibility no es «tener los nombres»:** la estructura efectiva se valida con las `PRAGMA` del
motor (columnas, tipos, `NOT NULL`, posición en la PK, unicidades, claves foráneas e índices nombrados)
y, para lo que ninguna `PRAGMA` expone —las restricciones `CHECK` y el tokenizer de FTS5—, con los
fragmentos de DDL que el propio adaptador emite, tomados de las **mismas constantes** que construyen el
esquema. Ningún objeto ajeno —tabla, **vista**, índice o **disparador**— se tolera.

La guarda de carrera de `_verificar_evidencia` **no** es una primitiva de bloqueo: `D-15` §9 dice que no
se diseña ninguna, y M-08 sigue sin mecanismo definido.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from book_text_rag.ports.storage import EstadoIngesta, StoreError, StoreErrorCode

SCHEMA_VERSION = 2
"""Versión del esquema físico. Todo cambio del esquema la incrementa; **no** hay migraciones."""

ESTADOS_INGESTA: tuple[str, ...] = (
    "decisión de identidad registrada",
    "ingesta incompleta",
    "ingesta completada e índice disponible para consulta",
)
"""Los tres valores nominales de `estado_ingesta`, **literales** de `D-13` (004:410-412)."""

_ESTADOS_SQL = ", ".join(f"'{valor}'" for valor in ESTADOS_INGESTA)
_HEX64 = "length({c}) = 64 AND {c} = lower({c}) AND {c} NOT GLOB '*[^0-9a-f]*'"

CHECK_ESTADO_INGESTA = f"CHECK (estado_ingesta IN ({_ESTADOS_SQL}))"
CHECK_HEX_VERSION = f"CHECK ({_HEX64.format(c='document_version')})"
CHECK_ORDINAL = "CHECK (ordinal >= 1)"
CHECK_BLOCK_TYPE = "CHECK (block_type IN ('prose', 'table'))"
CHECK_HEX_CONTENT_HASH = f"CHECK ({_HEX64.format(c='content_hash')})"
CHECK_ANCHOR_LEVEL = "CHECK (anchor_level IN ('posicional', 'pagina+tipografia'))"
CHECK_DESTINATION_USE = "CHECK (destination_use IN ('valid', 'scale_corrected', 'unusable'))"
CHECK_ANOMALIAS_TIPO = "CHECK (json_type(paginas_anomalas) = 'array')"
CHECK_ANOMALIAS_RECUENTO = "CHECK (recuento_anomalias_pagina = json_array_length(paginas_anomalas))"
TOKENIZER_FTS = "unicode61 remove_diacritics 2"
TOKENIZE_FTS = f"tokenize = '{TOKENIZER_FTS}'"

SQLITE_VEC_PIN = "0.1.9"
"""Pin declarado por `D-02`: es el valor de la identidad (versión **fijada**), según `D-24`."""

TIPO_ASIGNACION_DELIBERADA = "deliberada"
"""Literal de `D-13` P7 para el camino con `document_id` explícito."""

DDL: tuple[str, ...] = (
    """
    CREATE TABLE fuente (
        document_id TEXT PRIMARY KEY NOT NULL,
        source_format TEXT,
        page_count INTEGER
    )
    """,
    f"""
    CREATE TABLE referencia_fuente (
        document_id TEXT NOT NULL REFERENCES fuente (document_id),
        alias TEXT NOT NULL,
        tipo_asignacion TEXT NOT NULL,
        fecha TEXT NOT NULL,
        estado_ingesta TEXT NOT NULL {CHECK_ESTADO_INGESTA},
        ubicacion_observada TEXT,
        PRIMARY KEY (document_id, alias)
    )
    """,
    f"""
    CREATE TABLE version_documento (
        document_id TEXT NOT NULL REFERENCES fuente (document_id),
        document_version TEXT NOT NULL {CHECK_HEX_VERSION},
        PRIMARY KEY (document_id, document_version)
    )
    """,
    f"""
    CREATE TABLE fragmento (
        document_id TEXT NOT NULL,
        document_version TEXT NOT NULL,
        ordinal INTEGER NOT NULL {CHECK_ORDINAL},
        chunk_id TEXT NOT NULL UNIQUE,
        section_path TEXT NOT NULL,
        level INTEGER NOT NULL,
        block_type TEXT NOT NULL {CHECK_BLOCK_TYPE},
        captions TEXT NOT NULL,
        pdf_page_start INTEGER,
        pdf_page_end INTEGER,
        content TEXT NOT NULL,
        content_hash TEXT NOT NULL {CHECK_HEX_CONTENT_HASH},
        anchor_level TEXT NOT NULL {CHECK_ANCHOR_LEVEL},
        PRIMARY KEY (document_id, document_version, ordinal),
        FOREIGN KEY (document_id, document_version)
            REFERENCES version_documento (document_id, document_version)
    )
    """,
    f"""
    CREATE TABLE anclaje_cache (
        document_id TEXT NOT NULL,
        document_version TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        page INTEGER NOT NULL,
        y0 REAL,
        y_dest REAL,
        destination_use TEXT NOT NULL {CHECK_DESTINATION_USE},
        PRIMARY KEY (document_id, document_version, ordinal),
        FOREIGN KEY (document_id, document_version, ordinal)
            REFERENCES fragmento (document_id, document_version, ordinal)
    )
    """,
    f"""
    CREATE TABLE construccion (
        construction_key INTEGER PRIMARY KEY,
        document_id TEXT NOT NULL,
        document_version TEXT NOT NULL,
        extractor_nombre TEXT NOT NULL,
        extractor_version TEXT NOT NULL,
        extractor_config_efectiva TEXT NOT NULL,
        geometry_tool TEXT NOT NULL,
        manifiesto_canonico TEXT NOT NULL,
        chunking_config_version TEXT NOT NULL,
        calibracion_procedimiento TEXT NOT NULL,
        calibracion_entradas INTEGER NOT NULL,
        calibracion_delta_pt REAL NOT NULL,
        calibracion_dispersion_pt REAL NOT NULL,
        calibracion_tolerancia_pt REAL NOT NULL,
        calibracion_banda_pt REAL NOT NULL,
        calibracion_umbral_tamano_pt REAL NOT NULL,
        escala_entradas_corregidas INTEGER NOT NULL,
        escala_factor REAL,
        escala_residuo_max_pt REAL,
        escala_destinos_inutilizables INTEGER NOT NULL,
        recuento_unidades_corpus INTEGER NOT NULL,
        recuento_ancladas_por_nivel TEXT NOT NULL,
        recuento_fragmentos INTEGER NOT NULL,
        recuento_bloques_tabla INTEGER NOT NULL,
        recuento_lineas_excluidas INTEGER NOT NULL,
        recuento_anomalias_pagina INTEGER NOT NULL {CHECK_ANOMALIAS_RECUENTO},
        paginas_anomalas TEXT NOT NULL {CHECK_ANOMALIAS_TIPO},
        tokenizer TEXT NOT NULL,
        sqlite_version TEXT NOT NULL,
        sqlite_vec_version TEXT NOT NULL,
        FOREIGN KEY (document_id, document_version)
            REFERENCES version_documento (document_id, document_version)
    )
    """,
    """
    CREATE INDEX idx_version_documento_document_version
        ON version_documento (document_version)
    """,
    """
    CREATE INDEX idx_construccion_version
        ON construccion (document_id, document_version)
    """,
    f"""
    CREATE VIRTUAL TABLE fragmento_fts USING fts5 (
        document_id UNINDEXED,
        document_version UNINDEXED,
        ordinal UNINDEXED,
        content,
        {TOKENIZE_FTS}
    )
    """,
)
"""Sentencias del esquema físico. `fragmento_fts` se declara con el tokenizer de `D-10`/PD-13."""


@dataclass(frozen=True)
class _Columna:
    """Columna esperada: nombre, tipo declarado, obligatoriedad y posición en la clave primaria."""

    nombre: str
    tipo: str
    not_null: bool
    pk: int = 0


def _col(nombre: str, tipo: str, not_null: bool = True, pk: int = 0) -> _Columna:
    return _Columna(nombre=nombre, tipo=tipo, not_null=not_null, pk=pk)


COLUMNAS_ESPERADAS: dict[str, tuple[_Columna, ...]] = {
    "fuente": (
        _col("document_id", "TEXT", pk=1),
        _col("source_format", "TEXT", not_null=False),
        _col("page_count", "INTEGER", not_null=False),
    ),
    "referencia_fuente": (
        _col("document_id", "TEXT", pk=1),
        _col("alias", "TEXT", pk=2),
        _col("tipo_asignacion", "TEXT"),
        _col("fecha", "TEXT"),
        _col("estado_ingesta", "TEXT"),
        _col("ubicacion_observada", "TEXT", not_null=False),
    ),
    "version_documento": (
        _col("document_id", "TEXT", pk=1),
        _col("document_version", "TEXT", pk=2),
    ),
    "fragmento": (
        _col("document_id", "TEXT", pk=1),
        _col("document_version", "TEXT", pk=2),
        _col("ordinal", "INTEGER", pk=3),
        _col("chunk_id", "TEXT"),
        _col("section_path", "TEXT"),
        _col("level", "INTEGER"),
        _col("block_type", "TEXT"),
        _col("captions", "TEXT"),
        _col("pdf_page_start", "INTEGER", not_null=False),
        _col("pdf_page_end", "INTEGER", not_null=False),
        _col("content", "TEXT"),
        _col("content_hash", "TEXT"),
        _col("anchor_level", "TEXT"),
    ),
    "anclaje_cache": (
        _col("document_id", "TEXT", pk=1),
        _col("document_version", "TEXT", pk=2),
        _col("ordinal", "INTEGER", pk=3),
        _col("page", "INTEGER"),
        _col("y0", "REAL", not_null=False),
        _col("y_dest", "REAL", not_null=False),
        _col("destination_use", "TEXT"),
    ),
    # `construction_key` es alias de `rowid`: SQLite informa `notnull = 0` aunque sea la PK.
    "construccion": (
        _col("construction_key", "INTEGER", not_null=False, pk=1),
        _col("document_id", "TEXT"),
        _col("document_version", "TEXT"),
        _col("extractor_nombre", "TEXT"),
        _col("extractor_version", "TEXT"),
        _col("extractor_config_efectiva", "TEXT"),
        _col("geometry_tool", "TEXT"),
        _col("manifiesto_canonico", "TEXT"),
        _col("chunking_config_version", "TEXT"),
        _col("calibracion_procedimiento", "TEXT"),
        _col("calibracion_entradas", "INTEGER"),
        _col("calibracion_delta_pt", "REAL"),
        _col("calibracion_dispersion_pt", "REAL"),
        _col("calibracion_tolerancia_pt", "REAL"),
        _col("calibracion_banda_pt", "REAL"),
        _col("calibracion_umbral_tamano_pt", "REAL"),
        _col("escala_entradas_corregidas", "INTEGER"),
        _col("escala_factor", "REAL", not_null=False),
        _col("escala_residuo_max_pt", "REAL", not_null=False),
        _col("escala_destinos_inutilizables", "INTEGER"),
        _col("recuento_unidades_corpus", "INTEGER"),
        _col("recuento_ancladas_por_nivel", "TEXT"),
        _col("recuento_fragmentos", "INTEGER"),
        _col("recuento_bloques_tabla", "INTEGER"),
        _col("recuento_lineas_excluidas", "INTEGER"),
        _col("recuento_anomalias_pagina", "INTEGER"),
        _col("paginas_anomalas", "TEXT"),
        _col("tokenizer", "TEXT"),
        _col("sqlite_version", "TEXT"),
        _col("sqlite_vec_version", "TEXT"),
    ),
}
"""Columnas esperadas por tabla, **en orden**, con tipo declarado, `NOT NULL` y posición en la PK."""

TABLAS_ESPERADAS = frozenset(COLUMNAS_ESPERADAS) | {"fragmento_fts"}
"""Tablas del esquema aprobado. `fragmento_fts` es la estructura **derivada** FTS5."""

INDICES_ESPERADOS = frozenset(
    {
        "idx_version_documento_document_version",
        "idx_construccion_version",
    }
)
"""Índices **nombrados** del esquema. Los `sqlite_autoindex_*` del motor no se enumeran."""

PREFIJO_SOMBRA_FTS = "fragmento_fts_"
"""Tablas internas que crea FTS5; no cuentan como objetos ajenos."""

PREFIJO_AUTOINDICE = "sqlite_autoindex_"
"""Índices internos de `UNIQUE` y de PK compuesta; se validan por estructura, no por nombre."""

UNICOS_ESPERADOS: dict[str, frozenset[frozenset[str]]] = {
    "fuente": frozenset({frozenset({"document_id"})}),
    "referencia_fuente": frozenset({frozenset({"document_id", "alias"})}),
    "version_documento": frozenset({frozenset({"document_id", "document_version"})}),
    "fragmento": frozenset(
        {
            frozenset({"document_id", "document_version", "ordinal"}),
            frozenset({"chunk_id"}),
        }
    ),
    "anclaje_cache": frozenset({frozenset({"document_id", "document_version", "ordinal"})}),
    "construccion": frozenset(),
}
"""Conjuntos de columnas con unicidad **por tabla**. `D-5`: ninguna sobre `document_version` sola."""

FORANEAS_ESPERADAS: dict[str, frozenset[tuple[str, str, str]]] = {
    "fuente": frozenset(),
    "referencia_fuente": frozenset({("fuente", "document_id", "document_id")}),
    "version_documento": frozenset({("fuente", "document_id", "document_id")}),
    "fragmento": frozenset(
        {
            ("version_documento", "document_id", "document_id"),
            ("version_documento", "document_version", "document_version"),
        }
    ),
    "anclaje_cache": frozenset(
        {
            ("fragmento", "document_id", "document_id"),
            ("fragmento", "document_version", "document_version"),
            ("fragmento", "ordinal", "ordinal"),
        }
    ),
    "construccion": frozenset(
        {
            ("version_documento", "document_id", "document_id"),
            ("version_documento", "document_version", "document_version"),
        }
    ),
}
"""(tabla destino, columna origen, columna destino) por tabla. La dependencia es de un solo sentido."""

DDL_REQUERIDO: dict[str, tuple[str, ...]] = {
    "fuente": (),
    "referencia_fuente": (CHECK_ESTADO_INGESTA,),
    "version_documento": (CHECK_HEX_VERSION,),
    "fragmento": (CHECK_ORDINAL, CHECK_BLOCK_TYPE, CHECK_HEX_CONTENT_HASH, CHECK_ANCHOR_LEVEL),
    "anclaje_cache": (CHECK_DESTINATION_USE,),
    "construccion": (CHECK_ANOMALIAS_RECUENTO, CHECK_ANOMALIAS_TIPO),
    "fragmento_fts": ("fts5", TOKENIZER_FTS),
}
"""Lo que **ninguna** `PRAGMA` expone: restricciones `CHECK` y tokenizer. Mismas constantes del DDL."""


@dataclass(frozen=True)
class _Evidence:
    """Estado observado del destino. Se compara para detectar cambios entre inspección y escritura."""

    existe: bool
    tamano: int
    mtime_ns: int
    user_version: int
    objetos: tuple[tuple[str, str, str], ...]
    valido: bool


def _normalizar(sql: str) -> str:
    return " ".join(sql.split())


def _nombres(evidencia: _Evidence, tipo: str) -> frozenset[str]:
    return frozenset(nombre for clase, nombre, _ in evidencia.objetos if clase == tipo)


def _tablas_propias(evidencia: _Evidence) -> frozenset[str]:
    """Tablas del esquema, sin las sombras internas que FTS5 crea con el prefijo reservado."""
    return frozenset(n for n in _nombres(evidencia, "table") if not n.startswith(PREFIJO_SOMBRA_FTS))


def _objetos_ajenos(evidencia: _Evidence) -> frozenset[str]:
    """Cualquier objeto que no pertenezca al esquema: tablas, **vistas**, índices y **disparadores**."""
    return frozenset(
        nombre
        for _, nombre, _ in evidencia.objetos
        if nombre not in TABLAS_ESPERADAS
        and nombre not in INDICES_ESPERADOS
        and not nombre.startswith(PREFIJO_SOMBRA_FTS)
        and not nombre.startswith(PREFIJO_AUTOINDICE)
    )


def _columnas_coinciden(conexion: sqlite3.Connection, tabla: str, esperadas: tuple[_Columna, ...]) -> bool:
    filas = conexion.execute(f"PRAGMA table_info('{tabla}')").fetchall()
    if len(filas) != len(esperadas):
        return False
    for fila, esperada in zip(filas, esperadas, strict=True):
        if str(fila[1]) != esperada.nombre:
            return False
        if str(fila[2]).upper() != esperada.tipo:
            return False
        if bool(fila[3]) is not esperada.not_null:
            return False
        if fila[4] is not None:
            return False
        if int(fila[5]) != esperada.pk:
            return False
    return True


def _unicos_coinciden(conexion: sqlite3.Connection, tabla: str) -> bool:
    conjuntos: set[frozenset[str]] = set()
    filas = conexion.execute(f"PRAGMA index_list('{tabla}')").fetchall()
    for fila in filas:
        if not int(fila[2]):
            continue
        columnas = frozenset(str(c[2]) for c in conexion.execute(f"PRAGMA index_info('{fila[1]}')"))
        conjuntos.add(columnas)
    return frozenset(conjuntos) == UNICOS_ESPERADOS[tabla]


def _foraneas_coinciden(conexion: sqlite3.Connection, tabla: str) -> bool:
    filas = conexion.execute(f"PRAGMA foreign_key_list('{tabla}')").fetchall()
    presentes = frozenset((str(fila[2]), str(fila[3]), str(fila[4])) for fila in filas)
    return presentes == FORANEAS_ESPERADAS[tabla]


def _ddl_requerido_presente(evidencia: _Evidence) -> bool:
    por_nombre = {nombre: _normalizar(sql) for _, nombre, sql in evidencia.objetos}
    for objeto, fragmentos in DDL_REQUERIDO.items():
        sql = por_nombre.get(objeto)
        if sql is None:
            return False
        if not all(_normalizar(fragmento) in sql for fragmento in fragmentos):
            return False
    return True


def _estructura_valida(conexion: sqlite3.Connection, evidencia: _Evidence) -> bool:
    """Valida la estructura **efectiva** del esquema aprobado. Un nombre igual no basta."""
    if _objetos_ajenos(evidencia):
        return False
    if _tablas_propias(evidencia) != TABLAS_ESPERADAS:
        return False
    if not _nombres(evidencia, "index") >= INDICES_ESPERADOS:
        return False
    for tabla, columnas in COLUMNAS_ESPERADAS.items():
        if not _columnas_coinciden(conexion, tabla, columnas):
            return False
        if not _unicos_coinciden(conexion, tabla):
            return False
        if not _foraneas_coinciden(conexion, tabla):
            return False
    return _ddl_requerido_presente(evidencia)


def _leer_estado(conexion: sqlite3.Connection, ruta: Path) -> tuple[int, tuple[tuple[str, str, str], ...]]:
    """Lee `user_version` y `sqlite_master`. Distingue el archivo inválido del error operativo."""
    try:
        fila = conexion.execute("PRAGMA user_version").fetchone()
        if fila is None:
            raise StoreError(StoreErrorCode.ERROR_SQLITE, "el motor no devolvió `user_version`", ruta=str(ruta))
        version = int(fila[0])
        filas = conexion.execute("SELECT type, name, sql FROM sqlite_master").fetchall()
    except sqlite3.OperationalError as error:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE, "el motor falló al inspeccionar el destino", ruta=str(ruta)
        ) from error
    except sqlite3.DatabaseError as error:
        raise StoreError(
            StoreErrorCode.NO_ES_BASE, "el destino no es una base SQLite válida", ruta=str(ruta)
        ) from error
    objetos = [
        (str(fila_objeto[0]), str(fila_objeto[1]), "" if fila_objeto[2] is None else str(fila_objeto[2]))
        for fila_objeto in filas
    ]
    return version, tuple(sorted(objetos))


def _abrir_solo_lectura(ruta: Path) -> sqlite3.Connection:
    """Abre en **solo lectura**: la inspección no puede escribir (condición de E4 y E5)."""
    try:
        return sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    except sqlite3.OperationalError as error:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE, "no se pudo abrir el destino en solo lectura", ruta=str(ruta)
        ) from error
    except sqlite3.DatabaseError as error:
        raise StoreError(
            StoreErrorCode.NO_ES_BASE, "el destino no es una base SQLite válida", ruta=str(ruta)
        ) from error


def _abrir_escritura(ruta: Path) -> sqlite3.Connection:
    try:
        return sqlite3.connect(ruta, isolation_level=None)
    except sqlite3.OperationalError as error:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE, "no se pudo abrir el destino para escritura", ruta=str(ruta)
        ) from error
    except sqlite3.DatabaseError as error:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE, "el motor rechazó la apertura del destino", ruta=str(ruta)
        ) from error


def _evidencia_de(ruta: Path) -> _Evidence:
    """Inspección en solo lectura. Un archivo arbitrario **no** se clasifica como almacén vacío."""
    if not ruta.exists():
        return _Evidence(False, 0, 0, 0, (), False)
    conexion = _abrir_solo_lectura(ruta)
    try:
        version, objetos = _leer_estado(conexion, ruta)
        preliminar = _Evidence(True, 0, 0, version, objetos, False)
        valido = _estructura_valida(conexion, preliminar)
    finally:
        conexion.close()
    estado = ruta.stat()
    return _Evidence(True, estado.st_size, estado.st_mtime_ns, version, objetos, valido)


def _verificar_evidencia(esperada: _Evidence, actual: _Evidence, ruta: Path) -> None:
    """Guarda de evidencia: el destino debe seguir **sin objetos** y sin versión. **No** es un bloqueo.

    **Garantía y ventana residual.** Corre **dentro** de la transacción, inmediatamente después de
    `BEGIN IMMEDIATE`: **reduce** la ventana entre la inspección y la escritura y **detecta más cambios**
    que una comprobación previa al bloqueo, pero **no elimina la carrera**. Siguen siendo posibles
    (a) un cambio que deje **idéntica** la evidencia comparada —mismo tamaño, `mtime`, `user_version` y
    objetos— y (b) cualquier escritor que **no respete los bloqueos de SQLite**: la exclusión es de
    SQLite sobre este archivo y solo mientras el bloqueo está tomado. La **exclusión entre escritores**
    (M-08) **no tiene mecanismo definido**: `D-15` §9 declara que no se diseña primitiva de bloqueo.
    """
    if not actual.existe:
        raise StoreError(StoreErrorCode.DESTINO_CAMBIADO, "el destino dejó de existir", ruta=str(ruta))
    if esperada.existe and (actual.tamano, actual.mtime_ns) != (esperada.tamano, esperada.mtime_ns):
        raise StoreError(
            StoreErrorCode.DESTINO_CAMBIADO,
            "el destino cambió entre la inspección y la inicialización",
            ruta=str(ruta),
        )
    if actual.user_version != 0 or actual.objetos:
        raise StoreError(
            StoreErrorCode.DESTINO_CAMBIADO,
            "el destino contiene objetos o una versión inesperados",
            ruta=str(ruta),
        )


def _abrir_lectura_valida(ruta: Path) -> sqlite3.Connection:
    """Abre en **solo lectura** y exige el almacén de la versión vigente. Nunca escribe."""
    if not ruta.exists():
        raise StoreError(StoreErrorCode.NO_ES_BASE, "el destino no existe", ruta=str(ruta))
    conexion = _abrir_solo_lectura(ruta)
    try:
        version, objetos = _leer_estado(conexion, ruta)
        preliminar = _Evidence(True, 0, 0, version, objetos, False)
        if version != SCHEMA_VERSION or not _estructura_valida(conexion, preliminar):
            raise StoreError(
                StoreErrorCode.INCOMPATIBLE,
                "el destino no es un almacén de la versión vigente",
                ruta=str(ruta),
                user_version=version,
                version_esperada=SCHEMA_VERSION,
            )
    except Exception:
        conexion.close()
        raise
    return conexion


def _evidencia_de_conexion(conexion: sqlite3.Connection, ruta: Path) -> _Evidence:
    version, objetos = _leer_estado(conexion, ruta)
    if not ruta.exists():
        return _Evidence(False, 0, 0, version, objetos, False)
    estado = ruta.stat()
    return _Evidence(True, estado.st_size, estado.st_mtime_ns, version, objetos, False)


# --- Primitivas de consulta compartidas ----------------------------------------------------------
#
# Trasladadas desde `sqlite.py` en el incremento B2: las usa el camino de lectura y verificacion y
# tambien la reconstruccion del indice derivado, que vive en `sqlite_write.py`. Se alojan aqui para que
# la direccion de dependencias siga siendo aciclica: `sqlite` -> `sqlite_write` -> `sqlite_schema`.


def _consultar(
    conexion: sqlite3.Connection, sql: str, parametros: tuple[object, ...], contexto: str
) -> list[tuple[object, ...]]:
    """Ejecuta una lectura y envuelve el fallo del motor en un error explícito del almacén."""
    try:
        return [tuple(fila) for fila in conexion.execute(sql, parametros).fetchall()]
    except sqlite3.DatabaseError as error:
        raise StoreError(StoreErrorCode.ERROR_SQLITE, contexto) from error


def _entero(valor: object, columna: str) -> int:
    """Entero leído del almacén; un tipo inesperado es un fallo explícito, nunca una coerción muda."""
    if isinstance(valor, int):
        return valor
    raise StoreError(StoreErrorCode.ERROR_SQLITE, "el almacén devolvió un valor no entero", columna=columna)


def _estado_de_ingesta(valor: object) -> EstadoIngesta:
    try:
        return EstadoIngesta(str(valor))
    except ValueError as error:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE, "el almacén tiene un estado de ingesta desconocido", obtenido=str(valor)
        ) from error


def _referencias(conexion: sqlite3.Connection, document_id: str) -> tuple[tuple[str, EstadoIngesta], ...]:
    """Referencias del documento con su estado (`D-13`), ordenadas por alias."""
    filas = _consultar(
        conexion,
        "SELECT alias, estado_ingesta FROM referencia_fuente WHERE document_id = ? ORDER BY alias",
        (document_id,),
        "el motor falló al leer las referencias del documento",
    )
    return tuple((str(fila[0]), _estado_de_ingesta(fila[1])) for fila in filas)


def _version_registrada(conexion: sqlite3.Connection, document_id: str, document_version: str) -> bool:
    """`True` si la versión está registrada. **Cero** fragmentos es legítimo (`C-14`), no ausencia."""
    filas = _consultar(
        conexion,
        "SELECT 1 FROM version_documento WHERE document_id = ? AND document_version = ?",
        (document_id, document_version),
        "el motor falló al comprobar la versión",
    )
    return bool(filas)
