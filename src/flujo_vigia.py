"""
Flujo multi-tabla: arma la base al nivel de contrato uniendo contratos y procesos.

    contratos --(id_proceso)--> procesos (reconciliados)
    contratos --(duraciones entre fechas clave)

Es el insumo del reporte descriptivo y, más adelante, de los modelos e índices
de riesgo. Replica el tratamiento de VigIA (Salazar, Pérez y Gallego, 2024).

    python -m src.flujo_vigia --config config/config.yaml

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.extraccion import crear_cliente, extraer_dataset
from src.pipeline import cargar_config
from src.procesamiento import (
    convertir_columnas_fecha,
    calcular_duraciones,
    normalizar_nombres_columnas,
    reconciliar_por_llave,
    unir_tablas,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("flujo_vigia")

RAIZ = Path(__file__).resolve().parents[1]

# Nombres de columna esperados. Cambian entre datasets, así que hay que
# confirmarlos contra los datos reales (notebooks/01_exploracion.ipynb).
LLAVE_PROCESO = "id_del_proceso"
FECHAS_CONTRATO = [
    "fecha_de_firma",
    "fecha_de_inicio_del_contrato",
    "fecha_de_fin_del_contrato",
]
FECHA_PUBLICACION = "fecha_de_publicacion"  # en la tabla de procesos

DURACIONES = {
    "dias_firma_a_inicio": ("fecha_de_firma", "fecha_de_inicio_del_contrato"),
    "dias_inicio_a_fin": ("fecha_de_inicio_del_contrato", "fecha_de_fin_del_contrato"),
}


def construir_base_contratos(config: dict, limite: int | None = 5000):
    """Extrae, procesa y une contratos con procesos al nivel de contrato."""
    cliente = crear_cliente(app_token=config.get("app_token") or None)
    try:
        contratos = extraer_dataset(cliente, "contratos", limite_total=limite)
        procesos = extraer_dataset(cliente, "procesos", limite_total=limite)
    finally:
        cliente.close()

    if contratos.empty:
        logger.warning("No se extrajeron contratos.")
        return contratos

    contratos = normalizar_nombres_columnas(contratos)
    contratos = convertir_columnas_fecha(contratos, FECHAS_CONTRATO)
    contratos = calcular_duraciones(contratos, DURACIONES)

    if not procesos.empty:
        procesos = normalizar_nombres_columnas(procesos)
        procesos = convertir_columnas_fecha(procesos, [FECHA_PUBLICACION])
        procesos = reconciliar_por_llave(
            procesos, LLAVE_PROCESO, fecha_mas_antigua=[FECHA_PUBLICACION]
        )
        contratos = unir_tablas(
            contratos, procesos, LLAVE_PROCESO, LLAVE_PROCESO, como="left"
        )

    logger.info(
        "Base de contratos lista: %d filas, %d columnas",
        len(contratos), contratos.shape[1],
    )
    return contratos


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Flujo multi-tabla de SECOP 2 al estilo VigIA."
    )
    parser.add_argument("--config", default=str(RAIZ / "config" / "config.yaml"))
    parser.add_argument("--limite", type=int, default=5000)
    args = parser.parse_args()

    config = cargar_config(args.config)
    base = construir_base_contratos(config, limite=args.limite)

    if not base.empty:
        salida = RAIZ / "data" / "processed" / "base_contratos_vigia.csv"
        salida.parent.mkdir(parents=True, exist_ok=True)
        base.to_csv(salida, index=False, encoding="utf-8-sig")
        logger.info("Base guardada en %s", salida)


if __name__ == "__main__":
    main()
