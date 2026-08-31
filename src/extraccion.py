"""
Extracción de datos de SECOP 2 desde datos.gov.co, vía Socrata (SODA).

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import logging
import time

import pandas as pd
from sodapy import Socrata

logger = logging.getLogger(__name__)

DOMINIO = "www.datos.gov.co"

# Dataset ids de SECOP II en Socrata. Pueden cambiar: si una tabla deja de
# responder, el id se reconfirma en datos.gov.co. Las cuatro primeras son las
# que usa VigIA (Salazar, Pérez y Gallego, 2024).
DATASETS = {
    "contratos": "jbjy-vk9h",    # SECOP II - Contratos Electrónicos (tabla principal)
    "procesos": "p6dx-8zbt",     # SECOP II - Procesos de Contratación
    "proveedores": "qmzu-gj57",  # SECOP II - Proveedores Registrados
    "adiciones": "cb9c-h8sn",    # SECOP II - Adiciones (sobrecostos y prórrogas)
    "integrado": "rpmr-utcd",    # SECOP Integrado (SECOP I + II con contrato)
}


def crear_cliente(app_token: str | None = None, timeout: int = 60) -> Socrata:
    """
    Cliente de Socrata para el portal de datos abiertos.

    El acceso es público: con app_token=None funciona igual, solo con límites
    de uso más bajos (https://dev.socrata.com/docs/app-tokens.html).
    """
    cliente = Socrata(DOMINIO, app_token, timeout=timeout)
    logger.info("Cliente Socrata creado para el dominio %s", DOMINIO)
    return cliente


def _construir_where(filtros: dict | None) -> str | None:
    """
    Traduce un diccionario de filtros a una cláusula WHERE de SoQL.

    Igualdad simple:  {"columna": "valor"}
    Rango de fechas:  {"columna": {"desde": "2024-01-01", "hasta": "2024-12-31"}}
    """
    if not filtros:
        return None

    condiciones: list[str] = []
    for columna, valor in filtros.items():
        if isinstance(valor, dict):  # rango de fechas
            desde = valor.get("desde")
            hasta = valor.get("hasta")
            if desde:
                condiciones.append(f"{columna} >= '{desde}'")
            if hasta:
                condiciones.append(f"{columna} <= '{hasta}'")
        else:  # igualdad simple (texto)
            # comillas simples dobladas para no romper la consulta
            valor_escapado = str(valor).replace("'", "''")
            condiciones.append(f"{columna} = '{valor_escapado}'")

    return " AND ".join(condiciones) if condiciones else None


def extraer_dataset(
    cliente: Socrata,
    tabla: str,
    filtros: dict | None = None,
    tamano_pagina: int = 50_000,
    limite_total: int | None = None,
) -> pd.DataFrame:
    """
    Descarga una tabla de SECOP 2 paginando sobre la API.

    Socrata limita las filas por petición, así que se recorre con limit/offset
    hasta agotar los resultados o llegar a limite_total (None = sin tope).
    """
    if tabla not in DATASETS:
        raise ValueError(
            f"Tabla '{tabla}' no reconocida. Opciones: {list(DATASETS)}"
        )

    dataset_id = DATASETS[tabla]
    where = _construir_where(filtros)
    logger.info("Extrayendo tabla '%s' (id=%s) where=%s", tabla, dataset_id, where)

    paginas: list[pd.DataFrame] = []
    offset = 0
    total = 0

    while True:
        limite = tamano_pagina
        if limite_total is not None:
            limite = min(tamano_pagina, limite_total - total)
            if limite <= 0:
                break

        registros = cliente.get(
            dataset_id,
            where=where,
            limit=limite,
            offset=offset,
        )
        if not registros:
            break

        df_pagina = pd.DataFrame.from_records(registros)
        paginas.append(df_pagina)

        n = len(df_pagina)
        total += n
        offset += n
        logger.info("  página descargada: %d filas (acumulado: %d)", n, total)

        if n < limite:  # última página
            break

        time.sleep(0.2)  # evitar throttling de la API

    if not paginas:
        logger.warning("La consulta no devolvió registros.")
        return pd.DataFrame()

    df = pd.concat(paginas, ignore_index=True)
    logger.info("Extracción finalizada: %d filas, %d columnas", len(df), df.shape[1])
    return df
