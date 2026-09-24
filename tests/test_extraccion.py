"""
Prueba de la consulta que se le manda al portal.

No toca la red: solo revisa el texto del WHERE.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

from src.extraccion import _construir_where


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
