"""Cuerpos de peticion (entrada JSON camelCase, populate_by_name snake_case)."""

from pydantic import BaseModel, ConfigDict

from app.domain.catalogos import EtapasCicloVida, Roles


def _alias_camel_case(nombre: str) -> str:
    cabeza, *cola = nombre.split("_")
    return cabeza + "".join(parte.capitalize() for parte in cola)


class Cuerpo(BaseModel):
    model_config = ConfigDict(alias_generator=_alias_camel_case, populate_by_name=True)


class CuerpoProyecto(Cuerpo):
    nombre: str
    descripcion: str = ""
    patrocinador_id: str | None = None
    presupuesto_estimado: float = 0
    fecha_objetivo: str = ""


class CuerpoEdicionProyecto(Cuerpo):
    nombre: str | None = None
    descripcion: str | None = None
    fecha_objetivo: str | None = None


class CuerpoComentario(Cuerpo):
    comentario: str | None = None


class CuerpoLogin(Cuerpo):
    correo: str
    contrasena: str


class CuerpoTransicion(Cuerpo):
    destino: EtapasCicloVida
    comentario: str | None = None


class CuerpoEtapa(Cuerpo):
    proyecto_id: str | None = None
    nombre: str
    fecha_inicio: str
    fecha_fin: str
    responsable_id: str
    presupuesto_asignado: float = 0
    avance: float = 0
    dependencias: list[str] = []  # 6.5: ids de etapas prerequisito


class CuerpoEdicionEtapa(Cuerpo):
    nombre: str | None = None
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    responsable_id: str | None = None
    presupuesto_asignado: float | None = None
    avance: float | None = None
    dependencias: list[str] | None = None  # 6.5: reemplaza la lista completa


class CuerpoAvance(Cuerpo):
    avance: float


class CuerpoConsumo(Cuerpo):
    consumo: float


class CuerpoEntregable(Cuerpo):
    etapa: EtapasCicloVida
    nombre: str
    version: int = 1


class CuerpoUsuario(Cuerpo):
    nombre: str
    correo: str
    roles: list[Roles]
    activo: bool = True


class CuerpoEdicionUsuario(Cuerpo):
    nombre: str | None = None
    correo: str | None = None
    roles: list[Roles] | None = None
    activo: bool | None = None
