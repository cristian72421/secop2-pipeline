"""
Orquestador del pipeline de extracción y procesamiento de SECOP 2.

Une los tres pasos del flujo:
  1. Lee la configuración (config/config.yaml)  -> parametrización (Entregable 2)
  2. Extrae los datos de SECOP 2 vía Socrata     -> extracción (Entregable 1)
  3. Procesa/limpia los datos                    -> procesamiento (Entregable 1)
  4. Guarda el resultado en data/processed

Uso:
    python -m src.pipeline --config config/config.yaml

Autor: Cristian Camilo Rodríguez Cagüeñas
Monitoría de investigación - Beca Avanza, Universidad de los Andes
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import yaml

from src.extraccion import crear_cliente, extraer_dataset
from src.procesamiento import procesar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

# Directorios base del proyecto
RAIZ = Path(__file__).resolve().parents[1]
DIR_PROCESADO = RAIZ / "data" / "processed"


def cargar_config(ruta: str | Path) -> dict:
    """Lee el archivo YAML de configuración y lo devuelve como diccionario."""
    with open(ruta, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    logger.info("Configuración cargada desde %s", ruta)
    return config


def ejecutar(config: dict) -> Path:
    """Ejecuta el pipeline completo con los parámetros dados y guarda el CSV."""
    # 1. Cliente
    cliente = crear_cliente(app_token=config.get("app_token") or None)

    try:
        # 2. Extracción (Entregable 1 + parametrización del Entregable 2)
        df = extraer_dataset(
            cliente,
            tabla=config.get("tabla", "contratos"),
            filtros=config.get("filtros") or None,
            tamano_pagina=int(config.get("tamano_pagina", 50_000)),
            limite_total=config.get("limite_total"),
        )
    finally:
        cliente.close()

    if df.empty:
        logger.warning("No se extrajeron datos. Revisa los filtros de config.")
        return DIR_PROCESADO

    # 3. Procesamiento (Entregable 1)
    # Las duraciones vienen como lista de {nombre, desde, hasta} en el YAML;
    # se convierten al formato {nombre: (desde, hasta)} que espera procesar().
    pares_duraciones = None
    if config.get("duraciones"):
        pares_duraciones = {
            d["nombre"]: (d["desde"], d["hasta"]) for d in config["duraciones"]
        }

    df = procesar(
        df,
        columnas_fecha=config.get("columnas_fecha"),
        columnas_numericas=config.get("columnas_numericas"),
        subset_duplicados=config.get("subset_duplicados"),
        pares_duraciones=pares_duraciones,
    )

    # 4. Guardado con timestamp para trazabilidad
    DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    tabla = config.get("tabla", "contratos")
    salida = DIR_PROCESADO / f"secop2_{tabla}_{marca}.csv"
    df.to_csv(salida, index=False, encoding="utf-8-sig")
    logger.info("Datos guardados en %s (%d filas)", salida, len(df))
    return salida


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline de extracción y procesamiento de datos de SECOP 2."
    )
    parser.add_argument(
        "--config",
        default=str(RAIZ / "config" / "config.yaml"),
        help="Ruta al archivo de configuración YAML.",
    )
    args = parser.parse_args()

    config = cargar_config(args.config)
    ejecutar(config)


if __name__ == "__main__":
    main()
