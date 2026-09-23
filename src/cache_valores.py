"""
Caché en disco de lo que se consulta para armar los filtros.

Cada vez que se elige una columna, la interfaz le pregunta al portal qué
valores tiene. Esa consulta es un group by sobre toda la tabla y tarda entre
varios segundos y medio minuto, y se repetía en cada arranque de la aplicación
porque la caché de Streamlit vive en memoria y muere con el proceso.

Aquí se guarda el resultado en `data/cache/`, así que a partir de la segunda vez
la lista aparece de inmediato, incluso después de reiniciar o sin conexión.

Lo guardado caduca a los 30 días: los nombres de entidades y ciudades cambian
poco, pero no son fijos.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "data" / "cache"
DIAS_VIGENCIA = 30


def _ruta(nombre: str) -> Path:
    return CARPETA / f"{nombre}.json"


def _leer_json(ruta: Path) -> dict:
    """Contenido del archivo, o un diccionario vacío si no existe o está roto."""
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # Un archivo de caché dañado no puede tumbar la aplicación: se ignora
        # y en la siguiente consulta se vuelve a escribir.
        logger.warning("Caché ilegible en %s (%s); se ignora.", ruta.name, exc)
        return {}


def _escribir_json(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def _vigente(guardado: str | None, dias: int) -> bool:
    if not guardado:
        return False
    try:
        return datetime.fromisoformat(guardado) > datetime.now() - timedelta(days=dias)
    except ValueError:
        return False


# ------------------------------ valores de una columna ----------------------

def leer_valores(
    tabla: str, columna: str, dias_vigencia: int = DIAS_VIGENCIA
) -> list[str] | None:
    """
    Valores guardados de una columna, o None si no hay o ya caducaron.

    Se devuelve None —y no una lista vacía— para poder distinguir "no hay nada
    guardado" de "se consultó y la columna no tiene valores".
    """
    entrada = _leer_json(_ruta(f"valores_{tabla}")).get(columna)
    if not entrada or not _vigente(entrada.get("guardado"), dias_vigencia):
        return None
    return entrada.get("valores", [])


def guardar_valores(tabla: str, columna: str, valores: list[str]) -> None:
    ruta = _ruta(f"valores_{tabla}")
    datos = _leer_json(ruta)
    datos[columna] = {
        "guardado": datetime.now().isoformat(timespec="seconds"),
        "valores": list(valores),
    }
    _escribir_json(ruta, datos)
    logger.info("Guardados %d valores de '%s' en la caché.", len(valores), columna)


# ------------------------------ columnas de una tabla -----------------------

def leer_columnas(tabla: str, dias_vigencia: int = DIAS_VIGENCIA) -> pd.DataFrame | None:
    """Metadatos de las columnas guardados, o None si no hay o ya caducaron."""
    datos = _leer_json(_ruta(f"columnas_{tabla}"))
    if not datos or not _vigente(datos.get("guardado"), dias_vigencia):
        return None
    return pd.DataFrame(datos.get("columnas", []))


def guardar_columnas(tabla: str, meta: pd.DataFrame) -> None:
    _escribir_json(_ruta(f"columnas_{tabla}"), {
        "guardado": datetime.now().isoformat(timespec="seconds"),
        "columnas": meta.to_dict(orient="records"),
    })
    logger.info("Guardadas %d columnas de '%s' en la caché.", len(meta), tabla)


# ---------------------------------- mantenimiento ---------------------------

def resumen() -> pd.DataFrame:
    """Qué hay guardado y desde cuándo, para poder revisarlo desde la interfaz."""
    filas = []
    for ruta in sorted(CARPETA.glob("valores_*.json")):
        tabla = ruta.stem.replace("valores_", "")
        for columna, entrada in _leer_json(ruta).items():
            filas.append({
                "tabla": tabla,
                "columna": columna,
                "valores": len(entrada.get("valores", [])),
                "guardado": entrada.get("guardado", ""),
            })
    return pd.DataFrame(filas, columns=["tabla", "columna", "valores", "guardado"])


def limpiar(tabla: str | None = None) -> int:
    """Borra lo guardado de una tabla, o todo si no se indica ninguna. Devuelve archivos borrados."""
    patron = f"*_{tabla}.json" if tabla else "*.json"
    borrados = 0
    for ruta in CARPETA.glob(patron):
        try:
            ruta.unlink()
            borrados += 1
        except OSError as exc:
            # Si el archivo está bloqueado, se vacía: el efecto para quien usa
            # la interfaz es el mismo y no se cae la aplicación.
            logger.warning("No se pudo borrar %s (%s); se vacía.", ruta.name, exc)
            _escribir_json(ruta, {})
    logger.info("Caché limpiada: %d archivos borrados.", borrados)
    return borrados
