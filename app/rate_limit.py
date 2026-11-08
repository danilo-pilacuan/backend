"""Limitador de intentos de login en memoria (mitigacion VULN-003).

Ventana fija por clave (correo normalizado + IP del cliente): si en la
ventana se supera el maximo de intentos fallidos, los siguientes devuelven
429 hasta que la ventana expire. Solo cuentan los intentos FALLIDOS (un
usuario real que se equivoca una vez no acumula bloqueo con sus logins
exitosos posteriores). Config por entorno: RATE_LIMIT_LOGIN_INTENTOS
(5) y RATE_LIMIT_LOGIN_VENTANA_SEG (60); un valor de intentos <= 0
desactiva el limitador (escapes de pruebas o despliegues con un proxy
externo ya limitando).

Memoria, no persistente: reiniciar el servicio limpia los contadores, lo
que es aceptable para la demora del atacante y no afecta al dominio. Para
despliegues con varias instancias conviene un limitador externo (Redis);
queda registrado como decision abierta.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict


def intentos_permitidos_login() -> int:
    try:
        return int(os.environ.get("RATE_LIMIT_LOGIN_INTENTOS", "5").strip() or "5")
    except ValueError:
        return 5


def ventana_login_segundos() -> int:
    try:
        return int(os.environ.get("RATE_LIMIT_LOGIN_VENTANA_SEG", "60").strip() or "60")
    except ValueError:
        return 60


class LimitadorLogin:
    """Contador de fallos por clave con ventana fija y limpieza perezosa."""

    def __init__(self) -> None:
        self._fallos: dict[str, list[float]] = defaultdict(list)
        self._candado = threading.Lock()

    def registrar_fallo(self, clave: str, ahora: float | None = None) -> None:
        momento = time.time() if ahora is None else ahora
        ventana = ventana_login_segundos()
        with self._candado:
            lista = self._fallos[clave]
            lista.append(momento)
            self._fallos[clave] = [t for t in lista if t > momento - ventana]

    def bloqueado(self, clave: str, ahora: float | None = None) -> bool:
        """True si los fallos recientes alcanzan el maximo permitido."""
        maximo = intentos_permitidos_login()
        if maximo <= 0:
            return False
        momento = time.time() if ahora is None else ahora
        ventana = ventana_login_segundos()
        with self._candado:
            recientes = [t for t in self._fallos.get(clave, []) if t > momento - ventana]
            self._fallos[clave] = recientes
            return len(recientes) >= maximo

    def limpiar(self) -> None:
        """Vacía el registro (uso administrativo y de tests)."""
        with self._candado:
            self._fallos.clear()


limitador = LimitadorLogin()
