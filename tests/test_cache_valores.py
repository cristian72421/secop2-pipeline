"""
Pruebas de la caché en disco de los valores de los filtros.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import pytest

from src import cache_valores as cache


@pytest.fixture(autouse=True)
def carpeta_temporal(tmp_path, monkeypatch):
    """Cada prueba escribe en su propia carpeta, nunca en la caché real."""
    monkeypatch.setattr(cache, "CARPETA", tmp_path)


def test_lo_guardado_se_vuelve_a_leer_igual():
    """
    Es el punto de la caché: consultar una vez y no volver a esperar.

    Una columna que nunca se consultó devuelve None, no una lista vacía: hay
    que poder distinguirla de una columna que sí se consultó y no tiene valores.
    """
    assert cache.leer_valores("contratos", "ciudad") is None

    cache.guardar_valores("contratos", "ciudad", ["Bogotá", "Medellín", "Cali"])
    assert cache.leer_valores("contratos", "ciudad") == ["Bogotá", "Medellín", "Cali"]


def test_lo_guardado_caduca():
    """Los nombres de entidades cambian poco, pero no son fijos."""
    cache.guardar_valores("contratos", "ciudad", ["Bogotá"])
    assert cache.leer_valores("contratos", "ciudad", dias_vigencia=0) is None
