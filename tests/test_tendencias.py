"""
Pruebas del análisis de cambios en el tiempo.

Cubren lo que se rompe en silencio: por qué fecha se agrupa, que el quiebre
marque el periodo en que cambia el nivel y no todos los siguientes, que una
variación sin base no se reporte como un cambio enorme, y que un filtro sin
resultados no reviente la pestaña.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import pandas as pd

from src import tendencias as t


def test_la_serie_se_agrupa_por_la_fecha_de_firma(contratos):
    """
    La fecha de inicio depende de trámites posteriores y movería el contrato de
    trimestre sin que la entidad hubiera decidido nada distinto.
    """
    serie = t.serie_temporal(contratos, "QE")
    assert list(serie["periodo"]) == ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]
    assert serie["contratos"].sum() == len(contratos)

    por_firma = contratos["fecha_de_firma"].dt.to_period("Q").value_counts()
    assert serie.set_index("periodo")["contratos"]["2025Q1"] == por_firma["2025Q1"]


def test_el_quiebre_marca_el_periodo_en_que_cambia_el_nivel():
    """
    Ocho trimestres estables en ~100 y luego cuatro en ~400: lo que interesa es
    el trimestre del salto. Los siguientes ya no son noticia, porque el nivel
    nuevo pasó a ser lo normal.
    """
    periodos = pd.period_range("2022Q1", periods=12, freq="Q")
    estable_y_salto = [100, 104, 98, 102, 99, 101, 103, 100, 400, 410, 395, 405]
    serie = pd.DataFrame({
        "entidad": "Entidad de prueba",
        "periodo": [str(p) for p in periodos],
        "inicio": [p.start_time for p in periodos],
        "contratos": estable_y_salto,
    })

    marcados = t.quiebres(serie, "contratos", ventana=4, umbral=2.0)
    assert len(marcados) == 1
    assert marcados.loc[0, "periodo"] == "2024Q1"
    assert marcados.loc[0, "sentido"] == "Subida"


def test_una_variacion_sin_base_no_se_reporta_como_cambio(contratos):
    """
    Si antes del corte un indicador valía cero, la variación relativa sería
    infinita. Se deja vacía en vez de mostrar un número sin sentido.
    """
    tabla = t.comparar_corte(contratos, "2025-02-01")
    assert list(tabla.index) == ["Antes", "Después", "Cambio %"]
    cambios = tabla.loc["Cambio %"]
    assert not any(abs(v) == float("inf") for v in cambios.dropna())


def test_sin_datos_devuelve_tablas_vacias(vacio):
    """Un filtro que no deja filas no debe reventar la pestaña."""
    assert t.serie_temporal(vacio).empty
    assert t.comparar_corte(vacio, "2025-01-01").empty
    assert t.quiebres(pd.DataFrame()).empty


def test_la_estacionalidad_tapa_el_cambio_real_si_no_se_tiene_en_cuenta():
    """
    Defecto encontrado contra datos reales: las entidades firman su planta de
    contratistas en enero, así que todos los primeros trimestres disparan.

    Aquí hay cuatro años de esa estacionalidad y un salto genuino en el tercer
    trimestre de 2024. Comparando con los periodos inmediatamente anteriores el
    salto **no se ve**: el promedio va inflado por el enero que lleva dentro.
    Comparando contra el mismo trimestre de los años anteriores, aparece.
    """
    por_trimestre = [
        1000, 200, 215, 210,
        1010, 205, 225, 212,
        990, 198, 218, 208,
        1005, 202, 900, 211,   # el salto real: un tercer trimestre de 900
        1000, 200, 220, 209,
    ]
    periodos = pd.period_range("2021Q1", periods=len(por_trimestre), freq="Q")
    serie = pd.DataFrame({
        "entidad": "Entidad de prueba",
        "periodo": [str(p) for p in periodos],
        "inicio": [p.start_time for p in periodos],
        "completo": True,
        "contratos": por_trimestre,
    })

    sin_ciclo = t.quiebres(serie, "contratos", ciclo=1)
    assert "2024Q3" not in list(sin_ciclo.get("periodo", []))

    con_ciclo = t.quiebres(serie, "contratos", ciclo=4)
    assert "2024Q3" in list(con_ciclo["periodo"])
    salto = con_ciclo.set_index("periodo").loc["2024Q3"]
    assert salto["sentido"] == "Subida"
    # Es, de lejos, el más marcado de los que aparecen.
    assert salto["desvios"] == con_ciclo["desvios"].abs().max()


def test_la_tabla_dice_cuantos_anios_sostienen_cada_marca():
    """
    Con dos observaciones previas la desviación es casi cero y cualquier
    diferencia se dispara. La columna «base» deja eso a la vista en vez de
    esconderlo detrás de un número grande.
    """
    periodos = pd.period_range("2022Q1", periods=12, freq="Q")
    serie = pd.DataFrame({
        "entidad": "Entidad de prueba",
        "periodo": [str(p) for p in periodos],
        "inicio": [p.start_time for p in periodos],
        "completo": True,
        "contratos": [100, 50, 52, 51, 101, 49, 53, 50, 300, 51, 52, 49],
    })
    marcados = t.quiebres(serie, "contratos", ciclo=4)
    assert "base" in marcados.columns
    assert marcados["base"].min() >= 2


def test_el_periodo_en_curso_no_se_analiza(contratos):
    """Su caída es del calendario, no de la entidad."""
    serie = t.serie_temporal(contratos, "QE")
    assert "completo" in serie.columns
    assert serie["completo"].all()   # el fixture es de 2025, ya cerrado
