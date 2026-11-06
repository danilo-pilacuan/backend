"""Errores de dominio tipados (espejo de shared-lib/domain/errores.ts, 9.3).

Codigos estables que la API mapea a HTTP y la UI puede traducir.
"""


class ErrorDominio(Exception):
    codigo = "VALIDACION"

    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


class ErrorTransicionInvalida(ErrorDominio):
    codigo = "TRANSICION_INVALIDA"

    def __init__(self, origen: str, destino: str) -> None:
        super().__init__(
            f'Transicion invalida: no se puede pasar de "{origen}" a "{destino}".'
        )


class ErrorPermisoDenegado(ErrorDominio):
    codigo = "PERMISO_DENEGADO"

    def __init__(self, accion: str, etapa: str, roles: list[str]) -> None:
        super().__init__(
            f'Permiso denegado: la accion "{accion}" en la etapa "{etapa}" requiere '
            f"uno de estos roles: {', '.join(roles)}."
        )


class ErrorValidacion(ErrorDominio):
    codigo = "VALIDACION"

    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)


class ErrorEstadoProyecto(ErrorDominio):
    codigo = "ESTADO_PROYECTO"

    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)


class ErrorEntidadNoEncontrada(ErrorDominio):
    codigo = "ENTIDAD_NO_ENCONTRADA"

    def __init__(self, entidad: str, id: str) -> None:
        super().__init__(f'{entidad} con id "{id}" no existe.')


class ErrorDuplicado(ErrorDominio):
    codigo = "DUPLICADO"

    def __init__(self, entidad: str, campo: str, valor: str) -> None:
        super().__init__(f'Ya existe {entidad} con {campo} "{valor}".')


# Mapeo codigo de dominio -> HTTP para la capa API (10.3).
CODIGOS_HTTP = {
    "ENTIDAD_NO_ENCONTRADA": 404,
    "DUPLICADO": 409,
    "PERMISO_DENEGADO": 409,
    "ESTADO_PROYECTO": 409,
    "TRANSICION_INVALIDA": 409,
    "VALIDACION": 422,
}
