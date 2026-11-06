"""Catalogos de dominio (espejo de shared-lib/domain/catalogos.ts)."""

from typing import Literal

EstadoProyecto = Literal["Activo", "Cancelado", "Cerrado"]
ESTADOS_PROYECTO: tuple[str, ...] = ("Activo", "Cancelado", "Cerrado")

# Etapas del ciclo de vida (3.1): "Iniciativa" es una etapa, no una entidad.
EtapasCicloVida = Literal[
    "Planteamiento",
    "Iniciativa",
    "PoC",
    "ValidacionPoC",
    "Planeacion",
    "Contratos",
    "Ejecucion",
    "Operacion",
    "Cierre",
]
ETAPAS_CICLO_VIDA: tuple[EtapasCicloVida, ...] = (
    "Planteamiento",
    "Iniciativa",
    "PoC",
    "ValidacionPoC",
    "Planeacion",
    "Contratos",
    "Ejecucion",
    "Operacion",
    "Cierre",
)

Roles = Literal["Admin", "Sponsor", "ProjectManager", "Analista", "Stakeholder"]
ROLES: tuple[Roles, ...] = (
    "Admin",
    "Sponsor",
    "ProjectManager",
    "Analista",
    "Stakeholder",
)

Acciones = Literal[
    "verProyecto",
    "editarProyecto",
    "avanzarEtapa",
    "retrocederEtapa",
    "aprobarEntregable",
    "editarEtapaTrabajo",
    "editarPresupuesto",
    "registrarConsumo",
    "cancelarProyecto",
    "cerrarProyecto",
]
ACCIONES: tuple[Acciones, ...] = (
    "verProyecto",
    "editarProyecto",
    "avanzarEtapa",
    "retrocederEtapa",
    "aprobarEntregable",
    "editarEtapaTrabajo",
    "editarPresupuesto",
    "registrarConsumo",
    "cancelarProyecto",
    "cerrarProyecto",
)
