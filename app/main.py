"""Punto de entrada FastAPI (seccion 7 de AGENTS.md, item 10.3).

Contrato JSON camelCase identico a @projecthub/shared; errores de dominio
mapeados a HTTP con body {codigo, mensaje}. La persistencia se elige por
DATABASE_URL (DEC-006): RepositorioPostgres si esta definida, o
RepositorioMemoria con semilla por defecto.
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.almacen import RepositorioMemoria, RepositorioPostgres
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

logger = logging.getLogger("projecthub")


def _crear_repositorio() -> RepositorioMemoria | RepositorioPostgres:
    """Construye el repositorio segun DATABASE_URL con fallback a memoria.

    Un DSN invalido o una BD inaccesible degradan a memoria (semilla) en
    lugar de tumbar el arranque; el aviso queda en el log.
    """
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        return RepositorioMemoria()
    try:
        repositorio = RepositorioPostgres(dsn)
        repositorio.crear_esquema()
        repositorio.cargar_semilla()
        logger.info("Persistencia PostgreSQL activa (DATABASE_URL).")
        return repositorio
    except Exception as exc:  # pragma: no cover - ruta de degradacion
        logger.warning(
            "PostgreSQL no disponible (%s); se usa RepositorioMemoria.", exc
        )
        return RepositorioMemoria()


servicio = ServicioProyectos(_crear_repositorio())

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
