"""Guard de ultimo Admin activo (hallazgo iteracion 50).

El sistema debe conservar siempre al menos un Admin activo: si el unico
Admin activo es desactivado o pierde el rol, ninguna cuenta podria volver
a administrar usuarios (ninguna ruta reactiva cuentas: solo acceso directo
a la base de datos). El guard vive en ServicioProyectos y cubre las dos
vias de edicion: PUT /api/sincronizacion (reemplazo total) y
PATCH /api/usuarios/{id}.
"""

import pytest
from fastapi.testclient import TestClient

from app.auth import CONTRASENA_DEMO_DEFAULT
from app.domain.errores import ErrorValidacion
from app.main import app
from app.semilla import USUARIOS_SEMILLA
from app.servicio import ServicioProyectos

client = TestClient(app, headers={"X-Actor-Id": "u-admin"})


@pytest.fixture(scope="module", autouse=True)
def _estado_restaurado():
    """Guarda el estado completo al entrar y lo restaura al salir para no
    contaminar los demas modulos (mismo patron que test_auth.py)."""
    estado = client.get("/api/sincronizacion").json()
    yield
    client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": "u-admin"})


def _login(correo: str, contrasena: str):
    return client.post("/api/auth/login", json={"correo": correo, "contrasena": contrasena})


def _admin():
    return next(u for u in USUARIOS_SEMILLA if "Admin" in u.roles)


def test_editar_usuario_rechaza_desactivar_ultimo_admin_activo():
    servicio = ServicioProyectos()
    with pytest.raises(ErrorValidacion) as exc:
        servicio.editar_usuario("u-admin", {"activo": False}, _admin())
    assert "al menos un Admin activo" in str(exc.value)


def test_editar_usuario_rechaza_quitar_rol_admin_al_ultimo_admin_activo():
    servicio = ServicioProyectos()
    with pytest.raises(ErrorValidacion) as exc:
        servicio.editar_usuario("u-admin", {"roles": ["Analista"]}, _admin())
    assert "al menos un Admin activo" in str(exc.value)


def test_editar_usuario_permite_desactivar_un_admin_con_otros_activos():
    servicio = ServicioProyectos()
    segundo = _admin().model_copy(
        update={"id": "u-admin2", "correo": "admin2@projecthub.local", "nombre": "Admin Dos"}
    )
    servicio._usuarios_agregar(segundo)
    servicio.editar_usuario("u-admin", {"activo": False}, _admin())
    diana = servicio.usuario_por_id("u-admin")
    assert diana is not None and diana.activo is False


def test_editar_usuario_no_activa_guard_si_usuario_ya_inactivo():
    # Reenviar la misma edicion a un usuario ya inactivo no debe bloquearse:
    # el guard solo aplica cuando se pasa de activo a inactivo (o se retira
    # el rol a un Admin activo).
    servicio = ServicioProyectos()
    servicio._repo.usuarios_reemplazar(
        [u if u.id != "u-admin" else u.model_copy(update={"activo": False}) for u in USUARIOS_SEMILLA]
    )
    servicio.editar_usuario("u-admin", {"activo": False}, _admin())
    diana = servicio.usuario_por_id("u-admin")
    assert diana is not None and diana.activo is False


def test_editar_usuario_permite_retirar_rol_admin_a_usuario_inactivo():
    servicio = ServicioProyectos()
    segundo = _admin().model_copy(
        update={"id": "u-admin2", "correo": "admin2b@projecthub.local", "nombre": "Admin Dos"}
    )
    servicio._usuarios_agregar(segundo)
    servicio.editar_usuario("u-admin", {"activo": False}, _admin())
    servicio.editar_usuario("u-admin", {"roles": ["Analista"]}, _admin())
    diana = servicio.usuario_por_id("u-admin")
    assert diana is not None and "Analista" in diana.roles and "Admin" not in diana.roles


def test_sincronizacion_reemplazo_rechaza_estado_sin_admin_activo():
    servicio = ServicioProyectos()
    entrantes = [
        u if u.id != "u-admin" else u.model_copy(update={"activo": False}) for u in USUARIOS_SEMILLA
    ]
    with pytest.raises(ErrorValidacion) as exc:
        servicio.escribir_estado_completo(
            {
                "usuarios": [u.model_dump(mode="json", by_alias=True) for u in entrantes],
                "proyectos": [],
                "etapas": [],
                "entregables": [],
                "bitacora": [],
            },
            _admin().id,
        )
    assert "al menos un Admin activo" in str(exc.value)


def test_sincronizacion_reemplazo_acepta_estado_con_admin_activo():
    servicio = ServicioProyectos()
    entrantes = [
        u if u.id != "u-analista" else u.model_copy(update={"activo": False}) for u in USUARIOS_SEMILLA
    ]
    estado = servicio.escribir_estado_completo(
        {
            "usuarios": [u.model_dump(mode="json", by_alias=True) for u in entrantes],
            "proyectos": [p.model_dump(mode="json", by_alias=True) for p in servicio.proyectos()],
            "etapas": [e.model_dump(mode="json", by_alias=True) for e in servicio.etapas()],
            "entregables": [e.model_dump(mode="json", by_alias=True) for e in servicio.entregables()],
            "bitacora": [b.model_dump(mode="json", by_alias=True) for b in servicio.bitacora()],
        },
        _admin().id,
    )
    analista = next(u for u in estado["usuarios"] if u["id"] == "u-analista")
    assert analista["activo"] is False


# ---------- Via HTTP (reproduce el hallazgo de la iteracion 50) ----------


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_api_desactivar_ultimo_admin_por_sincronizacion_responde_422():
    # Hallazgo iteracion 50: un Admin podia desactivarse a si mismo y a los
    # demas Admins via PUT /api/sincronizacion, dejando al sistema sin
    # ninguna via de reactivacion. Ahora el guard responde 422.
    admin_token = _login("diana@projecthub.local", CONTRASENA_DEMO_DEFAULT).json()["token"]
    usuarios = client.get("/api/usuarios").json()
    diana = next(u for u in usuarios if u["correo"] == "diana@projecthub.local")
    diana["activo"] = False
    otros_admins = [u for u in usuarios if u["id"] != diana["id"] and "Admin" in u.get("roles", [])]
    for u in otros_admins:
        u["activo"] = False
    sincronizar = client.put(
        "/api/sincronizacion",
        json={
            "usuarios": usuarios,
            "proyectos": client.get("/api/proyectos").json(),
            "etapas": client.get("/api/etapas").json(),
            "entregables": client.get("/api/entregables").json(),
            "bitacora": client.get("/api/bitacora").json(),
        },
        headers=_bearer(admin_token),
    )
    assert sincronizar.status_code == 422
    assert "al menos un Admin activo" in sincronizar.json()["mensaje"]
    # Diana sigue activa: el estado no fue reemplazado.
    me = client.get("/api/auth/me", headers=_bearer(admin_token))
    assert me.status_code == 200


def test_api_desactivar_admin_con_otros_activos_responde_200():
    # Con otro Admin activo (semilla, pues solo semilla administra usuarios:
    # proteccion preexistente contra X-Actor-Id suplantado), desactivar a
    # Diana es valido. Se promueve a u-doble (semilla, doble rol) a Admin.
    usuarios = client.get("/api/usuarios").json()
    doble = next(u for u in usuarios if u["id"] == "u-doble")
    doble["roles"] = [*doble["roles"], "Admin"]
    promovido = client.put(
        "/api/sincronizacion",
        json={
            "usuarios": usuarios,
            "proyectos": client.get("/api/proyectos").json(),
            "etapas": client.get("/api/etapas").json(),
            "entregables": client.get("/api/entregables").json(),
            "bitacora": client.get("/api/bitacora").json(),
        },
    )
    assert promovido.status_code == 200
    usuarios = client.get("/api/usuarios").json()
    diana = next(u for u in usuarios if u["correo"] == "diana@projecthub.local")
    diana["activo"] = False
    sincronizar = client.put(
        "/api/sincronizacion",
        json={
            "usuarios": usuarios,
            "proyectos": client.get("/api/proyectos").json(),
            "etapas": client.get("/api/etapas").json(),
            "entregables": client.get("/api/entregables").json(),
            "bitacora": client.get("/api/bitacora").json(),
        },
    )
    assert sincronizar.status_code == 200
    # Restaurar a Diana actuando como el otro Admin activo (Diana esta
    # inactiva y no puede ser actor del reemplazo).
    usuarios = client.get("/api/usuarios").json()
    diana = next(u for u in usuarios if u["correo"] == "diana@projecthub.local")
    diana["activo"] = True
    restaurar = client.put(
        "/api/sincronizacion",
        json={
            "usuarios": usuarios,
            "proyectos": client.get("/api/proyectos").json(),
            "etapas": client.get("/api/etapas").json(),
            "entregables": client.get("/api/entregables").json(),
            "bitacora": client.get("/api/bitacora").json(),
        },
        headers={"X-Actor-Id": "u-doble"},
    )
    assert restaurar.status_code == 200
