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
    contar_filas,
    crear_cliente,
    diagnosticar_filtros,
    extraer_dataset,
    listar_columnas,
    valores_distintos,
)
from src.flujo_vigia import construir_base_contratos
from src.pipeline import (
    borrar_consulta,
    cargar_consultas,
    configurar_logging,
    guardar_config,
    guardar_consulta,
    leer_log,
)
from src.procesamiento import columnas_comparables, procesar

RAIZ = Path(__file__).resolve().parent
RUTA_CONFIG = RAIZ / "config" / "config.yaml"
DIR_PROCESADO = RAIZ / "data" / "processed"

# Un solo color para todas las gráficas: cada una muestra una sola serie, así
# que varios colores no codificarían nada.
COLOR = "#2E7D32"

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


def aplicar_consulta(consulta: dict) -> None:
    """
    Carga una consulta guardada en el formulario.

    Hay que borrar las claves de los controles: Streamlit recuerda lo que el
    usuario eligió y eso ganaría sobre los valores nuevos.
    """
    for clave in list(st.session_state):
        if clave.startswith(("f_col_", "f_val_", "f_txt_", "f_load_", "rango_", "sel_")):
            del st.session_state[clave]
    st.session_state.consulta_cargada = consulta
    st.session_state.filas_filtro = [
        {"columna": k, "valor": str(v)}
        for k, v in (consulta.get("filtros") or {}).items()
        if not isinstance(v, dict)
    ] or [{"columna": "", "valor": ""}]
    st.rerun()


cfg = cargar_defaults()
st.session_state.setdefault("resultado", None)
st.session_state.setdefault("cols_consultadas", set())
st.session_state.setdefault("consulta_cargada", None)

# Los valores iniciales salen de la consulta cargada si hay una; si no, del YAML.
base = st.session_state.consulta_cargada or cfg


# --------------------------------- Cabecera ---------------------------------
st.title("Pipeline SECOP 2")
st.caption(
    "Extracción y limpieza de datos de contratación pública desde "
    "datos.gov.co. Los valores iniciales vienen de `config/config.yaml`."
)

with st.sidebar:
    consultas = cargar_consultas()
    if consultas:
        st.header("CONSULTAS GUARDADAS")
        elegida = st.selectbox("Abrir", ["—"] + sorted(consultas), key="sel_guardada")
        g1, g2 = st.columns(2)
        if g1.button("Cargar", disabled=elegida == "—"):
            aplicar_consulta(consultas[elegida])
        if g2.button("Borrar", disabled=elegida == "—"):
            borrar_consulta(elegida)
            st.rerun()
        st.divider()

    st.header("FUENTE")
    modos = ["Una tabla", "Contratos + procesos"]
    modo = st.radio(
        "Qué construir", modos, key="sel_modo",
        index=modos.index(base.get("modo")) if base.get("modo") in modos else 0,
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
            index=tablas.index(base.get("tabla", "contratos"))
            if base.get("tabla") in tablas else 0, key="sel_tabla",
        )
    st.caption(f"Dataset: `{DATASETS[tabla]}`")

    st.header("ALCANCE")
    sin_tope = st.toggle("Traer todo", value=base.get("limite_total") is None, key="sel_tope",
                         help="Sin tope de filas. Puede tardar bastante.")
    limite_total = None
    if not sin_tope:
        limite_total = st.number_input(
            "Máximo de filas", min_value=1, max_value=5_000_000,
            value=int(base.get("limite_total") or 5000), step=1000, key="sel_limite",
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

filtros_cfg = base.get("filtros") or {}
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
usar_rango = st.toggle("Acotar por rango de fechas", value=rango_cfg[0] is not None, key="rango_on")
if usar_rango:
    f1, f2, f3 = st.columns(3)
    col_fecha = f1.selectbox(
        "Columna de fecha", campos_fecha or ["fecha_de_firma"],
        index=campos_fecha.index(rango_cfg[0]) if rango_cfg[0] in campos_fecha else 0, key="rango_col",
    )
    desde = f2.text_input("Desde", value=(rango_cfg[1] or {}).get("desde", ""),
                          placeholder="2025-01-01", key="rango_desde")
    hasta = f3.text_input("Hasta", value=(rango_cfg[1] or {}).get("hasta", ""),
                          placeholder="2025-12-31", key="rango_hasta")
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

e1, e2 = st.columns([1, 1])

if e2.button("¿Cuántas filas hay?", icon=":material/pin:",
             help="Una sola consulta, sin descargar los datos."):
    try:
        cliente = crear_cliente(app_token=app_token or None)
        try:
            total = contar_filas(cliente, tabla, filtros or None)
        finally:
            cliente.close()

        if total == 0:
            st.error("Esa combinación de filtros no devuelve ninguna fila.")
            if filtros:
                st.caption("Filtro por filtro, para ver cuál es el que sobra:")
                cliente = crear_cliente(app_token=app_token or None)
                try:
                    st.dataframe(diagnosticar_filtros(cliente, tabla, filtros), hide_index=True)
                finally:
                    cliente.close()
        elif limite_total and total > limite_total:
            st.warning(
                f"La consulta devuelve **{total:,}** filas y el tope está en "
                f"{limite_total:,}: vas a traer una parte, no el conjunto completo."
                .replace(",", ".")
            )
        else:
            st.success(f"La consulta devuelve **{total:,}** filas.".replace(",", "."))
    except Exception as exc:
        logger.exception("Falló el conteo")
        st.error(f"No se pudo contar: {exc}")

if e1.button("Extraer datos", type="primary", icon=":material/download:"):
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
            st.warning("La consulta no devolvió filas.")
            if filtros:
                st.caption("Filtro por filtro, para ver cuál es el que sobra:")
                cliente = crear_cliente(app_token=app_token or None)
                try:
                    st.dataframe(diagnosticar_filtros(cliente, tabla, filtros), hide_index=True)
                finally:
                    cliente.close()
            st.session_state.resultado = None
        else:
            st.session_state.resultado = {
                "df": limpio, "filas_crudas": filas_crudas, "tabla": tabla, "vigia": vigia,
            }
    except Exception as exc:
        logger.exception("Falló la extracción")
        st.error(f"Falló la extracción: {exc}")
        st.session_state.resultado = None

# ---------------------------- Extracciones previas --------------------------
anteriores = sorted(DIR_PROCESADO.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
if anteriores:
    with st.expander(f"Extracciones anteriores ({len(anteriores)})"):
        st.caption(f"Archivos guardados en `data/processed`.")
        tabla_hist = pd.DataFrame([
            {
                "archivo": f.name,
                "guardado": pd.Timestamp(f.stat().st_mtime, unit="s").strftime("%d/%m/%Y %H:%M"),
                "tamaño": f"{f.stat().st_size / 1e6:.1f} MB",
            }
            for f in anteriores[:20]
        ])
        st.dataframe(tabla_hist, hide_index=True)

        h1, h2 = st.columns([3, 1], vertical_alignment="bottom")
        cual = h1.selectbox("Abrir uno", [f.name for f in anteriores[:20]],
                            label_visibility="collapsed")
        if h2.button("Abrir", icon=":material/folder_open:"):
            ruta = DIR_PROCESADO / cual
            leido = pd.read_csv(ruta, low_memory=False)
            st.session_state.resultado = {
                "df": leido, "filas_crudas": len(leido),
                "tabla": tabla, "vigia": False, "origen": cual,
            }
            st.rerun()

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

    t1, t2 = st.tabs(["Datos", "Resumen"])

    with t1:
        seleccion = st.multiselect(
            "Columnas", list(df.columns), default=list(df.columns),
            help="Recorta la vista y la descarga. Con 144 columnas conviene "
                 "quedarse con las que vas a usar.",
        )
        vista = df[seleccion] if seleccion else df

        st.dataframe(vista.head(200), hide_index=True)
        st.caption(
            f"Primeras 200 filas de {len(vista):,}".replace(",", ".")
            + f" · {vista.shape[1]} de {df.shape[1]} columnas."
        )

        d1, d2 = st.columns(2)
        nombre_archivo = f"secop2_{'vigia' if res['vigia'] else res['tabla']}"
        d1.download_button(
            "Descargar CSV", icon=":material/download:",
            data=vista.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{nombre_archivo}.csv", mime="text/csv",
        )
        if d2.button("Guardar en data/processed", icon=":material/save:"):
            try:
                DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
                marca = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
                destino = DIR_PROCESADO / f"{nombre_archivo}_{marca}.csv"
                vista.to_csv(destino, index=False, encoding="utf-8-sig")
                logger.info("Guardado desde la interfaz en %s", destino)
                st.success(f"Guardado como `{destino.name}`.")
            except Exception as exc:
                logger.exception("No se pudo guardar el CSV")
                st.error(f"No se pudo guardar: {exc}")

    with t2:
        col_fechas = [c for c in texto_a_lista(txt_fechas) if c in df.columns]
        col_montos = [c for c in texto_a_lista(txt_moneda) if c in df.columns]

        if col_fechas:
            st.markdown("**Contratos por mes**")
            elegida_f = st.selectbox("Fecha de referencia", col_fechas,
                                     label_visibility="collapsed")
            serie = pd.to_datetime(df[elegida_f], errors="coerce").dropna()
            if not serie.empty:
                por_mes = serie.dt.to_period("M").value_counts().sort_index()
                por_mes.index = por_mes.index.astype(str)
                st.bar_chart(por_mes, color=COLOR, height=240,
                             x_label="Mes", y_label="Contratos")

            if col_montos:
                st.markdown("**Valor total por mes**")
                montos = pd.to_numeric(df[col_montos[0]], errors="coerce")
                fechas = pd.to_datetime(df[elegida_f], errors="coerce")
                suma = montos.groupby(fechas.dt.to_period("M")).sum().sort_index()
                suma.index = suma.index.astype(str)
                st.bar_chart(suma, color=COLOR, height=240,
                             x_label="Mes", y_label=col_montos[0])

        # Categóricas: solo las que tienen un número de valores legible.
        # columnas_comparables descarta las que llegan como diccionario: nunique
        # y value_counts fallan sobre ellas.
        candidatas = [
            c for c in columnas_comparables(df)
            if df[c].dtype == object and 1 < df[c].nunique(dropna=True) <= 60
        ]
        if candidatas:
            st.markdown("**Distribución por categoría**")
            elegida_c = st.selectbox("Columna", candidatas, label_visibility="collapsed",
                                     index=candidatas.index("modalidad_de_contratacion")
                                     if "modalidad_de_contratacion" in candidatas else 0)
            conteo = df[elegida_c].value_counts().head(10).sort_values()
            st.bar_chart(conteo, color=COLOR, horizontal=True, height=300,
                         x_label="Contratos", y_label="")

        numericas = df.select_dtypes("number")
        if not numericas.empty:
            with st.expander("Estadísticas de las columnas numéricas"):
                st.dataframe(numericas.describe().T)

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

    st.divider()
    st.caption(
        "O guárdala con un nombre, para volver a ella desde la barra lateral "
        "sin perder la configuración actual."
    )
    n1, n2 = st.columns([3, 1], vertical_alignment="bottom")
    nombre = n1.text_input("Nombre", placeholder="UNP 2025", label_visibility="collapsed")
    if n2.button("Guardar consulta", disabled=not nombre.strip()):
        guardar_consulta(nombre.strip(), {**cfg_actual, "modo": modo})
        st.success(f"Guardada como «{nombre.strip()}».")
        st.rerun()

with st.expander("Registro de la última corrida"):
    st.caption("Las últimas líneas de `logs/secop2.log`.")
    st.code(leer_log(60), language="log")

    if app_token:
        st.info(
            "El app token no se escribe en el archivo: el repositorio es "
            "público. Para no pegarlo cada vez, defínelo como variable de "
            "entorno `SECOP_APP_TOKEN` antes de lanzar la app.",
            icon=":material/key:",
        )
