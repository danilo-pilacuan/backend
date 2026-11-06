"""Gate de etapa (espejo de gates.ts, 3.4 y principio rector del rulebook).

No se avanza de etapa sin los entregables obligatorios aprobados: el gate es
funcionalidad de primera clase, no un adorno.
"""

from pydantic import BaseModel

from .catalogos import EtapasCicloVida, Roles
from .errores import ErrorValidacion
from .modelos import Entregable

# Documentos obligatorios por etapa; sin ellos el gate no abre.
ENTREGABLES_OBLIGATORIOS: dict[EtapasCicloVida, tuple[str, ...]] = {
    "Planteamiento": ("Acta de planteamiento",),
    "Iniciativa": ("Documento de iniciativa",),
    "PoC": ("Plan de prueba de concepto",),
    "ValidacionPoC": ("Informe de validacion de PoC",),
    "Planeacion": ("Plan de proyecto",),
    "Contratos": ("Contrato o acta de compromisos",),
    "Ejecucion": ("Acta de avance de ejecucion",),
    "Operacion": ("Acta de operacion",),
    "Cierre": ("Acta de cierre",),
}

# Roles cuya aprobacion se exige para abrir el gate (matriz 1.5).
APROBADORES_REQUERIDOS: tuple[Roles, ...] = ("Admin", "Sponsor")


class EstadoGate(BaseModel):
    etapa: EtapasCicloVida
    entregables: list[Entregable]
    faltantes: list[str]
    pendientes_aprobacion: list[str]
    abierto: bool


def evaluar_gate(etapa: EtapasCicloVida, entregables: list[Entregable]) -> EstadoGate:
    obligatorios = ENTREGABLES_OBLIGATORIOS[etapa]
    de_etapa = [e for e in entregables if e.etapa == etapa]
    faltantes = [n for n in obligatorios if not any(e.nombre == n for e in de_etapa)]
    pendientes = [e.nombre for e in de_etapa if e.nombre in obligatorios and e.aprobado_por_id is None]
    return EstadoGate(
        etapa=etapa,
        entregables=de_etapa,
        faltantes=faltantes,
        pendientes_aprobacion=pendientes,
        abierto=len(faltantes) == 0 and len(pendientes) == 0,
    )


def validar_aprobacion(entregable: Entregable, aprobador_id: str) -> None:
    """Caso limite del rulebook: el autor no aprueba su propio documento y un
    entregable ya aprobado no se reaprueba."""
    if entregable.aprobado_por_id is not None:
        raise ErrorValidacion(
            f'El entregable "{entregable.nombre}" ya fue aprobado y no admite otra aprobacion.'
        )
    if entregable.creado_por_id == aprobador_id:
        raise ErrorValidacion("El autor de un entregable no puede aprobar su propio documento.")
