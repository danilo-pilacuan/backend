"""Matriz de responsabilidades (espejo de matriz-permisos.ts, 1.5).

Que acciones puede hacer cada rol en cada etapa del ciclo de vida.
"""

from .catalogos import Acciones, EtapasCicloVida, Roles
from .errores import ErrorPermisoDenegado

TODOS_LOS_ROLES: tuple[Roles, ...] = (
    "Admin",
    "Sponsor",
    "ProjectManager",
    "Analista",
    "Stakeholder",
)
SOLO_GOBERNANZA: tuple[Roles, ...] = ("Admin", "Sponsor")
GOBERNANZA_Y_PM: tuple[Roles, ...] = ("Admin", "Sponsor", "ProjectManager")

MATRIZ: dict[EtapasCicloVida, dict[Acciones, tuple[Roles, ...]]] = {
    "Planteamiento": {
        "verProyecto": TODOS_LOS_ROLES,
        "editarProyecto": GOBERNANZA_Y_PM,
        "avanzarEtapa": GOBERNANZA_Y_PM,
        "retrocederEtapa": (),
        "aprobarEntregable": SOLO_GOBERNANZA,
        "editarEtapaTrabajo": GOBERNANZA_Y_PM,
        "editarPresupuesto": GOBERNANZA_Y_PM,
        "registrarConsumo": (),
        "cancelarProyecto": SOLO_GOBERNANZA,
        "cerrarProyecto": (),
    },
    "Iniciativa": {
        "verProyecto": TODOS_LOS_ROLES,
        "editarProyecto": GOBERNANZA_Y_PM,
        "avanzarEtapa": GOBERNANZA_Y_PM,
        "retrocederEtapa": (),
        "aprobarEntregable": SOLO_GOBERNANZA,
        "editarEtapaTrabajo": GOBERNANZA_Y_PM,
        "editarPresupuesto": GOBERNANZA_Y_PM,
        "registrarConsumo": (),
        "cancelarProyecto": SOLO_GOBERNANZA,
        "cerrarProyecto": (),
    },
    "PoC": {
        "verProyecto": TODOS_LOS_ROLES,
        "editarProyecto": GOBERNANZA_Y_PM,
        "avanzarEtapa": SOLO_GOBERNANZA,
        "retrocederEtapa": SOLO_GOBERNANZA,
        "aprobarEntregable": SOLO_GOBERNANZA,
        "editarEtapaTrabajo": GOBERNANZA_Y_PM,
        "editarPresupuesto": GOBERNANZA_Y_PM,
        "registrarConsumo": (),
        "cancelarProyecto": SOLO_GOBERNANZA,
        "cerrarProyecto": (),
    },
    "ValidacionPoC": {
        "verProyecto": TODOS_LOS_ROLES,
        "editarProyecto": GOBERNANZA_Y_PM,
        "avanzarEtapa": SOLO_GOBERNANZA,
        "retrocederEtapa": SOLO_GOBERNANZA,
        "aprobarEntregable": SOLO_GOBERNANZA,
        "editarEtapaTrabajo": GOBERNANZA_Y_PM,
        "editarPresupuesto": GOBERNANZA_Y_PM,
        "registrarConsumo": (),
        "cancelarProyecto": SOLO_GOBERNANZA,
        "cerrarProyecto": (),
    },
    "Planeacion": {
        "verProyecto": TODOS_LOS_ROLES,
        "editarProyecto": GOBERNANZA_Y_PM,
        "avanzarEtapa": SOLO_GOBERNANZA,
        "retrocederEtapa": (),
        "aprobarEntregable": SOLO_GOBERNANZA,
        "editarEtapaTrabajo": GOBERNANZA_Y_PM,
        "editarPresupuesto": GOBERNANZA_Y_PM,
        "registrarConsumo": (),
        "cancelarProyecto": SOLO_GOBERNANZA,
        "cerrarProyecto": (),
    },
    "Contratos": {
        "verProyecto": TODOS_LOS_ROLES,
        "editarProyecto": SOLO_GOBERNANZA,
        "avanzarEtapa": SOLO_GOBERNANZA,
        "retrocederEtapa": (),
        "aprobarEntregable": SOLO_GOBERNANZA,
        "editarEtapaTrabajo": SOLO_GOBERNANZA,
        "editarPresupuesto": SOLO_GOBERNANZA,
        "registrarConsumo": (),
        "cancelarProyecto": SOLO_GOBERNANZA,
        "cerrarProyecto": (),
    },
    "Ejecucion": {
        "verProyecto": TODOS_LOS_ROLES,
        "editarProyecto": GOBERNANZA_Y_PM,
        "avanzarEtapa": SOLO_GOBERNANZA,
        "retrocederEtapa": (),
        "aprobarEntregable": SOLO_GOBERNANZA,
        "editarEtapaTrabajo": GOBERNANZA_Y_PM,
        "editarPresupuesto": SOLO_GOBERNANZA,
        "registrarConsumo": GOBERNANZA_Y_PM,
        "cancelarProyecto": SOLO_GOBERNANZA,
        "cerrarProyecto": (),
    },
    "Operacion": {
        "verProyecto": TODOS_LOS_ROLES,
        "editarProyecto": GOBERNANZA_Y_PM,
        "avanzarEtapa": SOLO_GOBERNANZA,
        "retrocederEtapa": (),
        "aprobarEntregable": SOLO_GOBERNANZA,
        "editarEtapaTrabajo": GOBERNANZA_Y_PM,
        "editarPresupuesto": SOLO_GOBERNANZA,
        "registrarConsumo": GOBERNANZA_Y_PM,
        "cancelarProyecto": SOLO_GOBERNANZA,
        "cerrarProyecto": (),
    },
    "Cierre": {
        "verProyecto": TODOS_LOS_ROLES,
        "editarProyecto": (),
        "avanzarEtapa": (),
        "retrocederEtapa": (),
        "aprobarEntregable": SOLO_GOBERNANZA,
        "editarEtapaTrabajo": (),
        "editarPresupuesto": (),
        "registrarConsumo": (),
        "cancelarProyecto": (),
        "cerrarProyecto": SOLO_GOBERNANZA,
    },
}


def roles_permitidos(etapa: EtapasCicloVida, accion: Acciones) -> tuple[Roles, ...]:
    return MATRIZ[etapa][accion]


def tiene_permiso(etapa: EtapasCicloVida, accion: Acciones, roles: list[Roles]) -> bool:
    permitidos = MATRIZ[etapa][accion]
    return any(r in permitidos for r in roles)


def exigir_permiso(etapa: EtapasCicloVida, accion: Acciones, roles: list[Roles]) -> None:
    if not tiene_permiso(etapa, accion, roles):
        raise ErrorPermisoDenegado(accion, etapa, list(MATRIZ[etapa][accion]))
