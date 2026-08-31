"""
Limpieza y estandarización de los datos de SECOP 2.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import logging
import re
import unicodedata

import pandas as pd

logger = logging.getLogger(__name__)


def normalizar_nombres_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pasa los nombres a snake_case sin tildes: 'Valor del Contrato' -> 'valor_del_contrato'.

    El portal devuelve los nombres con tildes, mayúsculas y espacios, que no
    sirven para referenciarlos desde la configuración.
    """
    def limpiar(nombre: str) -> str:
        nfkd = unicodedata.normalize("NFKD", nombre)
        sin_tilde = "".join(c for c in nfkd if not unicodedata.combining(c))
        s = sin_tilde.strip().lower()
        s = re.sub(r"[^\w]+", "_", s)
        return s.strip("_")

    df = df.copy()
    df.columns = [limpiar(c) for c in df.columns]
    return df


def convertir_columnas_fecha(
    df: pd.DataFrame,
    columnas: list[str],
    formato: str | None = None,
) -> pd.DataFrame:
    """
    Convierte las columnas indicadas a datetime (errores -> NaT).

    El formato depende de la fuente: la API entrega ISO
    (2025-01-15T00:00:00.000) y el CSV que exporta el portal, MM/DD/YYYY. Si el
    formato indicado deja la columna entera en NaT, se reintenta infiriendo, en
    lugar de devolver una columna vacía sin avisar.
    """
    df = df.copy()
    for col in columnas:
        if col not in df.columns:
            continue

        original = df[col]
        convertida = pd.to_datetime(original, format=formato, errors="coerce")

        if formato and convertida.isna().all() and original.notna().any():
            convertida = pd.to_datetime(original, errors="coerce")
            logger.warning(
                "Columna '%s': el formato '%s' no coincide con los datos; "
                "se infirió el formato.", col, formato,
            )

        df[col] = convertida
        logger.info(
            "Columna '%s' convertida a fecha (%d sin valor de %d)",
            col, int(convertida.isna().sum()), len(convertida),
        )
    return df


def limpiar_columnas_moneda(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    """
    Convierte montos a numérico: "$13.339.049" -> 13339049.0

    El CSV del portal trae el formato colombiano, con símbolo de peso y punto
    de miles; la API entrega el número plano. Quitar los puntos sin mirar
    multiplicaría por 100 un valor con decimales, así que solo se limpia lo que
    no sea ya un número.
    """
    patron_numero = re.compile(r"^-?\d+(\.\d+)?$")

    df = df.copy()
    for col in columnas:
        if col not in df.columns:
            continue

        serie = df[col].astype(str).str.strip()
        ya_numerica = serie.str.match(patron_numero)
        limpia = (
            serie
            .str.replace(r"[$\s]", "", regex=True)   # quitar $ y espacios
            .str.replace(".", "", regex=False)        # quitar separador de miles
            .str.replace(",", ".", regex=False)       # coma decimal -> punto
        )

        df[col] = pd.to_numeric(serie.where(ya_numerica, limpia), errors="coerce")
        logger.info(
            "Columna de moneda '%s' convertida (%d ya venían como número)",
            col, int(ya_numerica.sum()),
        )
    return df


def convertir_columnas_numericas(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    """Convierte las columnas indicadas a numérico (errores -> NaN)."""
    df = df.copy()
    for col in columnas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            logger.info("Columna '%s' convertida a numérico", col)
    return df


def eliminar_duplicados(df: pd.DataFrame, subset: list[str] | None = None) -> pd.DataFrame:
    """Elimina filas duplicadas, opcionalmente según un subconjunto de columnas."""
    antes = len(df)
    df = df.drop_duplicates(subset=subset).reset_index(drop=True)
    logger.info("Duplicados eliminados: %d filas (%d -> %d)", antes - len(df), antes, len(df))
    return df


def calcular_duraciones(
    df: pd.DataFrame,
    pares_fechas: dict[str, tuple[str, str]],
) -> pd.DataFrame:
    """
    Crea variables de duración en días entre pares de fechas del contrato.

    pares_fechas es {nombre_nueva_columna: (fecha_inicial, fecha_final)} y la
    duración se calcula como fecha_final - fecha_inicial. Las columnas de fecha
    tienen que estar ya convertidas a datetime.

    Las duraciones negativas se conservan a propósito: un contrato firmado
    después de su fecha de inicio no es un error de datos, es una señal de
    riesgo que hay que poder contar (VigIA la reporta como red flag).
    """
    df = df.copy()
    for nombre, (col_ini, col_fin) in pares_fechas.items():
        if col_ini in df.columns and col_fin in df.columns:
            df[nombre] = (df[col_fin] - df[col_ini]).dt.days
            logger.info(
                "Duración '%s' = (%s - %s) creada", nombre, col_fin, col_ini
            )
        else:
            faltan = [c for c in (col_ini, col_fin) if c not in df.columns]
            logger.warning(
                "No se pudo crear '%s': faltan columnas %s", nombre, faltan
            )
    return df


def reconciliar_por_llave(
    df: pd.DataFrame,
    llave: str,
    fecha_mas_antigua: list[str] | None = None,
) -> pd.DataFrame:
    """
    Deja un registro por llave, resolviendo los conflictos entre duplicados.

    Un mismo proceso puede aparecer en varias filas con datos distintos. Se
    quitan los duplicados exactos y, en las columnas de fecha listadas en
    fecha_mas_antigua, se conserva el valor mínimo; el resto toma el primer
    valor disponible. Es el tratamiento que VigIA aplica a la tabla de procesos.
    """
    if llave not in df.columns:
        logger.warning("Llave '%s' no está en el DataFrame; se omite.", llave)
        return df

    fecha_mas_antigua = fecha_mas_antigua or []
    antes = len(df)

    df = df.drop_duplicates().reset_index(drop=True)

    agregaciones: dict[str, str] = {}
    for col in df.columns:
        if col == llave:
            continue
        if col in fecha_mas_antigua:
            agregaciones[col] = "min"          # fecha más antigua
        else:
            agregaciones[col] = "first"        # primer valor disponible

    df_reconciliado = df.groupby(llave, as_index=False).agg(agregaciones)
    logger.info(
        "Reconciliación por '%s': %d -> %d filas",
        llave, antes, len(df_reconciliado),
    )
    return df_reconciliado


def unir_tablas(
    izquierda: pd.DataFrame,
    derecha: pd.DataFrame,
    llave_izq: str,
    llave_der: str,
    como: str = "left",
    sufijos: tuple[str, str] = ("", "_der"),
) -> pd.DataFrame:
    """
    Une dos tablas por sus llaves.

    Sirve para llevar al nivel de contrato las variables del proceso (número de
    ofertas, período de publicación), que es la unidad de análisis.
    """
    if llave_izq not in izquierda.columns or llave_der not in derecha.columns:
        logger.warning(
            "No se puede unir: falta llave (%s en izquierda o %s en derecha).",
            llave_izq, llave_der,
        )
        return izquierda

    resultado = izquierda.merge(
        derecha,
        left_on=llave_izq,
        right_on=llave_der,
        how=como,
        suffixes=sufijos,
    )
    logger.info(
        "Unión %s: %d filas resultantes (%d columnas)",
        como, len(resultado), resultado.shape[1],
    )
    return resultado


def procesar(
    df: pd.DataFrame,
    columnas_fecha: list[str] | None = None,
    columnas_numericas: list[str] | None = None,
    columnas_moneda: list[str] | None = None,
    subset_duplicados: list[str] | None = None,
    pares_duraciones: dict[str, tuple[str, str]] | None = None,
    formato_fecha: str | None = None,
) -> pd.DataFrame:
    """
    Encadena los pasos de limpieza en un único punto de entrada.

    Cada paso es opcional: si no se pasan columnas, se salta.
    """
    if df.empty:
        logger.warning("DataFrame vacío: no hay nada que procesar.")
        return df

    df = normalizar_nombres_columnas(df)
    if columnas_fecha:
        df = convertir_columnas_fecha(df, columnas_fecha, formato=formato_fecha)
    if columnas_moneda:
        df = limpiar_columnas_moneda(df, columnas_moneda)
    if columnas_numericas:
        df = convertir_columnas_numericas(df, columnas_numericas)
    if pares_duraciones:
        df = calcular_duraciones(df, pares_duraciones)
    df = eliminar_duplicados(df, subset=subset_duplicados)

    logger.info("Procesamiento finalizado: %d filas, %d columnas", len(df), df.shape[1])
    return df
