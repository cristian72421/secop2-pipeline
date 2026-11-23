"""
Prueba de la consulta que se le manda al portal.

No toca la red: solo revisa el texto del WHERE.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import pytest
import requests

from src import extraccion
from src.extraccion import _construir_where, extraer_dataset


def test_la_consulta_al_portal_se_arma_bien():
    """
    Tres formas de filtro: igualdad, rango de fechas y un nombre con apóstrofo,
    que sin escapar deja la consulta mal formada.
    """
    assert _construir_where({"ciudad": "Bogotá", "nombre_entidad": "UNP"}) == \
        "ciudad = 'Bogotá' AND nombre_entidad = 'UNP'"

    assert _construir_where({"fecha_de_firma": {"desde": "2025-01-01", "hasta": "2025-12-31"}}) == \
        "fecha_de_firma >= '2025-01-01' AND fecha_de_firma <= '2025-12-31'"

    assert _construir_where({"proveedor": "FUNDACION O'BRIEN"}) == \
        "proveedor = 'FUNDACION O''BRIEN'"

    assert _construir_where({}) is None


def test_varias_entidades_se_traducen_a_in():
    """
    El Entregable 2 pide poder definir "entidad/es": varias en una consulta.

    Con un solo valor sigue saliendo una igualdad, para no ensuciar el WHERE.
    """
    assert _construir_where({"nombre_entidad": ["UNP", "INVIAS"]}) == \
        "nombre_entidad IN ('UNP', 'INVIAS')"
    assert _construir_where({"nombre_entidad": ["UNP"]}) == "nombre_entidad = 'UNP'"
    assert _construir_where({"proveedor": ["O'BRIEN", "OTRA"]}) == \
        "proveedor IN ('O''BRIEN', 'OTRA')"


class ClienteFalso:
    """Imita al cliente de Socrata: devuelve filas numeradas y falla a pedido."""

    def __init__(self, filas: int, fallas: int = 0):
        self.filas, self.fallas, self.pedidos = filas, fallas, []

    def get(self, dataset_id, where=None, limit=None, offset=0, order=None):
        self.pedidos.append({"offset": offset, "order": order})
        if self.fallas:
            self.fallas -= 1
            raise requests.exceptions.ReadTimeout("el portal tardó")
        return [{"fila": i} for i in range(offset, min(offset + limit, self.filas))]


def test_la_paginacion_ordena_y_no_repite_filas(monkeypatch):
    """Sin un orden fijo el portal puede repetir o saltar filas entre páginas."""
    monkeypatch.setattr(extraccion.time, "sleep", lambda s: None)
    cliente = ClienteFalso(filas=25)
    df = extraer_dataset(cliente, "contratos", tamano_pagina=10)
    assert df["fila"].tolist() == list(range(25))
    assert {p["order"] for p in cliente.pedidos} == {":id"}


def test_reintenta_si_el_portal_tarda(monkeypatch):
    monkeypatch.setattr(extraccion.time, "sleep", lambda s: None)
    cliente = ClienteFalso(filas=5, fallas=2)
    assert len(extraer_dataset(cliente, "contratos")) == 5

    cliente = ClienteFalso(filas=5, fallas=extraccion.REINTENTOS)
    with pytest.raises(requests.exceptions.Timeout):
        extraer_dataset(cliente, "contratos")
