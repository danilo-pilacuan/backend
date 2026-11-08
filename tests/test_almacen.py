"""Pruebas de la capa de persistencia (DEC-006).

Cubren RepositorioMemoria (default sin DATABASE_URL) y, si Docker tiene
Postgres en localhost:5433 con la BD efimera projecthub_test, el roundtrip
completo de RepositorioPostgres: esquema, semilla idempotente, agregados y
reemplazos. Si Postgres no esta disponible los tests de roundtrip se saltan.
"""

import os

import pytest

from app.almacen import RepositorioMemoria, RepositorioPostgres
from app.domain.modelos import (
    Usuario,
)
from app.semilla import (
    BITACORA_SEMILLA,
    ENTREGABLES_SEMILLA,
    ETAPAS_SEMILLA,
    PROYECTOS_SEMILLA,
    USUARIOS_SEMILLA,
)

DSN_TEST = os.environ.get(
    "DATABASE_URL_TEST",
    "postgresql://projecthub:cambiar@localhost:5433/projecthub_test",
)


def _hay_postgres() -> bool:
    try:
        import psycopg

        conn = psycopg.connect(DSN_TEST, autocommit=True, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


NECESITA_POSTGRES = pytest.mark.skipif(not _hay_postgres(), reason="PostgreSQL no disponible en localhost:5433")


# ---------- RepositorioMemoria ----------


def test_memoria_carga_semilla_completa() -> None:
    repo = RepositorioMemoria(con_semilla=True)
    assert len(repo.usuarios()) == len(USUARIOS_SEMILLA)
    assert len(repo.proyectos()) == len(PROYECTOS_SEMILLA)
    assert len(repo.etapas()) == len(ETAPAS_SEMILLA)
    assert len(repo.entregables()) == len(ENTREGABLES_SEMILLA)
    assert len(repo.bitacora()) == len(BITACORA_SEMILLA)


def test_memoria_vacia_sin_semilla() -> None:
    repo = RepositorioMemoria(con_semilla=False)
    assert repo.usuarios() == []
    assert repo.proyectos() == []
    assert repo.etapas() == []
    assert repo.entregables() == []
    assert repo.bitacora() == []


def test_memoria_agregar_y_reemplazar() -> None:
    repo = RepositorioMemoria(con_semilla=False)
    usuario = Usuario(id="u-x", nombre="X", correo="x@x.com", roles=["Sponsor"], activo=True)
    repo.usuarios_agregar(usuario)
    assert [u.id for u in repo.usuarios()] == ["u-x"]

    otro = Usuario(id="u-y", nombre="Y", correo="y@x.com", roles=["ProjectManager"], activo=False)
    repo.usuarios_reemplazar([usuario, otro])
    assert sorted(u.id for u in repo.usuarios()) == ["u-x", "u-y"]

    repo.usuarios_reemplazar([otro])
    assert [u.id for u in repo.usuarios()] == ["u-y"]


def test_memoria_devuelve_listas_vivas() -> None:
    repo = RepositorioMemoria(con_semilla=False)
    lista = repo.proyectos()
    assert lista == []
    # El repositorio devuelve la lista viva: mutarla por fuera no es el caso
    # de uso del servicio (usa agregar/reemplazar), pero la identidad se
    # conserva para el getter del servicio en modo memoria.
    lista2 = repo.proyectos()
    assert lista is lista2


# ---------- RepositorioPostgres (requiere Docker) ----------


@NECESITA_POSTGRES
def test_pg_roundtrip_agregar_y_leer() -> None:
    repo = RepositorioPostgres(DSN_TEST)
    repo.crear_esquema()
    for nombre in ("usuarios", "proyectos", "etapas", "entregables", "bitacora"):
        repo._reemplazar_todo(nombre, [])

    usuario = Usuario(id="u-t1", nombre="T", correo="t@t.com", roles=["ProjectManager"], activo=True)
    repo.usuarios_agregar(usuario)
    leidos = repo.usuarios()
    assert len(leidos) == 1
    assert leidos[0] == usuario

    # Idempotencia del upsert: mismo id no duplica
    repo.usuarios_agregar(usuario)
    assert len(repo.usuarios()) == 1

    repo._reemplazar_todo("usuarios", [])


@NECESITA_POSTGRES
def test_pg_reemplazo_sincroniza_todo() -> None:
    repo = RepositorioPostgres(DSN_TEST)
    repo.crear_esquema()
    repo._reemplazar_todo("usuarios", [])

    a = Usuario(id="u-t2", nombre="A", correo="a@t.com", roles=["ProjectManager"], activo=True)
    b = Usuario(id="u-t3", nombre="B", correo="b@t.com", roles=["ProjectManager"], activo=True)
    repo.usuarios_reemplazar([a, b])
    assert sorted(u.id for u in repo.usuarios()) == ["u-t2", "u-t3"]

    # Reemplazo por otro contenido: sin eliminados previos no quedaria solo b
    repo.usuarios_reemplazar([b])
    assert [u.id for u in repo.usuarios()] == ["u-t3"]

    repo._reemplazar_todo("usuarios", [])


@NECESITA_POSTGRES
def test_pg_cargar_semilla_idempotente() -> None:
    repo = RepositorioPostgres(DSN_TEST)
    repo.crear_esquema()
    for nombre in ("usuarios", "proyectos", "etapas", "entregables", "bitacora"):
        repo._reemplazar_todo(nombre, [])

    repo.cargar_semilla()
    total1 = sum(len(repo._leer_todos(n)) for n in ("usuarios", "proyectos", "etapas", "entregables", "bitacora"))
    repo.cargar_semilla()
    total2 = sum(len(repo._leer_todos(n)) for n in ("usuarios", "proyectos", "etapas", "entregables", "bitacora"))
    assert total1 == total2
    assert len(repo.usuarios()) == len(USUARIOS_SEMILLA)


@NECESITA_POSTGRES
def test_pg_servicio_completo_sobre_postgres() -> None:
    from app.servicio import ServicioProyectos

    repo = RepositorioPostgres(DSN_TEST)
    repo.crear_esquema()
    for nombre in ("usuarios", "proyectos", "etapas", "entregables", "bitacora"):
        repo._reemplazar_todo(nombre, [])
    repo.cargar_semilla()

    servicio = ServicioProyectos(repo)
    admin = next(u for u in repo.usuarios() if u.id == "u-admin")
    pm = next(u for u in repo.usuarios() if u.id == "u-pm")
    proyecto = servicio.crear_proyecto(
        datos={
            "nombre": "PG Test",
            "descripcion": "proyecto desde repositorio postgres",
            "patrocinador_id": "u-sponsor",
        },
        actor=admin,
    )
    assert servicio.proyecto_por_id(proyecto.id) is not None
    # Persistido en BD, no solo en memoria
    assert any(p.id == proyecto.id for p in repo._leer_todos("proyectos"))

    etapa = servicio.crear_etapa(
        datos={
            "proyecto_id": proyecto.id,
            "nombre": "Analisis",
            "responsable_id": "u-analista",
            "fecha_inicio": "2025-01-10",
            "fecha_fin": "2025-02-20",
        },
        actor=pm,
    )
    assert any(e.id == etapa.id for e in repo._leer_todos("etapas"))

    # Bitacora registro el alta del proyecto
    entradas = repo._leer_todos("bitacora")
    assert any(b.proyecto_id == proyecto.id for b in entradas)

    for nombre in ("usuarios", "proyectos", "etapas", "entregables", "bitacora"):
        repo._reemplazar_todo(nombre, [])
