"""
Interfaz para configurar y ejecutar la extracción de SECOP 2.

    streamlit run app.py

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# _construir_where es privada, pero mostrar la consulta SoQL generada antes de
# lanzarla ahorra mucho tiempo cuando un filtro no devuelve nada.
from src.extraccion import DATASETS, _construir_where, crear_cliente, extraer_dataset
from src.procesamiento import procesar

RAIZ = Path(__file__).resolve().parent
RUTA_CONFIG = RAIZ / "config" / "config.yaml"

st.set_page_config(page_title="Pipeline SECOP 2", page_icon="📄", layout="wide")


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
st.subheader("Filtros")
st.caption(
    "Los nombres son los de la API, no los del portal: 'Fecha de Firma' es "
    "`fecha_de_firma`. Se combinan con AND. Sin filas, se descarga todo."
)

filtros_cfg = cfg.get("filtros") or {}
filas_iniciales = [
    {"columna": k, "valor": v}
    for k, v in filtros_cfg.items()
    if not isinstance(v, dict)
] or [{"columna": "", "valor": ""}]

editor = st.data_editor(
    pd.DataFrame(filas_iniciales),
    num_rows="dynamic",
    column_config={
        "columna": st.column_config.TextColumn("Columna"),
        "valor": st.column_config.TextColumn("Valor (igualdad exacta)"),
    },
    key="editor_filtros",
)

# Rango de fechas: lo maneja aparte porque genera >= y <=, no igualdad.
rango_cfg = next(
    ((k, v) for k, v in filtros_cfg.items() if isinstance(v, dict)), (None, {})
)
col_a, col_b, col_c = st.columns([2, 1, 1])
with col_a:
    usar_rango = st.checkbox("Filtrar por rango de fechas", value=rango_cfg[0] is not None)
    col_fecha = st.text_input(
        "Columna de fecha", value=rango_cfg[0] or "fecha_de_firma", disabled=not usar_rango
    )
with col_b:
    desde = st.text_input(
        "Desde (AAAA-MM-DD)", value=(rango_cfg[1] or {}).get("desde", ""), disabled=not usar_rango
    )
with col_c:
    hasta = st.text_input(
        "Hasta (AAAA-MM-DD)", value=(rango_cfg[1] or {}).get("hasta", ""), disabled=not usar_rango
    )

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
        formato_fecha = st.text_input(
            "Formato de fecha", value=cfg.get("formato_fecha", "%m/%d/%Y"),
            help="SECOP II entrega MM/DD/YYYY.",
        )
    with c2:
        txt_moneda = st.text_area(
            "Columnas de moneda", lista_a_texto(cfg.get("columnas_moneda")), height=110
        )
        txt_dedup = st.text_area(
            "Columnas para eliminar duplicados", lista_a_texto(cfg.get("subset_duplicados")), height=68
        )

# --------------------------- Consulta y ejecución ---------------------------
filtros: dict = {}
for fila in editor.to_dict("records"):
    col, val = str(fila.get("columna") or "").strip(), str(fila.get("valor") or "").strip()
    if col and val:
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
                "La consulta no devolvió filas. Suele ser un nombre de columna "
                "o un valor que no coincide exactamente con el del dataset."
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
                subset_duplicados=texto_a_lista(txt_dedup) or None,
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
    esperadas = set(texto_a_lista(txt_fechas) + texto_a_lista(txt_moneda) + texto_a_lista(txt_dedup))
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
        "Genera el YAML equivalente a lo seleccionado arriba. Se descarga "
        "aparte en vez de sobrescribir config/config.yaml, que tiene comentarios."
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
        "subset_duplicados": texto_a_lista(txt_dedup),
        "duraciones": cfg.get("duraciones") or [],
    }
    yaml_texto = yaml.safe_dump(cfg_actual, allow_unicode=True, sort_keys=False)
    st.code(yaml_texto, language="yaml")
    st.download_button("Descargar config.yaml", data=yaml_texto.encode("utf-8"),
                       file_name="config.yaml", mime="text/yaml")
