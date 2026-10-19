"""
Cómo cambia la contratación de una entidad a lo largo del tiempo.

El resto de los indicadores describe una foto: cuánto contrató la entidad en el
periodo cargado. Este módulo describe la película: si ese comportamiento se
mantuvo, cuándo se movió y en qué dirección.

Nada de lo que hay aquí es una prueba estadística. Son descripciones: una serie
por periodo, una comparación entre dos tramos y una marca sobre los periodos
que se salen de lo que venía siendo normal. Sirven para decidir qué mirar de
cerca, no para concluir.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src.indicadores import _col, _num, es_prestacion_servicios

logger = logging.getLogger(__name__)

# En Colombia los periodos presidenciales empiezan el 7 de agosto. Son las
# fechas de corte por defecto; el usuario puede poner cualquier otra.
INICIO_DE_GOBIERNO = ("2018-08-07", "2022-08-07", "2026-08-07")

PERIODOS = {"Mensual": "ME", "Trimestral": "QE", "Anual": "YE"}

# Cuántos periodos tiene un año en cada agrupación: es el ciclo
# estacional que `quiebres()` necesita para no marcar todos los eneros.
CICLO = {"ME": 12, "QE": 4, "YE": 1}

# Cuántos proveedores entran en la medida de concentración. Cinco es lo que usa
# el resto de la aplicación, y cambiarlo aquí rompería la comparación.
TOP_PROVEEDORES = 5

SIN_ENTIDAD = "Entidad única"


def _entidad(df: pd.DataFrame, columnas: dict | None = None) -> pd.Series:
    """La columna de entidad, o una etiqueta fija si la tabla no la trae."""
    nombre = (columnas or {}).get("entidad", "nombre_entidad")
    if nombre in df.columns:
        return df[nombre].fillna(SIN_ENTIDAD).astype(str)
    return pd.Series(SIN_ENTIDAD, index=df.index)


def _concentracion(valores: pd.Series, proveedores: pd.Series) -> float:
    """Qué parte del dinero del periodo se llevan los mayores proveedores."""
    total = valores.sum()
    if not total or proveedores.empty:
        return np.nan
    por_proveedor = valores.groupby(proveedores).sum().sort_values(ascending=False)
    return 100 * por_proveedor.head(TOP_PROVEEDORES).sum() / total


def serie_temporal(df: pd.DataFrame, periodo: str = "QE",
                   columnas: dict | None = None) -> pd.DataFrame:
    """
    Una fila por entidad y periodo, con los indicadores que pueden moverse.

    Se agrupa por la fecha de firma, que es la que marca cuándo la entidad
    decidió contratar. La de inicio depende de trámites posteriores y mueve el
    dato de mes sin que haya cambiado ninguna decisión.
    """
    col_firma = _col(df, "firma", columnas)
    if col_firma is None or df.empty:
        return pd.DataFrame()

    fechas = pd.to_datetime(df[col_firma], errors="coerce")
    if fechas.notna().sum() == 0:
        return pd.DataFrame()

    base = pd.DataFrame({
        "entidad": _entidad(df, columnas),
        "periodo": fechas.dt.to_period(periodo[0] if periodo[0] in "MQY" else "Q"),
        "valor": _num(df, _col(df, "valor", columnas)).reindex(df.index),
        "servicios": es_prestacion_servicios(df, columnas),
    })
    col_mod = _col(df, "modalidad", columnas)
    base["directa"] = (
        df[col_mod].astype(str).str.lower().str.contains("directa")
        if col_mod else False
    )
    col_prov = _col(df, "proveedor", columnas)
    base["proveedor"] = df[col_prov].astype(str) if col_prov else ""
    base = base.loc[fechas.notna()]

    hoy = pd.Timestamp.today().normalize()
    filas = []
    for (entidad, per), grupo in base.groupby(["entidad", "periodo"], observed=True):
        valores = grupo["valor"].dropna()
        filas.append({
            "entidad": entidad,
            "periodo": str(per),
            "inicio": per.start_time,
            # El periodo en curso tiene menos días que los demás y su caída es
            # del calendario, no de la entidad. Se muestra pero no se analiza.
            "completo": per.end_time <= hoy,
            "contratos": len(grupo),
            "valor": valores.sum() if not valores.empty else np.nan,
            "valor_mediano": valores.median() if not valores.empty else np.nan,
            "pct_directa": 100 * grupo["directa"].mean(),
            "pct_servicios": 100 * grupo["servicios"].mean(),
            "pct_top_proveedores": _concentracion(grupo["valor"].fillna(0),
                                                  grupo["proveedor"]),
        })
    return pd.DataFrame(filas).sort_values(["entidad", "inicio"]).reset_index(drop=True)


MEDIDAS = {
    "contratos": "Contratos firmados",
    "valor": "Valor contratado",
    "valor_mediano": "Valor mediano por contrato",
    "pct_directa": "% contratación directa",
    "pct_servicios": "% prestación de servicios",
    "pct_top_proveedores": f"% del valor en los {TOP_PROVEEDORES} mayores proveedores",
}


def comparar_corte(df: pd.DataFrame, corte, meses: int | None = None,
                   columnas: dict | None = None) -> pd.DataFrame:
    """
    Los mismos indicadores antes y después de una fecha, y la diferencia.

    `meses` recorta ventanas iguales a cada lado del corte. Sin él se usa todo
    lo cargado, y entonces los dos tramos pueden tener duraciones distintas:
    la columna de contratos no sería comparable, los porcentajes sí.
    """
    col_firma = _col(df, "firma", columnas)
    if col_firma is None or df.empty:
        return pd.DataFrame()

    corte = pd.Timestamp(corte)
    fechas = pd.to_datetime(df[col_firma], errors="coerce")
    antes, despues = fechas < corte, fechas >= corte
    if meses:
        desplazamiento = pd.DateOffset(months=meses)
        antes &= fechas >= corte - desplazamiento
        despues &= fechas < corte + desplazamiento

    filas = []
    for tramo, mascara in (("Antes", antes), ("Después", despues)):
        sub = df.loc[mascara.fillna(False)]
        if sub.empty:
            continue
        serie = serie_temporal(sub, "YE", columnas)
        valores = _num(sub, _col(sub, "valor", columnas))
        col_mod = _col(sub, "modalidad", columnas)
        filas.append({
            "tramo": tramo,
            "contratos": len(sub),
            "valor": valores.sum() if not valores.empty else np.nan,
            "valor_mediano": valores.median() if not valores.empty else np.nan,
            "pct_directa": 100 * sub[col_mod].astype(str).str.lower()
                                 .str.contains("directa").mean() if col_mod else np.nan,
            "pct_servicios": 100 * es_prestacion_servicios(sub, columnas).mean(),
            "pct_top_proveedores": serie["pct_top_proveedores"].mean()
                                   if not serie.empty else np.nan,
        })

    tabla = pd.DataFrame(filas).set_index("tramo")
    if len(tabla) == 2:
        # La variación relativa solo tiene sentido si había algo antes.
        anterior = tabla.loc["Antes"]
        tabla.loc["Cambio %"] = np.where(
            anterior.to_numpy() != 0,
            100 * (tabla.loc["Después"] - anterior) / anterior.replace(0, np.nan),
            np.nan,
        ).round(1)
    return tabla


def quiebres(serie: pd.DataFrame, medida: str = "contratos",
             ventana: int = 4, umbral: float = 2.0, ciclo: int = 1) -> pd.DataFrame:
    """
    Periodos en que una medida se aparta de lo que venía siendo normal.

    Con `ciclo` en 1 cada periodo se compara con los `ventana` inmediatamente
    anteriores de la misma entidad. Con `ciclo` en 4 o 12 se compara con el
    **mismo trimestre o mes de los años anteriores**, que es lo que hay que
    hacer en contratación pública: las entidades firman su planta de
    contratistas en enero, así que todos los primeros trimestres disparan y un
    detector sin estacionalidad solo encuentra eneros.

    Los periodos incompletos quedan fuera: su caída es del calendario.

    No es una prueba estadística. Comparar contra tres o cuatro años da una
    desviación inestable, así que esto dice dónde mirar, no dónde hay algo.
    """
    if serie.empty or medida not in serie.columns:
        return pd.DataFrame()

    serie = serie.loc[serie["completo"]] if "completo" in serie.columns else serie
    if serie.empty:
        return pd.DataFrame()

    inicio = pd.to_datetime(serie["inicio"])
    if ciclo == 12:
        posicion = inicio.dt.month
    elif ciclo == 4:
        posicion = inicio.dt.quarter
    else:
        posicion = pd.Series(0, index=serie.index)
    serie = serie.assign(_posicion=posicion.to_numpy())

    # Con pocos años de historia exigir la ventana completa dejaría la tabla
    # vacía; dos observaciones previas es el mínimo para tener dispersión.
    minimo = 2 if ciclo > 1 else ventana

    partes = []
    for _, grupo in serie.groupby(["entidad", "_posicion"], observed=True):
        grupo = grupo.sort_values("inicio").copy()
        previos = grupo[medida].shift(1).rolling(ventana, min_periods=minimo)
        media, desviacion = previos.mean(), previos.std()
        grupo["esperado"] = media
        # Cuántas observaciones previas sostienen esa comparación. Con dos, la
        # desviación es casi cero y el resultado se dispara: hay que verlo.
        grupo["base"] = previos.count()
        # Sin variación previa, cualquier cambio sería infinito: se descarta.
        grupo["desvios"] = np.where(
            desviacion.to_numpy() > 0,
            (grupo[medida] - media) / desviacion.replace(0, np.nan),
            np.nan,
        )
        partes.append(grupo)

    marcados = pd.concat(partes, ignore_index=True)
    marcados = marcados.loc[marcados["desvios"].abs() >= umbral]
    if marcados.empty:
        return pd.DataFrame()
    marcados["sentido"] = np.where(marcados["desvios"] > 0, "Subida", "Caída")
    return marcados[
        ["entidad", "periodo", medida, "esperado", "desvios", "base", "sentido"]
    ].sort_values(["entidad", "periodo"]).reset_index(drop=True)
