"""Tests de autenticacion (10.3, fase 14): login, JWT, me y fallback X-Actor-Id."""

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app.auth import (
    CONTRASENA_DEMO_DEFAULT,
    hash_contrasena,
    leer_token,
    verificar_contrasena,
)
from app.main import app, secreto_auth
from app.rate_limit import limitador

# GET/PUT de dominio exigen sesion (VULN-002): header por defecto de admin.
# Los tests anonimos usan el cliente anon (sin headers).
client = TestClient(app, headers={"X-Actor-Id": "u-admin"})
anon = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _estado_restaurado():
    """El estado de la app es un singleton en memoria compartido por los tests.

    Algunos tests de este modulo reemplazan colecciones (p. ej. eliminar un
    usuario via PUT /api/sincronizacion); aqui se guarda el estado completo al
    entrar y se restaura al salir para no contaminar los demas modulos.
    """
    estado = client.get("/api/sincronizacion").json()
    yield
    client.put(
        "/api/sincronizacion",
        json=estado,
        headers={"X-Actor-Id": "u-admin"},
    )


def _login(correo: str, contrasena: str):
    return client.post("/api/auth/login", json={"correo": correo, "contrasena": contrasena})


# ---------- Hash de contrasena ----------


def test_hash_contrasena_con_sal_y_verificacion():
    almacenado = hash_contrasena("secreto-1")
    assert almacenado != "secreto-1"
    assert almacenado.startswith("pbkdf2_sha256$")
    assert verificar_contrasena("secreto-1", almacenado)
    assert not verificar_contrasena("otra", almacenado)


def test_hash_contrasena_determinista_con_misma_sal():
    a = hash_contrasena("x", sal=bytes(16))
    b = hash_contrasena("x", sal=bytes(16))
    assert a == b


def test_verificar_contrasena_formato_corrupto_es_false():
    assert not verificar_contrasena("x", "no-es-un-hash")
    assert not verificar_contrasena("x", "sha256$1$ab$cd")


# ---------- Token ----------


def test_token_crea_y_lee_sub():
    token = client.post(  # sesion real de usuario de semilla
        "/api/auth/login",
        json={"correo": "diana@projecthub.local", "contrasena": CONTRASENA_DEMO_DEFAULT},
    ).json()["token"]
    assert leer_token(token, secreto_auth) == "u-admin"


def test_token_con_secreto_distinto_es_rechazado():
    token = client.post(
        "/api/auth/login",
        json={"correo": "diana@projecthub.local", "contrasena": CONTRASENA_DEMO_DEFAULT},
    ).json()["token"]
    assert leer_token(token, "otro-secreto-suficientemente-largo-para-hmac") is None


def test_token_expirado_es_rechazado():
    token = pyjwt.encode({"sub": "u-admin", "exp": 1}, secreto_auth, algorithm="HS256")
    assert leer_token(token, secreto_auth) is None


# ---------- Login ----------


def test_login_demo_de_semilla_devuelve_token_y_usuario():
    respuesta = _login("diana@projecthub.local", CONTRASENA_DEMO_DEFAULT)
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["tipo"] == "Bearer"
    assert datos["usuario"]["id"] == "u-admin"
    assert "token" in datos and datos["token"].count(".") == 2


def test_login_correo_insensible_a_mayusculas():
    respuesta = _login("Diana@ProjectHub.local", CONTRASENA_DEMO_DEFAULT)
    assert respuesta.status_code == 200


def test_login_contrasena_incorrecta_responde_401():
    respuesta = _login("diana@projecthub.local", "incorrecta")
    assert respuesta.status_code == 401
    assert respuesta.json()["detail"]["codigo"] == "CREDENCIALES_INVALIDAS"


def test_login_usuario_inexistente_responde_401():
    respuesta = _login("nadie@projecthub.local", CONTRASENA_DEMO_DEFAULT)
    assert respuesta.status_code == 401


def test_login_usuario_inactivo_responde_403():
    respuesta = _login("ivan@projecthub.local", CONTRASENA_DEMO_DEFAULT)
    assert respuesta.status_code == 403
    assert respuesta.json()["detail"]["codigo"] == "USUARIO_INACTIVO"


def test_login_limita_intentos_fallidos_responde_429():
    """VULN-003 mitigada: superado el maximo de fallos en la ventana, 429."""
    limitador.limpiar()
    correo = "diana@projecthub.local"
    for _ in range(5):
        fallo = _login(correo, "incorrecta")
        assert fallo.status_code == 401
    bloqueado = _login(correo, "incorrecta")
    assert bloqueado.status_code == 429
    assert bloqueado.json()["detail"]["codigo"] == "LIMITE_INTENTOS"
    # Incluso con la contrasena correcta el bloqueo sigue activo en la ventana.
    correcto = _login(correo, CONTRASENA_DEMO_DEFAULT)
    assert correcto.status_code == 429
    # Otras cuentas siguen operativas (la clave incluye el correo).
    otro = _login("paula@projecthub.local", CONTRASENA_DEMO_DEFAULT)
    assert otro.status_code == 200
    limitador.limpiar()


def test_login_exitoso_no_acumula_fallos():
    limitador.limpiar()
    correo = "paula@projecthub.local"
    for _ in range(4):
        assert _login(correo, "incorrecta").status_code == 401
        assert _login(correo, CONTRASENA_DEMO_DEFAULT).status_code == 200
    # El quinto fallo seria bloqueo si los exitos contaran; aqui todavia es 401.
    assert _login(correo, "incorrecta").status_code == 401
    limitador.limpiar()


# ---------- Sesion con token ----------


def test_me_con_token_devuelve_usuario():
    token = _login("paula@projecthub.local", CONTRASENA_DEMO_DEFAULT).json()["token"]
    respuesta = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == "u-pm"


def test_me_sin_token_responde_422_validacion():
    respuesta = anon.get("/api/auth/me")
    assert respuesta.status_code == 422
    assert respuesta.json()["codigo"] == "VALIDACION"


def test_token_invalido_en_ruta_protegida_responde_401_sesion_invalida():
    # Token presente pero invalido/expirado: 401 SESION_INVALIDA (no 422),
    # para que el cliente distinga sesion expirada de peticion anonima.
    respuesta = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer no-es-un-jwt"}
    )
    assert respuesta.status_code == 401
    assert respuesta.json()["detail"]["codigo"] == "SESION_INVALIDA"
    assert "expirado" in respuesta.json()["detail"]["mensaje"]


def test_token_de_usuario_eliminado_responde_401_sesion_invalida():
    # Caso borde 14.6: token firmado y vigente cuyo usuario ya no existe
    # (p. ej. eliminado por sincronizacion). La credencial no se puede
    # resolver: 401 SESION_INVALIDA, no 404. Autocontenido: crea su propio
    # usuario para no depender del orden de la suite.
    admin_token = _login("diana@projecthub.local", CONTRASENA_DEMO_DEFAULT).json()["token"]
    creada = client.post(
        "/api/usuarios",
        json={
            "nombre": "Usuario Efimero",
            "correo": "efimero@projecthub.local",
            "roles": ["Analista"],
            "activo": True,
        },
        headers=_bearer(admin_token),
    )
    assert creada.status_code == 201
    token = _login("efimero@projecthub.local", CONTRASENA_DEMO_DEFAULT).json()["token"]
    usuarios = client.get("/api/usuarios").json()
    restantes = [u for u in usuarios if u["correo"] != "efimero@projecthub.local"]
    sincronizar = client.put(
        "/api/sincronizacion",
        json={"usuarios": restantes, "proyectos": [], "etapas": [], "entregables": [], "bitacora": []},
        headers=_bearer(admin_token),
    )
    assert sincronizar.status_code == 200
    after = client.get("/api/auth/me", headers=_bearer(token))
    assert after.status_code == 401
    assert after.json()["detail"]["codigo"] == "SESION_INVALIDA"


def test_token_de_usuario_eliminado_responde_404():
    # Ruta de compatibilidad X-Actor-Id: sin token que resolver, un id de
    # usuario inexistente sigue siendo entidad no encontrada (404).
    respuesta = client.get("/api/auth/me", headers={"X-Actor-Id": "u-inexistente"})
    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ENTIDAD_NO_ENCONTRADA"


def test_rutas_protegidas_aceptan_token_en_lugar_de_x_actor_id():
    token = _login("paula@projecthub.local", CONTRASENA_DEMO_DEFAULT).json()["token"]
    respuesta = client.post(
        "/api/proyectos",
        json={"nombre": "Proyecto con token", "fechaObjetivo": "2027-01-01"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert respuesta.status_code == 201


def test_fallback_x_actor_id_sigue_funcionando():
    respuesta = client.get("/api/auth/me", headers={"X-Actor-Id": "u-admin"})
    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == "u-admin"


def test_usuario_nuevo_recibe_credencial_demo():
    admin_token = _login("diana@projecthub.local", CONTRASENA_DEMO_DEFAULT).json()["token"]
    creada = client.post(
        "/api/usuarios",
        json={"nombre": "Nueva Usuario", "correo": "nueva@projecthub.local", "roles": ["Analista"], "activo": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert creada.status_code == 201
    respuesta = _login("nueva@projecthub.local", CONTRASENA_DEMO_DEFAULT)
    assert respuesta.status_code == 200


def test_orden_activo_inactivo_en_login_error_primero():
    # Cubre el orden de las guardas: contrasena incorrecta en usuario inactivo
    # responde 401 (credenciales), no 403.
    respuesta = _login("ivan@projecthub.local", "incorrecta")
    assert respuesta.status_code == 401


# ---------- Cambio de contrasena (14.5) ----------


def _bearer(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


def test_cambio_contrasena_exitoso_y_persistente():
    token = _login("diana@projecthub.local", CONTRASENA_DEMO_DEFAULT).json()["token"]
    cambio = client.put(
        "/api/auth/contrasena",
        json={"contrasenaActual": CONTRASENA_DEMO_DEFAULT, "contrasenaNueva": "nueva-clave-145"},
        headers=_bearer(token),
    )
    assert cambio.status_code == 200
    assert cambio.json()["cambiada"] is True
    # La nueva credencial verifica y la vieja ya no (persistio el upsert).
    respuesta = _login("diana@projecthub.local", "nueva-clave-145")
    assert respuesta.status_code == 200
    respuesta = _login("diana@projecthub.local", CONTRASENA_DEMO_DEFAULT)
    assert respuesta.status_code == 401
    # Estado demo restaurado para el resto de la suite.
    client.put(
        "/api/auth/contrasena",
        json={"contrasenaActual": "nueva-clave-145", "contrasenaNueva": CONTRASENA_DEMO_DEFAULT},
        headers=_bearer(token),
    )


def test_cambio_contrasena_actual_incorrecta_responde_401():
    token = _login("paula@projecthub.local", CONTRASENA_DEMO_DEFAULT).json()["token"]
    cambio = client.put(
        "/api/auth/contrasena",
        json={"contrasenaActual": "no-es-mi-clave", "contrasenaNueva": "otra-clave-larga-1"},
        headers=_bearer(token),
    )
    assert cambio.status_code == 401
    assert cambio.json()["detail"]["codigo"] == "CONTRASENA_ACTUAL_INVALIDA"
    # La credencial demo sigue vigente tras el rechazo.
    assert _login("paula@projecthub.local", CONTRASENA_DEMO_DEFAULT).status_code == 200


def test_cambio_contrasena_nueva_corta_responde_422():
    token = _login("paula@projecthub.local", CONTRASENA_DEMO_DEFAULT).json()["token"]
    cambio = client.put(
        "/api/auth/contrasena",
        json={"contrasenaActual": CONTRASENA_DEMO_DEFAULT, "contrasenaNueva": "corta"},
        headers=_bearer(token),
    )
    assert cambio.status_code == 422


def test_cambio_contrasena_requiere_sesion():
    respuesta = anon.put(
        "/api/auth/contrasena",
        json={"contrasenaActual": CONTRASENA_DEMO_DEFAULT, "contrasenaNueva": "otra-clave-larga-2"},
    )
    assert respuesta.status_code == 422
