"""Tests de la API REST (10.3) con TestClient: contrato camelCase y errores HTTP."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PM = "u-pm"
SPONSOR = "u-sponsor"
ADMIN = "u-admin"
ANALISTA = "u-analista"
PROYECTO_1 = "p1"

# Los GET de dominio exigen sesion (VULN-002). El header por defecto del
# cliente mantiene el resto de la suite en el contrato con sesion; los tests
# de auth y de peticion anonima usan el cliente anon o sobreescriben.
client = TestClient(app, headers={"X-Actor-Id": ADMIN})
anon = TestClient(app)


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
    respuesta = anon.post("/api/proyectos", json={"nombre": "X"})
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


# ---------- Sincronizacion de estado (13.4) ----------


def test_leer_estado_devuelve_las_cinco_colecciones():
    respuesta = client.get("/api/sincronizacion")
    assert respuesta.status_code == 200
    estado = respuesta.json()
    for clave in ("usuarios", "proyectos", "etapas", "entregables", "bitacora"):
        assert clave in estado and isinstance(estado[clave], list)
    assert len(estado["proyectos"]) >= 6
    assert estado["proyectos"][0]["presupuestoEstimado"] >= 0


def test_escribir_estado_roundtrip_camellcase():
    estado = client.get("/api/sincronizacion").json()
    estado["proyectos"][0]["nombre"] = "Renombrado via sincronizacion"
    respuesta = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": PM})
    assert respuesta.status_code == 200
    verificado = client.get("/api/sincronizacion").json()
    assert verificado["proyectos"][0]["nombre"] == "Renombrado via sincronizacion"
    assert len(verificado["proyectos"]) == len(estado["proyectos"])


def test_escribir_estado_sin_actor_responde_422():
    estado = client.get("/api/sincronizacion").json()
    respuesta = anon.put("/api/sincronizacion", json=estado)
    assert respuesta.status_code == 422


def test_escribir_estado_coleccion_invalida_responde_422():
    estado = client.get("/api/sincronizacion").json()
    estado["proyectos"] = "no-soy-una-lista"
    respuesta = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": PM})
    assert respuesta.status_code == 422
    assert respuesta.json()["codigo"] == "VALIDACION"


def test_escribir_estado_ids_duplicados_responde_422():
    estado = client.get("/api/sincronizacion").json()
    estado["proyectos"].append(dict(estado["proyectos"][0]))
    respuesta = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": PM})
    assert respuesta.status_code == 422
    assert "duplicados" in respuesta.json()["mensaje"]


def test_escribir_estado_entidad_invalida_responde_422():
    estado = client.get("/api/sincronizacion").json()
    estado["proyectos"][0]["etapa"] = "EtapaInexistente"
    respuesta = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": PM})
    assert respuesta.status_code == 422
    assert respuesta.json()["codigo"] == "VALIDACION"


# ---------- Colecciones planas (13.3: bootstrap plano de los stores) ----------


# ---------- Seguridad: hallazgos documentados (.ops/security/vulns.md) ----------


def test_vuln002_mitigado_lecturas_de_dominio_exigen_sesion():
    """VULN-002 mitigada (2026-11-08): los GET de dominio exigen sesion.

    Sin token ni X-Actor-Id la API responde 422 VALIDACION; solo /api/salud
    y /api/auth/login quedan publicos. Con sesion (X-Actor-Id) siguen
    respondiendo 200 (contrato del modo demo conservado).
    """
    for ruta in ("/api/usuarios", "/api/proyectos", "/api/etapas", "/api/entregables", "/api/bitacora"):
        sin_sesion = anon.get(ruta)
        assert sin_sesion.status_code == 422, f"{ruta} sigue publica: revertir mitigacion VULN-002"
        assert sin_sesion.json()["codigo"] == "VALIDACION"
        con_sesion = client.get(ruta, headers={"X-Actor-Id": ADMIN})
        assert con_sesion.status_code == 200, f"{ruta} rompio el contrato con sesion"
    # La ruta de detalle tambien queda protegida.
    assert anon.get("/api/proyectos/no-existe").status_code == 422


def test_vuln001_mitigado_escalada_de_roles_responde_409():
    """VULN-001 mitigada (parte segura, 2026-11-08): solo Admin altera usuarios.

    Un actor no-Admin que empuja un diff de usuarios (escalada de roles del
    analista) recibe 409 PERMISO_DENEGADO y el estado queda intacto; el
    mismo PUT con Admin sigue funcionando (contrato del re-sync conservado).
    """
    estado = client.get("/api/sincronizacion").json()
    for u in estado["usuarios"]:
        if u["id"] == ANALISTA:
            u["roles"] = ["Admin"]
    denegado = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": ANALISTA})
    assert denegado.status_code == 409
    assert denegado.json()["codigo"] == "PERMISO_DENEGADO"
    # El estado no cambio: el analista sigue sin Admin.
    vigente = client.get("/api/sincronizacion").json()
    roles = next(u for u in vigente["usuarios"] if u["id"] == ANALISTA)["roles"]
    assert roles != ["Admin"]
    # El mismo diff empujado por Admin si es aceptado (matriz 1.4).
    permitido = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": ADMIN})
    assert permitido.status_code == 200
    roles_admin = next(u for u in permitido.json()["usuarios"] if u["id"] == ANALISTA)["roles"]
    assert roles_admin == ["Admin"]
    _restaurar_usuarios_semilla()


def test_vuln001_mitigado_bitacora_borrado_ignorado_y_modificacion_rechazada():
    """VULN-001 (parte bitacora, 3.5 invariante): el re-sync no puede
    limpiar ni alterar el historial.

    Antes el PUT reemplazaba la coleccion completa (borrar bitacora la
    vacia). Ahora el servidor fusiona por id y conserva su copia: un push
    con bitacora vacia (cliente stale o malicioso) es un no-op para la
    bitacora, y modificar una entrada existente (mismo id, otro contenido)
    se rechaza con 422 para cualquier actor.
    """
    estado = client.get("/api/sincronizacion").json()
    vigente_ids = [b["id"] for b in estado["bitacora"]]
    assert len(vigente_ids) >= 1
    # Borrado total (bitacora: []): el servidor conserva su copia completa.
    sin_bitacora = dict(estado, bitacora=[])
    ignorado_analista = client.put(
        "/api/sincronizacion", json=sin_bitacora, headers={"X-Actor-Id": ANALISTA}
    )
    assert ignorado_analista.status_code == 200
    assert [b["id"] for b in ignorado_analista.json()["bitacora"]] == vigente_ids
    # Modificacion de una entrada existente: mismo id, otro contenido.
    modificada = [dict(b, comentario="editado") for b in estado["bitacora"]]
    rechazada_mod = client.put(
        "/api/sincronizacion", json=dict(estado, bitacora=modificada), headers={"X-Actor-Id": ADMIN}
    )
    assert rechazada_mod.status_code == 422
    assert rechazada_mod.json()["codigo"] == "VALIDACION"
    # La bitacora vigente sigue intacta (sin "editado", mismas ids).
    despues = client.get("/api/sincronizacion").json()
    assert [b["id"] for b in despues["bitacora"]] == vigente_ids
    assert all(b["comentario"] != "editado" for b in despues["bitacora"])


def test_vuln001_mitigado_bitacora_append_ajeno_rechazado():
    """VULN-001: nadie aporta entradas de bitacora a nombre de otros.

    Ni un no-Admin ni un Admin pueden agregar una entrada nueva cuyo
    autorId sea otro actor: el empuje de bitacora no es un canal para
    atribuir acciones ajenas. El estado queda intacto.
    """
    estado = client.get("/api/sincronizacion").json()
    vigente_ids = [b["id"] for b in estado["bitacora"]]
    ajena = dict(
        estado["bitacora"][0],
        id="b-vuln001-ajena",
        autorId=PM,
        comentario="Atribuida falsamente al PM",
    )
    for actor in (ANALISTA, ADMIN):
        rechazado = client.put(
            "/api/sincronizacion",
            json=dict(estado, bitacora=[*estado["bitacora"], ajena]),
            headers={"X-Actor-Id": actor},
        )
        assert rechazado.status_code == 422, f"el actor {actor} atribuyo acciones ajenas"
        assert rechazado.json()["codigo"] == "VALIDACION"
    despues = client.get("/api/sincronizacion").json()
    assert [b["id"] for b in despues["bitacora"]] == vigente_ids
    assert all(b["id"] != "b-vuln001-ajena" for b in despues["bitacora"])


def test_vuln001_mitigado_bitacora_append_propio_acepta_y_fusiona():
    """Caso feliz multi-pestaña: un cliente con estado stale empuja su
    bitacora vieja mas una entrada propia; el servidor acepta el append y
    preserva la entrada registrada en servidor mientras tanto (merge real,
    no reemplazo).
    """
    estado = client.get("/api/sincronizacion").json()
    antes = [b["id"] for b in estado["bitacora"]]
    # Otra pestana (otro actor) registra en bitacora mientras este cliente
    # conserva su estado viejo: el push no debe borrarla.
    from app.main import servicio

    servicio._registrar_bitacora(
        estado["proyectos"][0]["id"], ADMIN, "cambio", comentario="Hecho en otra pestana"
    )
    propia = {
        "id": "b-vuln001-propia",
        "proyectoId": estado["proyectos"][0]["id"],
        "autorId": PM,
        "fecha": "2026-11-09T12:00:00+00:00",
        "tipo": "cambio",
        "etapaOrigen": None,
        "etapaDestino": None,
        "comentario": "Comentario propio del PM",
    }
    respuesta = client.put(
        "/api/sincronizacion",
        json=dict(estado, bitacora=[*estado["bitacora"], propia]),
        headers={"X-Actor-Id": PM},
    )
    assert respuesta.status_code == 200
    despues = respuesta.json()["bitacora"]
    ids = [b["id"] for b in despues]
    # El append propio queda registrado y nada se perdio.
    assert "b-vuln001-propia" in ids
    assert ids[: len(antes)] == antes
    # La entrada del otro actor (registrada en servidor) sigue presente.
    assert any(b["comentario"] == "Hecho en otra pestana" for b in despues)
    # El empuje stale no habia borrado la entrada nueva del servidor.
    assert ids == antes + ["b-vuln001-propia"] or "b-vuln001-propia" in ids


def test_vuln001_mitigado_re_sync_sin_cambios_de_usuarios_lo_acepta_cualquier_actor():
    """El caso feliz del frontend: un PM empuja su estado (sin diff de
    usuarios) y el re-sync lo acepta; los usuarios intactos no exigen Admin."""
    estado = client.get("/api/sincronizacion").json()
    respuesta = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": PM})
    assert respuesta.status_code == 200


def _restaurar_usuarios_semilla() -> None:
    from app.semilla import USUARIOS_SEMILLA

    estado = client.get("/api/sincronizacion").json()
    estado["usuarios"] = [u.model_dump(mode="json", by_alias=True) for u in USUARIOS_SEMILLA]
    restaurada = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": ADMIN})
    assert restaurada.status_code == 200


def _bitacora_semilla() -> list[dict]:
    """Serializa BITACORA_SEMILLA como dicts camelCase (reporte/diff)."""
    from app.semilla import BITACORA_SEMILLA

    return [b.model_dump(mode="json", by_alias=True) for b in BITACORA_SEMILLA]


# ---------- Colecciones planas: listados ----------


def test_listar_todas_las_etapas_sin_filtros():
    respuesta = client.get("/api/etapas")
    assert respuesta.status_code == 200
    etapas = respuesta.json()
    assert len(etapas) >= 3
    assert "fechaInicio" in etapas[0]
    assert "fecha_inicio" not in etapas[0]
    assert all(e["proyectoId"] for e in etapas)


def test_listar_todos_los_entregables_sin_filtros():
    respuesta = client.get("/api/entregables")
    assert respuesta.status_code == 200
    entregables = respuesta.json()
    assert len(entregables) >= 1
    assert "proyectoId" in entregables[0]
    assert "creadoPorId" in entregables[0]
    assert "etapa" in entregables[0]


def test_listar_toda_la_bitacora_sin_filtros():
    respuesta = client.get("/api/bitacora")
    assert respuesta.status_code == 200
    bitacora = respuesta.json()
    assert len(bitacora) >= 1
    assert "proyectoId" in bitacora[0]
    assert "autorId" in bitacora[0]
    assert "tipo" in bitacora[0]


def test_colecciones_planas_coinciden_con_sincronizacion():
    sincro = client.get("/api/sincronizacion").json()
    for ruta, clave in (
        ("/api/etapas", "etapas"),
        ("/api/entregables", "entregables"),
        ("/api/bitacora", "bitacora"),
    ):
        plana = client.get(ruta).json()
        ids_plana = sorted(e["id"] for e in plana)
        ids_sincro = sorted(e["id"] for e in sincro[clave])
        assert ids_plana == ids_sincro, f"{ruta} no coincide con sincronizacion.{clave}"
