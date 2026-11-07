"""Capa de persistencia (DEC-006, item 13.2): repositorios para las 5
colecciones del dominio (usuarios, proyectos, etapas, entregables, bitacora).

Contrato: cada coleccion es una lista de modelos Pydantic frozen; las unicas
mutaciones que hace el servicio son append de una entidad y reemplazo de la
lista completa, por lo que el repositorio expone exactamente eso (mas un
volcado inicial para reponer la semilla). Sin DATABASE_URL (o si Postgres no
responde al arrancar) el ServicioProyectos cae a RepositorioMemoria y la
semilla se recarga en cada arranque, como hoy.

RepositorioPostgres persiste cada entidad como JSONB (serializacion camelCase
via alias, el mismo contrato que la API REST) en una tabla por coleccion. El
schema se crea en el arranque (CREATE TABLE IF NOT EXISTS) y la semilla carga
una sola vez si la tabla esta vacia (idempotente).
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Sequence

from .domain.modelos import (
    BitacoraEntrada,
    Entregable,
    EtapaTrabajo,
    Proyecto,
    Usuario,
)

_logger = logging.getLogger("projecthub.almacen")

# Coleccion: (modelo Pydantic, tipo devuelto, prefijo de id del seed)
# El prefijo es informativo (nuevo_id vive en servicio.py); aqui solo ordena
# el volcado y el seed.
_COLECCIONES: tuple[tuple[str, type, str], ...] = (
    ("usuarios", Usuario, "u"),
    ("proyectos", Proyecto, "p"),
    ("etapas", EtapaTrabajo, "t"),
    ("entregables", Entregable, "e"),
    ("bitacora", BitacoraEntrada, "b"),
)

# Fase 14.5: los hashes de contrasena viven en su propia tabla (correo ->
# hash PBKDF2), fuera del protocolo de sincronizacion: nunca viajan al
# frontend ni se exponen por la API. Clave = correo (el login busca por
# correo); renombrar correo mueve la credencial (renombrar()).
_TABLA_CREDENCIALES = "credenciales"


class RepositorioCredencialesMemoria:
    """Credenciales en memoria (fallback sin DATABASE_URL y tests)."""

    def __init__(self) -> None:
        self._hashes: dict[str, str] = {}

    def listar(self) -> dict[str, str]:
        return dict(self._hashes)

    def guardar(self, correo: str, hash_contrasena: str) -> None:
        self._hashes[correo] = hash_contrasena

    def eliminar(self, correo: str) -> None:
        self._hashes.pop(correo, None)

    def eliminar_excepto(self, correos: set[str]) -> None:
        for correo in [c for c in self._hashes if c not in correos]:
            self._hashes.pop(correo, None)


class RepositorioCredencialesPostgres:
    """Credenciales en su tabla PostgreSQL (14.5): correo text PRIMARY KEY,
    hash text NOT NULL. Contrato identico al repositorio en memoria; las
    escrituras son upsert y transaccion propia por operacion."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._conn_lectura = psycopg.connect(dsn, autocommit=True)
        self._conn_escritura = psycopg.connect(dsn)

    def cerrar(self) -> None:
        for conn in (self._conn_lectura, self._conn_escritura):
            try:
                conn.close()
            except Exception:
                pass

    def crear_esquema(self) -> None:
        with self._conn_escritura.cursor() as cur:
            cur.execute(
                f'CREATE TABLE IF NOT EXISTS "{_TABLA_CREDENCIALES}" ('
                "correo text PRIMARY KEY, hash text NOT NULL)"
            )
        self._conn_escritura.commit()

    def listar(self) -> dict[str, str]:
        with self._conn_lectura.cursor() as cur:
            cur.execute(f'SELECT correo, hash FROM "{_TABLA_CREDENCIALES}" ORDER BY correo')
            return {fila[0]: fila[1] for fila in cur.fetchall()}

    def guardar(self, correo: str, hash_contrasena: str) -> None:
        with self._conn_escritura.cursor() as cur:
            cur.execute(
                f'INSERT INTO "{_TABLA_CREDENCIALES}" (correo, hash) VALUES (%s, %s) '
                "ON CONFLICT (correo) DO UPDATE SET hash = EXCLUDED.hash",
                (correo, hash_contrasena),
            )
        self._conn_escritura.commit()

    def eliminar(self, correo: str) -> None:
        with self._conn_escritura.cursor() as cur:
            cur.execute(f'DELETE FROM "{_TABLA_CREDENCIALES}" WHERE correo = %s', (correo,))
        self._conn_escritura.commit()

    def eliminar_excepto(self, correos: set[str]) -> None:
        if not correos:
            return
        with self._conn_escritura.cursor() as cur:
            cur.execute(
                f'DELETE FROM "{_TABLA_CREDENCIALES}" WHERE NOT (correo = ANY(%s))',
                (sorted(correos),),
            )
        self._conn_escritura.commit()


class RepositorioMemoria:
    """Estado en memoria: listas vivas, identicas al comportamiento previo.

    `cargar()` repone las 5 listas desde semilla.py (fallback dev y tests);
    sin llamarlo las listas quedan vacias, igual que un repositorio recien
    creado sin datos.
    """

    def __init__(self, con_semilla: bool = True) -> None:
        self._usuarios: list[Usuario] = []
        self._proyectos: list[Proyecto] = []
        self._etapas: list[EtapaTrabajo] = []
        self._entregables: list[Entregable] = []
        self._bitacora: list[BitacoraEntrada] = []
        if con_semilla:
            self.cargar_semilla()

    def cargar_semilla(self) -> None:
        from .semilla import (
            BITACORA_SEMILLA,
            ENTREGABLES_SEMILLA,
            ETAPAS_SEMILLA,
            PROYECTOS_SEMILLA,
            USUARIOS_SEMILLA,
        )

        self.usuarios_reemplazar(list(USUARIOS_SEMILLA))
        self.proyectos_reemplazar(list(PROYECTOS_SEMILLA))
        self.etapas_reemplazar(list(ETAPAS_SEMILLA))
        self.entregables_reemplazar(list(ENTREGABLES_SEMILLA))
        self.bitacora_reemplazar(list(BITACORA_SEMILLA))

    # ---------- Contrato del repositorio ----------

    def usuarios(self) -> list[Usuario]:
        return self._usuarios

    def proyectos(self) -> list[Proyecto]:
        return self._proyectos

    def etapas(self) -> list[EtapaTrabajo]:
        return self._etapas

    def entregables(self) -> list[Entregable]:
        return self._entregables

    def bitacora(self) -> list[BitacoraEntrada]:
        return self._bitacora

    def usuarios_reemplazar(self, lista: Sequence[Usuario]) -> None:
        self._usuarios = list(lista)

    def proyectos_reemplazar(self, lista: Sequence[Proyecto]) -> None:
        self._proyectos = list(lista)

    def etapas_reemplazar(self, lista: Sequence[EtapaTrabajo]) -> None:
        self._etapas = list(lista)

    def entregables_reemplazar(self, lista: Sequence[Entregable]) -> None:
        self._entregables = list(lista)

    def bitacora_reemplazar(self, lista: Sequence[BitacoraEntrada]) -> None:
        self._bitacora = list(lista)

    def usuarios_agregar(self, entidad: Usuario) -> None:
        self._usuarios.append(entidad)

    def proyectos_agregar(self, entidad: Proyecto) -> None:
        self._proyectos.append(entidad)

    def etapas_agregar(self, entidad: EtapaTrabajo) -> None:
        self._etapas.append(entidad)

    def entregables_agregar(self, entidad: Entregable) -> None:
        self._entregables.append(entidad)

    def bitacora_agregar(self, entidad: BitacoraEntrada) -> None:
        self._bitacora.append(entidad)


class RepositorioPostgres:
    """Persistencia en PostgreSQL 17 (DEC-006): una tabla por coleccion con
    la entidad serializada a JSONB (camelCase, via alias de los modelos).

    Requiere psycopg 3 (`psycopg[binary]`). El esquema se crea en el arranque;
    la semilla carga solo si la coleccion esta vacia. Las escrituras usan
    transaccion propia por operacion y rollback en excepcion.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._fabricas: dict[str, Callable[[dict], object]] = {
            nombre: (lambda datos, modelo=modelo: modelo.model_validate(datos))
            for nombre, modelo, _prefijo in _COLECCIONES
        }
        import psycopg

        # Conexiones separadas para lectura y escritura: simple y suficiente
        # para el volumen actual; psycopg autocommit se maneja por operacion.
        self._conn_lectura = psycopg.connect(dsn, autocommit=True)
        self._conn_escritura = psycopg.connect(dsn)

    # ---------- Ciclo de vida ----------

    def crear_esquema(self) -> None:
        """CREATE TABLE IF NOT EXISTS por coleccion (idempotente)."""
        with self._conn_escritura.cursor() as cur:
            for nombre, _modelo, _prefijo in _COLECCIONES:
                cur.execute(
                    f'CREATE TABLE IF NOT EXISTS "{nombre}" ('
                    'id text PRIMARY KEY, datos jsonb NOT NULL)'
                )
        self._conn_escritura.commit()

    def cargar_semilla(self) -> None:
        """Vuelca la semilla solo en colecciones vacias (idempotente)."""
        from .semilla import (
            BITACORA_SEMILLA,
            ENTREGABLES_SEMILLA,
            ETAPAS_SEMILLA,
            PROYECTOS_SEMILLA,
            USUARIOS_SEMILLA,
        )

        semillas: dict[str, Sequence[object]] = {
            "usuarios": USUARIOS_SEMILLA,
            "proyectos": PROYECTOS_SEMILLA,
            "etapas": ETAPAS_SEMILLA,
            "entregables": ENTREGABLES_SEMILLA,
            "bitacora": BITACORA_SEMILLA,
        }
        with self._conn_escritura.cursor() as cur:
            for nombre, _modelo, _prefijo in _COLECCIONES:
                cur.execute(f'SELECT COUNT(*) FROM "{nombre}"')
                if cur.fetchone()[0] > 0:
                    continue
                for entidad in semillas[nombre]:
                    datos = entidad.model_dump(mode="json", by_alias=True)
                    cur.execute(
                        f'INSERT INTO "{nombre}" (id, datos) VALUES (%s, %s)',
                        (entidad.id, json.dumps(datos)),
                    )
        self._conn_escritura.commit()

    def cerrar(self) -> None:
        for conn in (self._conn_lectura, self._conn_escritura):
            try:
                conn.close()
            except Exception:
                pass

    # ---------- Consultas ----------

    def _leer_todos(self, nombre: str) -> list[object]:
        with self._conn_lectura.cursor() as cur:
            cur.execute(f'SELECT datos FROM "{nombre}" ORDER BY id')
            return [self._fabricas[nombre](fila[0]) for fila in cur.fetchall()]

    def usuarios(self) -> list[Usuario]:
        return self._leer_todos("usuarios")  # type: ignore[return-value]

    def proyectos(self) -> list[Proyecto]:
        return self._leer_todos("proyectos")  # type: ignore[return-value]

    def etapas(self) -> list[EtapaTrabajo]:
        return self._leer_todos("etapas")  # type: ignore[return-value]

    def entregables(self) -> list[Entregable]:
        return self._leer_todos("entregables")  # type: ignore[return-value]

    def bitacora(self) -> list[BitacoraEntrada]:
        return self._leer_todos("bitacora")  # type: ignore[return-value]

    # ---------- Escrituras ----------

    def _escribir_entidad(self, nombre: str, entidad: object) -> None:
        datos = entidad.model_dump(mode="json", by_alias=True)  # type: ignore[union-attr]
        with self._conn_escritura.cursor() as cur:
            cur.execute(
                'INSERT INTO "{0}" (id, datos) VALUES (%s, %s) '
                "ON CONFLICT (id) DO UPDATE SET datos = EXCLUDED.datos".format(nombre),
                (entidad.id, json.dumps(datos)),  # type: ignore[attr-defined]
            )
        self._conn_escritura.commit()

    def _reemplazar_todo(self, nombre: str, lista: Sequence[object]) -> None:
        with self._conn_escritura.cursor() as cur:
            cur.execute(f'DELETE FROM "{nombre}"')
            for entidad in lista:
                datos = entidad.model_dump(mode="json", by_alias=True)
                cur.execute(
                    f'INSERT INTO "{nombre}" (id, datos) VALUES (%s, %s)',
                    (entidad.id, json.dumps(datos)),
                )
        self._conn_escritura.commit()

    def usuarios_reemplazar(self, lista: Sequence[Usuario]) -> None:
        self._reemplazar_todo("usuarios", lista)

    def proyectos_reemplazar(self, lista: Sequence[Proyecto]) -> None:
        self._reemplazar_todo("proyectos", lista)

    def etapas_reemplazar(self, lista: Sequence[EtapaTrabajo]) -> None:
        self._reemplazar_todo("etapas", lista)

    def entregables_reemplazar(self, lista: Sequence[Entregable]) -> None:
        self._reemplazar_todo("entregables", lista)

    def bitacora_reemplazar(self, lista: Sequence[BitacoraEntrada]) -> None:
        self._reemplazar_todo("bitacora", lista)

    def usuarios_agregar(self, entidad: Usuario) -> None:
        self._escribir_entidad("usuarios", entidad)

    def proyectos_agregar(self, entidad: Proyecto) -> None:
        self._escribir_entidad("proyectos", entidad)

    def etapas_agregar(self, entidad: EtapaTrabajo) -> None:
        self._escribir_entidad("etapas", entidad)

    def entregables_agregar(self, entidad: Entregable) -> None:
        self._escribir_entidad("entregables", entidad)

    def bitacora_agregar(self, entidad: BitacoraEntrada) -> None:
        self._escribir_entidad("bitacora", entidad)
