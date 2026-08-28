"""
Procesa un CSV de SECOP 2 ya descargado desde el portal (sin llamar a la API).

Útil cuando ya tienes el archivo (por ejemplo, descargado manualmente con un
filtro desde datos.gov.co) y solo quieres aplicarle la limpieza y las
variables derivadas del pipeline.

Uso:
    python -m src.procesar_csv --entrada ruta/al/archivo.csv

    # opcional: indicar otra carpeta de salida
    python -m src.procesar_csv --entrada datos.csv --salida data/processed

Autor: Cristian Camilo Rodríguez Cagüeñas
Monitoría de investigación - Beca Avanza, Universidad de los Andes
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.procesamiento import procesar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("procesar_csv")

RAIZ = Path(__file__).resolve().parents[1]

# --- Parámetros de procesamiento para SECOP II - Contratos Electrónicos ---
# (nombres ya normalizados: minúsculas, sin tildes, con guión bajo)
COLUMNAS_FECHA = [
    "fecha_de_firma",
    "fecha_de_inicio_del_contrato",
    "fecha_de_fin_del_contrato",
]
FORMATO_FECHA = "%m/%d/%Y"  # SECOP II entrega las fechas como MM/DD/YYYY

COLUMNAS_MONEDA = [
    "valor_del_contrato",
    "valor_pagado",
    "valor_pendiente_de_pago",
]

SUBSET_DUPLICADOS = ["id_contrato"]

DURACIONES = {
    "dias_firma_a_inicio": ("fecha_de_firma", "fecha_de_inicio_del_contrato"),
    "dias_inicio_a_fin": ("fecha_de_inicio_del_contrato", "fecha_de_fin_del_contrato"),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Procesa un CSV de SECOP 2 ya descargado (sin API)."
    )
    parser.add_argument(
        "--entrada", required=True, help="Ruta al CSV descargado de SECOP 2."
    )
    parser.add_argument(
        "--salida",
        default=str(RAIZ / "data" / "processed"),
        help="Carpeta donde guardar el CSV procesado.",
    )
    args = parser.parse_args()

    # 1. Leer el CSV descargado
    logger.info("Leyendo %s ...", args.entrada)
    df = pd.read_csv(args.entrada, low_memory=False)
    logger.info("Entrada: %d filas, %d columnas", len(df), df.shape[1])

    # 2. Procesar (normaliza, convierte fechas/moneda, calcula duraciones, dedup)
    limpio = procesar(
        df,
        columnas_fecha=COLUMNAS_FECHA,
        formato_fecha=FORMATO_FECHA,
        columnas_moneda=COLUMNAS_MONEDA,
        subset_duplicados=SUBSET_DUPLICADOS,
        pares_duraciones=DURACIONES,
    )

    # 3. Guardar con marca de tiempo
    carpeta = Path(args.salida)
    carpeta.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    salida = carpeta / f"secop2_procesado_{marca}.csv"
    limpio.to_csv(salida, index=False, encoding="utf-8-sig")
    logger.info("Guardado: %s (%d filas, %d columnas)", salida, len(limpio), limpio.shape[1])


if __name__ == "__main__":
    main()
