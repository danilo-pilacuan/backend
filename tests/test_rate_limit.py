"""Tests del limitador de intentos de login (mitigacion VULN-003)."""

from app.rate_limit import LimitadorLogin


def test_primeros_intentos_no_bloquean():
    limitador = LimitadorLogin()
    for _ in range(4):
        assert not limitador.bloqueado("a|1.2.3.4")
        limitador.registrar_fallo("a|1.2.3.4")


def test_alcanzar_el_maximo_bloquea():
    limitador = LimitadorLogin()
    for _ in range(5):
        limitador.registrar_fallo("a|1.2.3.4")
    assert limitador.bloqueado("a|1.2.3.4")


def test_la_ventana_al_expirar_libera():
    limitador = LimitadorLogin()
    for _ in range(5):
        limitador.registrar_fallo("a|1.2.3.4", ahora=100.0)
    assert limitador.bloqueado("a|1.2.3.4", ahora=100.0)
    assert not limitador.bloqueado("a|1.2.3.4", ahora=161.0)


def test_cada_clave_es_independiente():
    limitador = LimitadorLogin()
    for _ in range(5):
        limitador.registrar_fallo("a|1.2.3.4")
    assert limitador.bloqueado("a|1.2.3.4")
    assert not limitador.bloqueado("b|1.2.3.4")
    assert not limitador.bloqueado("a|5.6.7.8")


def test_intentos_configurables_desactivan_el_limite(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_LOGIN_INTENTOS", "0")
    limitador = LimitadorLogin()
    for _ in range(50):
        limitador.registrar_fallo("a|1.2.3.4")
        assert not limitador.bloqueado("a|1.2.3.4")


def test_limpiar_reinicia_los_contadores():
    limitador = LimitadorLogin()
    for _ in range(5):
        limitador.registrar_fallo("a|1.2.3.4")
    assert limitador.bloqueado("a|1.2.3.4")
    limitador.limpiar()
    assert not limitador.bloqueado("a|1.2.3.4")
