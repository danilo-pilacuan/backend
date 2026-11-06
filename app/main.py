"""Punto de entrada FastAPI (seccion 7 de AGENTS.md, item 10.3).

Contrato JSON camelCase identico a @projecthub/shared; errores de dominio
mapeados a HTTP con body {codigo, mensaje}.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.rutas import _crear_router
from app.domain.errores import (
    CODIGOS_HTTP,
    ErrorDominio,
    ErrorDuplicado,
    ErrorEntidadNoEncontrada,
    ErrorEstadoProyecto,
    ErrorPermisoDenegado,
    ErrorTransicionInvalida,
    ErrorValidacion,
)
from app.servicio import ServicioProyectos

servicio = ServicioProyectos()

app = FastAPI(
    title="ProjectHub API",
    version="0.1.0",
    description=(
        "Backend de gobernanza de proyectos. El contrato JSON usa camelCase "
        "identico a @projecthub/shared; el actor de sesion llega en X-Actor-Id."
    ),
)

app.include_router(_crear_router())

_CODIGO_A_EXCEPCION: dict[type[ErrorDominio], str] = {
    ErrorEntidadNoEncontrada: "ENTIDAD_NO_ENCONTRADA",
    ErrorDuplicado: "DUPLICADO",
    ErrorPermisoDenegado: "PERMISO_DENEGADO",
    ErrorEstadoProyecto: "ESTADO_PROYECTO",
    ErrorTransicionInvalida: "TRANSICION_INVALIDA",
    ErrorValidacion: "VALIDACION",
}


@app.exception_handler(ErrorDominio)
def manejar_error_dominio(request: Request, error: ErrorDominio) -> JSONResponse:
    return JSONResponse(
        status_code=CODIGOS_HTTP[error.codigo],
        content={"codigo": error.codigo, "mensaje": error.mensaje},
    )


@app.exception_handler(Exception)
def manejar_error_inesperado(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"codigo": "ERROR_INTERNO", "mensaje": "Error interno del servidor."},
    )
