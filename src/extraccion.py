"""
Extracción de datos de SECOP 2 desde datos.gov.co, vía Socrata (SODA).

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import logging
import time

import pandas as pd
import requests
from sodapy import Socrata

logger = logging.getLogger(__name__)

DOMINIO = "www.datos.gov.co"
URL_METADATOS = "https://www.datos.gov.co/api/views/{dataset_id}.json"

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


def listar_columnas(tabla: str) -> pd.DataFrame:
    """
    Columnas de una tabla según los metadatos del portal.

    Devuelve el nombre de campo que espera SoQL (que no es el que se ve en la
    web), el nombre visible, el tipo y los valores más frecuentes que el portal
    mantiene en caché. Sirve para no adivinar nombres al armar los filtros.
    """
    if tabla not in DATASETS:
        raise ValueError(f"Tabla '{tabla}' no reconocida. Opciones: {list(DATASETS)}")

    url = URL_METADATOS.format(dataset_id=DATASETS[tabla])
    respuesta = requests.get(url, timeout=60)
    respuesta.raise_for_status()

    filas = []
    for col in respuesta.json().get("columns", []):
        campo = col.get("fieldName") or ""
        # Socrata expone columnas propias suyas (:id, :created_at) que no son
        # datos del contrato y solo ensucian la lista.
        if campo.startswith(":"):
            continue
        cache = (col.get("cachedContents") or {}).get("top") or []
        filas.append({
            "campo": campo,
            "nombre": col.get("name"),
            "tipo": col.get("dataTypeName"),
            "ejemplos": [str(v.get("item")) for v in cache[:15] if v.get("item") is not None],
        })

    logger.info("Metadatos de '%s': %d columnas", tabla, len(filas))
    return pd.DataFrame(filas)


def valores_distintos(
    cliente: Socrata,
    tabla: str,
    columna: str,
    limite: int = 300,
) -> pd.DataFrame:
    """
    Valores distintos de una columna, con su número de registros.

    Es un group by sobre toda la tabla, así que en columnas de alta
    cardinalidad (identificadores, objetos de contrato) es lento y poco útil.
    """
    if tabla not in DATASETS:
        raise ValueError(f"Tabla '{tabla}' no reconocida. Opciones: {list(DATASETS)}")

    registros = cliente.get(
        DATASETS[tabla],
        select=f"{columna} AS valor, count(*) AS n",
        group=columna,
        order="n DESC",
        limit=limite,
    )
    df = pd.DataFrame.from_records(registros)
    if not df.empty and "n" in df.columns:
        df["n"] = pd.to_numeric(df["n"], errors="coerce")
    return df


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

    # Se acumulan las páginas y se concatenan al final: hacerlo en cada vuelta
    # copiaría la tabla entera una y otra vez.
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

        # Una página más corta que el límite pedido significa que ya no hay más.
        if n < limite:
            break

        time.sleep(0.2)  # evitar throttling de la API

    if not paginas:
        logger.warning("La consulta no devolvió registros.")
        return pd.DataFrame()

    df = pd.concat(paginas, ignore_index=True)
    logger.info("Extracción finalizada: %d filas, %d columnas", len(df), df.shape[1])
    return df
