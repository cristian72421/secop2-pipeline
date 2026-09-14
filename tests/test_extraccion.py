"""
Pruebas de la construcción de consultas SoQL.

No tocan la red: solo verifican el texto del WHERE que se le manda al portal.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import re

from src.extraccion import DATASETS, _construir_where


def test_igualdad_simple():
    assert _construir_where({"ciudad": "Bogotá"}) == "ciudad = 'Bogotá'"


def test_varios_filtros_se_unen_con_and():
    where = _construir_where({"ciudad": "Bogotá", "nombre_entidad": "UNP"})
    assert where == "ciudad = 'Bogotá' AND nombre_entidad = 'UNP'"


def test_rango_de_fechas():
    where = _construir_where(
        {"fecha_de_firma": {"desde": "2025-01-01", "hasta": "2025-12-31"}}
    )
    assert where == "fecha_de_firma >= '2025-01-01' AND fecha_de_firma <= '2025-12-31'"


def test_rango_abierto_por_un_extremo():
    assert _construir_where({"f": {"desde": "2025-01-01"}}) == "f >= '2025-01-01'"
    assert _construir_where({"f": {"hasta": "2025-12-31"}}) == "f <= '2025-12-31'"


def test_la_comilla_del_nombre_no_rompe_la_consulta():
    """Hay entidades con apóstrofo; sin escapar, la consulta queda mal formada."""
    where = _construir_where({"proveedor": "FUNDACION O'BRIEN"})
    assert where == "proveedor = 'FUNDACION O''BRIEN'"


def test_sin_filtros_no_hay_where():
    assert _construir_where(None) is None
    assert _construir_where({}) is None


def test_los_identificadores_de_dataset_tienen_el_formato_de_socrata():
    for tabla, identificador in DATASETS.items():
        assert re.fullmatch(r"[a-z0-9]{4}-[a-z0-9]{4}", identificador), tabla
