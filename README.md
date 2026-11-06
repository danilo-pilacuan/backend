# backend - ProjectHub API

Backend de ProjectHub en FastAPI (rulebook AGENTS.md, seccion 7). Implementa el
mismo dominio que `@projecthub/shared` (stores en memoria con signals): los
modelos, la semilla y las reglas de negocio son espejo una a una, y el contrato
JSON es camelCase identico (por ejemplo `patrocinadorId`, `presupuestoEstimado`).

## Ejecutar

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8100
```

- `GET http://127.0.0.1:8100/api/salud` -> `{"estado":"ok",...}`
- Docs OpenAPI interactivas: `http://127.0.0.1:8100/docs`

## Autenticacion simulada

No hay sesiones reales todavia: cada peticion identifica al actor con el header
`X-Actor-Id` (id de usuario de la semilla, por ejemplo `u-admin`). Sin header la
API responde 422 con codigo `VALIDACION`; un actor desconocido responde 404.

## Persistencia (DEC-006)

La capa de persistencia vive en `app/almacen.py` y se elige por variable de
entorno `DATABASE_URL`:

- **Sin `DATABASE_URL`**: `RepositorioMemoria` con semilla en cada arranque
  (comportamiento original, ideal para desarrollo rapido y tests).
- **Con `DATABASE_URL`**: `RepositorioPostgres` persiste cada entidad como
  JSONB en una tabla por coleccion (`usuarios`, `proyectos`, `etapas`,
  `entregables`, `bitacora`). Si Postgres no responde al arrancar, la API
  degrada a memoria con un warning en el log (no se tumba el servicio).

El `ServicioProyectos` no conoce SQL: accede al estado solo por el contrato del
repositorio (getters, `*_agregar`, `*_reemplazar`), por lo que agregar otra
implementacion (SQLite, REST remota) no toca las reglas de negocio.

### PostgreSQL en Docker

```bash
copy .env.example .env    # ajustar credenciales; .env esta en .gitignore
docker compose up -d      # postgres:17-alpine en localhost:5433
```

Despues arranca la API con la URL apuntando al contenedor:

```bash
set DATABASE_URL=postgresql://projecthub:cambiar@localhost:5433/projecthub
.venv\Scripts\python -m uvicorn app.main:app --port 8100
```

El esquema se crea solo en el arranque (`CREATE TABLE IF NOT EXISTS`) y la
semilla se carga una sola vez (las colecciones vacias se llenan; las que ya
tienen datos se respetan). El volumen `projecthub_pgdata` conserva los datos
entre reinicios del contenedor.

## Arquitectura

```
app/
  main.py            app FastAPI + eleccion de repositorio + handlers de error
  semilla.py         datos semilla identicos a stores/semilla.ts de shared-lib
  almacen.py         RepositorioMemoria y RepositorioPostgres (DEC-006)
  servicio.py        ServicioProyectos: reglas de dominio sobre el repositorio
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

76 tests: dominio puro, API HTTP con TestClient y capa de persistencia. Cubren
transiciones de ciclo de vida, gates (entregables + aprobaciones, autor no
aprueba propio), matriz de permisos por etapa, avance ponderado, presupuesto y
unicidad de correo case-insensitive.

`tests/test_almacen.py` cubre `RepositorioMemoria` (semilla, agregar,
reemplazar, listas vivas) y, si Docker tiene Postgres en localhost:5433, el
roundtrip completo de `RepositorioPostgres` (esquema, semilla idempotente,
upsert, reemplazo total y un ciclo crear-proyecto/etapa sobre BD real). Sin
Docker esos casos se saltan automaticamente.

## Puerto

8100 (el host shell y los MFEs usan 4300-4304; Postgres usa 5433 para no pisar
una instalacion local). Los stores de `@projecthub/shared` siguen siendo la
fuente de estado en el navegador hasta integrar la capa HTTP (ver
docs/funcionalidades.md 13.3).
