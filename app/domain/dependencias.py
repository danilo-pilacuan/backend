"""Reglas de dependencias entre etapas de trabajo (espejo de shared-lib 6.5).

Una etapa puede declarar prerequisitos: etapas del mismo proyecto que deben
estar al 100% antes de que la dependiente registre avance mayor que cero.
Funciones puras; el servicio y la API las invocan antes de mutar.
"""

from .errores import ErrorValidacion
from .modelos import EtapaTrabajo


def prerequisitos_de(etapa: EtapaTrabajo) -> list[str]:
    return list(etapa.dependencias or [])


def dependientes_de(etapa_id: str, etapas: list[EtapaTrabajo]) -> list[EtapaTrabajo]:
    return [e for e in etapas if etapa_id in prerequisitos_de(e)]


def validar_dependencias(etapa_id: str, proyecto_id: str, etapas_del_proyecto: list[EtapaTrabajo]) -> None:
    etapa = next((e for e in etapas_del_proyecto if e.id == etapa_id), None)
    if etapa is None:
        raise ErrorValidacion(f'La etapa "{etapa_id}" no pertenece al proyecto indicado.')
    vistas: list[str] = []
    for prerequisito in prerequisitos_de(etapa):
        if prerequisito == etapa_id:
            raise ErrorValidacion("Una etapa no puede depender de si misma.")
        if prerequisito in vistas:
            raise ErrorValidacion(f'La etapa declara el prerequisito "{prerequisito}" mas de una vez.')
        vistas.append(prerequisito)
        existe = next((e for e in etapas_del_proyecto if e.id == prerequisito), None)
        if existe is None:
            raise ErrorValidacion(f'El prerequisito "{prerequisito}" no existe o no pertenece al proyecto.')
        if existe.proyecto_id != proyecto_id:
            raise ErrorValidacion("Las dependencias solo se permiten entre etapas del mismo proyecto.")
    if tiene_ciclo(etapa_id, etapas_del_proyecto):
        raise ErrorValidacion("Las dependencias forman un ciclo entre etapas.")


def tiene_ciclo(etapa_id: str, etapas: list[EtapaTrabajo]) -> bool:
    # Grafo dirigido prerequisito -> dependiente; ciclo si el DFS revisita la raiz.
    aristas: dict[str, list[str]] = {}
    for etapa in etapas:
        for prerequisito in prerequisitos_de(etapa):
            aristas.setdefault(prerequisito, []).append(etapa.id)
    visitados: set[str] = set()
    pila: list[str] = [etapa_id]
    while pila:
        actual = pila[-1]
        if actual not in visitados:
            visitados.add(actual)
            for siguiente in aristas.get(actual, []):
                if siguiente == etapa_id or siguiente in pila:
                    return True
                if siguiente not in visitados:
                    pila.append(siguiente)
        else:
            pila.pop()
    return False


def exigir_dependencias_completas(etapa: EtapaTrabajo, avance_nuevo: float, etapas: list[EtapaTrabajo]) -> None:
    if avance_nuevo <= 0:
        return
    for prerequisito_id in prerequisitos_de(etapa):
        prerequisito = next((e for e in etapas if e.id == prerequisito_id), None)
        if prerequisito is None:
            continue  # ya validado al declarar; ignora ids huerfanos defensivamente.
        if prerequisito.avance < 100:
            raise ErrorValidacion(
                f'No se puede registrar avance en "{etapa.nombre}": su prerequisito '
                f'"{prerequisito.nombre}" tiene {prerequisito.avance}% y requiere 100%.'
            )


def dependencias_gantt(etapas: list[EtapaTrabajo]) -> list[dict]:
    aristas = []
    for etapa in etapas:
        for prerequisito_id in prerequisitos_de(etapa):
            if any(e.id == prerequisito_id for e in etapas):
                aristas.append({"prerequisitoId": prerequisito_id, "dependienteId": etapa.id})
    return aristas
