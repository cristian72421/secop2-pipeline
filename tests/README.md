# Pruebas

```bash
pip install -r requirements-dev.txt
pytest
```

Son 15 pruebas. Ninguna toca la red ni necesita token: todas trabajan sobre las
tablas fijas de `tests/datos/`, así que corren igual sin conexión y dan siempre
el mismo resultado.

## Los datos de prueba

| Archivo | Qué es |
|---|---|
| `contratos.csv` | 43 contratos en el formato que devuelve la API. |
| `procesos.csv` | 44 filas con 42 procesos distintos: trae repeticiones a propósito. |
| `contratos_portal.csv` | 8 contratos en el formato del CSV que exporta la web: tildes en los encabezados, fechas MM/DD/AAAA y montos con `$`. |

Cada cifra esperada se puede verificar a mano:

- 43 contratos, 35 de contratación directa, valor total $70.320.000.000.
- 2 contratos por urgencia manifiesta que suman $50.000.000.000 — más que todos
  los demás contratos directos juntos.
- 4 licitaciones públicas, 3 de ellas sin una sola oferta.
- 1 contrato firmado 5 días después de haber iniciado.
- 1 con fecha de fin anterior al inicio, 1 con valor cero, 1 con valor vacío.
- 1 contrato sin proceso asociado, para que el cruce sea de 42 de 43.

Esas cifras están en `conftest.py` como constantes. Si se cambia un archivo de
datos hay que actualizarlas ahí.

## Las 15 pruebas

**`test_procesamiento.py` — la limpieza**

| Prueba | Qué protege |
|---|---|
| `test_los_montos_se_leen_bien_vengan_del_portal_o_de_la_api` | Quitar los puntos de miles sin mirar convertía `1234.56` en `123456`. |
| `test_un_formato_de_fecha_equivocado_no_deja_la_columna_vacia` | El formato del portal aplicado a datos de la API dejaba todas las fechas en nulo sin avisar. |
| `test_las_columnas_que_llegan_como_diccionario_quedan_fuera` | Socrata entrega las columnas de URL como diccionario y eso rompía la búsqueda de repetidos. |
| `test_una_firma_posterior_al_inicio_se_conserva_negativa` | La firma tardía es una señal de riesgo: si la limpieza la borra, se pierde el indicador. |
| `test_un_proceso_repetido_se_reduce_a_una_fila` | De las fechas repetidas de un mismo proceso debe quedar la más antigua. |
| `test_el_cruce_con_procesos_no_pierde_contratos` | Con la llave equivocada el emparejamiento daba 0%. |

**`test_indicadores.py` — que ningún indicador se lea al revés**

| Prueba | Qué protege |
|---|---|
| `test_la_contratacion_directa_manda_en_contratos_pero_no_en_dinero` | Leer solo el porcentaje de contratos da la conclusión contraria. |
| `test_cero_ofertas_no_significa_lo_mismo_en_cada_modalidad` | Cero ofertas es el procedimiento en contratación directa y la anomalía en una licitación. |
| `test_la_concentracion_en_dinero_no_es_la_de_contratos` | Confundir los dos porcentajes invierte la lectura. |
| `test_las_causales_raras_pesan_mas_que_las_frecuentes` | Dos contratos por urgencia manifiesta valen más que los 33 directos restantes. |
| `test_las_revisiones_de_calidad_encuentran_los_casos_sembrados` | Un valor mal digitado distorsiona cualquier promedio. |
| `test_ningun_indicador_falla_cuando_la_consulta_no_devuelve_nada` | La interfaz llega a ese caso cada vez que un filtro no encuentra filas. |

**`test_flujo_vigia.py` — el paso de una tabla a la otra**

| Prueba | Qué protege |
|---|---|
| `test_los_procesos_se_buscan_desde_antes_que_los_contratos` | Sin el margen hacia atrás, los contratos de enero se quedan sin proceso. |
| `test_los_filtros_se_adaptan_a_los_nombres_de_procesos` | La entidad se llama distinto en cada tabla y `ciudad` no existe en procesos. |

**`test_extraccion.py` — la consulta al portal**

| Prueba | Qué protege |
|---|---|
| `test_la_consulta_al_portal_se_arma_bien` | Igualdad, rango de fechas y el apóstrofo de un nombre, que sin escapar deja la consulta mal formada. |
