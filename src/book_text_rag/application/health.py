"""Salud del almacén: política de arranque sin índice disponible (`D-14`), en **solo lectura**.

`D-14` decide que el servicio **no** termina cuando el índice no está disponible: arranca y permanece
en ejecución en estado degradado, `health` informa el resumen y las consultas responden
`index_unavailable`. La disponibilidad se **re-valida** en cada operación que la necesita (R1), de modo
que un almacén creado o reparado después se resuelve en la ruta de consulta **sin reiniciar** el
proceso.

Lo que este módulo **no** hace: no crea ni modifica el almacén, no registra transiciones (`D-14`
ítem 5, pendiente de una decisión operativa sobre el destino de logging), no comprueba integridad de
contenido —eso es `verify`, O(N), y `D-15` §7 lo sitúa fuera de una consulta— y no publica la clase de
causa.
"""

from __future__ import annotations

from book_text_rag.domain.availability import HealthSummary
from book_text_rag.ports.storage import StoreError, StoreErrorCode, StoreHealth


def health(store: StoreHealth) -> HealthSummary:
    """Devuelve el resumen autorizado por `D-14`, re-validando la disponibilidad en esta llamada."""
    return HealthSummary.desde(store.probe_availability())


def exigir_disponible(store: StoreHealth) -> None:
    """Impide servir consultas sobre un almacén no disponible, con el código `index_unavailable`.

    Es el único código de esta condición (`D-14` ítem 6): no se usa `mode_not_available` —que describe
    los modos no implementados sobre un índice sano— ni `not_indexed` —que describe una versión no
    incorporada sobre un índice sano—. Cualquier otro fallo del camino de lectura conserva su código
    propio: esta guarda no lo enmascara.
    """
    if not store.probe_availability().disponible:
        raise StoreError(
            StoreErrorCode.INDEX_UNAVAILABLE,
            "el almacén no es válido y utilizable para el modo lexical",
        )
