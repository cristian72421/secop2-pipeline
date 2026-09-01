"""
Flujo multi-tabla: arma la base al nivel de contrato uniendo contratos y procesos.

    contratos --(llave del proceso)--> procesos (reconciliados)
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

from src.extraccion import crear_cliente, extraer_dataset, listar_columnas
from src.pipeline import cargar_config, configurar_logging, token_efectivo
from src.procesamiento import (
    convertir_columnas_fecha,
    calcular_duraciones,
    normalizar_nombres_columnas,
    reconciliar_por_llave,
    unir_tablas,
)

logger = logging.getLogger("flujo_vigia")

RAIZ = Path(__file__).resolve().parents[1]

# La llave que relaciona las dos tablas se llama distinto en cada una.
LLAVE_CONTRATOS = "proceso_de_compra"
LLAVE_PROCESOS = "id_del_proceso"

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


def _restar_meses(fecha: str, meses: int) -> str:
    """
    Retrocede una fecha 'AAAA-MM-DD' un número de meses, al día 1.

    Se usa el día 1 para no tener que lidiar con meses de distinta duración.
    """
    anio, mes, _ = (int(parte) for parte in fecha.split("-"))
    total = anio * 12 + (mes - 1) - meses
    anio_nuevo, mes_nuevo = divmod(total, 12)
    return f"{anio_nuevo:04d}-{mes_nuevo + 1:02d}-01"


def filtros_para_procesos(
    filtros: dict,
    columnas_procesos: set[str],
    margen_meses: int,
) -> dict:
    """
    Adapta a la tabla de procesos los filtros escritos para contratos.

    Hace dos ajustes:

    1. El rango de fechas se traslada a la fecha de publicación del proceso y se
       corre hacia atrás `margen_meses`. Un proceso siempre precede al contrato
       que origina, así que filtrar ambas tablas al mismo periodo dejaría sin
       proceso a los contratos del comienzo de la ventana.
    2. Los demás filtros solo se conservan si esa columna existe en procesos;
       las tablas no tienen las mismas columnas y un nombre inexistente hace
       fallar la consulta.
    """
    adaptados: dict = {}

    for columna, valor in filtros.items():
        if isinstance(valor, dict):  # rango de fechas
            rango = dict(valor)
            if rango.get("desde"):
                rango["desde"] = _restar_meses(rango["desde"], margen_meses)
            adaptados[FECHA_PUBLICACION] = rango
            logger.info(
                "Procesos: se busca desde %s (%d meses antes que los contratos)",
                rango.get("desde"), margen_meses,
            )
        elif columna in columnas_procesos:
            adaptados[columna] = valor
        else:
            logger.info(
                "Filtro '%s' no aplica a procesos: la columna no existe ahí.", columna
            )

    return adaptados


def construir_base_contratos(config: dict, limite: int | None = 5000):
    """Extrae, procesa y une contratos con procesos al nivel de contrato."""
    filtros = config.get("filtros") or {}
    margen_meses = int(config.get("margen_meses_procesos", 6))

    cliente = crear_cliente(app_token=token_efectivo(config))
    try:
        contratos = extraer_dataset(
            cliente, "contratos", filtros=filtros or None, limite_total=limite,
        )

        columnas_procesos = set(listar_columnas("procesos")["campo"])
        filtros_procesos = filtros_para_procesos(filtros, columnas_procesos, margen_meses)
        procesos = extraer_dataset(
            cliente, "procesos", filtros=filtros_procesos or None, limite_total=limite,
        )
    finally:
        cliente.close()

    if contratos.empty:
        logger.warning("No se extrajeron contratos.")
        return contratos

    contratos = normalizar_nombres_columnas(contratos)
    contratos = convertir_columnas_fecha(contratos, FECHAS_CONTRATO)
    contratos = calcular_duraciones(contratos, DURACIONES)

    if procesos.empty:
        logger.warning("No se extrajeron procesos: la base queda solo con contratos.")
        return contratos

    procesos = normalizar_nombres_columnas(procesos)
    procesos = convertir_columnas_fecha(procesos, [FECHA_PUBLICACION])
    procesos = reconciliar_por_llave(
        procesos, LLAVE_PROCESOS, fecha_mas_antigua=[FECHA_PUBLICACION]
    )

    # Antes de unir, medir cuántos contratos encuentran su proceso. Es la única
    # forma de notar que la unión no sirvió: si la llave no coincide, unir_tablas
    # devuelve los contratos intactos y el resultado parece correcto.
    if LLAVE_CONTRATOS in contratos.columns and LLAVE_PROCESOS in procesos.columns:
        con_proceso = contratos[LLAVE_CONTRATOS].isin(procesos[LLAVE_PROCESOS]).sum()
        logger.info(
            "Contratos que encuentran su proceso: %d de %d (%.1f%%)",
            con_proceso, len(contratos), 100 * con_proceso / len(contratos),
        )
        if con_proceso == 0:
            logger.warning(
                "Ningún contrato cruzó con un proceso. Revisar los nombres de "
                "llave ('%s' en contratos, '%s' en procesos) o ampliar el margen "
                "de meses.", LLAVE_CONTRATOS, LLAVE_PROCESOS,
            )

    contratos = unir_tablas(
        contratos, procesos, LLAVE_CONTRATOS, LLAVE_PROCESOS, como="left"
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

    configurar_logging()
    config = cargar_config(args.config)
    base = construir_base_contratos(config, limite=args.limite)

    if not base.empty:
        salida = RAIZ / "data" / "processed" / "base_contratos_vigia.csv"
        salida.parent.mkdir(parents=True, exist_ok=True)
        base.to_csv(salida, index=False, encoding="utf-8-sig")
        logger.info("Base guardada en %s", salida)


if __name__ == "__main__":
    main()
