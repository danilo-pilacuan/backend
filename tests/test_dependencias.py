"""Tests de dependencias entre etapas de trabajo (6.5): dominio puro y API."""

import pytest
from fastapi.testclient import TestClient

from app.domain.dependencias import (
    dependencias_gantt,
    dependientes_de,
    exigir_dependencias_completas,
    prerequisitos_de,
    tiene_ciclo,
    validar_dependencias,
)
from app.domain.errores import ErrorValidacion
from app.domain.modelos import EtapaTrabajo
from app.main import app
from app.semilla import ETAPAS_SEMILLA

client = TestClient(app)

PM = "u-pm"
PROYECTO_1 = "p1"
PROYECTO_2 = "p2"


def _etapa(
    id: str = "e1",
    proyecto_id: str = "p1",
    dependencias: list[str] | None = None,
    avance: float = 0,
) -> EtapaTrabajo:
    return EtapaTrabajo(
        id=id,
        proyecto_id=proyecto_id,
        nombre=f"Etapa {id}",
        fecha_inicio="2026-01-01",
        fecha_fin="2026-01-31",
        responsable_id="u-pm",
        presupuesto_asignado=1000,
        presupuesto_consumido=0,
        avance=avance,
        dependencias=dependencias or [],
    )


# ---------- Dominio puro ----------


def test_prerequisitos_de_sin_dependencias():
    assert prerequisitos_de(_etapa()) == []


def test_prerequisitos_de_con_dependencias():
    assert prerequisitos_de(_etapa(dependencias=["e2", "e3"])) == ["e2", "e3"]


def test_dependientes_de_encuentra_dependientes():
    etapas = [_etapa("e1"), _etapa("e2", dependencias=["e1"]), _etapa("e3", dependencias=["e1"])]
    ids = [e.id for e in dependientes_de("e1", etapas)]
    assert ids == ["e2", "e3"]


def test_dependientes_de_sin_dependientes():
    etapas = [_etapa("e1"), _etapa("e2", dependencias=["e1"])]
    assert dependientes_de("e2", etapas) == []


def test_auto_dependencia_rechazada():
    with pytest.raises(ErrorValidacion):
        validar_dependencias("e1", "p1", [_etapa("e1", dependencias=["e1"])])


def test_duplicado_rechazado():
    with pytest.raises(ErrorValidacion):
        validar_dependencias("e1", "p1", [_etapa("e1", dependencias=["e2", "e2"]), _etapa("e2")])


def test_prerequisito_inexistente_rechazado():
    with pytest.raises(ErrorValidacion):
        validar_dependencias("e1", "p1", [_etapa("e1", dependencias=["fantasma"])])


def test_prerequisito_de_otro_proyecto_rechazado():
    etapas = [_etapa("e1", dependencias=["e9"]), _etapa("e9", proyecto_id="p2")]
    with pytest.raises(ErrorValidacion):
        validar_dependencias("e1", "p1", etapas)


def test_ciclo_dos_nodos_rechazado():
    etapas = [_etapa("e1", dependencias=["e2"]), _etapa("e2", dependencias=["e1"])]
    with pytest.raises(ErrorValidacion):
        validar_dependencias("e1", "p1", etapas)


def test_ciclo_largo_rechazado():
    etapas = [
        _etapa("e1", dependencias=["e3"]),
        _etapa("e2", dependencias=["e1"]),
        _etapa("e3", dependencias=["e2"]),
    ]
    with pytest.raises(ErrorValidacion):
        validar_dependencias("e1", "p1", etapas)


def test_cadena_valida_sin_ciclo():
    etapas = [_etapa("e1"), _etapa("e2", dependencias=["e1"]), _etapa("e3", dependencias=["e2"])]
    validar_dependencias("e3", "p1", etapas)  # no lanza
    assert tiene_ciclo("e3", etapas) is False


def test_tiene_ciclo_detecta_ciclo():
    etapas = [_etapa("e1", dependencias=["e2"]), _etapa("e2", dependencias=["e1"])]
    assert tiene_ciclo("e1", etapas) is True


def test_exigir_dependencias_completas_no_exige_con_avance_cero():
    etapas = [_etapa("e1", avance=50), _etapa("e2", dependencias=["e1"], avance=0)]
    exigir_dependencias_completas(etapas[1], 0, etapas)  # no lanza


def test_exigir_dependencias_completas_lanza_con_prerequisito_incompleto():
    etapas = [_etapa("e1", avance=50), _etapa("e2", dependencias=["e1"], avance=10)]
    with pytest.raises(ErrorValidacion) as excinfo:
        exigir_dependencias_completas(etapas[1], 30, etapas)
    assert "Etapa e1" in str(excinfo.value)


def test_exigir_dependencias_completas_pasa_con_prerequisito_completo():
    etapas = [_etapa("e1", avance=100), _etapa("e2", dependencias=["e1"], avance=0)]
    exigir_dependencias_completas(etapas[1], 30, etapas)  # no lanza


def test_dependencias_gantt_ignora_huerfanas():
    etapas = [_etapa("e1"), _etapa("e2", dependencias=["e1"]), _etapa("e3", dependencias=["x"])]
    aristas = dependencias_gantt(etapas)
    assert aristas == [{"prerequisitoId": "e1", "dependienteId": "e2"}]


# ---------- Servicio y API ----------


def test_semilla_es_consistente_con_dependencias():
    e2 = next(e for e in ETAPAS_SEMILLA if e.id == "e2")
    e5 = next(e for e in ETAPAS_SEMILLA if e.id == "e5")
    assert e2.dependencias == ["e1"]
    assert e5.dependencias == ["e4"]
    e1 = next(e for e in ETAPAS_SEMILLA if e.id == "e1")
    e4 = next(e for e in ETAPAS_SEMILLA if e.id == "e4")
    assert e1.avance == 100 and e2.avance > 0
    assert e4.avance == 100 or e5.avance == 0


def test_crear_etapa_con_dependencias_validas_api():
    respuesta = client.post(
        f"/api/proyectos/{PROYECTO_2}/etapas",
        json={
            "nombre": "Con prerequisito",
            "fechaInicio": "2026-07-01",
            "fechaFin": "2026-07-31",
            "responsableId": "u-analista",
            "presupuestoAsignado": 5000,
            "dependencias": ["e4"],
        },
        headers={"X-Actor-Id": PM},
    )
    assert respuesta.status_code == 201
    etapa = respuesta.json()
    assert etapa["dependencias"] == ["e4"]


def test_editar_etapa_con_ciclo_422():
    # Una etapa nueva nunca forma ciclo (nadie apunta a ella); el ciclo solo
    # puede formarse al editar: e5 depende de e4 -> si e4 pasa a depender de
    # e5 se cierra el ciclo.
    respuesta = client.patch(
        "/api/etapas/e4",
        json={"dependencias": ["e5"]},
        headers={"X-Actor-Id": PM},
    )
    assert respuesta.status_code == 422


def test_crear_etapa_prerequisito_inexistente_422():
    respuesta = client.post(
        f"/api/proyectos/{PROYECTO_2}/etapas",
        json={
            "nombre": "Fantasma",
            "fechaInicio": "2026-07-01",
            "fechaFin": "2026-07-31",
            "responsableId": "u-analista",
            "presupuestoAsignado": 5000,
            "dependencias": ["no-existe"],
        },
        headers={"X-Actor-Id": PM},
    )
    assert respuesta.status_code == 422


def test_editar_etapa_agrega_dependencia():
    crear = client.post(
        f"/api/proyectos/{PROYECTO_2}/etapas",
        json={
            "nombre": "Editable",
            "fechaInicio": "2026-08-01",
            "fechaFin": "2026-08-31",
            "responsableId": "u-analista",
            "presupuestoAsignado": 5000,
        },
        headers={"X-Actor-Id": PM},
    )
    assert crear.status_code == 201
    etapa_id = crear.json()["id"]
    respuesta = client.patch(
        f"/api/etapas/{etapa_id}",
        json={"dependencias": ["e4"]},
        headers={"X-Actor-Id": PM},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["dependencias"] == ["e4"]


def test_editar_etapa_borra_dependencias_con_lista_vacia():
    crear = client.post(
        f"/api/proyectos/{PROYECTO_2}/etapas",
        json={
            "nombre": "Borrable",
            "fechaInicio": "2026-08-01",
            "fechaFin": "2026-08-31",
            "responsableId": "u-analista",
            "presupuestoAsignado": 5000,
            "dependencias": ["e4"],
        },
        headers={"X-Actor-Id": PM},
    )
    assert crear.status_code == 201
    etapa_id = crear.json()["id"]
    respuesta = client.patch(
        f"/api/etapas/{etapa_id}",
        json={"dependencias": []},
        headers={"X-Actor-Id": PM},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["dependencias"] == []


def test_eliminar_etapa_con_dependientes_422():
    crear = client.post(
        f"/api/proyectos/{PROYECTO_2}/etapas",
        json={
            "nombre": "Base",
            "fechaInicio": "2026-09-01",
            "fechaFin": "2026-09-30",
            "responsableId": "u-analista",
            "presupuestoAsignado": 5000,
        },
        headers={"X-Actor-Id": PM},
    )
    assert crear.status_code == 201
    base_id = crear.json()["id"]
    client.post(
        f"/api/proyectos/{PROYECTO_2}/etapas",
        json={
            "nombre": "Dependiente",
            "fechaInicio": "2026-10-01",
            "fechaFin": "2026-10-31",
            "responsableId": "u-analista",
            "presupuestoAsignado": 5000,
            "dependencias": [base_id],
        },
        headers={"X-Actor-Id": PM},
    )
    respuesta = client.delete(f"/api/etapas/{base_id}", headers={"X-Actor-Id": PM})
    assert respuesta.status_code == 422


def test_avance_bloqueado_por_prerequisito_incompleto():
    # e5 (p2) depende de e4 (10%): registrar avance > 0 debe fallar.
    respuesta = client.post(
        "/api/etapas/e5/avance",
        json={"avance": 10},
        headers={"X-Actor-Id": PM},
    )
    assert respuesta.status_code == 422
    assert "Modelo dimensional" in respuesta.json()["mensaje"]


def test_avance_libre_sin_dependencias():
    etapas = client.get(f"/api/proyectos/{PROYECTO_1}/etapas").json()
    e3 = next(e for e in etapas if e["id"] == "e3")
    assert e3["dependencias"] == []
    respuesta = client.post(
        f"/api/etapas/e3/avance",
        json={"avance": 25},
        headers={"X-Actor-Id": PM},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["avance"] == 25
