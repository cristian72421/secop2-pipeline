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

# _construir_where es privada, pero mostrar la consulta SoQL antes de lanzarla
# ahorra mucho tiempo cuando un filtro no devuelve nada.
from src.extraccion import (
    DATASETS,
    _construir_where,
    crear_cliente,
    extraer_dataset,
    listar_columnas,
    valores_distintos,
)
from src.flujo_vigia import construir_base_contratos
from src.pipeline import configurar_logging, guardar_config
from src.procesamiento import procesar

RAIZ = Path(__file__).resolve().parent
RUTA_CONFIG = RAIZ / "config" / "config.yaml"

SIN_FILTRO = "— sin filtro —"
OTRO_VALOR = "— otro valor —"

st.set_page_config(page_title="Pipeline SECOP 2", page_icon="📄", layout="wide")

# Deja constancia en logs/secop2.log de lo que hace cada corrida.
configurar_logging()
logger = logging.getLogger("app")

st.markdown(
    """
    <style>
      div.block-container {padding-top: 2.5rem; max-width: 1200px;}
      div[data-testid="stMetric"] {
          border: 1px solid rgba(128,128,128,.25);
          border-radius: .6rem; padding: .8rem 1rem;
      }
      div[data-testid="stMetricValue"] {font-size: 1.6rem;}
      section[data-testid="stSidebar"] h2 {font-size: 1rem; letter-spacing: .04em;}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------- Ayudas -----------------------------------
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


@st.cache_data(show_spinner="Leyendo las columnas del dataset ...")
def columnas_de(tabla: str) -> pd.DataFrame:
    return listar_columnas(tabla)


@st.cache_data(show_spinner="Consultando los valores ...")
def valores_de(tabla: str, columna: str, token: str) -> list[str]:
    cliente = crear_cliente(app_token=token or None)
    try:
        df = valores_distintos(cliente, tabla, columna)
    finally:
        cliente.close()
    if df.empty or "valor" not in df.columns:
        return []
    return df["valor"].dropna().astype(str).tolist()


def selector_de_valor(contenedor, opciones: list[str], actual: str, clave: str, etiqueta_visible: bool):
    """
    Desplegable de valores que además acepta texto escrito a mano.

    Las versiones recientes de Streamlit lo hacen en un solo control; en las
    anteriores se cae a un desplegable con una opción para escribir.
    """
    etiqueta = "Valor" if etiqueta_visible else " "
    visibilidad = "visible" if etiqueta_visible else "collapsed"
    try:
        return contenedor.selectbox(
            etiqueta, opciones, key=clave, label_visibility=visibilidad,
            index=opciones.index(actual) if actual in opciones else None,
            accept_new_options=True, placeholder="Elige o escribe el valor",
        ) or ""
    except TypeError:  # Streamlit anterior a la opción de texto libre
        lista = [OTRO_VALOR] + opciones
        elegido = contenedor.selectbox(
            etiqueta, lista, key=clave, label_visibility=visibilidad,
            index=lista.index(actual) if actual in lista else 0,
        )
        if elegido != OTRO_VALOR:
            return elegido
        return contenedor.text_input(
            " ", value=actual, key=f"{clave}_txt", label_visibility="collapsed",
            placeholder="Escribe el valor tal cual aparece",
        )


cfg = cargar_defaults()
st.session_state.setdefault("resultado", None)
st.session_state.setdefault("cols_consultadas", set())


# --------------------------------- Cabecera ---------------------------------
st.title("Pipeline SECOP 2")
st.caption(
    "Extracción y limpieza de datos de contratación pública desde "
    "datos.gov.co. Los valores iniciales vienen de `config/config.yaml`."
)

with st.sidebar:
    st.header("FUENTE")
    modo = st.radio(
        "Qué construir",
        ["Una tabla", "Contratos + procesos"],
        captions=[
            "Extrae y limpia una sola tabla.",
            "Une contratos con sus procesos: agrega ofertas, precio base y "
            "fecha de publicación.",
        ],
    )
    vigia = modo == "Contratos + procesos"

    tablas = list(DATASETS)
    if vigia:
        tabla = "contratos"
        st.info("En este modo la tabla es **contratos**, unida con **procesos**.")
    else:
        tabla = st.selectbox(
            "Tabla", tablas,
            index=tablas.index(cfg.get("tabla", "contratos"))
            if cfg.get("tabla") in tablas else 0,
        )
    st.caption(f"Dataset: `{DATASETS[tabla]}`")

    st.header("ALCANCE")
    sin_tope = st.toggle("Traer todo", value=cfg.get("limite_total") is None,
                         help="Sin tope de filas. Puede tardar bastante.")
    limite_total = None
    if not sin_tope:
        limite_total = st.number_input(
            "Máximo de filas", min_value=1, max_value=5_000_000,
            value=int(cfg.get("limite_total") or 5000), step=1000,
        )
    app_token = st.text_input(
        "App token de Socrata", value=cfg.get("app_token", ""), type="password",
        help="Opcional. Sin token la API aplica límites más estrictos.",
    )
    with st.expander("Opciones avanzadas"):
        tamano_pagina = st.number_input(
            "Filas por petición", min_value=1000, max_value=50_000,
            value=int(cfg.get("tamano_pagina", 50_000)), step=1000,
        )
        margen_meses = st.number_input(
            "Meses de margen para procesos", min_value=0, max_value=36,
            value=int(cfg.get("margen_meses_procesos", 6)),
            help="El proceso siempre precede al contrato, así que su ventana "
                 "empieza antes.", disabled=not vigia,
        )


# --------------------------------- Filtros ----------------------------------
st.subheader("1. Qué filas traer")

try:
    meta = columnas_de(tabla)
except Exception as exc:
    meta = pd.DataFrame(columns=["campo", "nombre", "tipo", "ejemplos"])
    st.error(f"No se pudieron leer las columnas del dataset: {exc}")

campos = meta["campo"].tolist()
ejemplos_por_campo = dict(zip(meta["campo"], meta["ejemplos"])) if not meta.empty else {}

filtros_cfg = cfg.get("filtros") or {}
if "filas_filtro" not in st.session_state:
    st.session_state.filas_filtro = [
        {"columna": k, "valor": str(v)}
        for k, v in filtros_cfg.items() if not isinstance(v, dict)
    ] or [{"columna": "", "valor": ""}]

quitar = None
for i, fila in enumerate(st.session_state.filas_filtro):
    c1, c2, c3 = st.columns([3, 3, 0.5], vertical_alignment="bottom")
    primera = i == 0

    opciones_col = [SIN_FILTRO] + campos
    columna = c1.selectbox(
        "Columna", opciones_col, key=f"f_col_{i}",
        index=opciones_col.index(fila["columna"]) if fila["columna"] in opciones_col else 0,
        label_visibility="visible" if primera else "collapsed",
    )

    valor = ""
    if columna != SIN_FILTRO:
        cacheados = ejemplos_por_campo.get(columna, [])
        consultar = columna in st.session_state.cols_consultadas
        opciones_val = cacheados
        if consultar:
            try:
                opciones_val = valores_de(tabla, columna, app_token)
            except Exception as exc:
                opciones_val = cacheados
                c2.warning(f"No se pudieron consultar los valores: {exc}")

        valor = selector_de_valor(c2, opciones_val, fila["valor"], f"f_val_{i}", primera)

        if not opciones_val and not consultar:
            if c2.button("Ver valores posibles", key=f"f_load_{i}",
                         help="Consulta a la API qué valores tiene esta columna."):
                st.session_state.cols_consultadas.add(columna)
                st.rerun()

    st.session_state.filas_filtro[i] = {"columna": columna, "valor": valor}
    if c3.button("✕", key=f"f_del_{i}", help="Quitar"):
        quitar = i

if quitar is not None and len(st.session_state.filas_filtro) > 1:
    st.session_state.filas_filtro.pop(quitar)
    st.rerun()

if st.button("Agregar filtro", icon=":material/add:"):
    st.session_state.filas_filtro.append({"columna": "", "valor": ""})
    st.rerun()

# Rango de fechas: aparte, porque genera >= y <= en vez de igualdad.
campos_fecha = (
    meta.loc[meta["tipo"].isin(["calendar_date", "floating_timestamp", "date"]), "campo"].tolist()
    if not meta.empty else []
) or campos

rango_cfg = next(((k, v) for k, v in filtros_cfg.items() if isinstance(v, dict)), (None, {}))
st.write("")
usar_rango = st.toggle("Acotar por rango de fechas", value=rango_cfg[0] is not None)
if usar_rango:
    f1, f2, f3 = st.columns(3)
    col_fecha = f1.selectbox(
        "Columna de fecha", campos_fecha or ["fecha_de_firma"],
        index=campos_fecha.index(rango_cfg[0]) if rango_cfg[0] in campos_fecha else 0,
    )
    desde = f2.text_input("Desde", value=(rango_cfg[1] or {}).get("desde", ""),
                          placeholder="2025-01-01")
    hasta = f3.text_input("Hasta", value=(rango_cfg[1] or {}).get("hasta", ""),
                          placeholder="2025-12-31")
else:
    col_fecha, desde, hasta = "", "", ""

with st.expander(f"Ver las {len(campos)} columnas de esta tabla"):
    st.caption(
        "`campo` es el nombre que entiende la API; `nombre` es el que se ve en "
        "el portal. Los filtros usan el primero."
    )
    if not meta.empty:
        st.dataframe(meta.assign(ejemplos=meta["ejemplos"].str.join(" · ")),
                     hide_index=True)

# ------------------------------ Procesamiento -------------------------------
st.subheader("2. Cómo limpiar")
with st.expander("Columnas a convertir", expanded=False):
    st.caption(
        "Estos valores están escritos para la tabla de contratos. Al cambiar de "
        "tabla conviene revisarlos: las columnas que no existan se ignoran."
    )
    p1, p2 = st.columns(2)
    txt_fechas = p1.text_area("Columnas de fecha", lista_a_texto(cfg.get("columnas_fecha")), height=110)
    formato_fecha = p1.text_input(
        "Formato de fecha", value=cfg.get("formato_fecha", "%m/%d/%Y"),
        help="La API entrega ISO y el CSV del portal MM/DD/YYYY. Si no coincide, se infiere.",
    )
    txt_moneda = p2.text_area("Columnas de moneda", lista_a_texto(cfg.get("columnas_moneda")), height=110)

# --------------------------- Consulta y ejecución ---------------------------
filtros: dict = {}
for fila in st.session_state.filas_filtro:
    col, val = fila["columna"], str(fila["valor"]).strip()
    if col and col != SIN_FILTRO and val:
        filtros[col] = val
if usar_rango and col_fecha and (desde or hasta):
    filtros[col_fecha] = {k: v for k, v in (("desde", desde), ("hasta", hasta)) if v}

st.subheader("3. Ejecutar")
where = _construir_where(filtros)
with st.expander("Ver la consulta que se va a enviar", expanded=not filtros):
    st.code(f"SELECT * FROM {DATASETS[tabla]}" + (f"\nWHERE {where}" if where else ""),
            language="sql")
    if vigia:
        st.caption(
            "En el modo combinado se lanza además una segunda consulta a la "
            "tabla de procesos, con los filtros adaptados."
        )

if st.button("Extraer datos", type="primary", icon=":material/download:"):
    try:
        with st.status("Trabajando ...", expanded=True) as estado:
            duraciones = {
                d["nombre"]: (d["desde"], d["hasta"]) for d in (cfg.get("duraciones") or [])
            }

            if vigia:
                estado.write("Descargando contratos y procesos ...")
                config_vigia = dict(cfg)
                config_vigia.update({
                    "app_token": app_token,
                    "filtros": filtros,
                    "margen_meses_procesos": int(margen_meses),
                })
                limpio = construir_base_contratos(config_vigia, limite=limite_total)
                filas_crudas = len(limpio)
            else:
                estado.write("Descargando ...")
                cliente = crear_cliente(app_token=app_token or None)
                try:
                    df = extraer_dataset(
                        cliente, tabla=tabla, filtros=filtros or None,
                        tamano_pagina=int(tamano_pagina), limite_total=limite_total,
                    )
                finally:
                    cliente.close()
                filas_crudas = len(df)

                estado.write("Limpiando ...")
                limpio = procesar(
                    df,
                    columnas_fecha=texto_a_lista(txt_fechas),
                    columnas_moneda=texto_a_lista(txt_moneda),
                    pares_duraciones=duraciones or None,
                    formato_fecha=formato_fecha or None,
                ) if not df.empty else df

            estado.update(label="Listo", state="complete", expanded=False)

        if limpio.empty:
            st.warning(
                "La consulta no devolvió filas: esa combinación de filtros no "
                "existe en el dataset. Usa **Ver valores posibles** para "
                "comprobar qué contiene realmente cada columna."
            )
            st.session_state.resultado = None
        else:
            st.session_state.resultado = {
                "df": limpio, "filas_crudas": filas_crudas, "tabla": tabla, "vigia": vigia,
            }
    except Exception as exc:
        logger.exception("Falló la extracción")
        st.error(f"Falló la extracción: {exc}")
        st.session_state.resultado = None

# --------------------------------- Resultado --------------------------------
res = st.session_state.resultado
if res is None:
    st.info(
        "Elige los filtros y pulsa **Extraer datos**. Todo lo que ocurra queda "
        "registrado en `logs/secop2.log`.",
        icon=":material/info:",
    )
else:
    df = res["df"]
    st.divider()
    st.subheader("Resultado")

    m1, m2, m3 = st.columns(3)
    m1.metric("Filas", f"{len(df):,}".replace(",", "."))
    m2.metric("Columnas", df.shape[1])
    fechas = [c for c in texto_a_lista(txt_fechas) if c in df.columns]
    if fechas:
        serie = pd.to_datetime(df[fechas[0]], errors="coerce")
        if serie.notna().any():
            m3.metric("Periodo", f"{serie.min():%b %Y} – {serie.max():%b %Y}")

    esperadas = set(texto_a_lista(txt_fechas) + texto_a_lista(txt_moneda))
    faltantes = sorted(c for c in esperadas if c not in df.columns)
    if faltantes:
        st.warning(
            "Estas columnas no existen en la tabla y se ignoraron: "
            + ", ".join(f"`{c}`" for c in faltantes)
        )

    t1, t2 = st.tabs(["Vista previa", "Resumen"])
    with t1:
        st.dataframe(df.head(200), hide_index=True)
        st.caption(f"Primeras 200 filas de {len(df):,}".replace(",", ".") + ".")
        st.download_button(
            "Descargar CSV", icon=":material/download:",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"secop2_{'vigia' if res['vigia'] else res['tabla']}.csv",
            mime="text/csv",
        )
    with t2:
        numericas = df.select_dtypes("number")
        if not numericas.empty:
            st.dataframe(numericas.describe().T, hide_index=False)
        else:
            st.caption("No hay columnas numéricas que resumir.")

# --------------------------- Guardar la selección ---------------------------
st.divider()
with st.expander("Guardar esta configuración"):
    st.caption(
        "El YAML equivalente a lo seleccionado arriba. Se puede escribir sobre "
        "`config/config.yaml` o descargar aparte."
    )
    cfg_actual = {
        "app_token": app_token,
        "tabla": tabla,
        "tamano_pagina": int(tamano_pagina),
        "limite_total": None if sin_tope else int(limite_total),
        "filtros": filtros,
        "margen_meses_procesos": int(margen_meses),
        "columnas_fecha": texto_a_lista(txt_fechas),
        "formato_fecha": formato_fecha,
        "columnas_moneda": texto_a_lista(txt_moneda),
        "duraciones": cfg.get("duraciones") or [],
    }
    yaml_texto = yaml.safe_dump(cfg_actual, allow_unicode=True, sort_keys=False)
    st.code(yaml_texto, language="yaml")

    b1, b2 = st.columns(2)
    if b1.button("Guardar en config/config.yaml", type="primary", icon=":material/save:"):
        try:
            guardar_config(cfg_actual, RUTA_CONFIG)
            st.success(
                "Guardado. El archivo está versionado: `git diff` muestra el "
                "cambio y `git checkout` lo revierte."
            )
        except Exception as exc:
            logger.exception("No se pudo guardar la configuración")
            st.error(f"No se pudo guardar: {exc}")

    b2.download_button("Descargar aparte", data=yaml_texto.encode("utf-8"),
                       file_name="config.yaml", mime="text/yaml")

    if app_token:
        st.info(
            "El app token no se escribe en el archivo: el repositorio es "
            "público. Para no pegarlo cada vez, defínelo como variable de "
            "entorno `SECOP_APP_TOKEN` antes de lanzar la app.",
            icon=":material/key:",
        )
