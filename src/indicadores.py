"""
Indicadores descriptivos de riesgo sobre la base de contratos.

Las funciones son puras: reciben un DataFrame ya procesado y devuelven otro,
sin tocar la red ni el disco. Así sirven igual desde la interfaz, desde un
notebook o desde un script del reporte.

Los indicadores siguen los red flags de VigIA (Salazar, Pérez y Gallego, 2024).
Ninguno es evidencia de irregularidad por sí solo: varios de ellos son el
comportamiento esperado en ciertas modalidades de contratación, y por eso casi
todos se presentan desagregados por modalidad.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Nombres por defecto, correspondientes a SECOP II - Contratos Electrónicos
# unido con Procesos de Contratación.
COLUMNAS = {
    "modalidad": "modalidad_de_contratacion",
    "tipo": "tipo_de_contrato",
    "valor": "valor_del_contrato",
    "firma_a_inicio": "dias_firma_a_inicio",
    "dias_adicionados": "dias_adicionados",
    "proveedor": "proveedor_adjudicado",
    "ofertas": "respuestas_al_procedimiento",
    "firma": "fecha_de_firma",
    "inicio": "fecha_de_inicio_del_contrato",
    "fin": "fecha_de_fin_del_contrato",
}

TRAMOS_FIRMA = [
    ("Firmado tras iniciar", -np.inf, -0.5),
    ("Mismo día", -0.5, 0.5),
    ("1 a 7 días", 0.5, 7),
    ("8 a 30 días", 7, 30),
    ("Más de 30 días", 30, np.inf),
]


def _col(df: pd.DataFrame, clave: str, columnas: dict | None = None) -> str | None:
    """Nombre real de una columna, o None si la tabla no la trae."""
    nombre = (columnas or COLUMNAS).get(clave)
    return nombre if nombre in df.columns else None


def _num(df: pd.DataFrame, columna: str | None) -> pd.Series:
    """Serie numérica, o una serie vacía si la columna no está."""
    if columna is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[columna], errors="coerce")


def resumen(df: pd.DataFrame, columnas: dict | None = None) -> dict:
    """
    Cifras de cabecera de la entidad y periodo cargados.

    Las claves cuyo dato no esté disponible salen en None, para que quien las
    muestre pueda omitirlas en vez de inventar un cero.
    """
    valores = _num(df, _col(df, "valor", columnas))
    firma = _num(df, _col(df, "firma_a_inicio", columnas))
    adicionados = _num(df, _col(df, "dias_adicionados", columnas))
    col_modalidad = _col(df, "modalidad", columnas)

    directa = None
    if col_modalidad:
        es_directa = df[col_modalidad].astype(str).str.lower().str.contains("directa")
        directa = 100 * es_directa.mean()

    return {
        "contratos": len(df),
        "valor_total": valores.sum() if not valores.empty else None,
        "valor_mediano": valores.median() if not valores.empty else None,
        "pct_directa": directa,
        "pct_con_prorroga": 100 * (adicionados > 0).mean() if not adicionados.empty else None,
        "pct_firma_tardia": 100 * (firma < 0).mean() if not firma.empty else None,
    }


def por_modalidad(df: pd.DataFrame, columnas: dict | None = None) -> pd.DataFrame:
    """
    Contratos y valor por modalidad de contratación.

    Se miran juntos a propósito: una modalidad puede dominar en número de
    contratos y ser marginal en dinero, o al revés, y esa diferencia suele ser
    la mitad de la lectura.
    """
    col_mod = _col(df, "modalidad", columnas)
    if col_mod is None:
        return pd.DataFrame()

    valores = _num(df, _col(df, "valor", columnas))
    tabla = pd.DataFrame({"modalidad": df[col_mod].fillna("Sin dato"), "valor": valores})
    agrupado = tabla.groupby("modalidad").agg(
        contratos=("valor", "size"), valor=("valor", "sum"),
    )
    return agrupado.sort_values("contratos", ascending=False)


def distribucion_firma_a_inicio(df: pd.DataFrame, columnas: dict | None = None) -> pd.DataFrame:
    """
    Contratos por tramo de días entre la firma y el inicio.

    Devuelve dos columnas para que el tramo negativo —el contrato firmado
    después de haber empezado— se pueda pintar aparte: es el red flag, no un
    tramo más de la distribución.
    """
    dias = _num(df, _col(df, "firma_a_inicio", columnas)).dropna()
    if dias.empty:
        return pd.DataFrame()

    filas = {}
    for etiqueta, desde, hasta in TRAMOS_FIRMA:
        n = int(((dias > desde) & (dias <= hasta)).sum())
        alerta = etiqueta == "Firmado tras iniciar"
        filas[etiqueta] = {
            "Firmado tras iniciar": n if alerta else 0,
            "En regla": 0 if alerta else n,
        }
    return pd.DataFrame(filas).T


def ofertas_por_modalidad(df: pd.DataFrame, columnas: dict | None = None) -> pd.DataFrame:
    """
    Cuántas ofertas recibió cada modalidad.

    Es la tabla que evita el falso positivo más común: cero ofertas es lo
    normal en contratación directa, donde no hay convocatoria, y anómalo en una
    licitación pública.
    """
    col_mod = _col(df, "modalidad", columnas)
    ofertas = _num(df, _col(df, "ofertas", columnas))
    if col_mod is None or ofertas.empty:
        return pd.DataFrame()

    tramos = pd.cut(
        ofertas, bins=[-np.inf, 0, 1, np.inf],
        labels=["Sin ofertas", "Una oferta", "Dos o más"],
    )
    cruce = pd.crosstab(df[col_mod].fillna("Sin dato"), tramos)
    cruce["Total"] = cruce.sum(axis=1)
    return cruce.sort_values("Total", ascending=False)


def concentracion_proveedores(
    df: pd.DataFrame, n: int = 10, columnas: dict | None = None,
) -> dict:
    """
    Qué parte de la contratación se lleva un puñado de proveedores.

    Se calcula en número de contratos y en dinero, porque no coinciden: un
    proveedor con un solo contrato enorme no aparece contando contratos.
    """
    col_prov = _col(df, "proveedor", columnas)
    if col_prov is None:
        return {}

    valores = _num(df, _col(df, "valor", columnas))
    tabla = pd.DataFrame({"proveedor": df[col_prov].fillna("Sin dato"), "valor": valores})
    por_proveedor = tabla.groupby("proveedor").agg(
        contratos=("valor", "size"), valor=("valor", "sum"),
    ).sort_values("valor", ascending=False)

    total_valor = por_proveedor["valor"].sum()
    top = por_proveedor.head(n)
    return {
        "proveedores": len(por_proveedor),
        "pct_contratos": 100 * top["contratos"].sum() / len(df) if len(df) else None,
        "pct_valor": 100 * top["valor"].sum() / total_valor if total_valor else None,
        "tabla": top,
    }


def distribucion_valores(df: pd.DataFrame, columnas: dict | None = None) -> pd.DataFrame:
    """
    Contratos por orden de magnitud del valor.

    En escala lineal un contrato de miles de millones aplasta a los demás; por
    tramos logarítmicos se ve la forma real de la distribución y dónde están
    los casos extremos.
    """
    valores = _num(df, _col(df, "valor", columnas)).dropna()
    valores = valores[valores > 0]
    if valores.empty:
        return pd.DataFrame()

    bordes = [0, 1e6, 1e7, 1e8, 1e9, 1e10, 1e11, np.inf]
    etiquetas = ["menos de 1M", "1M – 10M", "10M – 100M", "100M – 1.000M",
                 "1.000M – 10.000M", "10.000M – 100.000M", "más de 100.000M"]
    tramos = pd.cut(valores, bins=bordes, labels=etiquetas, right=False)
    conteo = tramos.value_counts().sort_index()
    return conteo[conteo > 0].to_frame("contratos")


def calidad_datos(df: pd.DataFrame, columnas: dict | None = None) -> pd.DataFrame:
    """
    Revisiones de consistencia sobre los datos cargados.

    No corrigen nada: señalan los registros que conviene mirar antes de
    calcular estadísticas, porque un solo valor mal digitado en la fuente
    distorsiona cualquier promedio.
    """
    revisiones = []

    firma = _num(df, _col(df, "firma_a_inicio", columnas))
    if not firma.empty:
        revisiones.append(("Firma posterior al inicio del contrato", int((firma < 0).sum())))
        revisiones.append(("Sin fecha de inicio o de firma", int(firma.isna().sum())))

    col_inicio, col_fin = _col(df, "inicio", columnas), _col(df, "fin", columnas)
    if col_inicio and col_fin:
        inicio = pd.to_datetime(df[col_inicio], errors="coerce")
        fin = pd.to_datetime(df[col_fin], errors="coerce")
        revisiones.append(("Fecha de fin anterior al inicio", int((fin < inicio).sum())))

    valores = _num(df, _col(df, "valor", columnas))
    if not valores.empty:
        revisiones.append(("Valor cero o vacío", int((valores.fillna(0) <= 0).sum())))
        mediana = valores.median()
        if mediana and mediana > 0:
            extremos = valores > mediana * 1000
            revisiones.append(
                (f"Valor más de 1.000 veces la mediana (${mediana:,.0f})".replace(",", "."),
                 int(extremos.sum()))
            )

    tabla = pd.DataFrame(revisiones, columns=["revisión", "casos"])
    return tabla[tabla["casos"] > 0].reset_index(drop=True)


def agrupar_modalidades(df: pd.DataFrame, n: int = 4, columnas: dict | None = None) -> pd.Series:
    """
    Deja las n modalidades más frecuentes y agrupa el resto en "Otras".

    Una paleta tiene un número fijo de colores; la categoría n+1 no recibe un
    color nuevo, se dobla en "Otras".
    """
    col_mod = _col(df, "modalidad", columnas)
    if col_mod is None:
        return pd.Series(dtype=object)

    serie = df[col_mod].fillna("Sin dato")
    principales = serie.value_counts().head(n).index
    return serie.where(serie.isin(principales), "Otras")


def curva_concentracion(df: pd.DataFrame, columnas: dict | None = None) -> pd.DataFrame:
    """
    Curva de Lorenz de la contratación: qué porcentaje del valor acumulan los
    proveedores, ordenados de mayor a menor.

    La diagonal sería el reparto perfectamente equitativo; cuanto más se separe
    la curva de ella, más concentrada está la contratación.
    """
    col_prov = _col(df, "proveedor", columnas)
    valores = _num(df, _col(df, "valor", columnas))
    if col_prov is None or valores.empty:
        return pd.DataFrame()

    por_proveedor = (
        pd.DataFrame({"proveedor": df[col_prov].fillna("Sin dato"), "valor": valores})
        .groupby("proveedor")["valor"].sum()
        .sort_values(ascending=False)
    )
    total = por_proveedor.sum()
    if not total:
        return pd.DataFrame()

    acumulado = por_proveedor.cumsum() / total * 100
    proveedores = np.arange(1, len(por_proveedor) + 1) / len(por_proveedor) * 100
    return pd.DataFrame({
        "pct_proveedores": np.concatenate([[0], proveedores]),
        "pct_valor": np.concatenate([[0], acumulado.to_numpy()]),
    })


def contratos_por_mes_modalidad(
    df: pd.DataFrame, n: int = 4, columnas: dict | None = None,
) -> pd.DataFrame:
    """Contratos por mes, desagregados por modalidad."""
    col_firma = _col(df, "firma", columnas)
    if col_firma is None:
        return pd.DataFrame()

    fechas = pd.to_datetime(df[col_firma], errors="coerce")
    modalidades = agrupar_modalidades(df, n=n, columnas=columnas)
    if modalidades.empty:
        return pd.DataFrame()

    tabla = pd.DataFrame({"mes": fechas.dt.to_period("M").astype(str),
                          "modalidad": modalidades}).dropna(subset=["mes"])
    return tabla.groupby(["mes", "modalidad"]).size().reset_index(name="contratos")


def valores_por_modalidad(
    df: pd.DataFrame, n: int = 4, columnas: dict | None = None,
) -> pd.DataFrame:
    """Valor de cada contrato con su modalidad, para ver la dispersión."""
    valores = _num(df, _col(df, "valor", columnas))
    modalidades = agrupar_modalidades(df, n=n, columnas=columnas)
    if valores.empty or modalidades.empty:
        return pd.DataFrame()

    tabla = pd.DataFrame({"valor": valores, "modalidad": modalidades})
    return tabla[tabla["valor"] > 0].dropna()


def dias_firma_a_inicio(df: pd.DataFrame, columnas: dict | None = None) -> pd.DataFrame:
    """Días entre firma e inicio, marcados según sean negativos o no."""
    dias = _num(df, _col(df, "firma_a_inicio", columnas)).dropna()
    if dias.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "dias": dias,
        "estado": np.where(dias < 0, "Firmado tras iniciar", "En regla"),
    })
