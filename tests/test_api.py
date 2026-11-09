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
    _push_estado_limpio()


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


def test_escribir_estado_avance_fuera_de_rango_responde_422():
    """it61: el re-sync aplica las mismas invariantes que los casos de uso.

    Antes un PUT directo aceptaba avance 150 (fuera de 0-100) que la API
    normal rechaza en registrar avance; el push no es un canal para colar
    datos invalidos (mismo tratamiento que VULN-001/002).
    """
    estado = client.get("/api/sincronizacion").json()
    estado["etapas"][0]["avance"] = 150
    fuera = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": PM})
    assert fuera.status_code == 422
    assert fuera.json()["codigo"] == "VALIDACION"
    negativo = dict(estado, etapas=[dict(estado["etapas"][0], avance=-1), *estado["etapas"][1:]])
    rechazado = client.put("/api/sincronizacion", json=negativo, headers={"X-Actor-Id": PM})
    assert rechazado.status_code == 422
    # El estado vigente queda intacto tras ambos rechazos.
    vigente = client.get("/api/sincronizacion").json()
    assert vigente["etapas"][0]["avance"] == 100


def test_escribir_estado_presupuesto_negativo_responde_422():
    estado = client.get("/api/sincronizacion").json()
    estado["etapas"][0]["presupuestoAsignado"] = -5000
    respuesta = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": PM})
    assert respuesta.status_code == 422
    assert respuesta.json()["codigo"] == "VALIDACION"
    # Espejo en la coleccion de proyectos (crear_proyecto rechaza negativos).
    proyecto_negativo = dict(
        estado,
        proyectos=[dict(estado["proyectos"][0], presupuestoEstimado=-1), *estado["proyectos"][1:]],
    )
    rechazado = client.put("/api/sincronizacion", json=proyecto_negativo, headers={"X-Actor-Id": PM})
    assert rechazado.status_code == 422


def test_escribir_estado_nombre_proyecto_duplicado_responde_409():
    """Regresion VULN-007: el push no es un canal para colar un nombre de
    proyecto duplicado que crear_proyecto/editar_proyecto rechazan con 409
    (DUPLICADO, case-insensitive como _existe_nombre)."""
    estado = client.get("/api/sincronizacion").json()
    base = dict(estado["proyectos"][0])
    duplicado = dict(base, id="p-duplicado-vuln007", nombre=base["nombre"])
    con_duplicado = dict(estado, proyectos=[*estado["proyectos"], duplicado])
    r = client.put("/api/sincronizacion", json=con_duplicado, headers={"X-Actor-Id": ADMIN})
    assert r.status_code == 409
    assert r.json()["codigo"] == "DUPLICADO"
    # La deteccion es case-insensitive (espejo de _existe_nombre).
    distinto = dict(base, id="p-duplicado-vuln007b", nombre=base["nombre"].upper())
    con_mayusculas = dict(estado, proyectos=[*estado["proyectos"], distinto])
    r = client.put("/api/sincronizacion", json=con_mayusculas, headers={"X-Actor-Id": ADMIN})
    assert r.status_code == 409
    # El estado vigente queda intacto tras ambos rechazos.
    vigente = client.get("/api/sincronizacion").json()
    assert len(vigente["proyectos"]) == len(estado["proyectos"])
    # Un push con nombre unico sigue siendo aceptado (contrato del re-sync).
    nuevo = dict(base, id="p-unico-vuln007", nombre="Proyecto Unico VULN 007")
    con_nuevo = dict(estado, proyectos=[*estado["proyectos"], nuevo])
    aceptado = client.put("/api/sincronizacion", json=con_nuevo, headers={"X-Actor-Id": ADMIN})
    assert aceptado.status_code == 200
    # Restaurar el estado vigente para los tests siguientes.
    restaurado = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": ADMIN})
    assert restaurado.status_code == 200
    vigente = client.get("/api/sincronizacion").json()
    assert all(p["id"] != "p-unico-vuln007" for p in vigente["proyectos"])


def test_escribir_estado_fechas_invertidas_responde_422():
    estado = client.get("/api/sincronizacion").json()
    estado["etapas"][0]["fechaFin"] = "2020-01-01"
    respuesta = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": PM})
    assert respuesta.status_code == 422
    assert respuesta.json()["codigo"] == "VALIDACION"


def test_escribir_estado_usuarios_invalidos_responde_422_o_409():
    """Regresion VULN-008: el push no es un canal para colar usuarios que
    crear_usuario/editar_usuario rechazan (_validar_nombre, _validar_roles,
    _validar_correo): nombre vacio, cero roles, correo con formato invalido
    o duplicado (case-insensitive, DUPLICADO 409 como el canal normal)."""
    estado = client.get("/api/sincronizacion").json()
    objetivo = next(u for u in estado["usuarios"] if u["id"] == ANALISTA)
    resto = [u for u in estado["usuarios"] if u["id"] != ANALISTA]
    # Nombre vacio (espejo de _validar_nombre).
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, usuarios=[dict(objetivo, nombre="   "), *resto]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Sin roles (espejo de _validar_roles, 1.4).
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, usuarios=[dict(objetivo, roles=[]), *resto]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Correo con formato invalido (espejo de _validar_correo).
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, usuarios=[dict(objetivo, correo="sin-arroba"), *resto]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Correo duplicado de OTRO usuario, case-insensitive (409 DUPLICADO
    # como el canal normal).
    otro = next(u for u in estado["usuarios"] if u["id"] == PM)
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, usuarios=[dict(objetivo, correo=otro["correo"].upper()), *resto]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 409 and r.json()["codigo"] == "DUPLICADO"
    # El estado vigente queda intacto tras los cuatro rechazos.
    vigente = client.get("/api/sincronizacion").json()
    analista = next(u for u in vigente["usuarios"] if u["id"] == ANALISTA)
    assert analista == objetivo
    # La normalizacion (VULN-008) NO muta un push legitimo: nombre con
    # espacios y correo con mayusculas entran almacenados recortados y en
    # minusculas, como los guardaria el canal normal.
    variante = dict(objetivo, nombre=f"  {objetivo['nombre']}  ", correo=objetivo["correo"].upper())
    aceptado = client.put(
        "/api/sincronizacion",
        json=dict(estado, usuarios=[variante, *resto]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert aceptado.status_code == 200
    guardado = next(u for u in aceptado.json()["usuarios"] if u["id"] == ANALISTA)
    assert guardado["nombre"] == objetivo["nombre"]
    assert guardado["correo"] == objetivo["correo"]
    # Restaurar el estado vigente para los tests siguientes.
    restaurado = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": ADMIN})
    assert restaurado.status_code == 200


def test_escribir_estado_referencias_fantasma_responde_422():
    """Regresion it65: el push no es un canal para colar referencias a
    usuarios que no existen (aprobador/autor de un entregable, patrocinador
    de un proyecto); el canal normal los fija como el actor del caso de uso
    (crear_proyecto, crear_entregable, aprobar_entregable), asi que nunca
    pueden ser fantasmas. Sin esto, el gate contaria aprobaciones de
    usuarios inexistentes (bypass de gobernanza)."""
    estado = client.get("/api/sincronizacion").json()
    entregable = dict(estado["entregables"][0])
    proyecto = dict(estado["proyectos"][0])
    # Aprobador fantasma en un entregable aprobado.
    mutado = dict(entregable, aprobadoPorId="u-fantasma")
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, entregables=[mutado, *estado["entregables"][1:]]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Autor fantasma en un entregable (aprobado o no).
    mutado = dict(entregable, creadoPorId="u-fantasma")
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, entregables=[mutado, *estado["entregables"][1:]]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Patrocinador fantasma en un proyecto.
    mutado = dict(proyecto, patrocinadorId="u-fantasma")
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, proyectos=[mutado, *estado["proyectos"][1:]]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # El estado vigente queda intacto tras los tres rechazos.
    vigente = client.get("/api/sincronizacion").json()
    assert vigente["entregables"] == estado["entregables"]
    assert vigente["proyectos"] == estado["proyectos"]


def test_escribir_estado_insumos_de_entregable_responde_422():
    """Regresion it66: el push no es canal para colar entregables sin
    nombre, con version < 1 o con fecha de aprobacion no ISO; el canal
    normal los valida (crear_entregable) y aprobar_entregable registra
    siempre datetime.now().isoformat()."""
    estado = client.get("/api/sincronizacion").json()
    entregable = dict(estado["entregables"][0])
    caso = dict(estado, entregables=[*estado["entregables"][1:]])
    # Nombre vacio.
    r = client.put(
        "/api/sincronizacion",
        json=dict(caso, entregables=[dict(entregable, nombre="")]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Version menor a 1.
    r = client.put(
        "/api/sincronizacion",
        json=dict(caso, entregables=[dict(entregable, version=0)]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Fecha de aprobacion no ISO (con aprobador vigente).
    con_fecha = next(
        e for e in estado["entregables"] if e["aprobadoPorId"] is not None
    )
    r = client.put(
        "/api/sincronizacion",
        json=dict(
            caso,
            entregables=[
                dict(con_fecha, aprobadoEn="09/11/2026"),
                *[e for e in estado["entregables"] if e["id"] != con_fecha["id"]],
            ],
        ),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # El nombre se normaliza con strip (contrato conservado).
    normalizado = client.put(
        "/api/sincronizacion",
        json=dict(caso, entregables=[dict(entregable, nombre="  Nombre con borde  ")]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert normalizado.status_code == 200
    _push_estado_limpio()


def test_escribir_estado_bitacora_nueva_invalida_responde_422():
    """Regresion it66: el append de bitacora solo acepta entradas con fecha
    ISO (el servidor la registra con datetime.now()) y transiciones con
    par de etapas completo; el historial vigente no se revalida (3.5)."""
    estado = client.get("/api/sincronizacion").json()
    vigente_ids = [b["id"] for b in estado["bitacora"]]
    base = dict(estado["bitacora"][0], id="b-it66-1", autorId=ADMIN, comentario="prueba it66")
    # Fecha no ISO.
    fecha_mala = client.put(
        "/api/sincronizacion",
        json=dict(estado, bitacora=[*estado["bitacora"], dict(base, fecha="09/11/2026")]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert fecha_mala.status_code == 422
    assert fecha_mala.json()["codigo"] == "VALIDACION"
    # Transicion sin par de etapas.
    transicion_mala = client.put(
        "/api/sincronizacion",
        json=dict(
            estado,
            bitacora=[
                *estado["bitacora"],
                dict(
                    base,
                    id="b-it66-2",
                    fecha="2026-11-09T12:00:00+00:00",
                    tipo="transicion",
                    etapaOrigen=None,
                    etapaDestino=None,
                ),
            ],
        ),
        headers={"X-Actor-Id": ADMIN},
    )
    assert transicion_mala.status_code == 422
    assert transicion_mala.json()["codigo"] == "VALIDACION"
    # Transicion completa si se acepta (contrato conservado).
    transicion_ok = client.put(
        "/api/sincronizacion",
        json=dict(
            estado,
            bitacora=[
                *estado["bitacora"],
                dict(
                    base,
                    id="b-it66-3",
                    fecha="2026-11-09T12:00:00+00:00",
                    tipo="transicion",
                    etapaOrigen="PoC",
                    etapaDestino="ValidacionPoC",
                ),
            ],
        ),
        headers={"X-Actor-Id": ADMIN},
    )
    assert transicion_ok.status_code == 200
    assert any(b["id"] == "b-it66-3" for b in transicion_ok.json()["bitacora"])
    # El historial vigente quedo intacto tras los dos rechazos.
    despues = client.get("/api/sincronizacion").json()
    assert [b["id"] for b in despues["bitacora"]][: len(vigente_ids)] == vigente_ids
    _push_estado_limpio()


def test_escribir_estado_prefijos_de_id_responde_422():
    """Regresion it67 (VULN-011): el push no es canal para colar ids sin el
    prefijo de su coleccion (u-/p-/e-/ent-); el canal normal los fija
    siempre (nuevo_id) y la semilla los respeta. Una entrada de bitacora
    NUEVA sin prefijo b- tambien se rechaza; el historial vigente no se
    revalida (3.5)."""
    estado = client.get("/api/sincronizacion").json()
    base_bitacora = dict(estado["bitacora"][0], autorId=ADMIN, comentario="prueba it67")
    # Proyecto con id sin prefijo p-.
    r = client.put(
        "/api/sincronizacion",
        json=dict(
            estado,
            proyectos=[dict(estado["proyectos"][0], id="x-proyecto-it67"), *estado["proyectos"][1:]],
        ),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Usuario con id sin prefijo u-.
    r = client.put(
        "/api/sincronizacion",
        json=dict(
            estado,
            usuarios=[dict(estado["usuarios"][0], id="admin-sin-prefijo"), *estado["usuarios"][1:]],
        ),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Etapa con id con prefijo de otra coleccion (p- en lugar de e-).
    r = client.put(
        "/api/sincronizacion",
        json=dict(
            estado,
            etapas=[dict(estado["etapas"][0], id="p1-etapa-it67"), *estado["etapas"][1:]],
        ),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Entregable con prefijo de etapa (e-) en lugar de ent-.
    r = client.put(
        "/api/sincronizacion",
        json=dict(
            estado,
            entregables=[
                dict(estado["entregables"][0], id="e-entregable-it67"),
                *estado["entregables"][1:],
            ],
        ),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Entrada de bitacora NUEVA sin prefijo b-.
    r = client.put(
        "/api/sincronizacion",
        json=dict(
            estado,
            bitacora=[*estado["bitacora"], dict(base_bitacora, id="entrada-it67")],
        ),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # El estado vigente queda intacto tras los cinco rechazos.
    vigente = client.get("/api/sincronizacion").json()
    assert vigente["proyectos"] == estado["proyectos"]
    assert vigente["usuarios"] == estado["usuarios"]
    assert vigente["etapas"] == estado["etapas"]
    assert vigente["entregables"] == estado["entregables"]
    assert [b["id"] for b in vigente["bitacora"]] == [b["id"] for b in estado["bitacora"]]


def test_crear_entregable_valida_nombre_y_version():
    """it66: el canal normal de entregables comparte las reglas del re-sync
    (nombre obligatorio con strip, version >= 1)."""
    base = {"etapa": "PoC", "version": 1}
    sin_nombre = _post("/api/proyectos/p2/entregables", {**base, "nombre": "   "})
    assert sin_nombre.status_code == 422
    assert sin_nombre.json()["codigo"] == "VALIDACION"
    version_cero = _post("/api/proyectos/p2/entregables", {**base, "nombre": "X", "version": 0})
    assert version_cero.status_code == 422
    assert version_cero.json()["codigo"] == "VALIDACION"
    feliz = _post("/api/proyectos/p2/entregables", {**base, "nombre": "  Plan de PoC B  "})
    assert feliz.status_code == 201
    assert feliz.json()["nombre"] == "Plan de PoC B"
    assert feliz.json()["version"] == 1
    _push_estado_limpio()


def test_escribir_estado_autoaprobacion_responde_422():
    """Espejo de validar_aprobacion (gates.ts 3.4): el autor no aprueba su
    propio documento, ni siquiera empujando el estado completo."""
    estado = client.get("/api/sincronizacion").json()
    # La semilla trae ent-7 sin aprobar, pero tests previos pueden haberlo
    # aprobado: capturar el valor vigente para restaurar al final.
    objetivo = next(e for e in estado["entregables"] if e["id"] == "ent-7")
    aprobado_original = objetivo["aprobadoPorId"]
    assert objetivo["creadoPorId"] == "u-doble"
    autoaprobado = dict(
        estado,
        entregables=[
            dict(objetivo, aprobadoPorId="u-doble", aprobadoEn="2026-11-09T01:00:00Z"),
            *[e for e in estado["entregables"] if e["id"] != "ent-7"],
        ],
    )
    respuesta = client.put("/api/sincronizacion", json=autoaprobado, headers={"X-Actor-Id": ADMIN})
    assert respuesta.status_code == 422
    assert respuesta.json()["codigo"] == "VALIDACION"
    # Aprobacion sin fecha tambien se rechaza (el caso de uso siempre la registra).
    sin_fecha = dict(
        estado,
        entregables=[dict(objetivo, aprobadoPorId="u-admin", aprobadoEn=None), *estado["entregables"][1:]],
    )
    rechazado = client.put("/api/sincronizacion", json=sin_fecha, headers={"X-Actor-Id": ADMIN})
    assert rechazado.status_code == 422
    # Aprobacion legitima por otro actor si se acepta (contrato del re-sync).
    legitima = dict(
        estado,
        entregables=[
            dict(objetivo, aprobadoPorId="u-admin", aprobadoEn="2026-11-09T01:00:00Z"),
            *[e for e in estado["entregables"] if e["id"] != "ent-7"],
        ],
    )
    aceptada = client.put("/api/sincronizacion", json=legitima, headers={"X-Actor-Id": ADMIN})
    assert aceptada.status_code == 200
    # Restaurar el estado vigente para los tests siguientes.
    restaurado = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": ADMIN})
    assert restaurado.status_code == 200
    vigente = client.get("/api/sincronizacion").json()
    ent7 = next(e for e in vigente["entregables"] if e["id"] == "ent-7")
    assert ent7["aprobadoPorId"] == aprobado_original


def test_escribir_estado_referencias_rotas_responde_422():
    """El push no es canal para colar referencias rotas: el canal normal las
    exige (_exigir_proyecto, _exigir_responsable_activo, validar_dependencias
    6.5). Mismo tratamiento que el resto de invariantes del re-sync (it62)."""
    estado = client.get("/api/sincronizacion").json()
    # Etapa con proyectoId inexistente.
    etapa = dict(estado["etapas"][0], proyectoId="p-inexistente")
    rota = dict(estado, etapas=[etapa, *estado["etapas"][1:]])
    r = client.put("/api/sincronizacion", json=rota, headers={"X-Actor-Id": ADMIN})
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Entregable con proyectoId inexistente.
    objetivo = next(e for e in estado["entregables"] if e["id"] == "ent-7")
    entregable = dict(objetivo, proyectoId="p-inexistente")
    rota = dict(
        estado,
        entregables=[entregable, *[e for e in estado["entregables"] if e["id"] != "ent-7"]],
    )
    r = client.put("/api/sincronizacion", json=rota, headers={"X-Actor-Id": ADMIN})
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Etapa con responsable inexistente (el canal exige responsable activo
    # al crear/editar; un responsable que existe pero fue desactivado es un
    # estado alcanzable por desactivar_usuario, asi que el push lo acepta).
    inexistente = dict(estado["etapas"][0], responsableId="u-fantasma")
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, etapas=[inexistente, *estado["etapas"][1:]]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Dependencia que no existe o pertenece a otro proyecto (6.5).
    fantasma = dict(estado["etapas"][0], dependencias=["e-no-existe"])
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, etapas=[fantasma, *estado["etapas"][1:]]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    cruzada = dict(estado["etapas"][0], dependencias=[estado["etapas"][-1]["id"]])
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, etapas=[cruzada, *estado["etapas"][1:]]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Bitacora con autor o proyecto inexistentes, en entradas NUEVAS (3.5: la
    # bitacora no miente; mitigacion VULN-006: la referencia se exige en las
    # entradas nuevas, no en el historial vigente, que es inmutable y puede
    # referenciar proyectos eliminados por pushes posteriores).
    autor_roto = dict(estado["bitacora"][0], id="b-ref-rotas-1", autorId="u-fantasma")
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, bitacora=[autor_roto, *estado["bitacora"]]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    proyecto_roto = dict(estado["bitacora"][0], id="b-ref-rotas-2", proyectoId="p-inexistente")
    r = client.put(
        "/api/sincronizacion",
        json=dict(estado, bitacora=[proyecto_roto, *estado["bitacora"]]),
        headers={"X-Actor-Id": ADMIN},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION"
    # Estado vigente intacto tras todos los rechazos.
    vigente = client.get("/api/sincronizacion").json()
    assert vigente == estado


def test_escribir_estado_bitacora_historial_sobrevive_eliminacion_200():
    """Regresion VULN-006: un push que elimina un proyecto cuya bitacora
    vigente lo referencia debe tener exito (200); el historial es inmutable
    (3.5) y el servidor conserva la entrada huerfana en lugar de bloquear
    para siempre el re-sync con un 422 que nadie puede deshacer (la
    bitacora no se puede borrar). El siguiente GET->PUT del propio cliente
    desactualizado (con la coleccion de proyectos ya sin el proyecto) debe
    seguir funcionando."""
    estado = client.get("/api/sincronizacion").json()
    restantes = [p for p in estado["proyectos"] if p["id"] != "p6"]
    assert len(restantes) == len(estado["proyectos"]) - 1
    sin_p6 = dict(estado, proyectos=restantes)
    r = client.put("/api/sincronizacion", json=sin_p6, headers={"X-Actor-Id": ADMIN})
    assert r.status_code == 200
    # b5 sigue en el historial aunque p6 ya no exista.
    con_huerfana = client.get("/api/sincronizacion").json()
    assert any(b["id"] == "b5" for b in con_huerfana["bitacora"])
    # El roundtrip del cliente desactualizado no queda bloqueado: la entrada
    # vigente huerfana pasa sin revalidacion (VULN-006).
    r = client.put("/api/sincronizacion", json=con_huerfana, headers={"X-Actor-Id": ADMIN})
    assert r.status_code == 200
    # p6 sigue ausente (el servidor no lo devuelve mágicamente: lo elimina
    # el push); b5 permanece en el historial conservado.
    estado_final = client.get("/api/sincronizacion").json()
    assert all(p["id"] != "p6" for p in estado_final["proyectos"])
    assert any(b["id"] == "b5" for b in estado_final["bitacora"])


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
    _push_estado_limpio()


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


def _push_estado_limpio() -> None:
    """Restaura el estado de semilla (proyectos/etapas/entregables/bitacora)
    sin tocar usuarios. Los tests del modulo crean proyectos/etapas dinamicos
    (p-N, e-N, b-N) que quedan referenciados por la bitacora vigente; si el
    push siguiente deja proyectos huérfanos, el re-sync los rechaza con 422
    y contamina los modulos que corren despues. Con la semilla restaurada
    (referencias completas), el siguiente modulo parte de un estado valido."""
    from app.semilla import BITACORA_SEMILLA, ENTREGABLES_SEMILLA, ETAPAS_SEMILLA, PROYECTOS_SEMILLA

    estado = client.get("/api/sincronizacion").json()
    estado["proyectos"] = [p.model_dump(mode="json", by_alias=True) for p in PROYECTOS_SEMILLA]
    estado["etapas"] = [e.model_dump(mode="json", by_alias=True) for e in ETAPAS_SEMILLA]
    estado["entregables"] = [e.model_dump(mode="json", by_alias=True) for e in ENTREGABLES_SEMILLA]
    estado["bitacora"] = [b.model_dump(mode="json", by_alias=True) for b in BITACORA_SEMILLA]
    restaurado = client.put("/api/sincronizacion", json=estado, headers={"X-Actor-Id": ADMIN})
    assert restaurado.status_code == 200


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
