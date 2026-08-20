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
from sodapy import Socrata

logger = logging.getLogger(__name__)

# Dominio del portal de datos abiertos de Colombia
DOMINIO = "www.datos.gov.co"

# Identificadores (dataset id) de las principales tablas de SECOP II en Socrata.
# Verificar/actualizar en https://www.datos.gov.co si cambian.
DATASETS = {
    "contratos": "jbjy-vk9h",    # SECOP II - Contratos Electrónicos (tabla principal)
    "procesos": "p6dx-8zbt",     # SECOP II - Procesos de Contratación
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
