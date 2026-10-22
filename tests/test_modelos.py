"""
Pruebas de los modelos de prórroga.

No miden si el modelo es bueno con los datos reales —eso depende de la
extracción— sino lo que haría que un buen número fuera falso: variables que
se conocen después de firmar, contratos que todavía pueden prorrogarse y una
división que mezcle pasado con futuro.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import modelos as m


def _contratos_con_senal(n: int = 2000, semilla: int = 0) -> pd.DataFrame:
    """
    Contratos inventados donde la prórroga depende de la duración pactada y
    del tipo. Llevan además dos columnas con fuga, como las reales: el estado
    y el valor ya actualizados por la prórroga.
    """
    rng = np.random.default_rng(semilla)
    firma = pd.Timestamp("2022-01-01") + pd.to_timedelta(rng.integers(0, 900, n), "D")
    duracion = rng.integers(30, 365, n)
    tipo = rng.choice(["Prestación de servicios", "Obra"], n, p=[0.8, 0.2])
    probabilidad = 1 / (1 + np.exp(-(-3 + duracion / 120 + (tipo == "Obra") * 1.5)))
    prorroga = rng.random(n) < probabilidad
    return pd.DataFrame({
        "fecha_de_firma": firma,
        "fecha_de_inicio_del_contrato": firma + pd.Timedelta(days=3),
        "fecha_de_fin_del_contrato": firma + pd.Timedelta(days=3)
                                     + pd.to_timedelta(duracion, "D"),
        "tipo_de_contrato": tipo,
        "modalidad_de_contratacion": "Contratación directa",
        "precio_base": rng.lognormal(17, 1, n),
        "dias_adicionados": np.where(prorroga, 60, 0),
        "estado_contrato": np.where(prorroga, "Modificado", "Cerrado"),
        "valor_del_contrato": rng.lognormal(17, 1, n) * np.where(prorroga, 1.5, 1.0),
    })


def test_las_variables_que_se_actualizan_despues_de_firmar_no_entran():
    """
    Medido contra los datos reales: el 66% de los contratos en estado
    «Modificado» tiene prórroga, y el valor del contrato ya trae sumada la
    adición. Con cualquiera de las dos dentro, el modelo acertaría leyendo el
    futuro.
    """
    tabla = m.preparar(_contratos_con_senal(), fecha_corte="2026-01-01")
    cat_int, cat_str, num = m.variables(tabla)
    usadas = set(cat_int + cat_str + num)

    assert "estado_contrato" not in usadas
    assert "valor_del_contrato" not in usadas
    assert m.OBJETIVO not in usadas
    assert usadas >= {"tipo_de_contrato", "duracion_planeada", "log_precio_base"}


def test_solo_entran_contratos_cuyo_fin_pactado_ya_paso(base):
    """
    Un contrato en ejecución todavía puede recibir su prórroga: contarlo como
    «sin prórroga» sería afirmar algo que no se sabe.
    """
    corte = pd.Timestamp("2025-06-30")
    tabla = m.preparar(base, fecha_corte=corte)
    terminados = (base["fecha_de_fin_del_contrato"] <= corte).sum()

    assert len(tabla) == terminados
    assert len(tabla) < len(base)


def test_se_entrena_con_el_pasado_y_se_evalua_con_el_futuro():
    """Mezclar al azar dejaría al modelo ver contratos posteriores a los que evalúa."""
    tabla = m.preparar(_contratos_con_senal(), fecha_corte="2026-01-01")
    entrenar, evaluar = m.dividir_en_el_tiempo(tabla, "2023-07-01")

    assert tabla.loc[entrenar, "fecha_de_firma"].max() < pd.Timestamp("2023-07-01")
    assert tabla.loc[evaluar, "fecha_de_firma"].min() >= pd.Timestamp("2023-07-01")
    assert entrenar.sum() + evaluar.sum() == len(tabla)


def test_la_logistica_supera_la_linea_base_y_la_exactitud_engana():
    """
    Con una señal plantada, la logística ordena mejor que el azar. Y la línea
    base, que nunca detecta una prórroga, saca de todos modos una exactitud
    alta: por eso la medida que se mira es otra.
    """
    tabla = m.preparar(_contratos_con_senal(), fecha_corte="2026-01-01")
    resultado, _ = m.comparar(tabla, "2023-07-01", con_red=False)

    base = resultado.loc["Línea base"]
    assert base["auc"] == 0.5
    assert base["veces_la_tasa"] == 1.0
    assert base["exactitud"] > 60          # alta sin acertar una sola prórroga

    logistica = resultado.loc["Regresión logística"]
    assert logistica["auc"] > 0.65
    assert logistica["veces_la_tasa"] > 1.5


def test_la_red_es_la_del_cuaderno_heart_del_curso():
    """
    Misma arquitectura que el ejemplo de clasificación de ACTD: una capa densa
    de 32 neuronas con ReLU y una salida sigmoide, Adam y entropía cruzada
    binaria. Y con la señal plantada, también supera la línea base.
    """
    pytest.importorskip("tensorflow")
    tabla = m.preparar(_contratos_con_senal(), fecha_corte="2026-01-01")
    resultado, modelos = m.comparar(tabla, "2023-07-01", epocas=10)
    red = modelos["Red neuronal"].model

    densas = [capa for capa in red.layers if capa.__class__.__name__ == "Dense"]
    assert [d.units for d in densas] == [32, 1]
    assert [d.activation.__name__ for d in densas] == ["relu", "sigmoid"]
    assert red.optimizer.__class__.__name__ == "Adam"
    assert red.loss == "binary_crossentropy"

    assert resultado.loc["Red neuronal", "auc"] > 0.65
    assert resultado.loc["Red neuronal", "veces_la_tasa"] > 1.5
