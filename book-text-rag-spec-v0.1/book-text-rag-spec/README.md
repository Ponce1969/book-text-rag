# Book Text RAG — Especificación inicial

Estado: **Spec v0.1 — propuesta para revisión; no autoriza todavía una implementación completa.**

`book-text-rag` será un servicio independiente para recuperar evidencia textual de libros técnicos y exponerla a los agentes de `pi-dev`. Complementa al proyecto existente `book-graph-rag`; no lo reemplaza ni modifica.

## Documentos

- `AGENTS.md`: reglas operativas para los agentes que trabajen en este repositorio.
- `docs/spec/001-architecture.md`: propósito, límites, arquitectura y contratos.
- `docs/spec/002-mvp.md`: alcance y fases de implementación.
- `docs/spec/003-evaluation.md`: evaluación de recuperación y criterios de aceptación.
- `docs/spec/004-decisions.md`: decisiones tomadas y cuestiones que deben resolverse con evidencia.

## Regla de trabajo

Leer todos los documentos antes de implementar. Primero revisar coherencia, riesgos y decisiones abiertas. No comenzar a programar hasta que el propietario apruebe la selección de almacenamiento e ingesta del primer libro. No reabrir decisiones ya cerradas sin evidencia concreta.

## Principio central

Una sola lógica de aplicación; tres adaptadores de entrada independientes: CLI, API HTTP y MCP. El contenido original, su procedencia y la configuración de indexación deben seguir siendo trazables. No introducir componentes avanzados por anticipación.
