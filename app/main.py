"""Punto de entrada FastAPI (seccion 7 de AGENTS.md, item 10.3).

Contrato JSON camelCase identico a @projecthub/shared; errores de dominio
mapeados a HTTP con body {codigo, mensaje}. La persistencia se elige por
DATABASE_URL (DEC-006): RepositorioPostgres si esta definida, o
RepositorioMemoria con semilla por defecto.
"""

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.almacen import RepositorioMemoria, RepositorioPostgres
from app.api.rutas import _crear_router
from app.auth import ServicioCredenciales, leer_secreto
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

# Carga backend/.env una sola vez al importar: DATABASE_URL y credenciales de
# la BD viven en configuracion (DEC-001/DEC-006), nunca como literales.
# No sobreescribe variables ya presentes en el entorno.
load_dotenv()

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

# Autenticacion (10.3, fase 14): credenciales en memoria + secreto de firma JWT.
credenciales = ServicioCredenciales()
secreto_auth = leer_secreto(logger)

app = FastAPI(
    title="ProjectHub API",
    version="0.1.0",
    description=(
        "Backend de gobernanza de proyectos. El contrato JSON usa camelCase "
        "identico a @projecthub/shared; autenticacion por Bearer JWT en "
        "/api/auth/login (X-Actor-Id queda como fallback de compatibilidad)."
    ),
)

app.include_router(_crear_router())

# CORS para el frontend federado (shell en 4300/4400, remotes 4301-4304).
# Sin credenciales (cookies); la sesion viaja en el header Authorization
# (Bearer JWT) y X-Actor-Id queda como fallback.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4300",
        "http://localhost:4400",
        "http://localhost:4301",
        "http://localhost:4302",
        "http://localhost:4303",
        "http://localhost:4304",
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Actor-Id", "Authorization"],
)

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
