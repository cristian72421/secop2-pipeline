"""
Pruebas de las gráficas.

No comprueban cómo se ven —eso hay que mirarlo— sino las dos cosas que se
rompen en silencio: el formato de los números y la paleta.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import pandas as pd

from src import graficas as gr

# Los tonos exactos que pasaron el validador de daltonismo, en el orden en que
# pasaron. Si alguien cambia uno, esta prueba falla y hay que volver a validar:
#   node scripts/validate_palette.js "<hex,hex,...>" --mode light|dark
PALETA_VALIDADA_CLARA = ("#12805F", "#4A3AA7", "#C4661F", "#3E7CC0", "#AE5183")
PALETA_VALIDADA_OSCURA = ("#159A72", "#8478E0", "#D9762B", "#4E90DC", "#C2699A")


def test_los_numeros_de_las_graficas_salen_con_coma_decimal():
    """
    Era la razón de fondo para cambiar de Altair a Plotly: el eje decía
    '1,257.0' donde debía decir '1.257,0', y desde Streamlit no se podía tocar.
    """
    fig = gr.barras(["Directa", "Mínima cuantía"], [3209, 26])
    assert fig.layout.separators == ",."      # coma decimal, punto de miles


def test_la_paleta_es_la_que_pasó_el_validador():
    """Cambiar un tono obliga a volver a validarlo, no a confiar en el ojo."""
    assert tuple(gr.paleta(oscuro=False)) == PALETA_VALIDADA_CLARA
    assert tuple(gr.paleta(oscuro=True)) == PALETA_VALIDADA_OSCURA
    # Ningún gris como serie: se confundía con el magenta en deuteranopía.
    for tono in gr.paleta() + gr.paleta(oscuro=True):
        r, v, a = (int(tono[i:i + 2], 16) for i in (1, 3, 5))
        assert max(r, v, a) - min(r, v, a) > 40, f"{tono} es casi gris"


def test_una_sola_serie_no_lleva_leyenda_y_varias_sí():
    """Con una serie el título ya la nombra; con dos, el color tiene que tener nombre."""
    una = gr.barras(["a", "b"], [1, 2])
    assert una.layout.showlegend is False

    varias = gr.barras_apiladas(
        pd.DataFrame({"mes": ["2025-01", "2025-01"], "n": [5, 3],
                      "modalidad": ["Directa", "Mínima"]}),
        x="mes", y="n", serie="modalidad",
    )
    assert varias.layout.showlegend is True
