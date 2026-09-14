"""
Pruebas del cruce entre contratos y procesos.

Es donde se perdieron las primeras extracciones: el cruce daba cero filas.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

from src.flujo_vigia import (
    FECHA_PUBLICACION, filtros_para_procesos,
)

COLUMNAS_PROCESOS = {"id_del_portafolio", "entidad", "fecha_de_publicacion_del",
                     "respuestas_al_procedimiento"}


def test_los_procesos_se_buscan_desde_antes_que_los_contratos():
    """
    Un proceso siempre es anterior al contrato que origina. Filtrar las dos
    tablas al mismo periodo deja sin proceso a los contratos de enero.
    """
    adaptados = filtros_para_procesos(
        {"fecha_de_firma": {"desde": "2025-01-01", "hasta": "2025-12-31"}},
        COLUMNAS_PROCESOS, margen_meses=6,
    )
    assert adaptados[FECHA_PUBLICACION] == {"desde": "2024-07-01", "hasta": "2025-12-31"}


def test_los_filtros_se_adaptan_a_los_nombres_de_procesos():
    """
    La entidad se llama distinto en cada tabla, y 'ciudad' no existe en
    procesos: mandarla haría fallar la consulta entera.
    """
    adaptados = filtros_para_procesos(
        {"nombre_entidad": "UNP", "ciudad": "Bogotá"}, COLUMNAS_PROCESOS, margen_meses=6,
    )
    assert adaptados == {"entidad": "UNP"}
