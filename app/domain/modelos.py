"""Modelos de dominio (espejo de shared-lib/domain/modelos.ts, 9.1).

Pydantic v2; las fechas viajan como string ISO para mantener el contrato JSON
identico al de @projecthub/shared (yyyy-mm-dd fechas, ISO datetime timestamps).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .catalogos import Acciones, EtapasCicloVida, EstadoProyecto, Roles


def _alias_camel_case(nombre: str) -> str:
    """proyecto_id -> proyectoId (contrato JSON identico a @projecthub/shared)."""

    cabeza, *cola = nombre.split("_")
    return cabeza + "".join(parte.capitalize() for parte in cola)


class ModeloDominio(BaseModel):
    """Base: acepta snake_case (populate_by_name) y serializa camelCase (alias)."""

    model_config = ConfigDict(frozen=True, alias_generator=_alias_camel_case, populate_by_name=True)


class Usuario(ModeloDominio):
    model_config = ConfigDict(frozen=True)

    id: str
    nombre: str
    correo: str
    roles: list[Roles]
    activo: bool


class EtapaTrabajo(ModeloDominio):
    model_config = ConfigDict(frozen=True)

    id: str
    proyecto_id: str
    nombre: str
    fecha_inicio: str  # ISO yyyy-mm-dd
    fecha_fin: str  # ISO yyyy-mm-dd
    responsable_id: str
    presupuesto_asignado: float
    presupuesto_consumido: float
    avance: float  # 0-100; el avance del proyecto se calcula, nunca se edita


class Proyecto(ModeloDominio):
    model_config = ConfigDict(frozen=True)

    id: str
    nombre: str
    descripcion: str
    patrocinador_id: str
    presupuesto_estimado: float
    fecha_objetivo: str  # ISO yyyy-mm-dd
    etapa: EtapasCicloVida
    estado: EstadoProyecto


class Entregable(ModeloDominio):
    model_config = ConfigDict(frozen=True)

    id: str
    proyecto_id: str
    etapa: EtapasCicloVida
    nombre: str
    version: int
    aprobado_por_id: str | None = None
    aprobado_en: str | None = None  # ISO datetime
    creado_por_id: str


class BitacoraEntrada(ModeloDominio):
    model_config = ConfigDict(frozen=True)

    id: str
    proyecto_id: str
    autor_id: str
    fecha: str  # ISO datetime
    tipo: Literal["transicion", "aprobacion", "cambio"]
    etapa_origen: EtapasCicloVida | None = None
    etapa_destino: EtapasCicloVida | None = None
    comentario: str | None = None


class PermisoMatriz(ModeloDominio):
    model_config = ConfigDict(frozen=True)

    etapa: EtapasCicloVida
    accion: Acciones
    roles: list[Roles]
