"""
Pruebas del modelo de prórroga.

No miden si el modelo es bueno con los datos reales —eso depende de la
extracción— sino que la tabla no traiga información posterior a la firma y que
la red sea la de los cuadernos de clase.

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
    # La fecha de fin del contrato se mueve con la prórroga (ver VARIABLES_PROHIBIDAS).
    assert "duracion_planeada" not in usadas
    assert usadas >= {"tipo_de_contrato", "log_precio_base"}


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


def test_la_red_es_la_del_cuaderno_heart_del_curso():
    """
    Misma red y mismos pasos que el cuaderno de clasificación de ACTD: capa
    densa de 32 neuronas relu, salida de 1 neurona sigmoide, adam, entropía
    cruzada binaria, métricas accuracy y recall, y partición 80/20 con 20% del
    entrenamiento para validación.
    """
    # exc_type=ImportError: también omite si Windows bloquea las DLL de TensorFlow
    pytest.importorskip("tensorflow", exc_type=ImportError)
    tabla = m.preparar(_contratos_con_senal(), fecha_corte="2026-01-01")
    resultado = m.entrenar_red(tabla, epocas=3)
    red = resultado["model"]

    densas = [capa for capa in red.layers if capa.__class__.__name__ == "Dense"]
    assert [d.units for d in densas] == [32, 1]
    assert [d.activation.__name__ for d in densas] == ["relu", "sigmoid"]
    assert red.optimizer.__class__.__name__ == "Adam"
    assert red.loss == "binary_crossentropy"
    assert set(resultado["test_res"]) == {"loss", "accuracy", "recall"}

    total = resultado["train"] + resultado["val"] + resultado["test"]
    assert total == len(tabla.dropna())
    assert resultado["test"] == round(0.2 * total)
    assert resultado["val"] == round(0.2 * (resultado["train"] + resultado["val"]))


def test_los_deltas_de_procesos_se_calculan_en_dias():
    """
    Notas del 26/10: traer de la tabla de procesos los deltas de fechas en
    días. Los de procesos competitivos se calculan, pero no entran a la red.
    """
    firma = pd.Timestamp("2024-03-10")
    df = pd.DataFrame({
        "fecha_de_firma": [firma],
        "fecha_de_inicio_del_contrato": [firma + pd.Timedelta(days=2)],
        "fecha_de_fin_del_contrato": [firma + pd.Timedelta(days=100)],
        "dias_adicionados": [0],
        "fecha_de_publicacion_del": [firma - pd.Timedelta(days=30)],
        "fecha_de_ultima_publicaci": [firma - pd.Timedelta(days=25)],
        "fecha_de_recepcion_de": [firma - pd.Timedelta(days=15)],
        "fecha_adjudicacion": [firma - pd.Timedelta(days=4)],
        "duracion": [3],
        "unidad_de_duracion": ["Mes(es)"],
    })
    fila = m.preparar(df, fecha_corte="2026-01-01").iloc[0]

    assert fila["dias_publicacion_a_firma"] == 30
    assert fila["dias_entre_publicaciones"] == 5
    assert fila["duracion_proceso"] == pytest.approx(91.2)
    assert fila["dias_publicacion_a_recepcion"] == 15
    assert fila["dias_recepcion_a_adjudicacion"] == 11
    assert fila["dias_adjudicacion_a_firma"] == 4

    _, _, numericas = m.variables(pd.concat([m.preparar(df, "2026-01-01")] * 2)
                                  .assign(dias_publicacion_a_firma=[30, 31],
                                          dias_entre_publicaciones=[5, 0],
                                          duracion_proceso=[91.2, 60.8]))
    assert {"dias_publicacion_a_firma", "dias_entre_publicaciones",
            "duracion_proceso"} <= set(numericas)
    assert not set(m.DELTAS_COMPETITIVOS) & set(numericas)


def test_las_metricas_son_las_de_la_matriz_de_confusion():
    """
    Diapositivas 13-14 de ACTD. Con 4 positivos y 6 negativos y umbral 0,5:
    TP=3, FN=1, TN=4, FP=2. El AUC se calcula con la probabilidad.
    """
    y = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
    prob = [0.9, 0.8, 0.7, 0.3, 0.6, 0.55, 0.4, 0.2, 0.1, 0.05]
    r = m.metricas(y, prob)

    assert (r["TP"], r["FN"], r["TN"], r["FP"]) == (3, 1, 4, 2)
    assert r["Accuracy"] == pytest.approx(7 / 10)
    assert r["Precision"] == pytest.approx(3 / 5)
    assert r["Valor de predicción negativa"] == pytest.approx(4 / 5)
    assert r["Recall"] == pytest.approx(3 / 4)
    assert r["Especificidad"] == pytest.approx(4 / 6)
    assert r["Tasa de falsos positivos (error tipo I)"] == pytest.approx(2 / 6)
    assert r["Tasa de falsos negativos (error tipo II)"] == pytest.approx(1 / 4)
    assert r["F1"] == pytest.approx(2 * 3 / (2 * 3 + 2 + 1))
    # De los 24 pares positivo-negativo, el positivo queda más alto en 21.
    assert r["AUC"] == pytest.approx(21 / 24)

    # Un umbral mayor es más exigente: menos falsos positivos.
    assert m.metricas(y, prob, umbral=0.75)["FP"] == 0

    roc = m.curva_roc(y, prob)
    assert roc["fpr"].iloc[0] == 0 and roc["tpr"].iloc[-1] == 1
