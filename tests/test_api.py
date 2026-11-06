"""Tests de la API REST (10.3) con TestClient: contrato camelCase y errores HTTP."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PM = "u-pm"
SPONSOR = "u-sponsor"
ADMIN = "u-admin"
ANALISTA = "u-analista"
PROYECTO_1 = "p1"


def _post(url: str, json: dict | None = None, actor: str = PM):
    return client.post(url, json=json if json is not None else {}, headers={"X-Actor-Id": actor})


def _patch(url: str, json: dict, actor: str = PM):
    return client.patch(url, json=json, headers={"X-Actor-Id": actor})


# ---------- Salud y consultas ----------


def test_salud_responde_ok():
    respuesta = client.get("/api/salud")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "ok", "servicio": "projecthub-backend"}


def test_proyectos_serializan_camel_case():
    respuesta = client.get("/api/proyectos")
    assert respuesta.status_code == 200
    primero = respuesta.json()[0]
    assert "presupuestoEstimado" in primero
    assert "presupuesto_estimado" not in primero


def test_resumen_calculado_en_servidor():
    respuesta = client.get(f"/api/proyectos/{PROYECTO_1}/resumen")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    # e1(100%) + e2(55%) + e3(20%) ponderado por duracion (30/76/120 dias).
    assert datos["presupuestoTotal"] == 150000.0
    assert datos["consumoTotal"] == 81500.0
    assert 0 < datos["avance"] < 100
    assert datos["etapas"][0]["fechaInicio"] == "2026-09-01"


def test_sin_actor_responde_422():
    respuesta = client.post("/api/proyectos", json={"nombre": "X"})
    assert respuesta.status_code == 422
    assert respuesta.json()["codigo"] == "VALIDACION"


def test_entidad_no_encontrada_responde_404():
    respuesta = client.get("/api/proyectos/no-existe")
    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ENTIDAD_NO_ENCONTRADA"


# ---------- Crear y editar proyectos ----------


def test_crear_proyecto_flujo_completo():
    respuesta = _post(
        "/api/proyectos",
        {
            "nombre": "Sistema de nomina via API",
            "descripcion": "Creado desde el test de integracion",
            "presupuestoEstimado": 50000,
        },
    )
    assert respuesta.status_code == 201
    creado = respuesta.json()
    assert creado["etapa"] == "Planteamiento"
    assert creado["estado"] == "Activo"
    assert creado["presupuestoEstimado"] == 50000


def test_crear_proyecto_duplicado_409():
    respuesta = _post("/api/proyectos", {"nombre": "portal de pagos"})
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "DUPLICADO"


def test_analista_no_crea_proyecto_409():
    respuesta = _post("/api/proyectos", {"nombre": "Proyecto de analista"}, actor=ANALISTA)
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "PERMISO_DENEGADO"


def test_editar_proyecto_actualiza_descripcion():
    respuesta = _patch(
        f"/api/proyectos/{PROYECTO_1}",
        {"descripcion": "Descripcion actualizada por test"},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["descripcion"] == "Descripcion actualizada por test"


# ---------- Transiciones y gate ----------


def test_transicion_sin_gate_bloqueada_422():
    # p1 (Ejecucion) tiene ent-7 sin aprobar: el gate de Ejecucion esta cerrado.
    respuesta = _post(
        f"/api/proyectos/{PROYECTO_1}/transicionar",
        {"destino": "Operacion"},
        actor=ADMIN,
    )
    assert respuesta.status_code == 422
    assert "gate" in respuesta.json()["mensaje"].lower()


def test_transicion_invalida_responde_409():
    respuesta = _post(
        f"/api/proyectos/{PROYECTO_1}/transicionar",
        {"destino": "Planeacion"},
        actor=ADMIN,
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "TRANSICION_INVALIDA"


def test_flujo_cargar_aprobar_entregables_y_avanzar():
    # p3 esta en PoC; su plan de PoC (ent-10) esta sin aprobar.
    aprobado = _post("/api/entregables/ent-10/aprobar", actor=SPONSOR)
    assert aprobado.status_code == 200
    # Con el gate de PoC abierto, solo gobernanza avanza (matriz PoC).
    avanzar = _post("/api/proyectos/p3/transicionar", {"destino": "ValidacionPoC"}, actor=PM)
    assert avanzar.status_code == 409
    avanzar = _post("/api/proyectos/p3/transicionar", {"destino": "ValidacionPoC"}, actor=ADMIN)
    assert avanzar.status_code == 200
    assert avanzar.json()["etapa"] == "ValidacionPoC"
    # La bitacora registro la transicion.
    bitacora = client.get("/api/proyectos/p3/bitacora").json()
    assert any(b["tipo"] == "transicion" and b["etapaDestino"] == "ValidacionPoC" for b in bitacora)


def test_aprobar_entregable_reglas_de_negocio():
    # ent-7 (Acta de avance de ejecucion) fue creado por u-doble y esta sin aprobar.
    # La matriz exige gobernanza para aprobar en Ejecucion; el sponsor (tercero) aprueba.
    autor = _post("/api/entregables/ent-7/aprobar", actor=SPONSOR)
    assert autor.status_code == 200
    # Ya aprobado: no se reaprueba.
    repetida = _post("/api/entregables/ent-7/aprobar", actor=ADMIN)
    assert repetida.status_code == 422


# ---------- Estados del proyecto ----------


def test_proyecto_cerrado_es_solo_lectura():
    # No hay proyecto Cerrado en semilla; se cierra p4 (esta en Cierre).
    cerrar = _post("/api/proyectos/p4/cerrar", actor=ADMIN)
    assert cerrar.status_code == 200
    respuesta = _patch("/api/proyectos/p4", {"descripcion": "intento"}, actor=PM)
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "ESTADO_PROYECTO"


def test_proyecto_cancelado_bloquea_edicion():
    # p6 esta Cancelado en semilla.
    respuesta = _patch("/api/proyectos/p6", {"descripcion": "intento"}, actor=PM)
    assert respuesta.status_code == 409


# ---------- Etapas de trabajo ----------


def test_crear_etapa_valida_y_errores():
    base = {
        "nombre": "Etapa de prueba API",
        "fechaInicio": "2026-06-01",
        "fechaFin": "2026-06-30",
        "responsableId": ANALISTA,
        "presupuestoAsignado": 10000,
    }
    respuesta = _post("/api/proyectos/p2/etapas", base)
    assert respuesta.status_code == 201
    etapa = respuesta.json()
    assert etapa["presupuestoAsignado"] == 10000
    # Fechas invertidas -> 422.
    invertida = _post(
        "/api/proyectos/p2/etapas",
        {**base, "nombre": "Invertida", "fechaInicio": "2026-06-30", "fechaFin": "2026-06-01"},
    )
    assert invertida.status_code == 422
    # Responsable inactivo -> 422.
    inactivo = _post(
        "/api/proyectos/p2/etapas",
        {**base, "nombre": "Resp inactivo", "responsableId": "u-inactivo"},
    )
    assert inactivo.status_code == 422


def test_avance_fuera_de_rango_422():
    etapas = client.get("/api/proyectos/p1/etapas").json()
    etapa = etapas[0]
    respuesta = _post(f"/api/etapas/{etapa['id']}/avance", {"avance": 120})
    assert respuesta.status_code == 422
    negativo = _post(f"/api/etapas/{etapa['id']}/avance", {"avance": -5})
    assert negativo.status_code == 422


def test_consumo_negativo_422():
    etapas = client.get("/api/proyectos/p1/etapas").json()
    etapa = etapas[0]
    respuesta = _post(f"/api/etapas/{etapa['id']}/consumo", {"consumo": -1})
    assert respuesta.status_code == 422


# ---------- Usuarios ----------


def test_crear_y_desactivar_usuario_como_admin():
    creador = _post(
        "/api/usuarios",
        {"nombre": "QA Nuevo", "correo": "qa-nuevo@projecthub.local", "roles": ["Analista"]},
        actor=ADMIN,
    )
    assert creador.status_code == 201
    creado = creador.json()
    respuesta = _patch(f"/api/usuarios/{creado['id']}", {"activo": False}, actor=ADMIN)
    assert respuesta.status_code == 200
    assert respuesta.json()["activo"] is False
    # El usuario inactivo no puede ejecutar acciones (1.8).
    bloqueado = _post("/api/proyectos", {"nombre": "Proyecto de inactivo"}, actor=creado["id"])
    assert bloqueado.status_code == 422


def test_correo_duplicado_409():
    # El correo se normaliza a minusculas: el de semilla es paula@projecthub.local.
    respuesta = _post(
        "/api/usuarios",
        {"nombre": "Duplicado", "correo": "Paula@projecthub.local", "roles": ["Analista"]},
        actor=ADMIN,
    )
    assert respuesta.status_code == 409


def test_no_admin_no_gestiona_usuarios():
    respuesta = _post(
        "/api/usuarios",
        {"nombre": "X", "correo": "x@projecthub.local", "roles": ["Analista"]},
        actor=PM,
    )
    assert respuesta.status_code == 409
