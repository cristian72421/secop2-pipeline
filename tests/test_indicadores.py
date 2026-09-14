"""
Pruebas de los indicadores descriptivos.

Interesa sobre todo que ningún indicador se pueda leer al revés.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import pytest

from src import indicadores as ind
from conftest import (
    TOTAL_CONTRATOS, TOTAL_DIRECTOS, VALOR_TOTAL, VALOR_URGENCIA_MANIFIESTA,
)


def test_la_contratacion_directa_manda_en_contratos_pero_no_en_dinero(contratos):
    """
    El hallazgo central del caso: es casi todos los contratos y una fracción
    del dinero. Leer solo el porcentaje de contratos da la conclusión contraria.
    """
    resumen = ind.resumen(contratos)
    assert resumen["contratos"] == TOTAL_CONTRATOS
    assert resumen["valor_total"] == VALOR_TOTAL
    assert resumen["pct_directa"] == pytest.approx(100 * TOTAL_DIRECTOS / TOTAL_CONTRATOS)

    tabla = ind.por_modalidad(contratos)
    assert tabla.index[0] == "Contratación Directa"
    assert 100 * tabla.loc["Contratación Directa", "valor"] / tabla["valor"].sum() < 80


def test_cero_ofertas_no_significa_lo_mismo_en_cada_modalidad(base):
    """
    Los 35 contratos directos sin ofertas son el procedimiento; las 3
    licitaciones públicas sin ofertas son la anomalía.
    """
    tabla = ind.ofertas_por_modalidad(base)
    assert tabla.loc["Contratación Directa", "Sin ofertas"] == TOTAL_DIRECTOS
    assert tabla.loc["Licitación Pública", "Sin ofertas"] == 3


def test_la_concentracion_en_dinero_no_es_la_de_contratos(contratos):
    """
    Confundir los dos porcentajes invierte la lectura: 3 proveedores con 5
    contratos de 43 se llevan la mayor parte del dinero.
    """
    c = ind.concentracion_proveedores(contratos, n=3)
    assert c["contratos_top"] == 5
    assert c["pct_contratos"] < 15
    assert c["pct_valor"] > 80


def test_las_causales_raras_pesan_mas_que_las_frecuentes(contratos):
    """
    Dos contratos por urgencia manifiesta valen más que los 33 restantes de
    contratación directa juntos. Por eso hay que desagregar por causal.
    """
    tabla = ind.justificacion_directa(contratos)
    urgencia = tabla.loc["Urgencia manifiesta"]
    assert urgencia["contratos"] == 2
    assert urgencia["valor"] == VALOR_URGENCIA_MANIFIESTA
    assert urgencia["valor"] > tabla["valor"].sum() - urgencia["valor"]


def test_las_revisiones_de_calidad_encuentran_los_casos_sembrados(contratos):
    """Un solo valor mal digitado distorsiona cualquier promedio."""
    tabla = ind.calidad_datos(contratos).set_index("revisión")["casos"]
    assert tabla["Firma posterior al inicio del contrato"] == 1
    assert tabla["Fecha de fin anterior al inicio"] == 1
    assert tabla["Valor cero o vacío"] == 2


def test_ningun_indicador_falla_cuando_la_consulta_no_devuelve_nada(vacio):
    """La interfaz llega a este caso cada vez que un filtro no encuentra filas."""
    for funcion in (ind.por_modalidad, ind.ofertas_por_modalidad, ind.calidad_datos,
                    ind.distribucion_valores, ind.distribucion_firma_a_inicio,
                    ind.curva_concentracion, ind.contratos_por_mes_modalidad,
                    ind.valores_por_modalidad, ind.dias_firma_a_inicio,
                    ind.justificacion_directa):
        assert funcion(vacio).empty, funcion.__name__
