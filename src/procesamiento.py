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
) -> pd.DataFrame:
    """
    Convierte las columnas indicadas a tipo datetime (errores -> NaT).
    """
    df = df.copy()
    for col in columnas:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
            logger.info("Columna '%s' convertida a fecha", col)
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

def procesar(
    df: pd.DataFrame,
    columnas_fecha: list[str] | None = None,
    columnas_numericas: list[str] | None = None,
    subset_duplicados: list[str] | None = None,
) -> pd.DataFrame:
    """
    Orquesta la limpieza básica: normaliza nombres de columnas, convierte
    tipos y elimina duplicados. Devuelve un DataFrame listo para análisis.
    """
    if df.empty:
        logger.warning("DataFrame vacío: no hay nada que procesar.")
        return df

    df = normalizar_nombres_columnas(df)
    if columnas_fecha:
        df = convertir_columnas_fecha(df, columnas_fecha)
    if columnas_numericas:
        df = convertir_columnas_numericas(df, columnas_numericas)
    df = eliminar_duplicados(df, subset=subset_duplicados)

    logger.info("Procesamiento finalizado: %d filas, %d columnas", len(df), df.shape[1])
    return df
