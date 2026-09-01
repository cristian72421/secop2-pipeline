"""
Interfaz para configurar y ejecutar la extracción de SECOP 2.

    streamlit run app.py

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# _construir_where es privada, pero mostrar la consulta SoQL generada antes de
# lanzarla ahorra mucho tiempo cuando un filtro no devuelve nada.
from src.extraccion import (
    DATASETS,
    _construir_where,
    crear_cliente,
    extraer_dataset,
    listar_columnas,
    valores_distintos,
)
from src.pipeline import configurar_logging, guardar_config
from src.procesamiento import procesar

RAIZ = Path(__file__).resolve().parent
RUTA_CONFIG = RAIZ / "config" / "config.yaml"

st.set_page_config(page_title="Pipeline SECOP 2", page_icon="📄", layout="wide")

# Deja constancia en logs/secop2.log de lo que hace cada corrida, para poder
# revisar después por qué una extracción salió como salió.
configurar_logging()
logger = logging.getLogger("app")


def cargar_defaults() -> dict:
    """Valores iniciales del formulario, tomados del YAML si existe."""
    if RUTA_CONFIG.exists():
        with open(RUTA_CONFIG, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def lista_a_texto(valores) -> str:
    return "\n".join(valores or [])


def texto_a_lista(texto: str) -> list[str]:
    return [linea.strip() for linea in texto.splitlines() if linea.strip()]


cfg = cargar_defaults()

if "resultado" not in st.session_state:
    st.session_state.resultado = None

st.title("Pipeline SECOP 2")
st.caption(
    "Extracción parametrizada desde datos.gov.co (Socrata). "
    "Los valores iniciales vienen de config/config.yaml."
)

# ----------------------------- Fuente y límites -----------------------------
with st.sidebar:
    st.header("Fuente")
    tablas = list(DATASETS)
    tabla = st.selectbox(
        "Tabla",
        tablas,
        index=tablas.index(cfg.get("tabla", "contratos")) if cfg.get("tabla") in tablas else 0,
    )
    st.caption(f"Dataset id: `{DATASETS[tabla]}`")

    st.header("Límites")
    sin_tope = st.checkbox("Descargar todo (sin tope)", value=cfg.get("limite_total") is None)
    limite_total = None
    if not sin_tope:
        limite_total = st.number_input(
            "Máximo de filas", min_value=1, max_value=5_000_000,
            value=int(cfg.get("limite_total") or 5000), step=1000,
        )
    tamano_pagina = st.number_input(
        "Filas por petición", min_value=1000, max_value=50_000,
        value=int(cfg.get("tamano_pagina", 50_000)), step=1000,
    )
    app_token = st.text_input(
        "App token de Socrata", value=cfg.get("app_token", ""), type="password",
        help="Opcional. Sin token la API aplica límites más bajos.",
    )

# --------------------------------- Filtros ----------------------------------
@st.cache_data(show_spinner="Leyendo columnas del dataset ...")
def columnas_de(tabla: str) -> pd.DataFrame:
    return listar_columnas(tabla)


@st.cache_data(show_spinner="Consultando valores ...")
def valores_de(tabla: str, columna: str, token: str) -> list[str]:
    cliente = crear_cliente(app_token=token or None)
    try:
        df = valores_distintos(cliente, tabla, columna)
    finally:
        cliente.close()
    if df.empty or "valor" not in df.columns:
        return []
    return df["valor"].dropna().astype(str).tolist()


st.subheader("Filtros")

try:
    meta = columnas_de(tabla)
except Exception as exc:
    meta = pd.DataFrame(columns=["campo", "nombre", "tipo", "ejemplos"])
    st.error(f"No se pudieron leer las columnas del dataset: {exc}")

campos = meta["campo"].tolist()
ejemplos_por_campo = dict(zip(meta["campo"], meta["ejemplos"])) if not meta.empty else {}

with st.expander(f"Ver las {len(campos)} columnas del dataset"):
    st.caption(
        "`campo` es el nombre que entiende la API; `nombre` es el que se ve en "
        "el portal. Los filtros usan el primero."
    )
    if not meta.empty:
        st.dataframe(meta.assign(ejemplos=meta["ejemplos"].str.join(" · ")))

consultar_api = st.checkbox(
    "Consultar los valores reales de todas las columnas",
    help=(
        "Por defecto las opciones salen de los valores que el portal tiene en "
        "caché, que no cubren todas las columnas. Marcado, se consulta la lista "
        "completa de cada columna elegida: es exacto pero lento. Para una sola "
        "columna conviene más el botón 'Cargar valores' que aparece debajo."
    ),
)

filtros_cfg = cfg.get("filtros") or {}
if "filas_filtro" not in st.session_state:
    st.session_state.filas_filtro = [
        {"columna": k, "valor": str(v)}
        for k, v in filtros_cfg.items()
        if not isinstance(v, dict)
    ] or [{"columna": "", "valor": ""}]

if "cols_consultadas" not in st.session_state:
    st.session_state.cols_consultadas = set()

SIN_FILTRO = "— sin filtro —"
A_MANO = "— escribir a mano —"

quitar = None
for i, fila in enumerate(st.session_state.filas_filtro):
    c1, c2, c3 = st.columns([3, 3, 0.5])
    visible = "visible" if i == 0 else "collapsed"

    opciones_col = [SIN_FILTRO] + campos
    idx = opciones_col.index(fila["columna"]) if fila["columna"] in opciones_col else 0
    columna = c1.selectbox("Columna", opciones_col, index=idx,
                           key=f"f_col_{i}", label_visibility=visible)

    valor = ""
    if columna != SIN_FILTRO:
        cacheados = ejemplos_por_campo.get(columna, [])
        consultar_esta = consultar_api or columna in st.session_state.cols_consultadas

        opciones_val = cacheados
        if consultar_esta:
            try:
                opciones_val = valores_de(tabla, columna, app_token)
            except Exception as exc:
                opciones_val = cacheados
                c2.warning(f"No se pudieron consultar los valores: {exc}")

        lista = [A_MANO] + opciones_val
        idx_v = lista.index(fila["valor"]) if fila["valor"] in lista else 0
        elegido = c2.selectbox("Valor", lista, index=idx_v,
                               key=f"f_val_{i}", label_visibility=visible)
        if elegido == A_MANO:
            valor = c2.text_input("Valor exacto", value=fila["valor"],
                                  key=f"f_txt_{i}", label_visibility="collapsed",
                                  placeholder="Escribe el valor tal cual aparece")
        else:
            valor = elegido

        # El portal solo cachea valores para algunas columnas; en las tablas
        # grandes casi ninguna los trae. Ahí se consultan a pedido, por columna,
        # en vez de obligar a activar la consulta para todas.
        if not opciones_val and not consultar_esta:
            c2.caption("Sin valores en caché para esta columna.")
            if c2.button("Cargar valores", key=f"f_load_{i}"):
                st.session_state.cols_consultadas.add(columna)
                st.rerun()

    st.session_state.filas_filtro[i] = {"columna": columna, "valor": valor}
    if i == 0:
        c3.write("")
    if c3.button("✕", key=f"f_del_{i}", help="Quitar esta fila"):
        quitar = i

if quitar is not None and len(st.session_state.filas_filtro) > 1:
    st.session_state.filas_filtro.pop(quitar)
    st.rerun()

if st.button("+ Agregar filtro"):
    st.session_state.filas_filtro.append({"columna": "", "valor": ""})
    st.rerun()

# Rango de fechas: aparte, porque genera >= y <= en vez de igualdad.
campos_fecha = (
    meta.loc[meta["tipo"].isin(["calendar_date", "floating_timestamp", "date"]), "campo"].tolist()
    if not meta.empty else []
) or campos

rango_cfg = next(
    ((k, v) for k, v in filtros_cfg.items() if isinstance(v, dict)), (None, {})
)
col_a, col_b, col_c = st.columns([2, 1, 1])
with col_a:
    usar_rango = st.checkbox("Filtrar por rango de fechas", value=rango_cfg[0] is not None)
    idx_f = campos_fecha.index(rango_cfg[0]) if rango_cfg[0] in campos_fecha else 0
    col_fecha = st.selectbox(
        "Columna de fecha", campos_fecha or ["fecha_de_firma"],
        index=idx_f, disabled=not usar_rango,
    )
with col_b:
    desde = st.text_input("Desde (AAAA-MM-DD)", value=(rango_cfg[1] or {}).get("desde", ""),
                          disabled=not usar_rango)
with col_c:
    hasta = st.text_input("Hasta (AAAA-MM-DD)", value=(rango_cfg[1] or {}).get("hasta", ""),
                          disabled=not usar_rango)

# ------------------------------ Procesamiento -------------------------------
with st.expander("Procesamiento (columnas a limpiar)"):
    st.caption(
        "Estos valores están escritos para la tabla de contratos. Al cambiar de "
        "tabla hay que revisarlos: las columnas que no existan se ignoran."
    )
    c1, c2 = st.columns(2)
    with c1:
        txt_fechas = st.text_area(
            "Columnas de fecha", lista_a_texto(cfg.get("columnas_fecha")), height=110
        )
    with c2:
        txt_moneda = st.text_area(
            "Columnas de moneda", lista_a_texto(cfg.get("columnas_moneda")), height=110
        )
        formato_fecha = st.text_input(
            "Formato de fecha", value=cfg.get("formato_fecha", "%m/%d/%Y"),
            help="La API entrega ISO; el CSV del portal, MM/DD/YYYY. Si no coincide se infiere.",
        )

# --------------------------- Consulta y ejecución ---------------------------
filtros: dict = {}
for fila in st.session_state.filas_filtro:
    col, val = fila["columna"], str(fila["valor"]).strip()
    if col and col != SIN_FILTRO and val:
        filtros[col] = val
if usar_rango and col_fecha and (desde or hasta):
    rango = {}
    if desde:
        rango["desde"] = desde
    if hasta:
        rango["hasta"] = hasta
    filtros[col_fecha] = rango

where = _construir_where(filtros)
st.markdown("**Consulta que se va a enviar**")
st.code(f"SELECT * FROM {DATASETS[tabla]}" + (f"\nWHERE {where}" if where else ""), language="sql")

if st.button("Extraer", type="primary"):
    barra = st.progress(0.0, text="Conectando con datos.gov.co ...")
    try:
        cliente = crear_cliente(app_token=app_token or None)
        try:
            barra.progress(0.3, text="Descargando ...")
            df = extraer_dataset(
                cliente, tabla=tabla, filtros=filtros or None,
                tamano_pagina=int(tamano_pagina), limite_total=limite_total,
            )
        finally:
            cliente.close()

        if df.empty:
            barra.empty()
            st.warning(
                "La consulta no devolvió filas: la combinación de filtros no "
                "existe en el dataset. Marca 'Consultar los valores reales en "
                "la API' para ver qué valores tiene realmente cada columna."
            )
            st.session_state.resultado = None
        else:
            barra.progress(0.7, text="Procesando ...")
            duraciones = {
                d["nombre"]: (d["desde"], d["hasta"]) for d in (cfg.get("duraciones") or [])
            }
            crudo_cols = set(df.columns)
            limpio = procesar(
                df,
                columnas_fecha=texto_a_lista(txt_fechas),
                columnas_moneda=texto_a_lista(txt_moneda),
                pares_duraciones=duraciones or None,
                formato_fecha=formato_fecha or None,
            )
            barra.empty()
            st.session_state.resultado = {
                "df": limpio, "filas_crudas": len(df), "tabla": tabla,
                "cols_crudas": crudo_cols,
            }
    except Exception as exc:
        barra.empty()
        logger.exception("Falló la extracción")
        st.error(f"Falló la extracción: {exc}")
        st.session_state.resultado = None

# --------------------------------- Resultado --------------------------------
res = st.session_state.resultado
if res:
    df = res["df"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Filas descargadas", f"{res['filas_crudas']:,}")
    m2.metric("Filas tras limpieza", f"{len(df):,}")
    m3.metric("Columnas", df.shape[1])

    # Avisar de columnas configuradas que la tabla no trae: procesar() las
    # ignora en silencio y es la causa más común de un resultado sin limpiar.
    esperadas = set(texto_a_lista(txt_fechas) + texto_a_lista(txt_moneda))
    faltantes = sorted(c for c in esperadas if c not in df.columns)
    if faltantes:
        st.warning(
            "Estas columnas no existen en la tabla y se ignoraron: "
            + ", ".join(f"`{c}`" for c in faltantes)
        )

    st.dataframe(df.head(200))
    st.caption(f"Vista previa de las primeras 200 filas de {len(df):,}.")

    st.download_button(
        "Descargar CSV",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"secop2_{res['tabla']}.csv",
        mime="text/csv",
    )

# --------------------------- Exportar la selección --------------------------
with st.expander("Guardar esta configuración"):
    st.caption(
        "El YAML equivalente a lo seleccionado arriba. Se puede escribir sobre "
        "config/config.yaml o descargar aparte."
    )
    cfg_actual = {
        "app_token": app_token,
        "tabla": tabla,
        "tamano_pagina": int(tamano_pagina),
        "limite_total": None if sin_tope else int(limite_total),
        "filtros": filtros,
        "columnas_fecha": texto_a_lista(txt_fechas),
        "formato_fecha": formato_fecha,
        "columnas_moneda": texto_a_lista(txt_moneda),
        "duraciones": cfg.get("duraciones") or [],
    }
    yaml_texto = yaml.safe_dump(cfg_actual, allow_unicode=True, sort_keys=False)
    st.code(yaml_texto, language="yaml")

    b1, b2 = st.columns(2)
    if b1.button("Guardar en config/config.yaml", type="primary"):
        try:
            guardar_config(cfg_actual, RUTA_CONFIG)
            st.success(
                "Guardado en config/config.yaml. El archivo está versionado: "
                "`git diff` muestra el cambio y `git checkout` lo revierte."
            )
        except Exception as exc:
            logger.exception("No se pudo guardar la configuración")
            st.error(f"No se pudo guardar: {exc}")

    b2.download_button("Descargar aparte", data=yaml_texto.encode("utf-8"),
                       file_name="config.yaml", mime="text/yaml")

    if app_token:
        st.info(
            "El app token no se escribe en el archivo: el repositorio es "
            "público. Para usarlo sin pegarlo cada vez, defínelo como variable "
            "de entorno `SECOP_APP_TOKEN` antes de lanzar la app."
        )
