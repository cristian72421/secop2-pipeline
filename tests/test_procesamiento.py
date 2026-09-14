"""
Pruebas de la limpieza de los datos.

Cada una corresponde a un defecto que apareció trabajando con datos reales.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.procesamiento import (
    columnas_comparables,
    convertir_columnas_fecha,
    limpiar_columnas_moneda,
    normalizar_nombres_columnas,
    reconciliar_por_llave,
)
from conftest import TOTAL_CONTRATOS


def test_los_montos_se_leen_bien_vengan_del_portal_o_de_la_api(contratos_portal):
    """
    '$13.339.049' son trece millones, y 1234.56 no puede volverse 123456: quitar
    los puntos de miles sin mirar multiplicaría por cien los montos de la API.
    """
    df = limpiar_columnas_moneda(
        normalizar_nombres_columnas(contratos_portal), ["valor_del_contrato"],
    )
    assert df.loc[0, "valor_del_contrato"] == 13_339_049      # "$13.339.049"
    assert df.loc[3, "valor_del_contrato"] == pytest.approx(1234.56)
    assert df.loc[4, "valor_del_contrato"] == 46_554_022_318


def test_un_formato_de_fecha_equivocado_no_deja_la_columna_vacia(contratos_crudos):
    """
    El portal entrega MM/DD/AAAA y la API, ISO. Aplicar el formato del portal a
    datos de la API dejaba todas las fechas en nulo sin avisar; ahora reintenta.
    """
    df = convertir_columnas_fecha(contratos_crudos, ["fecha_de_firma"], formato="%m/%d/%Y")
    assert df["fecha_de_firma"].notna().all()


def test_las_columnas_que_llegan_como_diccionario_quedan_fuera():
    """
    Socrata entrega las columnas de URL como diccionario, y eso rompe cualquier
    operación que busque valores repetidos.
    """
    df = pd.DataFrame({"id": ["1", "2"], "urlproceso": [{"url": "a"}, {"url": "b"}]})
    assert columnas_comparables(df) == ["id"]


def test_una_firma_posterior_al_inicio_se_conserva_negativa(contratos):
    """Firmar después de haber empezado es una señal de riesgo, no un error."""
    assert (contratos["dias_firma_a_inicio"] < 0).sum() == 1
    assert contratos["dias_firma_a_inicio"].min() == -5


def test_un_proceso_repetido_se_reduce_a_una_fila(procesos_crudos):
    """
    La fuente trae 44 filas para 42 procesos. Al reducirlas se conserva la fecha
    de publicación más antigua, que es la que corresponde al proceso.
    """
    df = convertir_columnas_fecha(procesos_crudos, ["fecha_de_publicacion_del"])
    reconciliado = reconciliar_por_llave(
        df, "id_del_portafolio", fecha_mas_antigua=["fecha_de_publicacion_del"],
    )
    assert len(reconciliado) == 42
    fila = reconciliado.loc[reconciliado["id_del_portafolio"] == "CO1.BDOS.100036"]
    assert fila["fecha_de_publicacion_del"].iloc[0] == pd.Timestamp("2025-03-01")


def test_el_cruce_con_procesos_no_pierde_contratos(base):
    """
    42 de los 43 contratos encuentran su proceso, y el que no lo encuentra se
    queda en la tabla con los campos vacíos en vez de desaparecer.

    El cruce va de proceso_de_compra a id_del_portafolio (ambos CO1.BDOS.*).
    Con id_del_proceso, que guarda un CO1.REQ.*, el emparejamiento daba 0%.
    """
    assert len(base) == TOTAL_CONTRATOS
    assert base["respuestas_al_procedimiento"].notna().sum() == 42
