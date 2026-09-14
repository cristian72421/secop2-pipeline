"""
Pruebas de la limpieza y estandarización.

Cada una corresponde a un defecto que apareció trabajando con datos reales.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.procesamiento import (
    calcular_duraciones,
    columnas_comparables,
    convertir_columnas_fecha,
    limpiar_columnas_moneda,
    normalizar_nombres_columnas,
    procesar,
    reconciliar_por_llave,
    unir_tablas,
)
from conftest import FECHAS_CONTRATO, TOTAL_CONTRATOS


# --------------------------------------------------------- nombres de columna

def test_normaliza_tildes_mayusculas_y_espacios(contratos_portal):
    columnas = normalizar_nombres_columnas(contratos_portal).columns
    assert "modalidad_de_contratacion" in columnas
    assert "dias_adicionados" in columnas          # 'Días Adicionados'
    assert "valor_del_contrato" in columnas


# ------------------------------------------------------------------- montos

def test_monto_con_formato_colombiano(contratos_portal):
    """'$13.339.049' es trece millones, no trece mil millones."""
    df = limpiar_columnas_moneda(
        normalizar_nombres_columnas(contratos_portal), ["valor_del_contrato"],
    )
    assert df.loc[0, "valor_del_contrato"] == 13_339_049
    assert df.loc[1, "valor_del_contrato"] == 1_234_567_890


def test_monto_con_decimales_no_se_multiplica():
    """
    Quitar los puntos sin mirar convertiría 1234.56 en 123456.

    La API entrega el número plano y el portal el formato colombiano; hay que
    distinguirlos por la forma del valor, no por la fuente.
    """
    df = pd.DataFrame({"valor": ["1234.56", "46554022318", "$13.339.049,50"]})
    resultado = limpiar_columnas_moneda(df, ["valor"])["valor"]
    assert resultado[0] == pytest.approx(1234.56)
    assert resultado[1] == 46_554_022_318
    assert resultado[2] == pytest.approx(13_339_049.50)


def test_monto_ilegible_queda_vacio_sin_romper():
    df = pd.DataFrame({"valor": ["Sin valor", None, "$1.000"]})
    resultado = limpiar_columnas_moneda(df, ["valor"])["valor"]
    assert resultado.isna().sum() == 2
    assert resultado[2] == 1000


# -------------------------------------------------------------------- fechas

def test_fecha_en_formato_del_portal(contratos_portal):
    df = convertir_columnas_fecha(
        normalizar_nombres_columnas(contratos_portal),
        ["fecha_de_firma"], formato="%m/%d/%Y",
    )
    assert df["fecha_de_firma"].notna().all()
    assert df.loc[0, "fecha_de_firma"] == pd.Timestamp("2025-01-15")


def test_formato_equivocado_no_deja_la_columna_vacia(contratos_crudos):
    """
    Regresión: con el formato del portal aplicado a datos de la API, las 2.396
    fechas quedaron nulas y el pipeline siguió sin avisar. Ahora reintenta.
    """
    df = convertir_columnas_fecha(
        contratos_crudos, ["fecha_de_firma"], formato="%m/%d/%Y",
    )
    assert df["fecha_de_firma"].notna().all()
    assert df.loc[0, "fecha_de_firma"] == pd.Timestamp("2025-01-10")


def test_columna_de_fecha_inexistente_se_ignora(contratos_crudos):
    convertir_columnas_fecha(contratos_crudos, ["columna_que_no_existe"])


# ----------------------------------------------------- columnas comparables

def test_columnas_con_diccionarios_quedan_fuera():
    """
    Regresión: Socrata entrega las columnas de URL y ubicación como dict, y
    drop_duplicates / nunique / value_counts fallan con 'unhashable type'.
    """
    df = pd.DataFrame({
        "id": ["1", "2"],
        "urlproceso": [{"url": "http://a"}, {"url": "http://b"}],
    })
    assert columnas_comparables(df) == ["id"]
    df[columnas_comparables(df)].drop_duplicates()   # no debe lanzar


# ----------------------------------------------------------------- duraciones

def test_duracion_negativa_se_conserva(contratos):
    """
    Firmar después de haber iniciado es una señal de riesgo de VigIA, no un
    error de datos: la duración negativa tiene que sobrevivir a la limpieza.
    """
    negativos = contratos["dias_firma_a_inicio"] < 0
    assert negativos.sum() == 1
    assert contratos.loc[negativos, "dias_firma_a_inicio"].iloc[0] == -5


def test_duracion_de_un_dia_para_otro(contratos):
    assert (contratos["dias_firma_a_inicio"] == 0).sum() == 1       # mismo día
    assert contratos["dias_firma_a_inicio"].notna().all()


def test_duracion_sin_columnas_no_rompe(contratos):
    resultado = calcular_duraciones(contratos, {"x": ("no_existe", "tampoco")})
    assert "x" not in resultado.columns


# ------------------------------------------------------------ reconciliación

def test_reconciliar_deja_una_fila_por_llave(procesos_crudos):
    """44 filas de la fuente, 42 procesos distintos."""
    df = convertir_columnas_fecha(procesos_crudos, ["fecha_de_publicacion_del"])
    reconciliado = reconciliar_por_llave(
        df, "id_del_portafolio", fecha_mas_antigua=["fecha_de_publicacion_del"],
    )
    assert len(procesos_crudos) == 44
    assert len(reconciliado) == 42
    assert reconciliado["id_del_portafolio"].is_unique


def test_reconciliar_conserva_la_publicacion_mas_antigua(procesos_crudos):
    """De las dos fechas del mismo proceso debe quedar la primera, no la última."""
    df = convertir_columnas_fecha(procesos_crudos, ["fecha_de_publicacion_del"])
    reconciliado = reconciliar_por_llave(
        df, "id_del_portafolio", fecha_mas_antigua=["fecha_de_publicacion_del"],
    )
    fila = reconciliado.loc[reconciliado["id_del_portafolio"] == "CO1.BDOS.100036"]
    assert fila["fecha_de_publicacion_del"].iloc[0] == pd.Timestamp("2025-03-01")


def test_reconciliar_sin_la_llave_devuelve_la_tabla(procesos_crudos):
    assert len(reconciliar_por_llave(procesos_crudos, "llave_inexistente")) == 44


# -------------------------------------------------------------------- unión

def test_la_union_no_pierde_contratos(base):
    """Es un left join: el contrato sin proceso se queda, con los campos vacíos."""
    assert len(base) == TOTAL_CONTRATOS


def test_el_contrato_sin_proceso_queda_marcado(base):
    sin_proceso = base["id_del_portafolio"].isna()
    assert sin_proceso.sum() == 1
    assert base.loc[sin_proceso, "proceso_de_compra"].iloc[0] == "CO1.BDOS.100043"


def test_union_sin_llave_devuelve_la_tabla_izquierda(contratos, procesos_crudos):
    resultado = unir_tablas(contratos, procesos_crudos, "no_existe", "tampoco")
    assert resultado.equals(contratos)


# ------------------------------------------------------------------ procesar

def test_procesar_no_toca_la_tabla_original(contratos_crudos):
    antes = contratos_crudos.copy()
    procesar(contratos_crudos, columnas_moneda=["valor_del_contrato"])
    pd.testing.assert_frame_equal(contratos_crudos, antes)


def test_procesar_tabla_vacia(vacio):
    assert procesar(vacio, columnas_fecha=FECHAS_CONTRATO).empty
