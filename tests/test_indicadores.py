"""
Pruebas de los indicadores descriptivos.

Interesa sobre todo que ningún indicador se lea al revés: que la concentración
se reporte en dinero y en contratos por separado, y que "cero ofertas" no se
cuente igual en contratación directa que en una licitación pública.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src import indicadores as ind
from conftest import (
    TOTAL_CONTRATOS, TOTAL_DIRECTOS, VALOR_TOTAL, VALOR_URGENCIA_MANIFIESTA,
)


# -------------------------------------------------------------------- resumen

def test_resumen_cifras_de_cabecera(contratos):
    r = ind.resumen(contratos)
    assert r["contratos"] == TOTAL_CONTRATOS
    assert r["valor_total"] == VALOR_TOTAL
    assert r["pct_directa"] == pytest.approx(100 * TOTAL_DIRECTOS / TOTAL_CONTRATOS)


def test_resumen_cuenta_la_firma_tardia(contratos):
    r = ind.resumen(contratos)
    assert r["pct_firma_tardia"] == pytest.approx(100 / TOTAL_CONTRATOS)
    assert r["pct_con_prorroga"] == pytest.approx(100 * 10 / TOTAL_CONTRATOS)


def test_resumen_devuelve_none_en_vez_de_cero(contratos):
    """Sin la columna, el dato falta; un cero se leería como 'ninguno'."""
    r = ind.resumen(contratos.drop(columns=["valor_del_contrato"]))
    assert r["valor_total"] is None
    assert r["contratos"] == TOTAL_CONTRATOS


# ----------------------------------------------------------------- modalidad

def test_modalidad_manda_en_contratos_pero_no_en_dinero(contratos):
    """
    El hallazgo central del caso UNP: la contratación directa es casi todos los
    contratos y una fracción del dinero.
    """
    tabla = ind.por_modalidad(contratos)
    assert tabla.loc["Contratación Directa", "contratos"] == TOTAL_DIRECTOS
    assert tabla.index[0] == "Contratación Directa"          # ordenada por contratos

    pct_dinero = 100 * tabla.loc["Contratación Directa", "valor"] / tabla["valor"].sum()
    assert pct_dinero < 80                                   # manda en número, no en valor


def test_modalidad_sin_la_columna_devuelve_vacio(contratos):
    assert ind.por_modalidad(contratos.drop(columns=["modalidad_de_contratacion"])).empty


def test_agrupar_modalidades_colapsa_la_cola(contratos):
    serie = ind.agrupar_modalidades(contratos, n=2)
    assert set(serie.unique()) == {"Contratación Directa", "Licitación Pública", "Otras"}
    assert len(serie) == TOTAL_CONTRATOS


# ------------------------------------------------------------------- ofertas

def test_cero_ofertas_significa_cosas_distintas_segun_la_modalidad(base):
    """
    La prueba que sostiene la pregunta al asesor sobre el sesgo de modalidad:
    los 35 contratos directos sin ofertas son el procedimiento, y las 3
    licitaciones públicas sin ofertas son la anomalía.
    """
    tabla = ind.ofertas_por_modalidad(base)
    assert tabla.loc["Contratación Directa", "Sin ofertas"] == TOTAL_DIRECTOS
    assert tabla.loc["Licitación Pública", "Sin ofertas"] == 3
    assert tabla.loc["Licitación Pública", "Dos o más"] == 1


def test_ofertas_sin_el_cruce_de_procesos(contratos):
    """Sin unir con procesos no hay columna de ofertas: debe salir vacío."""
    assert ind.ofertas_por_modalidad(contratos).empty


# ------------------------------------------------------------ concentración

def test_concentracion_separa_contratos_de_dinero(contratos):
    """
    Los dos porcentajes no son el mismo número y confundirlos invierte la
    lectura: pocos proveedores con pocos contratos pueden llevarse casi todo.
    """
    c = ind.concentracion_proveedores(contratos, n=3)
    assert c["proveedores"] == contratos["proveedor_adjudicado"].nunique()
    assert c["contratos_total"] == TOTAL_CONTRATOS
    assert c["contratos_top"] == 5            # 2 urgencia + 2 menor cuantía + 1 licitación
    assert c["pct_valor"] > c["pct_contratos"] * 5


def test_concentracion_top_no_excede_el_total(contratos):
    c = ind.concentracion_proveedores(contratos, n=1000)
    assert c["n"] == c["proveedores"]
    assert c["pct_proveedores"] == 100
    assert c["pct_valor"] == pytest.approx(100)


def test_curva_de_lorenz_es_creciente_y_cierra_en_cien(contratos):
    curva = ind.curva_concentracion(contratos)
    assert curva["pct_valor"].iloc[0] == 0
    assert curva["pct_valor"].iloc[-1] == pytest.approx(100)
    assert curva["pct_valor"].is_monotonic_increasing
    assert curva["pct_proveedores"].is_monotonic_increasing


# -------------------------------------------------------------------- valores

def test_distribucion_por_orden_de_magnitud(contratos):
    tabla = ind.distribucion_valores(contratos)
    con_valor = contratos["valor_del_contrato"] > 0
    assert tabla["contratos"].sum() == con_valor.sum()
    assert "10.000M – 100.000M" in tabla.index          # los dos de urgencia manifiesta


def test_valores_por_modalidad_excluye_ceros_y_vacios(contratos):
    tabla = ind.valores_por_modalidad(contratos)
    assert (tabla["valor"] > 0).all()
    assert len(tabla) == TOTAL_CONTRATOS - 2            # un cero y un vacío


# -------------------------------------------------------------- calidad datos

def test_calidad_detecta_las_inconsistencias_sembradas(contratos):
    tabla = ind.calidad_datos(contratos).set_index("revisión")["casos"]
    assert tabla["Firma posterior al inicio del contrato"] == 1
    assert tabla["Fecha de fin anterior al inicio"] == 1
    assert tabla["Valor cero o vacío"] == 2


def test_calidad_no_reporta_revisiones_en_cero(contratos):
    assert (ind.calidad_datos(contratos)["casos"] > 0).all()


# ------------------------------------------------------- contratación directa

def test_las_causales_raras_pesan_mas_que_las_frecuentes(contratos):
    """
    Dos contratos por urgencia manifiesta valen más que los 31 de prestación de
    servicios juntos. Es lo que justifica desagregar por causal y no quedarse
    con el 81% de contratación directa.
    """
    tabla = ind.justificacion_directa(contratos)
    urgencia = tabla.loc["Urgencia manifiesta"]
    assert urgencia["contratos"] == 2
    assert urgencia["valor"] == VALOR_URGENCIA_MANIFIESTA
    assert urgencia["valor"] > tabla["valor"].sum() - urgencia["valor"]
    assert urgencia["% de los directos"] < 6


def test_justificacion_solo_mira_la_contratacion_directa(contratos):
    tabla = ind.justificacion_directa(contratos)
    assert tabla["contratos"].sum() == TOTAL_DIRECTOS


# ----------------------------------------------------------------- serie mes

def test_contratos_por_mes(contratos):
    tabla = ind.contratos_por_mes_modalidad(contratos)
    assert tabla["contratos"].sum() == TOTAL_CONTRATOS
    assert tabla["mes"].str.match(r"\d{4}-\d{2}").all()


# ---------------------------------------------- una consulta que no dio filas

@pytest.mark.parametrize("funcion", [
    ind.por_modalidad, ind.distribucion_firma_a_inicio, ind.ofertas_por_modalidad,
    ind.distribucion_valores, ind.calidad_datos, ind.curva_concentracion,
    ind.contratos_por_mes_modalidad, ind.valores_por_modalidad,
    ind.dias_firma_a_inicio, ind.justificacion_directa,
])
def test_ningun_indicador_falla_con_la_tabla_vacia(funcion, vacio):
    """La interfaz llega a este caso cada vez que un filtro no devuelve nada."""
    assert funcion(vacio).empty


def test_resumen_y_concentracion_con_tabla_vacia(vacio):
    assert ind.resumen(vacio)["contratos"] == 0
    assert ind.concentracion_proveedores(vacio) == {}
