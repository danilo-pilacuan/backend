"""Grafo de transiciones del ciclo de vida (espejo de ciclo-vida.ts, 3.1-3.4).

Avances: cadena lineal Planteamiento -> ... -> Cierre. Retrocesos permitidos
(3.3): solo PoC -> Iniciativa y ValidacionPoC -> PoC.
"""

from .catalogos import ETAPAS_CICLO_VIDA, EtapasCicloVida
from .errores import ErrorTransicionInvalida

_INDICE_ETAPA: dict[str, int] = {etapa: i for i, etapa in enumerate(ETAPAS_CICLO_VIDA)}

# Retrocesos acotados: unica excepcion a la cadena lineal.
_RETROCESOS: dict[str, EtapasCicloVida] = {
    "PoC": "Iniciativa",
    "ValidacionPoC": "PoC",
}


def siguiente_etapa(etapa: EtapasCicloVida) -> EtapasCicloVida | None:
    i = _INDICE_ETAPA[etapa]
    if i < len(ETAPAS_CICLO_VIDA) - 1:
        return ETAPAS_CICLO_VIDA[i + 1]
    return None


def etapa_retroceso_permitido(etapa: EtapasCicloVida) -> EtapasCicloVida | None:
    return _RETROCESOS.get(etapa)


def es_transicion_valida(origen: EtapasCicloVida, destino: EtapasCicloVida) -> bool:
    if siguiente_etapa(origen) == destino:
        return True
    return etapa_retroceso_permitido(origen) == destino


def validar_transicion(origen: EtapasCicloVida, destino: EtapasCicloVida) -> EtapasCicloVida:
    if not es_transicion_valida(origen, destino):
        raise ErrorTransicionInvalida(origen, destino)
    return destino


def transiciones_disponibles(etapa: EtapasCicloVida) -> list[EtapasCicloVida]:
    destinos: list[EtapasCicloVida] = []
    sig = siguiente_etapa(etapa)
    if sig:
        destinos.append(sig)
    retro = etapa_retroceso_permitido(etapa)
    if retro:
        destinos.append(retro)
    return destinos
