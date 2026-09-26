"""
Números en convención colombiana: punto para los miles, coma para los decimales.

La interfaz venía resolviéndolo con `f"{x:,.1f}".replace(",", ".")`, que
funciona con enteros pero rompe en cuanto hay decimales: el valor total de la
UNP, 1.257.043.254.045 pesos, se mostraba como **1.257.0** miles de millones.
Dos puntos y ningún decimal reconocible.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import math

# De mayor a menor: se usa la primera unidad que deje pocos dígitos enteros.
UNIDADES: tuple[tuple[float, str], ...] = (
    (1e9, "miles de millones"),
    (1e6, "millones"),
    (1e3, "miles"),
    (1, "pesos"),
)

VACIO = "—"


def _es_vacio(valor) -> bool:
    if valor is None:
        return True
    try:
        return math.isnan(float(valor))
    except (TypeError, ValueError):
        return True


def numero(valor, decimales: int = 0) -> str:
    """
    Formatea un número a la colombiana: 1234567.8 -> '1.234.567,8'.

    Se parte del formato inglés que ya trae Python y se intercambian los
    separadores; hacerlo con un replace directo dejaría dos puntos.
    """
    if _es_vacio(valor):
        return VACIO

    texto = f"{float(valor):,.{decimales}f}"       # 1,234,567.8
    entero, _, decimal = texto.partition(".")
    entero = entero.replace(",", ".")              # 1.234.567
    return f"{entero},{decimal}" if decimal else entero


def pesos(valor, decimales: int = 0) -> str:
    """El monto con el signo delante: '$13.339.049'."""
    if _es_vacio(valor):
        return VACIO
    return "$" + numero(valor, decimales)


def escala_monetaria(maximo: float) -> tuple[float, str]:
    """
    Divisor y nombre de la unidad, según la magnitud de los datos.

    Los montos de contratación llegan a los miles de millones, y un eje con
    doce dígitos es ilegible. Se elige la unidad que deje pocos dígitos enteros.
    """
    if _es_vacio(maximo):
        return 1, "pesos"
    for divisor, unidad in UNIDADES:
        if abs(float(maximo)) >= divisor:
            return divisor, unidad
    return 1, "pesos"


def monto_corto(valor, decimales: int = 1) -> str:
    """
    El monto en su unidad natural: 1257043254045 -> '1.257,0 miles de millones'.

    Para titulares y tarjetas, donde el número exacto estorba más de lo que
    informa.
    """
    if _es_vacio(valor):
        return VACIO
    divisor, unidad = escala_monetaria(valor)
    return f"{numero(float(valor) / divisor, decimales)} {unidad}"
