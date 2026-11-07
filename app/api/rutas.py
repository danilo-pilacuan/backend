"""Rutas REST (10.3): agregados de dominio como HTTP, contrato camelCase.

El actor de la sesion simulada llega en el header X-Actor-Id (hasta 1.5/1.6
de autenticacion real). Los codigos de ErrorDominio se mapean a HTTP en el
handler global de main.py: 404 no encontrado, 409 conflicto de estado o
permiso, 422 validacion.
"""

from fastapi import APIRouter, Depends, Header, HTTPException

from app.auth import (
    ServicioCredenciales,
    contrasena_demo,
    crear_token,
    extraer_bearer,
    leer_secreto,
    leer_token,
)
from app.domain.errores import ErrorEntidadNoEncontrada, ErrorValidacion
from app.domain.modelos import Usuario
from app.servicio import ServicioProyectos, ResumenProyecto

from .esquemas import (
    CuerpoAvance,
    CuerpoCambioContrasena,
    CuerpoComentario,
    CuerpoConsumo,
    CuerpoEdicionEtapa,
    CuerpoEdicionProyecto,
    CuerpoEdicionUsuario,
    CuerpoEntregable,
    CuerpoEtapa,
    CuerpoLogin,
    CuerpoProyecto,
    CuerpoTransicion,
    CuerpoUsuario,
)


def obtener_servicio() -> ServicioProyectos:
    from app.main import servicio

    return servicio


def obtener_credenciales() -> ServicioCredenciales:
    from app.main import credenciales

    return credenciales


def obtener_secreto() -> str:
    from app.main import secreto_auth

    return secreto_auth


def obtener_actor(
    authorization: str | None = Header(default=None),
    x_actor_id: str | None = Header(default=None),
    servicio: ServicioProyectos = Depends(obtener_servicio),
    secreto: str = Depends(obtener_secreto),
) -> Usuario:
    """Actor de la peticion: Bearer JWT (prioridad) o X-Actor-Id (compatibilidad)."""
    token = extraer_bearer(authorization)
    if token is not None:
        usuario_id = leer_token(token, secreto)
        if usuario_id is None:
            raise ErrorValidacion("Token de sesion invalido o expirado.")
        actor = servicio.usuario_por_id(usuario_id)
        if actor is None:
            raise ErrorEntidadNoEncontrada("Usuario", usuario_id)
        return actor
    if not x_actor_id:
        raise ErrorValidacion("Falta autenticar la sesion (Bearer token o X-Actor-Id).")
    actor = servicio.usuario_por_id(x_actor_id)
    if actor is None:
        raise ErrorEntidadNoEncontrada("Usuario", x_actor_id)
    return actor


def _resumen_json(r: ResumenProyecto) -> dict:
    return {
        "proyecto": r.proyecto.model_dump(by_alias=True),
        "avance": r.avance,
        "presupuestoTotal": r.presupuesto_total,
        "consumoTotal": r.consumo_total,
        "excedido": r.excedido,
        "etapas": [e.model_dump(by_alias=True) for e in r.etapas],
    }


def _crear_router() -> APIRouter:
    router = APIRouter()

    # ----- Salud -----

    @router.get("/api/salud")
    def salud() -> dict:
        return {"estado": "ok", "servicio": "projecthub-backend"}

    # ----- Autenticacion (10.3, fase 14) -----

    @router.post("/api/auth/login")
    def iniciar_sesion(
        cuerpo: CuerpoLogin,
        servicio: ServicioProyectos = Depends(obtener_servicio),
        credenciales: ServicioCredenciales = Depends(obtener_credenciales),
        secreto: str = Depends(obtener_secreto),
    ) -> dict:
        """Valida credenciales y devuelve un JWT con sub = id de usuario."""
        usuario = next(
            (u for u in servicio.usuarios() if u.correo.lower() == cuerpo.correo.lower()),
            None,
        )
        if usuario is None or not credenciales.autenticar(usuario.correo, cuerpo.contrasena):
            raise HTTPException(
                status_code=401,
                detail={"codigo": "CREDENCIALES_INVALIDAS", "mensaje": "Correo o contrasena incorrectos."},
            )
        if not usuario.activo:
            raise HTTPException(
                status_code=403,
                detail={"codigo": "USUARIO_INACTIVO", "mensaje": "Un usuario inactivo no puede iniciar sesion."},
            )
        return {
            "token": crear_token(usuario.id, secreto),
            "tipo": "Bearer",
            "usuario": usuario.model_dump(by_alias=True),
        }

    @router.get("/api/auth/me")
    def usuario_actual(actor: Usuario = Depends(obtener_actor)) -> dict:
        """Usuario de la sesion (restaurar sesion al recargar el frontend)."""
        return actor.model_dump(by_alias=True)

    @router.put("/api/auth/contrasena")
    def cambiar_contrasena(
        cuerpo: CuerpoCambioContrasena,
        actor: Usuario = Depends(obtener_actor),
        credenciales: ServicioCredenciales = Depends(obtener_credenciales),
    ) -> dict:
        """Cambio de contrasena propia (14.5): exige la actual y politica minima.

        401 con CONTRASENA_ACTUAL_INVALIDA si la actual no verifica (no
        distingue usuario inexistente); ErrorValidacion -> 422 si la nueva
        viola la politica. La nueva credencial persiste en la tabla
        `credenciales` (Postgres) o memoria (fallback).
        """
        cambiada = credenciales.cambiar(actor.correo, cuerpo.contrasena_actual, cuerpo.contrasena_nueva)
        if not cambiada:
            raise HTTPException(
                status_code=401,
                detail={
                    "codigo": "CONTRASENA_ACTUAL_INVALIDA",
                    "mensaje": "La contrasena actual no es correcta.",
                },
            )
        return {"cambiada": True}

    # ----- Usuarios -----

    @router.get("/api/usuarios")
    def listar_usuarios(
        solo_activos: bool = False,
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> list[dict]:
        fuente = servicio.usuarios_activos() if solo_activos else servicio.usuarios()
        return [u.model_dump(by_alias=True) for u in fuente]

    @router.post("/api/usuarios", status_code=201)
    def crear_usuario(
        cuerpo: CuerpoUsuario,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
        credenciales: ServicioCredenciales = Depends(obtener_credenciales),
    ) -> dict:
        creado = servicio.crear_usuario(cuerpo.model_dump(), actor)
        # Credencial demo inicial; el cambio de contrasena es DEC pendiente.
        credenciales.registrar(creado.correo, contrasena_demo())
        return creado.model_dump(by_alias=True)

    @router.patch("/api/usuarios/{usuario_id}")
    def editar_usuario(
        usuario_id: str,
        cuerpo: CuerpoEdicionUsuario,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        servicio.editar_usuario(usuario_id, cuerpo.model_dump(exclude_none=True), actor)
        actualizado = servicio.usuario_por_id(usuario_id)
        if actualizado is None:
            raise ErrorEntidadNoEncontrada("Usuario", usuario_id)
        return actualizado.model_dump(by_alias=True)

    # ----- Proyectos -----

    @router.get("/api/proyectos")
    def listar_proyectos(
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> list[dict]:
        return [p.model_dump(by_alias=True) for p in servicio.proyectos()]

    @router.post("/api/proyectos", status_code=201)
    def crear_proyecto(
        cuerpo: CuerpoProyecto,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        creado = servicio.crear_proyecto(cuerpo.model_dump(), actor)
        return creado.model_dump(by_alias=True)

    @router.get("/api/proyectos/resumenes")
    def listar_resumenes(
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> list[dict]:
        return [_resumen_json(r) for r in servicio.resumenes()]

    @router.get("/api/proyectos/{proyecto_id}")
    def obtener_proyecto(
        proyecto_id: str,
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        proyecto = servicio.proyecto_por_id(proyecto_id)
        if proyecto is None:
            raise ErrorEntidadNoEncontrada("Proyecto", proyecto_id)
        return proyecto.model_dump(by_alias=True)

    @router.get("/api/proyectos/{proyecto_id}/resumen")
    def obtener_resumen(
        proyecto_id: str,
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        return _resumen_json(servicio.resumen(proyecto_id))

    @router.get("/api/proyectos/{proyecto_id}/gate")
    def obtener_gate(
        proyecto_id: str,
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        gate = servicio.gate_actual(proyecto_id)
        return {
            "etapa": gate.etapa,
            "abierto": gate.abierto,
            "entregables": [e.model_dump(by_alias=True) for e in gate.entregables],
            "faltantes": gate.faltantes,
            "pendientesAprobacion": list(gate.pendientes_aprobacion),
        }

    @router.patch("/api/proyectos/{proyecto_id}")
    def editar_proyecto(
        proyecto_id: str,
        cuerpo: CuerpoEdicionProyecto,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        servicio.editar_proyecto(proyecto_id, cuerpo.model_dump(exclude_none=True), actor)
        return servicio.proyecto_por_id(proyecto_id).model_dump(by_alias=True)  # type: ignore[union-attr]

    @router.post("/api/proyectos/{proyecto_id}/transicionar", status_code=200)
    def transicionar(
        proyecto_id: str,
        cuerpo: CuerpoTransicion,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        servicio.transicionar(proyecto_id, cuerpo.destino, actor, cuerpo.comentario)
        actualizado = servicio.proyecto_por_id(proyecto_id)
        if actualizado is None:
            raise ErrorEntidadNoEncontrada("Proyecto", proyecto_id)
        return actualizado.model_dump(by_alias=True)

    @router.post("/api/proyectos/{proyecto_id}/cancelar")
    def cancelar_proyecto(
        proyecto_id: str,
        cuerpo: CuerpoComentario | None = None,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        servicio.cancelar_proyecto(
            proyecto_id,
            actor,
            cuerpo.comentario if cuerpo is not None else None,
        )
        actualizado = servicio.proyecto_por_id(proyecto_id)
        if actualizado is None:
            raise ErrorEntidadNoEncontrada("Proyecto", proyecto_id)
        return actualizado.model_dump(by_alias=True)

    @router.post("/api/proyectos/{proyecto_id}/cerrar")
    def cerrar_proyecto(
        proyecto_id: str,
        cuerpo: CuerpoComentario | None = None,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        servicio.cerrar_proyecto(
            proyecto_id,
            actor,
            cuerpo.comentario if cuerpo is not None else None,
        )
        actualizado = servicio.proyecto_por_id(proyecto_id)
        if actualizado is None:
            raise ErrorEntidadNoEncontrada("Proyecto", proyecto_id)
        return actualizado.model_dump(by_alias=True)

    # ----- Etapas de trabajo -----

    @router.get("/api/proyectos/{proyecto_id}/etapas")
    def listar_etapas(
        proyecto_id: str,
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> list[dict]:
        return [e.model_dump(by_alias=True) for e in servicio.etapas_de_proyecto(proyecto_id)]

    @router.post("/api/proyectos/{proyecto_id}/etapas", status_code=201)
    def crear_etapa(
        proyecto_id: str,
        cuerpo: CuerpoEtapa,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        datos = cuerpo.model_dump()
        datos["proyecto_id"] = proyecto_id
        return servicio.crear_etapa(datos, actor).model_dump(by_alias=True)

    @router.patch("/api/etapas/{etapa_id}")
    def editar_etapa(
        etapa_id: str,
        cuerpo: CuerpoEdicionEtapa,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        cambios = cuerpo.model_dump(exclude_none=True)
        if "dependencias" in cuerpo.model_fields_set:
            # 6.5: enviar [] explicitamente borra las dependencias; exclude_none
            # no distingue, asi que se marca aparte.
            cambios["dependencias"] = cuerpo.dependencias
        servicio.editar_etapa(etapa_id, cambios, actor)
        return servicio._exigir_etapa(etapa_id).model_dump(by_alias=True)  # noqa: SLF001

    @router.delete("/api/etapas/{etapa_id}", status_code=204)
    def eliminar_etapa(
        etapa_id: str,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> None:
        servicio.eliminar_etapa(etapa_id, actor)

    @router.post("/api/etapas/{etapa_id}/avance")
    def registrar_avance(
        etapa_id: str,
        cuerpo: CuerpoAvance,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        servicio.registrar_avance(etapa_id, cuerpo.avance, actor)
        return servicio._exigir_etapa(etapa_id).model_dump(by_alias=True)  # noqa: SLF001

    @router.post("/api/etapas/{etapa_id}/consumo")
    def registrar_consumo(
        etapa_id: str,
        cuerpo: CuerpoConsumo,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        servicio.registrar_consumo(etapa_id, cuerpo.consumo, actor)
        return servicio._exigir_etapa(etapa_id).model_dump(by_alias=True)  # noqa: SLF001

    # ----- Entregables -----

    @router.get("/api/proyectos/{proyecto_id}/entregables")
    def listar_entregables(
        proyecto_id: str,
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> list[dict]:
        return [e.model_dump(by_alias=True) for e in servicio.entregables_de_proyecto(proyecto_id)]

    @router.post("/api/proyectos/{proyecto_id}/entregables", status_code=201)
    def crear_entregable(
        proyecto_id: str,
        cuerpo: CuerpoEntregable,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        datos = cuerpo.model_dump()
        datos["proyecto_id"] = proyecto_id
        return servicio.crear_entregable(datos, actor).model_dump(by_alias=True)

    @router.post("/api/entregables/{entregable_id}/aprobar")
    def aprobar_entregable(
        entregable_id: str,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        servicio.aprobar_entregable(entregable_id, actor)
        return servicio._exigir_entregable(entregable_id).model_dump(by_alias=True)  # noqa: SLF001

    # ----- Bitacora -----

    @router.get("/api/proyectos/{proyecto_id}/bitacora")
    def listar_bitacora(
        proyecto_id: str,
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> list[dict]:
        return [b.model_dump(by_alias=True) for b in servicio.bitacora_de_proyecto(proyecto_id)]

    # ----- Sincronizacion de estado (13.4: escrituras del frontend) -----

    @router.get("/api/sincronizacion")
    def leer_estado(
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        """Estado completo del dominio para el bootstrap de los stores."""
        return servicio.estado_completo()

    @router.put("/api/sincronizacion")
    def escribir_estado(
        cuerpo: dict,
        actor: Usuario = Depends(obtener_actor),
        servicio: ServicioProyectos = Depends(obtener_servicio),
    ) -> dict:
        """Reemplaza el estado con el del cliente (re-sync total).

        El frontend valida con las mismas reglas de dominio y empuja su
        estado completo tras cada mutacion; el backend revalida la
        invariante minima (estructuras y unicidad) y persiste.
        """
        return servicio.escribir_estado_completo(cuerpo, actor.id)

    return router
