"""Autenticacion real (item 10.3, fase 14): credenciales y token de sesion.

Diseno:
- Contrase\u00f1a: hash PBKDF2-HMAC-SHA256 (stdlib hashlib) con sal aleatoria por
  usuario e iteraciones fijas. Nunca se almacena ni se devuelve texto plano.
- Credenciales (14.5): repositorio propio de hashes correo -> PBKDF2 (tabla
  `credenciales` en Postgres, o memoria sin DATABASE_URL). Se siembran de
  forma perezosa en el primer login con la contrasena demo (env
  AUTH_CONTRASENA_DEMO, por defecto "projecthub-demo") y todo usuario nuevo
  creado por la API recibe la misma credencial demo. El cambio de contrasena
  exige la actual (re-verificacion) y una minima politica de longitud.
- Token: JWT HS256 (PyJWT) con sub = id de usuario y exp. La firma vive en
  AUTH_SECRET (env); si no esta definida, se genera una aleatoria al arrancar
  (los tokens no sobreviven al reinicio) y queda un warning en el log.

El actor sigue llegando tambien por X-Actor-Id (compatibilidad con la sesion
simulada); el Bearer token tiene prioridad cuando esta presente.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

import jwt

from .almacen import RepositorioCredencialesMemoria

_ITERACIONES = 240_000
_TokenDuracionSegundos = 7 * 24 * 3600

CONTRASENA_DEMO_DEFAULT = "projecthub-demo"

# Politica minima de contrasena (14.5): longitud >= 8, sin mas reglas por ahora.
LONGITUD_MINIMA_CONTRASENA = 8


def contrasena_valida(contrasena: str) -> bool:
    """Politica minima de la contrasena nueva (14.5)."""
    return isinstance(contrasena, str) and len(contrasena) >= LONGITUD_MINIMA_CONTRASENA


def contrasena_demo() -> str:
    """Contrasena demo de semilla y de usuarios nuevos (config, no literal)."""
    return os.environ.get("AUTH_CONTRASENA_DEMO", "").strip() or CONTRASENA_DEMO_DEFAULT


def hash_contrasena(contrasena: str, sal: bytes | None = None) -> str:
    """Hash PBKDF2; formato "pbkdf2_sha256$iteraciones$sal_hex$hash_hex"."""
    sal = sal if sal is not None else secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), sal, _ITERACIONES)
    return f"pbkdf2_sha256${_ITERACIONES}${sal.hex()}${derivado.hex()}"


def verificar_contrasena(contrasena: str, almacenado: str) -> bool:
    """Comparacion constante; False ante cualquier formato inesperado."""
    try:
        algoritmo, iteraciones, sal_hex, hash_hex = almacenado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        derivado = hashlib.pbkdf2_hmac(
            "sha256",
            contrasena.encode("utf-8"),
            bytes.fromhex(sal_hex),
            int(iteraciones),
        )
        return hmac.compare_digest(derivado.hex(), hash_hex)
    except ValueError, TypeError:
        return False


class ServicioCredenciales:
    """Credenciales por correo sobre un repositorio (Postgres o memoria),
    sembradas de forma perezosa con la demo en el primer login.

    El repositorio se inyecta para que los tests usen memoria y el proceso
    real persista (14.5): cambiar la contrasena sobrevive al reinicio.
    """

    def __init__(self, repositorio: RepositorioCredencialesMemoria | None = None) -> None:
        self._repositorio = repositorio if repositorio is not None else RepositorioCredencialesMemoria()

    def autenticar(self, correo: str, contrasena: str) -> bool:
        """True si la contrasena es valida. Siembra la demo si no existe credencial."""
        almacenado = self._repositorio.listar().get(correo)
        if almacenado is None:
            almacenado = hash_contrasena(contrasena_demo())
            self._repositorio.guardar(correo, almacenado)
        return verificar_contrasena(contrasena, almacenado)

    def registrar(self, correo: str, contrasena: str) -> None:
        """Credencial inicial de un usuario nuevo (sobrescribe si re-crea)."""
        self._repositorio.guardar(correo, hash_contrasena(contrasena))

    def cambiar(self, correo: str, contrasena_actual: str, contrasena_nueva: str) -> bool:
        """Cambio de contrasena (14.5): exige la actual y la politica minima.

        Devuelve False si la credencial no existe o la actual no verifica.
        Lanza ErrorValidacion si la nueva viola la politica. Idempotente ante
        reintentos: la escritura es un upsert.
        """
        from .domain.errores import ErrorValidacion

        almacenado = self._repositorio.listar().get(correo)
        if almacenado is None:
            almacenado = hash_contrasena(contrasena_demo())
            self._repositorio.guardar(correo, almacenado)
        if not verificar_contrasena(contrasena_actual, almacenado):
            return False
        if not contrasena_valida(contrasena_nueva):
            raise ErrorValidacion(f"La contrasena nueva debe tener al menos {LONGITUD_MINIMA_CONTRASENA} caracteres.")
        self._repositorio.guardar(correo, hash_contrasena(contrasena_nueva))
        return True

    def renombrar(self, correo_anterior: str, correo_nuevo: str) -> None:
        """Mueve la credencial si el correo del usuario cambia (edicion de perfil)."""
        if correo_anterior == correo_nuevo:
            return
        hashes = self._repositorio.listar()
        hash_actual = hashes.get(correo_anterior)
        if hash_actual is None:
            return
        self._repositorio.guardar(correo_nuevo, hash_actual)
        self._repositorio.eliminar(correo_anterior)

    def sincronizar_con_usuarios(self, correos: set[str]) -> None:
        """Limpia credenciales huerfanas tras un re-sync total (14.5)."""
        self._repositorio.eliminar_excepto(correos)


def leer_secreto(log: object) -> str:
    """AUTH_SECRET de entorno; sin ella, secreto efimero con warning (log.info/warning)."""
    secreto = os.environ.get("AUTH_SECRET", "").strip()
    if secreto:
        return secreto
    log.warning(  # type: ignore[attr-defined]
        "AUTH_SECRET no definida: se genera un secreto efimero; los tokens no sobreviviran al reinicio del servicio."
    )
    return secrets.token_hex(32)


def crear_token(usuario_id: str, secreto: str, ahora: float | None = None) -> str:
    """JWT HS256 con sub y exp (7 dias)."""
    emitido = ahora if ahora is not None else time.time()
    payload = {"sub": usuario_id, "iat": int(emitido), "exp": int(emitido) + _TokenDuracionSegundos}
    return jwt.encode(payload, secreto, algorithm="HS256")


def leer_token(token: str, secreto: str) -> str | None:
    """Id del usuario si el token es valido y no expiro; None si no."""
    try:
        payload = jwt.decode(token, secreto, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None


def extraer_bearer(authorization: str | None) -> str | None:
    """Token de un header "Authorization: Bearer <jwt>"; None si no aplica."""
    if authorization is None:
        return None
    partes = authorization.split(" ", 1)
    if len(partes) == 2 and partes[0].lower() == "bearer" and partes[1].strip():
        return partes[1].strip()
    return None
