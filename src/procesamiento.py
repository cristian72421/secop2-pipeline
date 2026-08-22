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
