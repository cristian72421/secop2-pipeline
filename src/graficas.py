"""
Gráficas de la interfaz, en Plotly.

Antes eran Altair y `st.bar_chart`. El cambio da tres cosas que faltaban:

1. Los números salen con coma decimal (`separators=",."`). Altair los formatea
   en el navegador y esa configuración no es accesible desde Streamlit, así que
   los ejes decían "1,257.0" donde debían decir "1.257,0".
2. El recuadro emergente se redacta entero, en español y con las unidades
   puestas, en vez de mostrar el nombre crudo de la columna.
3. Cada gráfica trae zoom y descarga a PNG sin escribir código.

**La paleta está validada, no elegida a ojo.** Los cinco tonos pasan las cinco
comprobaciones del validador de daltonismo —banda de luminosidad, saturación
mínima, separación entre tonos vecinos para protanopía y deuteranopía,
separación para visión normal y contraste contra el fondo— en modo claro y en
modo oscuro. Dos consecuencias concretas:

- El gris que ocupaba el quinto puesto **no pasaba**: se confunde con el
  magenta (ΔE 2,2 en deuteranopía). Se cambió por violeta. El gris queda solo
  para líneas de referencia, nunca como serie.
- El violeta va en el segundo puesto, no en el quinto, porque al lado del
  magenta tampoco se distinguen. El orden de los tonos es parte de lo validado.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# Verde, violeta, naranja, azul, magenta. El orden es fijo: la cuarta serie
# siempre recibe el azul, se muestren tres categorías o cinco. Si el color
# dependiera del puesto en el ranking, filtrar repintaría lo que queda.
PALETA_CLARA = ("#12805F", "#4A3AA7", "#C4661F", "#3E7CC0", "#AE5183")
# Los mismos cinco tonos, subidos de luminosidad para el fondo oscuro. No es un
# volteo automático: se validaron como conjunto aparte.
PALETA_OSCURA = ("#159A72", "#8478E0", "#D9762B", "#4E90DC", "#C2699A")

TEMA_CLARO = {
    "tinta": "#262626", "tinta_suave": "#5F5F5F",
    "rejilla": "#E6E6E6", "superficie": "#FFFFFF",
}
TEMA_OSCURO = {
    "tinta": "#E8E8E8", "tinta_suave": "#A8A8A8",
    "rejilla": "#3A3A3A", "superficie": "#0E1117",
}


def paleta(oscuro: bool = False) -> list[str]:
    return list(PALETA_OSCURA if oscuro else PALETA_CLARA)


def colores(oscuro: bool = False) -> dict:
    """Los colores con nombre de función, no de tono."""
    base = dict(TEMA_OSCURO if oscuro else TEMA_CLARO)
    tonos = paleta(oscuro)
    base.update({
        "serie": tonos[0],          # una sola serie
        "normal": tonos[3],         # lo esperable
        "alerta": tonos[2],         # lo que hay que mirar
        "referencia": "#8A8A8A",    # diagonales y guías, nunca una serie
        "paleta": tonos,
    })
    return base


def tema(fig: go.Figure, oscuro: bool = False, alto: int = 320,
         leyenda: bool | None = None) -> go.Figure:
    """
    Deja la figura con el aspecto común: números en español, ejes discretos.

    `leyenda=None` la deja como esté; la regla es que haya leyenda desde dos
    series y no la haya con una sola, porque ahí el título ya la nombra.
    """
    c = colores(oscuro)
    fig.update_layout(
        # Primero el separador decimal, después el de miles: coma y punto.
        separators=",.",
        template="simple_white",
        height=alto,
        margin=dict(l=8, r=8, t=48 if fig.layout.title.text else 16, b=8),
        font=dict(size=13, color=c["tinta"]),
        title=dict(font=dict(size=15, color=c["tinta"]), x=0, xanchor="left"),
        # Transparente para que herede el fondo de Streamlit en los dos modos.
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=c["paleta"],
        hoverlabel=dict(font_size=13, bgcolor=c["superficie"],
                        bordercolor=c["rejilla"], font_color=c["tinta"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0, title_text="",
                    font=dict(color=c["tinta_suave"])),
        dragmode=False,
    )
    if leyenda is not None:
        fig.update_layout(showlegend=leyenda)

    ejes = dict(showline=True, linecolor=c["rejilla"], linewidth=1,
                ticks="outside", tickcolor=c["rejilla"],
                tickfont=dict(color=c["tinta_suave"]),
                title_font=dict(color=c["tinta_suave"], size=12))
    fig.update_xaxes(showgrid=False, **ejes)
    fig.update_yaxes(showgrid=True, gridcolor=c["rejilla"], zeroline=False, **ejes)
    return fig


def _recortar(etiquetas, largo: int = 46) -> list[str]:
    """Nombres de modalidad largos; sin recortar se comen media gráfica."""
    return [e if len(str(e)) <= largo else str(e)[: largo - 1] + "…" for e in etiquetas]


def barras(etiquetas, valores, titulo: str = "", unidad: str = "",
           decimales: int = 0, horizontal: bool = True, color: str | None = None,
           eje: str | None = None, oscuro: bool = False,
           alto: int = 320) -> go.Figure:
    """
    Una serie de barras con el valor escrito al final de cada una.

    La etiqueta directa es lo que permite leer la magnitud sin perseguir el eje,
    y es también la "codificación secundaria" que pide el validador cuando dos
    tonos quedan cerca en visión daltónica.
    """
    c = colores(oscuro)
    formato = f",.{decimales}f"
    textos = [f"%{{{'x' if horizontal else 'y'}:{formato}}}"]
    etiquetas = _recortar(etiquetas)

    traza = go.Bar(
        x=list(valores) if horizontal else list(etiquetas),
        y=list(etiquetas) if horizontal else list(valores),
        orientation="h" if horizontal else "v",
        marker=dict(color=color or c["serie"], cornerradius=4),
        texttemplate=textos[0], textposition="outside",
        textfont=dict(color=c["tinta_suave"], size=12),
        cliponaxis=False,
        hovertemplate=("%{y}<br>%{x:" + formato + "}" if horizontal
                       else "%{x}<br>%{y:" + formato + "}")
                      + (f" {unidad}" if unidad else "") + "<extra></extra>",
    )
    fig = go.Figure(traza)
    fig.update_layout(title_text=titulo, bargap=0.28)
    # Si el título ya dice la magnitud, repetirla en el eje sobra.
    if eje is None:
        eje = "" if titulo.strip().lower().startswith(unidad.strip().lower() or "\0") else unidad

    # "," agrupa los miles y deja que Plotly elija cuántos decimales necesita
    # el eje; forzarlos deja rótulos como "800,0" donde basta "800".
    numerico = dict(tickformat=",")
    if horizontal:
        # Un 12% de aire a la derecha: la etiqueta va por fuera de la barra y
        # sin margen se sale del área de dibujo.
        tope = max([v for v in valores if v == v] or [0])
        fig.update_yaxes(autorange="reversed", showgrid=False, type="category")
        fig.update_xaxes(showgrid=True, gridcolor=c["rejilla"], title_text=eje,
                         range=[0, tope * 1.12] if tope else None, **numerico)
    else:
        # Categórico a la fuerza: con etiquetas como "2025-01" Plotly las toma
        # por fechas y las rotula en inglés ("Jan 2025").
        fig.update_xaxes(type="category")
        fig.update_yaxes(title_text=eje, **numerico)
    return tema(fig, oscuro, alto, leyenda=False)


def torta(etiquetas, valores, titulo: str = "", oscuro: bool = False,
          alto: int = 320) -> go.Figure:
    """Porciones con su porcentaje escrito encima y separadas por un filo."""
    c = colores(oscuro)
    valores = [float(v) for v in valores]
    total = sum(valores) or 1
    # Por debajo del 4% la etiqueta no cabe en la porción y se encima con las
    # vecinas hasta volverse un borrón. El dato sigue en el recuadro emergente.
    textos = [f"{100 * v / total:.1f}%".replace(".", ",") if v / total >= 0.04 else ""
              for v in valores]

    fig = go.Figure(go.Pie(
        labels=_recortar(etiquetas, 34), values=valores, sort=False, hole=0.45,
        marker=dict(colors=c["paleta"], line=dict(color=c["superficie"], width=2)),
        text=textos, textinfo="text", textposition="inside",
        insidetextfont=dict(color="#FFFFFF", size=13),
        hovertemplate="%{label}<br>%{value:,.0f} · %{percent:.2%}<extra></extra>",
    ))
    fig.update_layout(title_text=titulo)
    fig = tema(fig, oscuro, alto, leyenda=True)
    # En la torta la leyenda va abajo: arriba se encima con el título.
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.02,
                                  xanchor="center", x=0.5),
                      margin=dict(t=40, b=8))
    return fig


def histograma_estados(datos: pd.DataFrame, valor: str, estado: str,
                       normal: str, alerta: str, titulo_x: str = "",
                       oscuro: bool = False, alto: int = 300) -> go.Figure:
    """Histograma de dos estados superpuestos; el de alerta va en su color."""
    c = colores(oscuro)
    fig = go.Figure()
    for nombre, tono in ((normal, c["normal"]), (alerta, c["alerta"])):
        parte = datos.loc[datos[estado] == nombre, valor]
        if parte.empty:
            continue
        fig.add_trace(go.Histogram(
            x=parte, name=nombre, marker=dict(color=tono,
                                              line=dict(color=c["superficie"], width=1)),
            nbinsx=60,
            hovertemplate=nombre + "<br>%{x} días<br>%{y:,.0f} contratos<extra></extra>",
        ))
    fig.update_layout(barmode="overlay", bargap=0.04)
    fig.update_traces(opacity=0.9)
    fig.update_xaxes(title_text=titulo_x)
    fig.update_yaxes(title_text="Contratos", tickformat=",")
    return tema(fig, oscuro, alto, leyenda=fig.data and len(fig.data) > 1)


def caja_logaritmica(datos: pd.DataFrame, valor: str, grupo: str,
                     titulo_y: str = "", oscuro: bool = False,
                     alto: int = 420) -> go.Figure:
    """
    Diagrama de caja en escala logarítmica, una caja por categoría.

    En escala lineal un contrato de miles de millones aplasta a los demás y
    todas las cajas quedan pegadas al eje.
    """
    c = colores(oscuro)
    orden = datos.groupby(grupo)[valor].median().sort_values(ascending=False).index
    fig = go.Figure()
    for i, nombre in enumerate(orden):
        fig.add_trace(go.Box(
            y=datos.loc[datos[grupo] == nombre, valor],
            name=_recortar([nombre], 34)[0],
            marker=dict(color=c["paleta"][i % len(c["paleta"])], size=5, opacity=0.55),
            line=dict(width=1.5), boxpoints="outliers",
            hovertemplate="%{y:,.1f}<extra></extra>",
        ))
    # dtick=1 deja una marca por década; sin esto Plotly intercala las menores
    # y el eje queda con "2, 100k, 5, 10k, 5, 1000…", ilegible.
    fig.update_yaxes(type="log", dtick=1, tickformat=",", exponentformat="none",
                     title_text=titulo_y)
    fig.update_xaxes(tickangle=-20)
    return tema(fig, oscuro, alto, leyenda=False)


def barras_apiladas(datos: pd.DataFrame, x: str, y: str, serie: str,
                    titulo_y: str = "", oscuro: bool = False,
                    alto: int = 300) -> go.Figure:
    """Barras apiladas con 2px de fondo entre segmentos, para que se separen."""
    c = colores(oscuro)
    fig = go.Figure()
    for i, nombre in enumerate(sorted(datos[serie].unique())):
        parte = datos[datos[serie] == nombre]
        fig.add_trace(go.Bar(
            x=parte[x], y=parte[y], name=_recortar([nombre], 34)[0],
            marker=dict(color=c["paleta"][i % len(c["paleta"])],
                        line=dict(color=c["superficie"], width=2)),
            hovertemplate="%{x}<br>" + str(nombre) + "<br>%{y:,.0f}<extra></extra>",
        ))
    fig.update_layout(barmode="stack", bargap=0.25, legend_traceorder="normal")
    # Ver el comentario de `barras`: los meses son texto, no fechas.
    fig.update_xaxes(type="category")
    fig.update_yaxes(title_text=titulo_y, tickformat=",")
    return tema(fig, oscuro, alto, leyenda=True)


def curva_lorenz(curva: pd.DataFrame, oscuro: bool = False,
                 alto: int = 320) -> go.Figure:
    """La curva contra la diagonal del reparto perfectamente equitativo."""
    c = colores(oscuro)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[0, 100], y=[0, 100], mode="lines", name="Reparto equitativo",
        line=dict(color=c["referencia"], width=1, dash="dash"),
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=curva["pct_proveedores"], y=curva["pct_valor"], mode="lines",
        name="Concentración observada",
        line=dict(color=c["alerta"], width=2),
        hovertemplate="El %{x:.1f}% de los proveedores<br>"
                      "acumula el %{y:.1f}% del valor<extra></extra>",
    ))
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(title_text="% de proveedores", range=[0, 100], ticksuffix="%")
    fig.update_yaxes(title_text="% del valor acumulado", range=[0, 100], ticksuffix="%")
    return tema(fig, oscuro, alto, leyenda=True)
