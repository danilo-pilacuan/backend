# backend - ProjectHub API

Backend de ProjectHub en FastAPI (rulebook AGENTS.md, seccion 7). Implementa el
mismo dominio que `@projecthub/shared` (stores en memoria con signals): los
modelos, la semilla y las reglas de negocio son espejo una a una, y el contrato
JSON es camelCase identico (por ejemplo `patrocinadorId`, `presupuestoEstimado`).

## Ejecutar

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 4500
```

- `GET http://127.0.0.1:4500/api/salud` -> `{"estado":"ok",...}`
- Docs OpenAPI interactivas: `http://127.0.0.1:4500/docs`

## Autenticacion simulada

No hay sesiones reales todavia: cada peticion identifica al actor con el header
`X-Actor-Id` (id de usuario de la semilla, por ejemplo `u-admin`). Sin header la
API responde 422 con codigo `VALIDACION`; un actor desconocido responde 404.

## Arquitectura

```
app/
  main.py            app FastAPI + handlers de error
  semilla.py         datos semilla identicos a stores/semilla.ts de shared-lib
  servicio.py        ServicioProyectos: reglas de dominio en memoria
  domain/
    modelos.py       modelos Pydantic (base con alias camelCase)
    errores.py       ErrorDominio y subclases + CODIGOS_HTTP
    matriz_permisos.py  matriz rol x accion (fuente para tests)
    gates.py         checklist de gate y validacion de aprobaciones
  api/
    esquemas.py      cuerpos de peticion (alias camelCase)
    rutas.py         18 rutas REST bajo /api
```

Los errores de dominio se mapean a HTTP de forma determinista:
`404 ENTIDAD_NO_ENCONTRADA`, `409 DUPLICADO / PERMISO_DENEGADO /
ESTADO_PROYECTO / TRANSICION_INVALIDA`, `422 VALIDACION` (incluye gate cerrado).
El cuerpo de error es siempre `{"codigo": "...", "mensaje": "..."}`.

## Tests

```bash
.venv\Scripts\python -m pytest -q
```

43 tests: dominio puro (24) y API HTTP con TestClient (19). Cubren transiciones
de ciclo de vida, gates (entregables + aprobaciones, autor no aprueba propio),
matriz de permisos por etapa, avance ponderado, presupuesto y unicidad de
correo case-insensitive.

## Puerto

4500 (el host shell y los MFEs usan 4300-4304). El frontend todavia no consume
esta API: los stores de `@projecthub/shared` siguen siendo la fuente de estado
en el navegador hasta integrar la capa HTTP (ver docs/funcionalidades.md 10.3).
