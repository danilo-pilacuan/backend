"""Tests de reglas de dominio puras (ciclo de vida, gates, calculos, matriz)."""

import pytest

from app.domain.calculos import (
    avance_ponderado,
    duracion_dias,
    presupuesto_excedido,
    presupuesto_total,
    validar_etapa,
)
from app.domain.ciclo_vida import (
    etapa_retroceso_permitido,
    es_transicion_valida,
    siguiente_etapa,
    transiciones_disponibles,
    validar_transicion,
)
from app.domain.errores import (
    ErrorDuplicado,
    ErrorEstadoProyecto,
    ErrorTransicionInvalida,
    ErrorValidacion,
)
from app.domain.gates import ENTREGABLES_OBLIGATORIOS, evaluar_gate, validar_aprobacion
from app.domain.matriz_permisos import roles_permitidos, tiene_permiso
from app.domain.modelos import Entregable
from app.servicio import ServicioProyectos
from app.semilla import USUARIOS_SEMILLA


def _usuario(rol: str):
    return next(u for u in USUARIOS_SEMILLA if rol in u.roles)


def _entregable(nombre: str, etapa: str, creado_por: str, aprobado_por: str | None) -> Entregable:
    return Entregable(
        id=f"ent-{nombre}",
        proyecto_id="p1",
        etapa=etapa,
        nombre=nombre,
        version=1,
        creado_por_id=creado_por,
        aprobado_por_id=aprobado_por,
        aprobado_en="2026-01-01T00:00:00Z" if aprobado_por else None,
    )


def _etapa_dict(avance: float, dias: int, asignado: float = 0, consumido: float = 0) -> dict:
    return {
        "fecha_inicio": "2026-01-01",
        "fecha_fin": f"2026-01-{dias:02d}",
        "avance": avance,
        "presupuesto_asignado": asignado,
        "presupuesto_consumido": consumido,
    }


# ---------- Ciclo de vida ----------


def test_cadena_lineal_de_nueve_etapas():
    assert siguiente_etapa("Planteamiento") == "Iniciativa"
    assert siguiente_etapa("Cierre") is None


def test_transicion_invalida_saltando_etapas():
    with pytest.raises(ErrorTransicionInvalida):
        validar_transicion("Planteamiento", "Planeacion")


def test_retroceso_solo_permitido_en_poc_y_validacion_poc():
    assert etapa_retroceso_permitido("PoC") == "Iniciativa"
    assert etapa_retroceso_permitido("ValidacionPoC") == "PoC"
    assert etapa_retroceso_permitido("Ejecucion") is None
    with pytest.raises(ErrorTransicionInvalida):
        validar_transicion("Ejecucion", "Planeacion")


def test_transiciones_disponibles_incluyen_avance_y_retroceso():
    disponibles = transiciones_disponibles("PoC")
    assert "ValidacionPoC" in disponibles
    assert "Iniciativa" in disponibles


def test_transicion_desde_cierre_es_invalida():
    assert es_transicion_valida("Cierre", "Cierre") is False


# ---------- Gates ----------


def test_gate_cerrado_falta_entregable():
    gate = evaluar_gate("Planteamiento", [])
    assert gate.abierto is False
    assert gate.faltantes == list(ENTREGABLES_OBLIGATORIOS["Planteamiento"])


def test_gate_abierto_con_entregables_aprobados():
    entregable = _entregable("Acta de planteamiento", "Planteamiento", "u-pm", "u-sponsor")
    gate = evaluar_gate("Planteamiento", [entregable])
    assert gate.abierto is True
    assert gate.faltantes == []
    assert gate.pendientes_aprobacion == []


def test_gate_pendiente_de_aprobacion():
    entregable = _entregable("Acta de planteamiento", "Planteamiento", "u-pm", None)
    gate = evaluar_gate("Planteamiento", [entregable])
    assert gate.abierto is False
    assert gate.pendientes_aprobacion == ["Acta de planteamiento"]


def test_autor_no_aprueba_su_propio_entregable():
    entregable = _entregable("Acta de planteamiento", "Planteamiento", "u-pm", None)
    with pytest.raises(ErrorValidacion):
        validar_aprobacion(entregable, "u-pm")


def test_entregable_aprobado_no_se_reaprueba():
    entregable = _entregable("Acta de planteamiento", "Planteamiento", "u-pm", "u-sponsor")
    with pytest.raises(ErrorValidacion):
        validar_aprobacion(entregable, "u-admin")


# ---------- Calculos ----------


def test_duracion_minima_un_dia():
    assert duracion_dias("2026-01-01", "2026-01-01") == 1
    assert duracion_dias("2026-01-01", "2026-01-05") == 5


def test_avance_ponderado_por_duracion():
    etapas = [
        _etapa_dict(avance=100, dias=5),
        _etapa_dict(avance=0, dias=5),
    ]
    assert avance_ponderado(etapas) == 50.0


def test_presupuesto_total_y_excedido():
    etapas = [
        _etapa_dict(avance=0, dias=1, asignado=100, consumido=100),
        _etapa_dict(avance=0, dias=1, asignado=50, consumido=20),
    ]
    assert presupuesto_total(etapas) == 150.0
    assert presupuesto_excedido(etapas[0]) is False
    assert presupuesto_excedido({**etapas[0], "presupuesto_consumido": 101}) is True


def test_validar_etapa_rechaza_avance_fuera_de_rango():
    with pytest.raises(ErrorValidacion):
        validar_etapa("2026-01-01", "2026-01-02", 150, 0, 0)
    with pytest.raises(ErrorValidacion):
        validar_etapa("2026-01-01", "2026-01-02", -1, 0, 0)


def test_validar_etapa_rechaza_fechas_invertidas():
    with pytest.raises(ErrorValidacion):
        validar_etapa("2026-02-01", "2026-01-01", 0, 0, 0)


def test_validar_etapa_rechaza_monto_negativo():
    with pytest.raises(ErrorValidacion):
        validar_etapa("2026-01-01", "2026-01-02", 0, -100, 0)
    with pytest.raises(ErrorValidacion):
        validar_etapa("2026-01-01", "2026-01-02", 0, 100, -5)


# ---------- Matriz de permisos ----------


def test_matriz_permisos_basicos():
    assert tiene_permiso("Planteamiento", "editarProyecto", ["ProjectManager"]) is True
    assert tiene_permiso("Planteamiento", "editarProyecto", ["Analista"]) is False
    assert tiene_permiso("Cierre", "cerrarProyecto", ["Admin"]) is True
    assert tiene_permiso("Cierre", "cerrarProyecto", ["ProjectManager"]) is False


def test_cancelar_y_cerrar_son_de_gobernanza():
    assert roles_permitidos("Planteamiento", "cancelarProyecto") == ("Admin", "Sponsor")
    assert roles_permitidos("Cierre", "cerrarProyecto") == ("Admin", "Sponsor")
    assert tiene_permiso("Planteamiento", "cancelarProyecto", ["ProjectManager"]) is False


# ---------- Reglas del servicio (store) ----------


def test_servicio_actor_inactivo_no_ejecuta_acciones():
    servicio = ServicioProyectos()
    pm = _usuario("ProjectManager")
    inactivo = pm.model_copy(update={"activo": False})
    with pytest.raises(ErrorValidacion):
        servicio.crear_proyecto({"nombre": "X"}, inactivo)


def test_servicio_nombre_duplicado_rechazado_case_insensitive():
    servicio = ServicioProyectos()
    pm = _usuario("ProjectManager")
    with pytest.raises(ErrorDuplicado) as exc:
        servicio.crear_proyecto({"nombre": "PORTAL DE PAGOS"}, pm)
    assert "Ya existe" in str(exc.value)


def test_servicio_proyecto_cancelado_bloquea_operaciones():
    servicio = ServicioProyectos()
    pm = _usuario("ProjectManager")
    # p6 esta Cancelado en semilla y no tiene etapas; intentar crear una
    # etapa debe bloquearse por estado (solo registrar consumo esta permitido).
    with pytest.raises(ErrorEstadoProyecto):
        servicio.crear_etapa(
            {
                "proyecto_id": "p6",
                "nombre": "Etapa sobre cancelado",
                "fecha_inicio": "2026-06-01",
                "fecha_fin": "2026-06-30",
                "responsable_id": "u-pm",
            },
            pm,
        )


def test_servicio_gate_cerrado_bloquea_transicion():
    servicio = ServicioProyectos()
    # p2 esta en Planeacion y no tiene entregables cargados.
    with pytest.raises(ErrorValidacion) as exc:
        servicio.transicionar("p2", "Contratos", _usuario("Admin"))
    assert "gate" in str(exc.value).lower()
