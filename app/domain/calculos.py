"""Calculos de dominio (espejo de calculos.ts, 4.3-4.5, 5.2, 5.4).

Puros y sin framework; las rutas no los reimplementan.
"""

import math
from datetime import date

from .errores import ErrorValidacion

_MS_POR_DIA = 86_400_000  # paridad con la implementacion TS (unix epoch)


def _parse_fecha(fecha: str) -> date:
    try:
        return date.fromisoformat(fecha)
    except ValueError as exc:
        raise ErrorValidacion("Las fechas de la etapa deben ser fechas validas.") from exc


def duracion_dias(fecha_inicio: str, fecha_fin: str) -> int:
    inicio = _parse_fecha(fecha_inicio)
    fin = _parse_fecha(fecha_fin)
    if fin < inicio:
        raise ErrorValidacion("La fecha de fin no puede ser anterior a la fecha de inicio.")
    # (fin - inicio) en ms + 1 dia, como duracionDias de TS.
    diff_ms = (fin - inicio).days * _MS_POR_DIA
    return max(1, round(diff_ms / _MS_POR_DIA) + 1)


def validar_etapa(
    fecha_inicio: str,
    fecha_fin: str,
    avance: float,
    presupuesto_asignado: float,
    presupuesto_consumido: float,
) -> None:
    duracion_dias(fecha_inicio, fecha_fin)
    if not isinstance(avance, (int, float)) or isinstance(avance, bool) or not math.isfinite(avance) or avance < 0 or avance > 100:
        raise ErrorValidacion("El avance de la etapa debe estar entre 0 y 100.")
    for monto, mensaje in (
        (presupuesto_asignado, "El presupuesto asignado no puede ser negativo."),
        (presupuesto_consumido, "El presupuesto consumido no puede ser negativo."),
    ):
        if not isinstance(monto, (int, float)) or isinstance(monto, bool) or not math.isfinite(monto) or monto < 0:
            raise ErrorValidacion(mensaje)


def _redondear2(valor: float) -> float:
    return round(valor * 100) / 100


def avance_ponderado(etapas: list[dict]) -> float:
    """Promedio ponderado por duracion (4.4); 0 si no hay etapas."""
    if not etapas:
        return 0.0
    suma_ponderada = 0.0
    suma_duraciones = 0
    for etapa in etapas:
        validar_etapa(
            etapa["fecha_inicio"],
            etapa["fecha_fin"],
            etapa["avance"],
            etapa["presupuesto_asignado"],
            etapa["presupuesto_consumido"],
        )
        dias = duracion_dias(etapa["fecha_inicio"], etapa["fecha_fin"])
        suma_ponderada += etapa["avance"] * dias
        suma_duraciones += dias
    return _redondear2(suma_ponderada / suma_duraciones)


def presupuesto_total(etapas: list[dict]) -> float:
    total = 0.0
    for etapa in etapas:
        validar_etapa(
            etapa["fecha_inicio"],
            etapa["fecha_fin"],
            etapa["avance"],
            etapa["presupuesto_asignado"],
            etapa["presupuesto_consumido"],
        )
        total += etapa["presupuesto_asignado"]
    return _redondear2(total)


def consumo_total(etapas: list[dict]) -> float:
    total = 0.0
    for etapa in etapas:
        validar_etapa(
            etapa["fecha_inicio"],
            etapa["fecha_fin"],
            etapa["avance"],
            etapa["presupuesto_asignado"],
            etapa["presupuesto_consumido"],
        )
        total += etapa["presupuesto_consumido"]
    return _redondear2(total)


def desviacion_presupuesto(etapa: dict) -> float:
    validar_etapa(
        etapa["fecha_inicio"],
        etapa["fecha_fin"],
        etapa["avance"],
        etapa["presupuesto_asignado"],
        etapa["presupuesto_consumido"],
    )
    return _redondear2(etapa["presupuesto_consumido"] - etapa["presupuesto_asignado"])


def presupuesto_excedido(etapa: dict) -> bool:
    return desviacion_presupuesto(etapa) > 0
