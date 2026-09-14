"""
Datos y utilidades compartidas por las pruebas.

Las tres tablas de `tests/datos/` son pequeñas y fijas, y están construidas para
que cada cifra esperada se pueda verificar a mano. No salen de la API: las
pruebas no tocan la red, así que corren igual sin conexión y sin token.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# La raíz del proyecto al path, para poder importar `src` sin instalarlo.
RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.flujo_vigia import (  # noqa: E402
    DURACIONES, FECHA_PUBLICACION, LLAVE_CONTRATOS, LLAVE_PROCESOS,
)
from src.procesamiento import procesar, reconciliar_por_llave, unir_tablas  # noqa: E402

DATOS = Path(__file__).parent / "datos"

FECHAS_CONTRATO = [
    "fecha_de_firma", "fecha_de_inicio_del_contrato", "fecha_de_fin_del_contrato",
]

# Cifras de `contratos.csv` verificables a mano; si una prueba falla contra
# estas constantes, o cambió el fixture o se rompió un cálculo.
TOTAL_CONTRATOS = 43
TOTAL_DIRECTOS = 35
VALOR_TOTAL = 70_320_000_000
VALOR_URGENCIA_MANIFIESTA = 50_000_000_000


@pytest.fixture
def contratos_crudos() -> pd.DataFrame:
    """La tabla de contratos tal como la entrega la API: texto sin convertir."""
    return pd.read_csv(DATOS / "contratos.csv", dtype=str)


@pytest.fixture
def contratos(contratos_crudos) -> pd.DataFrame:
    """Contratos ya procesados: fechas en datetime, montos numéricos, duraciones."""
    return procesar(
        contratos_crudos,
        columnas_fecha=FECHAS_CONTRATO,
        columnas_numericas=["dias_adicionados"],
        columnas_moneda=["valor_del_contrato"],
        pares_duraciones=DURACIONES,
    )


@pytest.fixture
def procesos_crudos() -> pd.DataFrame:
    """Procesos de contratación, con las filas repetidas que trae la fuente."""
    return pd.read_csv(DATOS / "procesos.csv", dtype=str)


@pytest.fixture
def base(contratos, procesos_crudos) -> pd.DataFrame:
    """
    La base al nivel de contrato que usan la interfaz y el reporte.

    Reproduce el flujo de `flujo_vigia`: se reconcilian los procesos y se unen
    a los contratos por la izquierda, para no perder ningún contrato.
    """
    procesos = procesar(
        procesos_crudos,
        columnas_fecha=[FECHA_PUBLICACION],
        columnas_numericas=["respuestas_al_procedimiento"],
    )
    procesos = reconciliar_por_llave(
        procesos, LLAVE_PROCESOS, fecha_mas_antigua=[FECHA_PUBLICACION],
    )
    return unir_tablas(contratos, procesos, LLAVE_CONTRATOS, LLAVE_PROCESOS)


@pytest.fixture
def contratos_portal() -> pd.DataFrame:
    """El CSV que exporta la web del portal: otros nombres, otro formato."""
    return pd.read_csv(DATOS / "contratos_portal.csv", dtype=str)


@pytest.fixture
def vacio() -> pd.DataFrame:
    """Una consulta que no devolvió filas. La interfaz llega a este caso."""
    return pd.DataFrame()
