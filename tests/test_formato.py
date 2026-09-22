"""
Pruebas del formato de números a la colombiana.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

from src import formato as fmt


def test_el_punto_es_de_miles_y_la_coma_de_decimales():
    """
    Regresión: el valor total de la UNP se mostraba como '1.257.0' miles de
    millones, con dos puntos, porque se cambiaban todas las comas por puntos.
    """
    assert fmt.numero(1_257_043_254_045 / 1e9, 1) == "1.257,0"
    assert fmt.numero(13_339_049) == "13.339.049"
    assert fmt.numero(1234.567, 2) == "1.234,57"
    assert fmt.pesos(46_554_022_318) == "$46.554.022.318"


def test_el_monto_se_muestra_en_su_unidad_natural():
    """Un eje con doce dígitos es ilegible; sin dato se pone una raya, no un cero."""
    assert fmt.monto_corto(1_257_043_254_045) == "1.257,0 miles de millones"
    assert fmt.monto_corto(35_726_000) == "35,7 millones"
    assert fmt.numero(None) == "—"
