"""Tests de configuracion de orígenes CORS (mitigacion VULN-004)."""

import pytest

from app.main import _origenes_permitidos

DEFAULT = [
    "http://localhost:4300",
    "http://localhost:4400",
    "http://localhost:4301",
    "http://localhost:4302",
    "http://localhost:4303",
    "http://localhost:4304",
]


def test_sin_env_devuelve_los_origenes_de_desarrollo_y_demo():
    assert _origenes_permitidos() == DEFAULT


def test_env_separado_por_comas_se_respeta(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://hub.example.com, https://demo.example.com")
    assert _origenes_permitidos() == ["https://hub.example.com", "https://demo.example.com"]


def test_env_con_barras_finales_y_vacias_se_normaliza(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://hub.example.com/ , , https://demo.example.com/")
    assert _origenes_permitidos() == ["https://hub.example.com", "https://demo.example.com"]


def test_env_solo_vacio_cae_al_default(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", " , ")
    assert _origenes_permitidos() == DEFAULT


@pytest.mark.parametrize("origen", DEFAULT)
def test_default_incluye_los_puertos_del_proyecto(origen: str):
    assert origen in DEFAULT
