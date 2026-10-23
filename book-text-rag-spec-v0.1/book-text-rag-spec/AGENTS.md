# Instrucciones para agentes — book-text-rag

## Antes de actuar
1. Lee `README.md` y todos los documentos de `docs/spec/`.
2. Identifica si la tarea corresponde a la fase aprobada. Si no está claro, pregunta antes de modificar.
3. Presenta un plan corto antes de cambios que afecten arquitectura, contratos, almacenamiento o datos.
4. No implementes toda la hoja de ruta de una vez. Trabaja en incrementos pequeños y verificables.

## Límites del proyecto
- Este repositorio es independiente de `book-graph-rag`; no modifiques ese proyecto ni dupliques su grafo, extracción de entidades, comunidades o evaluaciones.
- No diseñes todavía `agent-memory`; solo deja interfaces desacopladas cuando estén justificadas.
- No ejecutes modelos de IA localmente en la Orange Pi para embeddings o generación. La generación de embeddings, si se elige, será mediante proveedor externo durante la ingesta; no regenerar vectores en cada consulta.
- No añadas reranking, contextual retrieval, query rewriting, caché semántica, agentes autónomos ni enrutamiento entre sistemas al MVP.
- No añadas servicios/contendores o dependencias hasta justificar qué requisito cubren.
- MCP de lectura para agentes por defecto. La ingesta, reindexación y otras operaciones de escritura son administrativas y no deben exponerse como herramientas abiertas a cualquier consumidor.

## Reglas de ingeniería
- Python 3.13; usar `uv` exclusivamente para dependencias, entorno, ejecución y lockfile. No usar `pip` como flujo de proyecto.
- Definir dependencias y configuración en `pyproject.toml`; mantener lockfile versionado.
- Pydantic v2 para contratos y validación.
- FastAPI para API HTTP; adaptar MCP mediante su adaptador, sin duplicar casos de uso.
- Ruff, MyPy estricto y pytest. No introducir `Any` salvo justificación documentada.
- Separar dominio, aplicación, puertos y adaptadores. El dominio y los casos de uso no importan FastAPI, SDK MCP, clientes de base de datos ni SDK de proveedores.
- No guardar secretos en código, archivos de configuración versionados, logs o mensajes de error. No imprimir variables de entorno ni contenido de `.env`.
- Errores explícitos y tipados; no ocultar fallos de indexación ni devolver resultados parciales como si fueran completos.
- No realizar borrados, reindexaciones destructivas ni migraciones de datos sin autorización explícita.
- No introducir abstracciones genéricas que no tengan al menos un uso real y necesario.

## Modularidad y tamaño de los archivos
- Mantener los archivos de código habitualmente en torno a 400 líneas o menos, contando líneas en blanco y comentarios.
- Al acercarse a ese tamaño, evaluar si conviene extraer una responsabilidad funcional independiente; el objetivo es la legibilidad, la cohesión, las pruebas, la depuración y el mantenimiento.
- El tamaño es una señal para revisar el diseño, no una razón automática para dividir un archivo. No crear abstracciones, capas, archivos ni módulos solo para cumplir un número.
- Si superar las 400 líneas resulta razonable, explicar brevemente por qué y qué alternativas se evaluaron. No hay un máximo absoluto de 600 u 800 líneas: si un archivo crece considerablemente, justificarlo antes de seguir ampliándolo.
- Aplicar el mismo criterio de cohesión y legibilidad a los archivos de pruebas, sin exigir que todos tengan el mismo tamaño.
- No emprender refactorizaciones masivas de archivos existentes solo para ajustarlos a esta regla; respetar el alcance de la tarea autorizada.

## Cambios pequeños y auditables
Refuerza lo ya dispuesto en «Antes de actuar» 4 (incrementos pequeños y verificables) y en «Entregas» (cambios pequeños y localizados, sin refactors ajenos a la tarea).
- No incorporar trabajo ajeno al objetivo autorizado, aunque parezca una mejora conveniente.
- Si una tarea empieza a abarcar responsabilidades independientes, proponer su separación antes de ampliar el alcance.
- Si dividir el trabajo puede dejar el proyecto en un estado inconsistente o dificultar las pruebas, explicar el problema y proponer una alternativa.
- No asumir que una mejora de diseño, una refactorización o una decisión arquitectónica están autorizadas por el mero hecho de ser convenientes.

## Verificación mínima por cambio
Ejecutar las comprobaciones relevantes: formato/lint, tipos, tests y validación de arquitectura. Informar comandos ejecutados, resultados y limitaciones. No afirmar que una prueba pasó si no se ejecutó.

## Entregas
- Cambios pequeños y localizados; evitar refactors ajenos a la tarea.
- Actualizar documentación cuando cambie un contrato o una decisión.
- Al finalizar: resumir qué cambió, pruebas realizadas, decisiones pendientes y riesgos conocidos.
