# backend - ProjectHub API (placeholder)

Backend de ProjectHub en FastAPI (rulebook AGENTS.md, seccion 7). Esta carpeta
es un placeholder documentado: la fase 0 no incluye backend funcional
(docs/funcionalidades.md, item 10.3 "futuro"). Aqui vivira la API de
persistencia real cuando el proyecto la alcance.

## Contrato previsto

- FastAPI + Pydantic, persistencia a definir (DEC pendiente).
- Expone los agregados de `@projecthub/shared` (proyectos, etapas de trabajo,
  entregables, gates, usuarios, roles, bitacora) como recursos REST.
- La UI de Angular no consume esta API todavia: el estado vive en memoria con
  signals (item 10.1).

## Estado

- No hay codigo ejecutable en esta fase. No agregar dependencias ni servicios
  hasta que exista una especificacion (IMPL) que lo pida.
- Cuando arranque: `python -m venv .venv`, `pip install fastapi uvicorn`,
  `uvicorn app.main:app --reload --port 4500` (puerto por definir en DEC).
