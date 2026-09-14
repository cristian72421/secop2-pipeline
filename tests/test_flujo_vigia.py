"""
Pruebas de la adaptación de filtros entre las dos tablas.

Es donde se perdieron las primeras extracciones: el filtro de entidad se
llamaba distinto en procesos, la fecha era otra columna, y el cruce daba cero.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import pytest

from src.flujo_vigia import (
    FECHA_PUBLICACION, LLAVE_CONTRATOS, LLAVE_PROCESOS,
    _restar_meses, filtros_para_procesos,
)

COLUMNAS_PROCESOS = {
    "id_del_portafolio", "entidad", "fecha_de_publicacion_del",
    "respuestas_al_procedimiento", "precio_base",
}


# ------------------------------------------------------------- restar meses

@pytest.mark.parametrize("fecha, meses, esperado", [
    ("2025-07-15", 6, "2025-01-01"),
    ("2025-01-01", 6, "2024-07-01"),     # cruza el año hacia atrás
    ("2025-01-31", 1, "2024-12-01"),
    ("2025-03-31", 13, "2024-02-01"),    # más de un año
    ("2025-05-10", 0, "2025-05-01"),
])
def test_restar_meses(fecha, meses, esperado):
    assert _restar_meses(fecha, meses) == esperado


# --------------------------------------------------------- filtros adaptados

def test_el_rango_se_corre_hacia_atras_y_cambia_de_columna():
    """
    El proceso siempre es anterior al contrato: filtrar ambas tablas al mismo
    periodo deja sin proceso a los contratos del comienzo de la ventana.
    """
    filtros = {"fecha_de_firma": {"desde": "2025-01-01", "hasta": "2025-12-31"}}
    adaptados = filtros_para_procesos(filtros, COLUMNAS_PROCESOS, margen_meses=6)

    assert "fecha_de_firma" not in adaptados
    assert adaptados[FECHA_PUBLICACION] == {"desde": "2024-07-01", "hasta": "2025-12-31"}


def test_la_entidad_se_traduce_al_nombre_de_procesos():
    """En contratos es 'nombre_entidad' y en procesos 'entidad'."""
    adaptados = filtros_para_procesos(
        {"nombre_entidad": "UNP"}, COLUMNAS_PROCESOS, margen_meses=6,
    )
    assert adaptados == {"entidad": "UNP"}


def test_el_filtro_que_no_existe_en_procesos_se_descarta():
    """
    'ciudad' no está en procesos. Enviarlo haría fallar la consulta entera.
    """
    adaptados = filtros_para_procesos(
        {"ciudad": "Bogotá", "nombre_entidad": "UNP"}, COLUMNAS_PROCESOS, margen_meses=6,
    )
    assert adaptados == {"entidad": "UNP"}


def test_rango_sin_fecha_inicial():
    adaptados = filtros_para_procesos(
        {"fecha_de_firma": {"hasta": "2025-12-31"}}, COLUMNAS_PROCESOS, margen_meses=6,
    )
    assert adaptados[FECHA_PUBLICACION] == {"hasta": "2025-12-31"}


def test_sin_filtros_no_inventa_ninguno():
    assert filtros_para_procesos({}, COLUMNAS_PROCESOS, margen_meses=6) == {}


# ------------------------------------------------------------------- llaves

def test_las_llaves_del_cruce_son_las_correctas():
    """
    Regresión: con 'id_del_proceso' (CO1.REQ.*) el cruce daba 0%. La columna que
    coincide con proceso_de_compra (CO1.BDOS.*) es id_del_portafolio.
    """
    assert LLAVE_CONTRATOS == "proceso_de_compra"
    assert LLAVE_PROCESOS == "id_del_portafolio"


def test_el_cruce_encuentra_casi_todos_los_procesos(base):
    """42 de 43 contratos encuentran su proceso; el otro no está en la fuente."""
    emparejados = base["id_del_portafolio"].notna().sum()
    assert emparejados == 42
    assert 100 * emparejados / len(base) > 95


def test_el_cruce_trae_las_ofertas_al_nivel_de_contrato(base):
    """El número de ofertas vive en procesos y el análisis es por contrato."""
    assert "respuestas_al_procedimiento" in base.columns
    assert base["respuestas_al_procedimiento"].notna().sum() == 42
