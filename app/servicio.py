"""Servicio de dominio (espejo de stores/project.store.ts y usuario.store.ts).

Reglas de negocio identicas: matriz de permisos, gate de etapa, ciclo de vida,
validaciones de etapa/presupuesto, bitacora inmutable y unicidad de
nombre/correo. El estado vive en un repositorio inyectado (app/almacen.py):
RepositorioMemoria por defecto (semilla en cada arranque) o RepositorioPostgres
cuando main.py recibe DATABASE_URL (DEC-006). El servicio nunca toca SQL.
"""

import itertools
import logging
import re
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError

from .almacen import RepositorioMemoria, RepositorioPostgres
from .domain.calculos import (
    avance_ponderado,
    consumo_total,
    presupuesto_excedido,
    presupuesto_total,
    validar_etapa,
)
from .domain.catalogos import Acciones, EstadoProyecto, EtapasCicloVida, Roles
from .domain.ciclo_vida import _INDICE_ETAPA, validar_transicion
from .domain.dependencias import (
    dependientes_de,
    exigir_dependencias_completas,
    validar_dependencias,
)
from .domain.errores import (
    ErrorDuplicado,
    ErrorEntidadNoEncontrada,
    ErrorEstadoProyecto,
    ErrorPermisoDenegado,
    ErrorValidacion,
)
from .domain.gates import EstadoGate, evaluar_gate, validar_aprobacion
from .domain.matriz_permisos import exigir_permiso
from .domain.modelos import BitacoraEntrada, Entregable, EtapaTrabajo, Proyecto, Usuario
from .semilla import (
    USUARIOS_SEMILLA,
)

logger = logging.getLogger("projecthub")

_CORREO_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

_contador = itertools.count(1)


def nuevo_id(prefijo: str) -> str:
    return f"{prefijo}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{next(_contador)}"


class ResumenProyecto(BaseModel):
    """Calculos agregados del proyecto (5.1-5.5); nada se edita a mano."""

    proyecto: Proyecto
    avance: float
    presupuesto_total: float
    consumo_total: float
    etapas: list[EtapaTrabajo]
    excedido: bool


class ServicioProyectos:
    """Casos de uso de proyectos, etapas, entregables, gates y bitacora.

    El estado se lee y escribe unicamente a traves de un repositorio
    (app/almacen.py); las properties privadas mantienen la forma de lista
    que usaban los 40+ metodos originales. Los agregados nuevos pasan por
    los metodos _agregar para funcionar igual con memoria y Postgres.
    """

    def __init__(
        self,
        repositorio: RepositorioMemoria | RepositorioPostgres | None = None,
    ) -> None:
        self._repo = repositorio if repositorio is not None else RepositorioMemoria()

    # Properties de acceso al repositorio. El setter hace el reemplazo de
    # coleccion completa (patron de comprension de lista del servicio); el
    # agregado de una entidad nueva debe usar los helpers _X_agregar.

    @property
    def _usuarios(self) -> list[Usuario]:
        return self._repo.usuarios()

    @_usuarios.setter
    def _usuarios(self, lista: list[Usuario]) -> None:
        self._repo.usuarios_reemplazar(lista)

    @property
    def _proyectos(self) -> list[Proyecto]:
        return self._repo.proyectos()

    @_proyectos.setter
    def _proyectos(self, lista: list[Proyecto]) -> None:
        self._repo.proyectos_reemplazar(lista)

    @property
    def _etapas(self) -> list[EtapaTrabajo]:
        return self._repo.etapas()

    @_etapas.setter
    def _etapas(self, lista: list[EtapaTrabajo]) -> None:
        self._repo.etapas_reemplazar(lista)

    @property
    def _entregables(self) -> list[Entregable]:
        return self._repo.entregables()

    @_entregables.setter
    def _entregables(self, lista: list[Entregable]) -> None:
        self._repo.entregables_reemplazar(lista)

    @property
    def _bitacora(self) -> list[BitacoraEntrada]:
        return self._repo.bitacora()

    @_bitacora.setter
    def _bitacora(self, lista: list[BitacoraEntrada]) -> None:
        self._repo.bitacora_reemplazar(lista)

    # Helpers de agregado (reemplazan los .append directos sobre la lista).

    def _usuarios_agregar(self, entidad: Usuario) -> None:
        self._repo.usuarios_agregar(entidad)

    def _proyectos_agregar(self, entidad: Proyecto) -> None:
        self._repo.proyectos_agregar(entidad)

    def _etapas_agregar(self, entidad: EtapaTrabajo) -> None:
        self._repo.etapas_agregar(entidad)

    def _entregables_agregar(self, entidad: Entregable) -> None:
        self._repo.entregables_agregar(entidad)

    def _bitacora_agregar(self, entidad: BitacoraEntrada) -> None:
        self._repo.bitacora_agregar(entidad)

    # ---------- Consultas ----------

    def proyectos(self) -> list[Proyecto]:
        return list(self._proyectos)

    def proyecto_por_id(self, proyecto_id: str) -> Proyecto | None:
        return next((p for p in self._proyectos if p.id == proyecto_id), None)

    def etapas_de_proyecto(self, proyecto_id: str) -> list[EtapaTrabajo]:
        return [e for e in self._etapas if e.proyecto_id == proyecto_id]

    def etapas(self) -> list[EtapaTrabajo]:
        return list(self._etapas)

    def entregables_de_proyecto(self, proyecto_id: str) -> list[Entregable]:
        return [e for e in self._entregables if e.proyecto_id == proyecto_id]

    def entregables(self) -> list[Entregable]:
        return list(self._entregables)

    def bitacora_de_proyecto(self, proyecto_id: str) -> list[BitacoraEntrada]:
        return [b for b in self._bitacora if b.proyecto_id == proyecto_id]

    def bitacora(self) -> list[BitacoraEntrada]:
        return list(self._bitacora)

    def resumen(self, proyecto_id: str) -> ResumenProyecto:
        proyecto = self._exigir_proyecto(proyecto_id)
        etapas = self.etapas_de_proyecto(proyecto_id)
        datos = [e.model_dump() for e in etapas]
        return ResumenProyecto(
            proyecto=proyecto,
            avance=avance_ponderado(datos),
            presupuesto_total=presupuesto_total(datos),
            consumo_total=consumo_total(datos),
            etapas=etapas,
            excedido=any(presupuesto_excedido(d) for d in datos),
        )

    def resumenes(self) -> list[ResumenProyecto]:
        return [self.resumen(p.id) for p in self._proyectos]

    def gate_actual(self, proyecto_id: str) -> EstadoGate:
        proyecto = self._exigir_proyecto(proyecto_id)
        return evaluar_gate(proyecto.etapa, self.entregables_de_proyecto(proyecto_id))

    # ---------- Sincronizacion de estado (13.4: escrituras del frontend) ----------

    def estado_completo(self) -> dict:
        """Estado completo del dominio en JSON camelCase (lectura masiva)."""
        return {
            "usuarios": [u.model_dump(mode="json", by_alias=True) for u in self._usuarios],
            "proyectos": [p.model_dump(mode="json", by_alias=True) for p in self._proyectos],
            "etapas": [e.model_dump(mode="json", by_alias=True) for e in self._etapas],
            "entregables": [e.model_dump(mode="json", by_alias=True) for e in self._entregables],
            "bitacora": [b.model_dump(mode="json", by_alias=True) for b in self._bitacora],
        }

    def escribir_estado_completo(self, cuerpo: dict, actor_id: str) -> dict:
        """Reemplaza el estado con el que empuja el cliente (re-sync total).

        Validacion minima: cada coleccion debe ser una lista de objetos con
        `id` string unico dentro de su coleccion; los modelos se validan con
        Pydantic (populate_by_name acepta camelCase). Lanza ErrorValidacion
        si el payload no tiene la forma esperada.
        """
        claves = {"usuarios", "proyectos", "etapas", "entregables", "bitacora"}
        for clave in claves:
            coleccion = cuerpo.get(clave)
            if not isinstance(coleccion, list):
                raise ErrorValidacion(f"La coleccion '{clave}' debe ser una lista.")
            ids = [item.get("id") for item in coleccion if isinstance(item, dict)]
            if any(not isinstance(i, str) for i in ids):
                raise ErrorValidacion(f"Todas las entidades de '{clave}' requieren id string.")
            if len(ids) != len(set(ids)):
                raise ErrorValidacion(f"La coleccion '{clave}' tiene ids duplicados.")
        try:
            usuarios = [Usuario.model_validate(u) for u in cuerpo["usuarios"]]
            proyectos = [Proyecto.model_validate(p) for p in cuerpo["proyectos"]]
            etapas = [EtapaTrabajo.model_validate(e) for e in cuerpo["etapas"]]
            entregables = [Entregable.model_validate(e) for e in cuerpo["entregables"]]
            bitacora = [BitacoraEntrada.model_validate(b) for b in cuerpo["bitacora"]]
        except ValidationError as exc:
            raise ErrorValidacion(f"Entidad invalida en el estado: {exc}") from exc
        self._usuarios = usuarios
        self._proyectos = proyectos
        self._etapas = etapas
        self._entregables = entregables
        self._bitacora = bitacora
        logger.info("Estado sincronizado por el actor %s (%d proyectos).", actor_id, len(proyectos))
        from .auth import ServicioCredenciales

        credenciales: ServicioCredenciales | None = getattr(self, "_credenciales", None)
        if credenciales is not None:
            credenciales.sincronizar_con_usuarios({u.correo for u in usuarios})
        return self.estado_completo()

    def asignar_credenciales(self, credenciales: object) -> None:
        """Inyeccion tardia del servicio de credenciales (14.5): el singleton
        se crea antes que las credenciales por orden de import; el enlace se
        hace al cablear la app para limpiar huerfanas en cada re-sync."""
        self._credenciales = credenciales

    # ---------- Proyectos ----------

    def crear_proyecto(self, datos: dict, actor: Usuario) -> Proyecto:
        self._exigir_actor_valido(actor)
        exigir_permiso("Planteamiento", "editarProyecto", actor.roles)
        nombre = str(datos.get("nombre", "")).strip()
        if not nombre:
            raise ErrorValidacion("El nombre del proyecto es obligatorio.")
        if self._existe_nombre(nombre):
            raise ErrorDuplicado("proyecto", "nombre", nombre)
        presupuesto = datos.get("presupuesto_estimado", 0)
        if isinstance(presupuesto, bool) or not isinstance(presupuesto, (int, float)) or presupuesto < 0:
            raise ErrorValidacion("El presupuesto estimado no puede ser negativo.")
        proyecto = Proyecto(
            id=nuevo_id("p"),
            nombre=nombre,
            descripcion=str(datos.get("descripcion", "")),
            patrocinador_id=str(datos.get("patrocinador_id", actor.id)),
            presupuesto_estimado=presupuesto,
            fecha_objetivo=str(datos.get("fecha_objetivo", "")),
            etapa="Planteamiento",
            estado="Activo",
        )
        self._proyectos_agregar(proyecto)
        self._registrar_bitacora(
            proyecto_id=proyecto.id,
            autor_id=actor.id,
            tipo="cambio",
            comentario="Proyecto creado en etapa Planteamiento.",
        )
        return proyecto

    def editar_proyecto(self, proyecto_id: str, cambios: dict, actor: Usuario) -> None:
        proyecto = self._exigir_proyecto(proyecto_id)
        self._exigir_actor_valido(actor)
        self._exigir_estado_editable(proyecto.estado, "editar el proyecto")
        exigir_permiso(proyecto.etapa, "editarProyecto", actor.roles)
        if cambios.get("nombre") is not None:
            nombre = str(cambios["nombre"]).strip()
            if not nombre:
                raise ErrorValidacion("El nombre del proyecto es obligatorio.")
            if self._existe_nombre(nombre, proyecto_id):
                raise ErrorDuplicado("proyecto", "nombre", nombre)
            cambios = {**cambios, "nombre": nombre}
        permitidos = ("nombre", "descripcion", "fecha_objetivo")
        filtrados = {k: v for k, v in cambios.items() if k in permitidos and v is not None}
        self._proyectos = [p if p.id != proyecto_id else p.model_copy(update=filtrados) for p in self._proyectos]
        self._registrar_bitacora(
            proyecto_id=proyecto_id,
            autor_id=actor.id,
            tipo="cambio",
            comentario="Proyecto editado.",
        )

    def cancelar_proyecto(self, proyecto_id: str, actor: Usuario, comentario: str | None = None) -> None:
        proyecto = self._exigir_proyecto(proyecto_id)
        self._exigir_actor_valido(actor)
        if proyecto.estado == "Cerrado":
            raise ErrorEstadoProyecto("Un proyecto cerrado es de solo lectura.")
        if proyecto.etapa == "Cierre":
            raise ErrorEstadoProyecto("No se puede cancelar un proyecto en etapa Cierre; use cerrar proyecto.")
        exigir_permiso(proyecto.etapa, "cancelarProyecto", actor.roles)
        self._proyectos = [
            p if p.id != proyecto_id else p.model_copy(update={"estado": "Cancelado"}) for p in self._proyectos
        ]
        self._registrar_bitacora(
            proyecto_id=proyecto_id,
            autor_id=actor.id,
            tipo="cambio",
            comentario=comentario or "Proyecto cancelado.",
        )

    def cerrar_proyecto(self, proyecto_id: str, actor: Usuario, comentario: str | None = None) -> None:
        proyecto = self._exigir_proyecto(proyecto_id)
        self._exigir_actor_valido(actor)
        if proyecto.etapa != "Cierre":
            raise ErrorEstadoProyecto("Solo se puede cerrar un proyecto en etapa Cierre.")
        if proyecto.estado == "Cerrado":
            raise ErrorEstadoProyecto("El proyecto ya esta cerrado.")
        exigir_permiso("Cierre", "cerrarProyecto", actor.roles)
        self._proyectos = [
            p if p.id != proyecto_id else p.model_copy(update={"estado": "Cerrado"}) for p in self._proyectos
        ]
        self._registrar_bitacora(
            proyecto_id=proyecto_id,
            autor_id=actor.id,
            tipo="cambio",
            comentario=comentario or "Proyecto cerrado.",
        )

    def transicionar(
        self,
        proyecto_id: str,
        destino: EtapasCicloVida,
        actor: Usuario,
        comentario: str | None = None,
    ) -> None:
        proyecto = self._exigir_proyecto(proyecto_id)
        self._exigir_actor_valido(actor)
        if proyecto.estado != "Activo":
            raise ErrorEstadoProyecto(f"Un proyecto {proyecto.estado.lower()} no admite transiciones.")
        validar_transicion(proyecto.etapa, destino)
        accion: Acciones = (
            "retrocederEtapa" if _INDICE_ETAPA[destino] < _INDICE_ETAPA[proyecto.etapa] else "avanzarEtapa"
        )
        exigir_permiso(proyecto.etapa, accion, actor.roles)
        gate = evaluar_gate(proyecto.etapa, self.entregables_de_proyecto(proyecto_id))
        if not gate.abierto:
            raise ErrorValidacion(
                f'El gate de "{proyecto.etapa}" esta cerrado: faltan {len(gate.faltantes)} '
                f"entregable(s) y hay {len(gate.pendientes_aprobacion)} sin aprobar."
            )
        self._proyectos = [
            p if p.id != proyecto_id else p.model_copy(update={"etapa": destino}) for p in self._proyectos
        ]
        self._registrar_bitacora(
            proyecto_id=proyecto_id,
            autor_id=actor.id,
            tipo="transicion",
            etapa_origen=proyecto.etapa,
            etapa_destino=destino,
            comentario=comentario,
        )

    # ---------- Etapas de trabajo ----------

    def crear_etapa(self, datos: dict, actor: Usuario) -> EtapaTrabajo:
        proyecto = self._exigir_proyecto(str(datos.get("proyecto_id", "")))
        self._exigir_actor_valido(actor)
        self._exigir_estado_editable(proyecto.estado, "crear etapas")
        exigir_permiso(proyecto.etapa, "editarEtapaTrabajo", actor.roles)
        etapa = EtapaTrabajo(
            id=nuevo_id("e"),
            proyecto_id=proyecto.id,
            nombre=str(datos.get("nombre", "")),
            fecha_inicio=str(datos.get("fecha_inicio", "")),
            fecha_fin=str(datos.get("fecha_fin", "")),
            responsable_id=str(datos.get("responsable_id", "")),
            presupuesto_asignado=float(datos.get("presupuesto_asignado", 0)),
            presupuesto_consumido=0,
            avance=float(datos.get("avance", 0)),
            dependencias=[str(d) for d in datos.get("dependencias", [])],
        )
        self._validar_datos_etapa(etapa)
        self._exigir_responsable_activo(etapa.responsable_id)
        self._validar_dependencias_candidata(etapa)
        self._etapas_agregar(etapa)
        self._registrar_bitacora(
            proyecto_id=proyecto.id,
            autor_id=actor.id,
            tipo="cambio",
            comentario=f'Etapa de trabajo "{etapa.nombre}" creada.',
        )
        return etapa

    def editar_etapa(self, etapa_id: str, cambios: dict, actor: Usuario) -> None:
        etapa = self._exigir_etapa(etapa_id)
        proyecto = self._exigir_proyecto(etapa.proyecto_id)
        self._exigir_actor_valido(actor)
        self._exigir_estado_editable(proyecto.estado, "editar etapas")
        exigir_permiso(proyecto.etapa, "editarEtapaTrabajo", actor.roles)
        # 6.5: dependencias enviadas explicitamente (incluso []) reemplazan la
        # lista completa; el resto de cambios None no sobreescribe.
        cambios_fusion = {k: v for k, v in cambios.items() if v is not None}
        if "dependencias" in cambios:
            cambios_fusion["dependencias"] = list(cambios["dependencias"])
        fusion = {**etapa.model_dump(), **cambios_fusion}
        candidata = EtapaTrabajo(**fusion)
        self._validar_datos_etapa(candidata)
        if cambios.get("responsable_id") is not None:
            self._exigir_responsable_activo(str(cambios["responsable_id"]))
        self._validar_dependencias_candidata(candidata)
        # 6.5: al editar siempre se reexige el invariante de prerequisitos 100%
        # si la etapa ya registra avance (protege contra relajar dependencias
        # de una etapa avanzada).
        exigir_dependencias_completas(
            candidata, candidata.avance, self._etapas_del_proyecto_local(proyecto.id, candidata)
        )
        self._etapas = [e if e.id != etapa_id else candidata for e in self._etapas]

    def eliminar_etapa(self, etapa_id: str, actor: Usuario) -> None:
        etapa = self._exigir_etapa(etapa_id)
        proyecto = self._exigir_proyecto(etapa.proyecto_id)
        self._exigir_actor_valido(actor)
        self._exigir_estado_editable(proyecto.estado, "eliminar etapas")
        exigir_permiso(proyecto.etapa, "editarEtapaTrabajo", actor.roles)
        dependientes = dependientes_de(etapa_id, self._etapas)
        if dependientes:
            nombres = ", ".join(d.nombre for d in dependientes)
            raise ErrorValidacion(
                f'No se puede eliminar la etapa "{etapa.nombre}": las etapas {nombres} dependen de ella.'
            )
        self._etapas = [e for e in self._etapas if e.id != etapa_id]

    def registrar_avance(self, etapa_id: str, avance: float, actor: Usuario) -> None:
        etapa = self._exigir_etapa(etapa_id)
        proyecto = self._exigir_proyecto(etapa.proyecto_id)
        self._exigir_actor_valido(actor)
        self._exigir_estado_editable(proyecto.estado, "registrar avance")
        exigir_permiso(proyecto.etapa, "editarEtapaTrabajo", actor.roles)
        candidata = etapa.model_copy(update={"avance": avance})
        self._validar_datos_etapa(candidata)
        exigir_dependencias_completas(candidata, avance, self._etapas_del_proyecto_local(proyecto.id, candidata))
        self._etapas = [e if e.id != etapa_id else candidata for e in self._etapas]

    def registrar_consumo(self, etapa_id: str, consumo: float, actor: Usuario) -> None:
        etapa = self._exigir_etapa(etapa_id)
        proyecto = self._exigir_proyecto(etapa.proyecto_id)
        self._exigir_actor_valido(actor)
        self._exigir_estado_editable(proyecto.estado, "registrar consumo")
        exigir_permiso(proyecto.etapa, "registrarConsumo", actor.roles)
        if isinstance(consumo, bool) or not isinstance(consumo, (int, float)) or consumo < 0:
            raise ErrorValidacion("El consumo no puede ser negativo.")
        self._etapas = [
            e if e.id != etapa_id else e.model_copy(update={"presupuesto_consumido": consumo}) for e in self._etapas
        ]

    # ---------- Entregables y gate ----------

    def crear_entregable(self, datos: dict, actor: Usuario) -> Entregable:
        proyecto = self._exigir_proyecto(str(datos.get("proyecto_id", "")))
        self._exigir_actor_valido(actor)
        self._exigir_estado_editable(proyecto.estado, "cargar entregables")
        entregable = Entregable(
            id=nuevo_id("ent"),
            proyecto_id=proyecto.id,
            etapa=datos["etapa"],
            nombre=str(datos.get("nombre", "")),
            version=int(datos.get("version", 1)),
            creado_por_id=actor.id,
        )
        self._entregables_agregar(entregable)
        self._registrar_bitacora(
            proyecto_id=proyecto.id,
            autor_id=actor.id,
            tipo="cambio",
            comentario=f'Entregable "{entregable.nombre}" cargado (v{entregable.version}).',
        )
        return entregable

    def aprobar_entregable(self, entregable_id: str, actor: Usuario) -> None:
        entregable = self._exigir_entregable(entregable_id)
        proyecto = self._exigir_proyecto(entregable.proyecto_id)
        self._exigir_actor_valido(actor)
        self._exigir_estado_editable(proyecto.estado, "aprobar entregables")
        exigir_permiso(entregable.etapa, "aprobarEntregable", actor.roles)
        validar_aprobacion(entregable, actor.id)
        aprobado_en = datetime.now(UTC).isoformat()
        self._entregables = [
            e
            if e.id != entregable_id
            else e.model_copy(update={"aprobado_por_id": actor.id, "aprobado_en": aprobado_en})
            for e in self._entregables
        ]
        self._registrar_bitacora(
            proyecto_id=proyecto.id,
            autor_id=actor.id,
            tipo="aprobacion",
            comentario=f'Entregable "{entregable.nombre}" aprobado (v{entregable.version}).',
        )

    # ---------- Usuarios (1.1-1.4, 1.8) ----------

    def usuarios(self) -> list[Usuario]:
        return list(self._usuarios)

    def usuarios_activos(self) -> list[Usuario]:
        return [u for u in self._usuarios if u.activo]

    def usuario_por_id(self, usuario_id: str) -> Usuario | None:
        return next((u for u in self._usuarios if u.id == usuario_id), None)

    def crear_usuario(self, datos: dict, actor: Usuario) -> Usuario:
        self._exigir_admin(actor)
        nombre = self._validar_nombre(str(datos.get("nombre", "")))
        correo = self._validar_correo(str(datos.get("correo", "")))
        roles = self._validar_roles(datos.get("roles"))
        usuario = Usuario(
            id=nuevo_id("u"),
            nombre=nombre,
            correo=correo,
            roles=roles,
            activo=bool(datos.get("activo", True)),
        )
        self._usuarios_agregar(usuario)
        return usuario

    def editar_usuario(self, usuario_id: str, cambios: dict, actor: Usuario) -> None:
        self._exigir_admin(actor)
        actual = self.usuario_por_id(usuario_id)
        if actual is None:
            raise ErrorValidacion(f'El usuario "{usuario_id}" no existe.')
        nombre = actual.nombre
        if cambios.get("nombre") is not None:
            nombre = self._validar_nombre(str(cambios["nombre"]))
        correo = actual.correo
        if cambios.get("correo") is not None:
            correo = self._validar_correo(str(cambios["correo"]), usuario_id)
        roles = actual.roles
        if cambios.get("roles") is not None:
            roles = self._validar_roles(cambios["roles"])
        activo = bool(cambios["activo"]) if cambios.get("activo") is not None else actual.activo
        credenciales = getattr(self, "_credenciales", None)
        if credenciales is not None and correo != actual.correo:
            credenciales.renombrar(actual.correo, correo)
        self._usuarios = [
            u
            if u.id != usuario_id
            else u.model_copy(update={"nombre": nombre, "correo": correo, "roles": roles, "activo": activo})
            for u in self._usuarios
        ]

    def desactivar_usuario(self, usuario_id: str, actor: Usuario) -> None:
        self.editar_usuario(usuario_id, {"activo": False}, actor)

    # ---------- Helpers ----------

    def _existe_nombre(self, nombre: str, excepto_id: str | None = None) -> bool:
        normalizado = nombre.lower()
        return any(p.id != excepto_id and p.nombre.lower() == normalizado for p in self._proyectos)

    def _exigir_proyecto(self, proyecto_id: str) -> Proyecto:
        proyecto = self.proyecto_por_id(proyecto_id)
        if proyecto is None:
            raise ErrorEntidadNoEncontrada("Proyecto", proyecto_id)
        return proyecto

    def _exigir_etapa(self, etapa_id: str) -> EtapaTrabajo:
        etapa = next((e for e in self._etapas if e.id == etapa_id), None)
        if etapa is None:
            raise ErrorEntidadNoEncontrada("Etapa de trabajo", etapa_id)
        return etapa

    def _exigir_entregable(self, entregable_id: str) -> Entregable:
        entregable = next((e for e in self._entregables if e.id == entregable_id), None)
        if entregable is None:
            raise ErrorEntidadNoEncontrada("Entregable", entregable_id)
        return entregable

    def _exigir_actor_valido(self, actor: Usuario) -> None:
        if not actor.activo:
            raise ErrorValidacion("Un usuario inactivo no puede ejecutar acciones (1.8).")

    def _exigir_estado_editable(self, estado: EstadoProyecto, operacion: str) -> None:
        if estado == "Cerrado":
            raise ErrorEstadoProyecto("Un proyecto cerrado es de solo lectura.")
        if estado == "Cancelado" and operacion != "registrar consumo":
            raise ErrorEstadoProyecto("Un proyecto cancelado no admite esta operacion.")

    def _exigir_responsable_activo(self, responsable_id: str) -> None:
        responsable = self.usuario_por_id(responsable_id)
        if responsable is None:
            raise ErrorEntidadNoEncontrada("Usuario", responsable_id)
        if not responsable.activo:
            raise ErrorValidacion("El responsable debe ser un usuario activo (1.8).")

    def _exigir_admin(self, actor: Usuario) -> None:
        semilla = any(u.id == actor.id for u in USUARIOS_SEMILLA)
        if not actor or not semilla or not actor.activo:
            raise ErrorValidacion("Se requiere una sesion activa para administrar usuarios.")
        if "Admin" not in actor.roles:
            raise ErrorPermisoDenegado("administrarUsuarios", "Administracion", ["Admin"])

    def _validar_datos_etapa(self, etapa: EtapaTrabajo) -> None:
        validar_etapa(
            etapa.fecha_inicio,
            etapa.fecha_fin,
            etapa.avance,
            etapa.presupuesto_asignado,
            etapa.presupuesto_consumido,
        )

    def _validar_dependencias_candidata(self, candidata: EtapaTrabajo) -> None:
        # 6.5: valida prerequisitos contra el estado proyectado (candidata ya
        # sustituida). En creacion la candidata aun no esta en _etapas, por lo
        # que se incluye explicitamente aunque su id sea nuevo.
        proyectadas = [e for e in self._etapas if e.proyecto_id == candidata.proyecto_id]
        if not any(e.id == candidata.id for e in proyectadas):
            proyectadas.append(candidata)
        validar_dependencias(candidata.id, candidata.proyecto_id, proyectadas)

    def _etapas_del_proyecto_local(self, proyecto_id: str, candidata: EtapaTrabajo) -> list[EtapaTrabajo]:
        # En edicion la candidata sustituye a la existente; en creacion (id
        # nuevo) se agrega. Cubre ambos casos como _validar_dependencias_candidata.
        resto = [e for e in self._etapas if e.proyecto_id == proyecto_id and e.id != candidata.id]
        return [*resto, candidata]

    def _validar_nombre(self, nombre: str) -> str:
        limpio = nombre.strip()
        if not limpio:
            raise ErrorValidacion("El nombre del usuario es obligatorio.")
        return limpio

    def _validar_correo(self, correo: str, excepto_id: str | None = None) -> str:
        limpio = correo.strip().lower()
        if not _CORREO_RE.match(limpio):
            raise ErrorValidacion("El correo no tiene un formato valido.")
        if any(u.correo == limpio and u.id != excepto_id for u in self._usuarios):
            raise ErrorDuplicado("usuario", "correo", limpio)
        return limpio

    def _validar_roles(self, roles: object) -> list[Roles]:
        if not isinstance(roles, (list, tuple)) or len(roles) == 0:
            raise ErrorValidacion("El usuario requiere al menos un rol (1.4).")
        validos: list[Roles] = []
        for rol in roles:
            if rol not in ("Admin", "Sponsor", "ProjectManager", "Analista", "Stakeholder"):
                raise ErrorValidacion(f'Rol desconocido: "{rol}".')
            if rol not in validos:
                validos.append(rol)  # type: ignore[arg-type]
        return validos

    def _registrar_bitacora(
        self,
        proyecto_id: str,
        autor_id: str,
        tipo: str,
        comentario: str | None = None,
        etapa_origen: EtapasCicloVida | None = None,
        etapa_destino: EtapasCicloVida | None = None,
    ) -> None:
        self._bitacora_agregar(
            BitacoraEntrada(
                id=nuevo_id("b"),
                proyecto_id=proyecto_id,
                autor_id=autor_id,
                fecha=datetime.now(UTC).isoformat(),
                tipo=tipo,  # type: ignore[arg-type]
                etapa_origen=etapa_origen,
                etapa_destino=etapa_destino,
                comentario=comentario,
            )
        )
