"""
Orquestador del pipeline: configuración -> extracción -> procesamiento -> CSV.

    python -m src.pipeline --config config/config.yaml

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

import yaml

from src.extraccion import crear_cliente, extraer_dataset
from src.procesamiento import procesar

logger = logging.getLogger("pipeline")

# Se calcula la raíz a partir de la ubicación de este archivo, para que las
# rutas funcionen sin importar desde qué carpeta se lance el comando.
RAIZ = Path(__file__).resolve().parents[1]
DIR_PROCESADO = RAIZ / "data" / "processed"
DIR_LOGS = RAIZ / "logs"


def configurar_logging(nivel: int = logging.INFO) -> Path:
    """
    Manda los mensajes a la consola y a logs/secop2.log.

    El archivo permite revisar después qué pasó en una corrida: qué consulta se
    lanzó, cuántas filas llegaron, qué columnas no se encontraron. Sin él, los
    avisos se pierden al cerrar la terminal, que es justo cuando hacen falta.

    El archivo rota al llegar a 1 MB y se conservan cinco anteriores, para que
    no crezca sin límite.
    """
    raiz_log = logging.getLogger()
    raiz_log.setLevel(nivel)

    # Streamlit vuelve a ejecutar el script en cada interacción; sin esta guarda
    # se acumularían handlers y cada mensaje saldría repetido.
    if any(getattr(h, "_secop2", False) for h in raiz_log.handlers):
        return DIR_LOGS / "secop2.log"

    DIR_LOGS.mkdir(parents=True, exist_ok=True)
    ruta = DIR_LOGS / "secop2.log"

    archivo = logging.handlers.RotatingFileHandler(
        ruta, maxBytes=1_000_000, backupCount=5, encoding="utf-8",
    )
    archivo.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    ))
    archivo._secop2 = True

    consola = logging.StreamHandler()
    consola.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S",
    ))
    consola._secop2 = True

    raiz_log.addHandler(archivo)
    raiz_log.addHandler(consola)
    logger.info("Registro de esta corrida en %s", ruta)
    return ruta


# Comentario que acompaña a cada clave al reescribir el YAML, para que el
# archivo siga siendo legible cuando lo genera la interfaz y no solo una mano.
COMENTARIOS_CONFIG = {
    "app_token": (
        "Token de Socrata. Se deja vacío a propósito: el repositorio es "
        "público.\n# Se puede pasar por la variable de entorno SECOP_APP_TOKEN."
    ),
    "tabla": "contratos | procesos | proveedores | adiciones | integrado",
    "tamano_pagina": "Filas por petición a la API",
    "limite_total": "Tope de filas a descargar. null = todo lo que devuelva el filtro.",
    "filtros": "Filtros de extracción. Bloque vacío ({}) = sin filtrar.",
    "columnas_fecha": "Columnas a convertir a fecha",
    "formato_fecha": (
        "Formato de fecha de la fuente. La API entrega ISO y el CSV del "
        "portal, MM/DD/YYYY;\n# si no coincide, el pipeline lo infiere."
    ),
    "columnas_moneda": 'Montos en formato colombiano ("$13.339.049" -> 13339049.0)',
    "duraciones": "Duraciones en días entre fechas clave del contrato",
}


def cargar_config(ruta: str | Path) -> dict:
    """Lee el YAML de configuración y lo devuelve como diccionario."""
    with open(ruta, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    logger.info("Configuración cargada desde %s", ruta)
    return config


def token_efectivo(config: dict) -> str | None:
    """
    App token a usar: primero el del YAML, si no la variable de entorno.

    Permite trabajar con token sin escribirlo en un archivo versionado.
    """
    return config.get("app_token") or os.getenv("SECOP_APP_TOKEN") or None


def guardar_config(config: dict, ruta: str | Path) -> Path:
    """
    Reescribe el YAML de configuración conservando los comentarios.

    yaml.safe_dump los borraría, así que cada clave se vuelca por separado
    precedida de su comentario. El app_token nunca se escribe: se guarda vacío
    aunque venga con valor, para no filtrarlo al repositorio.
    """
    a_guardar = dict(config)
    a_guardar["app_token"] = ""

    partes = [
        "# Parámetros del pipeline de SECOP 2.",
        "# Lo puede reescribir la interfaz (app.py) o editarse a mano.",
        "",
    ]
    for clave, comentario in COMENTARIOS_CONFIG.items():
        if clave not in a_guardar:
            continue
        partes.append(f"# {comentario}")
        volcado = yaml.safe_dump(
            {clave: a_guardar[clave]}, allow_unicode=True, sort_keys=False,
            default_flow_style=False,
        )
        partes.append(volcado.rstrip())
        partes.append("")

    ruta = Path(ruta)
    ruta.write_text("\n".join(partes), encoding="utf-8")
    logger.info("Configuración guardada en %s", ruta)
    return ruta


def ejecutar(config: dict) -> Path:
    """Ejecuta el pipeline completo con los parámetros dados y guarda el CSV."""
    cliente = crear_cliente(app_token=token_efectivo(config))

    # El try/finally garantiza que la conexión se cierre aunque la descarga
    # falle a mitad de camino.
    try:
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

    # En el YAML las duraciones son una lista de {nombre, desde, hasta};
    # procesar() las espera como {nombre: (desde, hasta)}.
    pares_duraciones = None
    if config.get("duraciones"):
        pares_duraciones = {
            d["nombre"]: (d["desde"], d["hasta"]) for d in config["duraciones"]
        }

    df = procesar(
        df,
        columnas_fecha=config.get("columnas_fecha"),
        columnas_numericas=config.get("columnas_numericas"),
        columnas_moneda=config.get("columnas_moneda"),
        pares_duraciones=pares_duraciones,
        formato_fecha=config.get("formato_fecha"),
    )

    # marca de tiempo en el nombre para no pisar corridas anteriores
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

    configurar_logging()
    config = cargar_config(args.config)
    ejecutar(config)


if __name__ == "__main__":
    main()
