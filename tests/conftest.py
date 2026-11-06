"""Aislamiento de tests: sin DATABASE_URL aunque exista backend/.env.

app.main llama load_dotenv() al importar y eso restaura DATABASE_URL desde
.env incluso despues de un pop (la carga ocurre durante el import del modulo).
load_dotenv NO sobreescribe variables ya presentes en el entorno, asi que se
fija DATABASE_URL = "" aqui: _crear_repositorio() la trata como ausente y usa
RepositorioMemoria (semilla fresca por corrida). Los tests de roundtrip
Postgres (test_almacen.py) crean su propia BD efimera y definen su DSN
explicito, por lo que no dependen de esta variable.
"""

import os

os.environ["DATABASE_URL"] = ""
