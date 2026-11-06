"""Autenticacion real (item 10.3, fase 14): credenciales y token de sesion.

Diseno:
- Contrase\u00f1a: hash PBKDF2-HMAC-SHA256 (stdlib hashlib) con sal aleatoria por
  usuario e iteraciones fijas. Nunca se almacena ni se devuelve texto plano.
- Credenciales: diccionario correo -> hash en memoria del proceso. Se siembran
  de forma perezosa en el primer login con la contrasena demo (env
  AUTH_CONTRASENA_DEMO, por defecto "projecthub-demo") y todo usuario nuevo
  creado por la API recibe la misma credencial demo. Limitacion documentada:
  no hay endpoint de cambio de contrasena, por lo que la memoria es suficiente;
  si se agrega, las credenciales deben migrar a su propia tabla (DEC pendiente).
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

_ITERACIONES = 240_000
_TokenDuracionSegundos = 7 * 24 * 3600

CONTRASENA_DEMO_DEFAULT = "projecthub-demo"


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
    except (ValueError, TypeError):
        return False


class ServicioCredenciales:
    """Credenciales por correo en memoria, sembradas de forma perezosa."""

    def __init__(self) -> None:
        self._hashes: dict[str, str] = {}

    def autenticar(self, correo: str, contrasena: str) -> bool:
        """True si la contrasena es valida. Siembra la demo si no existe credencial."""
        almacenado = self._hashes.get(correo)
        if almacenado is None:
            almacenado = hash_contrasena(contrasena_demo())
            self._hashes[correo] = almacenado
        return verificar_contrasena(contrasena, almacenado)

    def registrar(self, correo: str, contrasena: str) -> None:
        """Credencial inicial de un usuario nuevo (sobrescribe si re-crea)."""
        self._hashes[correo] = hash_contrasena(contrasena)


def leer_secreto(log: object) -> str:
    """AUTH_SECRET de entorno; sin ella, secreto efimero con warning (log.info/warning)."""
    secreto = os.environ.get("AUTH_SECRET", "").strip()
    if secreto:
        return secreto
    log.warning(  # type: ignore[attr-defined]
        "AUTH_SECRET no definida: se genera un secreto efimero; "
        "los tokens no sobreviviran al reinicio del servicio."
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
