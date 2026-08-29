"""
Módulo de procesamiento y limpieza de los datos de SECOP 2.

Parte del Entregable 1: procesamiento de los datos extraídos.
Aquí se estandarizan tipos, se normalizan nombres de columnas y se hacen
limpiezas básicas para dejar la data lista para análisis.

Autor: Cristian Camilo Rodríguez Cagüeñas
Monitoría de investigación - Beca Avanza, Universidad de los Andes
"""

from __future__ import annotations

import logging
import re
import unicodedata

import pandas as pd

logger = logging.getLogger(__name__)


def normalizar_nombres_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza los nombres de columnas: minúsculas, sin tildes, sin espacios.

    Ej.: 'Valor del Contrato' -> 'valor_del_contrato'
    """
    def limpiar(nombre: str) -> str:
        # quitar tildes
        nfkd = unicodedata.normalize("NFKD", nombre)
        sin_tilde = "".join(c for c in nfkd if not unicodedata.combining(c))
        # minúsculas, espacios y no alfanuméricos -> guión bajo
        s = sin_tilde.strip().lower()
        s = re.sub(r"[^\w]+", "_", s)
        return s.strip("_")

    df = df.copy()
    df.columns = [limpiar(c) for c in df.columns]
    return df


def convertir_columnas_fecha(
    df: pd.DataFrame,
    columnas: list[str],
    formato: str | None = None,
) -> pd.DataFrame:
    """
    Convierte las columnas indicadas a tipo datetime (errores -> NaT).

    En SECOP II las fechas vienen como MM/DD/YYYY, así que conviene pasar
    formato="%m/%d/%Y" para una conversión correcta y rápida.
    """
    df = df.copy()
    for col in columnas:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], format=formato, errors="coerce")
            logger.info("Columna '%s' convertida a fecha", col)
    return df


def limpiar_columnas_moneda(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    """
    Limpia columnas de moneda con formato colombiano y las pasa a numérico.

    Ejemplo: "$13.339.049" -> 13339049.0

    En SECOP II los montos vienen como texto con símbolo de peso y puntos como
    separador de miles. Se eliminan el '$', los espacios y los puntos, y se
    convierte a número (errores -> NaN).
    """
    df = df.copy()
    for col in columnas:
        if col in df.columns:
            serie = (
                df[col]
                .astype(str)
                .str.replace(r"[$\s]", "", regex=True)   # quitar $ y espacios
                .str.replace(".", "", regex=False)        # quitar separador de miles
                .str.replace(",", ".", regex=False)       # coma decimal -> punto
            )
            df[col] = pd.to_numeric(serie, errors="coerce")
            logger.info("Columna de moneda '%s' limpiada y convertida", col)
    return df


def convertir_columnas_numericas(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    """
    Convierte las columnas indicadas a numérico (errores -> NaN).

    Útil para montos como 'valor_del_contrato', que suelen venir como texto.
    """
    df = df.copy()
    for col in columnas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            logger.info("Columna '%s' convertida a numérico", col)
    return df


def eliminar_duplicados(df: pd.DataFrame, subset: list[str] | None = None) -> pd.DataFrame:
    """
    Elimina filas duplicadas, opcionalmente según un subconjunto de columnas
    (por ejemplo, el identificador único del contrato o proceso).
    """
    antes = len(df)
    df = df.drop_duplicates(subset=subset).reset_index(drop=True)
    logger.info("Duplicados eliminados: %d filas (%d -> %d)", antes - len(df), antes, len(df))
    return df


def calcular_duraciones(
    df: pd.DataFrame,
    pares_fechas: dict[str, tuple[str, str]],
) -> pd.DataFrame:
    """
    Crea variables de duración (en días) entre pares de fechas.

    Basado en las cinco fechas clave del ciclo de vida del contrato descritas
    en VigIA (firma, inicio, inicio de ejecución, fin de ejecución, fin) y en
    las variables derivadas como 'sign-to-start' o 'start-to-end'.

    Las columnas de fecha ya deben estar convertidas a datetime (usar
    `convertir_columnas_fecha` antes).

    NOTA: algunas duraciones pueden ser negativas —por ejemplo, cuando el
    contrato se firma después de su fecha de inicio—. Esto NO es un error: el
    artículo lo reporta como una práctica frecuente y, de hecho, como una
    señal (red flag) de posible ineficiencia, por lo que se conserva tal cual.

    Parameters
    ----------
    pares_fechas : dict[str, tuple[str, str]]
        Diccionario {nombre_nueva_columna: (fecha_inicial, fecha_final)}.
        La duración se calcula como fecha_final - fecha_inicial, en días.

    Returns
    -------
    pd.DataFrame
        DataFrame con las nuevas columnas de duración añadidas.
    """
    df = df.copy()
    for nombre, (col_ini, col_fin) in pares_fechas.items():
        if col_ini in df.columns and col_fin in df.columns:
            df[nombre] = (df[col_fin] - df[col_ini]).dt.days
            logger.info(
                "Duración '%s' = (%s - %s) creada", nombre, col_fin, col_ini
            )
        else:
            faltan = [c for c in (col_ini, col_fin) if c not in df.columns]
            logger.warning(
                "No se pudo crear '%s': faltan columnas %s", nombre, faltan
            )
    return df


def reconciliar_por_llave(
    df: pd.DataFrame,
    llave: str,
    fecha_mas_antigua: list[str] | None = None,
) -> pd.DataFrame:
    """
    Reconcilia registros duplicados que comparten la misma llave.

    Replica el tratamiento que VigIA aplica a la tabla de procesos: para un
    mismo identificador de proceso pueden existir varias filas; se eliminan
    duplicados exactos y, cuando hay conflicto en columnas de fecha, se
    conserva la fecha más antigua.

    Parameters
    ----------
    llave : str
        Columna identificadora por la que se agrupa (p. ej. 'id_del_proceso').
    fecha_mas_antigua : list[str] | None
        Columnas de fecha en las que, ante conflicto, se conserva el valor
        mínimo (más antiguo). El resto de columnas toma el primer valor no nulo.

    Returns
    -------
    pd.DataFrame
        Un registro por llave, con los conflictos reconciliados.
    """
    if llave not in df.columns:
        logger.warning("Llave '%s' no está en el DataFrame; se omite.", llave)
        return df

    fecha_mas_antigua = fecha_mas_antigua or []
    antes = len(df)

    # 1. Quitar duplicados exactos en todas las columnas
    df = df.drop_duplicates().reset_index(drop=True)

    # 2. Definir cómo agregar cada columna al agrupar por la llave
    agregaciones: dict[str, str] = {}
    for col in df.columns:
        if col == llave:
            continue
        if col in fecha_mas_antigua:
            agregaciones[col] = "min"          # fecha más antigua
        else:
            agregaciones[col] = "first"        # primer valor disponible

    df_reconciliado = df.groupby(llave, as_index=False).agg(agregaciones)
    logger.info(
        "Reconciliación por '%s': %d -> %d filas",
        llave, antes, len(df_reconciliado),
    )
    return df_reconciliado


def unir_tablas(
    izquierda: pd.DataFrame,
    derecha: pd.DataFrame,
    llave_izq: str,
    llave_der: str,
    como: str = "left",
    sufijos: tuple[str, str] = ("", "_der"),
) -> pd.DataFrame:
    """
    Une dos tablas por sus llaves (por ejemplo, contratos con procesos).

    VigIA une la tabla de contratos con la de procesos por el ID de proceso
    para llevar al nivel de contrato variables del proceso (número de ofertas,
    período de publicación, etc.).

    Parameters
    ----------
    izquierda, derecha : pd.DataFrame
        Tablas a unir.
    llave_izq, llave_der : str
        Columnas llave en cada tabla.
    como : str
        Tipo de join: 'left', 'inner', etc.
    sufijos : tuple[str, str]
        Sufijos para columnas con el mismo nombre en ambas tablas.

    Returns
    -------
    pd.DataFrame
        Tabla unida.
    """
    if llave_izq not in izquierda.columns or llave_der not in derecha.columns:
        logger.warning(
            "No se puede unir: falta llave (%s en izquierda o %s en derecha).",
            llave_izq, llave_der,
        )
        return izquierda

    resultado = izquierda.merge(
        derecha,
        left_on=llave_izq,
        right_on=llave_der,
        how=como,
        suffixes=sufijos,
    )
    logger.info(
        "Unión %s: %d filas resultantes (%d columnas)",
        como, len(resultado), resultado.shape[1],
    )
    return resultado


def procesar(
    df: pd.DataFrame,
    columnas_fecha: list[str] | None = None,
    columnas_numericas: list[str] | None = None,
    columnas_moneda: list[str] | None = None,
    subset_duplicados: list[str] | None = None,
    pares_duraciones: dict[str, tuple[str, str]] | None = None,
    formato_fecha: str | None = None,
) -> pd.DataFrame:
    """
    Orquesta la limpieza básica: normaliza columnas, convierte tipos, limpia
    moneda, calcula duraciones y elimina duplicados. Devuelve un DataFrame
    listo para análisis.
    """
    if df.empty:
        logger.warning("DataFrame vacío: no hay nada que procesar.")
        return df

    df = normalizar_nombres_columnas(df)
    if columnas_fecha:
        df = convertir_columnas_fecha(df, columnas_fecha, formato=formato_fecha)
    if columnas_moneda:
        df = limpiar_columnas_moneda(df, columnas_moneda)
    if columnas_numericas:
        df = convertir_columnas_numericas(df, columnas_numericas)
    if pares_duraciones:
        df = calcular_duraciones(df, pares_duraciones)
    df = eliminar_duplicados(df, subset=subset_duplicados)

    logger.info("Procesamiento finalizado: %d filas, %d columnas", len(df), df.shape[1])
    return df
