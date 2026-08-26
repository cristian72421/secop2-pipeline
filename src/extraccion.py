"""
Módulo de extracción de datos de SECOP 2 desde el portal de datos abiertos
de Colombia (datos.gov.co), basado en la Socrata Open Data API (SODA).

Entregable 1: implementación inicial del pipeline de extracción y procesamiento
de datos de SECOP 2, considerando las diferentes tablas disponibles.

Autor: Cristian Camilo Rodríguez Cagüeñas
Monitoría de investigación - Beca Avanza, Universidad de los Andes
"""

from __future__ import annotations

import logging
import time
from typing import Iterator

import pandas as pd
from sodapy import Socrata

logger = logging.getLogger(__name__)

# Dominio del portal de datos abiertos de Colombia
DOMINIO = "www.datos.gov.co"

# Identificadores (dataset id) de las principales tablas de SECOP II en Socrata.
# Verificar/actualizar en https://www.datos.gov.co si cambian.
# Tablas usadas por VigIA (Salazar, Pérez & Gallego, 2024) para construir
# los modelos e índices de riesgo de contratación pública.
DATASETS = {
    "contratos": "jbjy-vk9h",    # SECOP II - Contratos Electrónicos (tabla principal)
    "procesos": "p6dx-8zbt",     # SECOP II - Procesos de Contratación
    "proveedores": "qmzu-gj57",  # SECOP II - Proveedores Registrados
    "adiciones": "cb9c-h8sn",    # SECOP II - Adiciones (sobrecostos y prórrogas)
    "integrado": "rpmr-utcd",    # SECOP Integrado (SECOP I + II con contrato)
}


def crear_cliente(app_token: str | None = None, timeout: int = 60) -> Socrata:
    """
    Crea un cliente de Socrata para el portal de datos abiertos.

    El acceso es público y no requiere autenticación, pero registrar un
    app_token mejora los límites de uso de la API. Ver:
    https://dev.socrata.com/docs/app-tokens.html

    Parameters
    ----------
    app_token : str | None
        Token de aplicación de Socrata (opcional pero recomendado).
    timeout : int
        Tiempo máximo de espera por petición, en segundos.

    Returns
    -------
    Socrata
        Cliente listo para consultar el portal.
    """
    # Con app_token=None el cliente funciona igual, solo con límites más bajos.
    cliente = Socrata(DOMINIO, app_token, timeout=timeout)
    logger.info("Cliente Socrata creado para el dominio %s", DOMINIO)
    return cliente


def _construir_where(filtros: dict | None) -> str | None:
    """
    Construye la cláusula WHERE de SoQL a partir de un diccionario de filtros.

    Soporta:
      - Igualdad simple:      {"columna": "valor"}
      - Rangos de fecha:      {"columna": {"desde": "2024-01-01", "hasta": "2024-12-31"}}

    Los valores de texto se escapan con comillas simples dobladas para evitar
    romper la consulta.
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
    Extrae un dataset de SECOP 2 con paginación automática.

    La API de Socrata limita el número de filas por petición, por lo que se
    descarga por páginas (offset/limit) hasta agotar los resultados o alcanzar
    el límite total indicado.

    Parameters
    ----------
    cliente : Socrata
        Cliente creado con `crear_cliente`.
    tabla : str
        Clave lógica de la tabla ('contratos', 'procesos', 'integrado').
    filtros : dict | None
        Filtros a aplicar (ver `_construir_where`).
    tamano_pagina : int
        Número de filas por petición.
    limite_total : int | None
        Tope de filas a descargar en total (None = sin tope).

    Returns
    -------
    pd.DataFrame
        Datos extraídos y concatenados.
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

        time.sleep(0.2)  # cortesía con la API para evitar throttling

    if not paginas:
        logger.warning("La consulta no devolvió registros.")
        return pd.DataFrame()

    df = pd.concat(paginas, ignore_index=True)
    logger.info("Extracción finalizada: %d filas, %d columnas", len(df), df.shape[1])
    return df
