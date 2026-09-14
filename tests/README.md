# Pruebas

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Ninguna prueba toca la red ni necesita token: todas trabajan sobre las tablas
fijas de `tests/datos/`.

## Los datos de prueba

| Archivo | Qué es |
|---|---|
| `contratos.csv` | 43 contratos en el formato que devuelve la API (nombres snake_case, fechas ISO, montos planos). |
| `procesos.csv` | 44 filas con 42 procesos distintos: trae repeticiones a propósito. |
| `contratos_portal.csv` | 8 contratos en el formato del CSV que exporta la web (nombres con tildes, fechas MM/DD/AAAA, montos con `$` y punto de miles). |

Están construidos para que cada cifra esperada se pueda verificar a mano:

- 43 contratos, 35 de contratación directa, valor total $70.320.000.000.
- 2 contratos por urgencia manifiesta que suman $50.000.000.000 — más que todos
  los demás contratos directos juntos.
- 4 licitaciones públicas, 3 de ellas sin una sola oferta.
- 1 contrato firmado 5 días después de haber iniciado.
- 1 con fecha de fin anterior al inicio, 1 con valor cero, 1 con valor vacío.
- 1 contrato sin proceso asociado, para que el cruce sea del 42/43.

Las cifras están en `conftest.py` como constantes. Si se cambia un fixture hay
que actualizarlas ahí.

## Qué cubre cada archivo

| Archivo | Qué verifica |
|---|---|
| `test_procesamiento.py` | Limpieza: nombres de columna, montos, fechas, duraciones, reconciliación y unión. |
| `test_indicadores.py` | Que los indicadores no se puedan leer al revés, y que ninguno falle con una consulta vacía. |
| `test_flujo_vigia.py` | La traducción de filtros entre contratos y procesos, y el cruce. |
| `test_extraccion.py` | El texto de la consulta SoQL, sin salir a la red. |

## Regresiones

Varias pruebas existen porque el defecto ya ocurrió con datos reales:

- El formato de fecha del portal aplicado a datos de la API dejaba las 2.396
  fechas en nulo sin avisar.
- Quitar los puntos de miles sin mirar convertía `1234.56` en `123456`.
- Las columnas que Socrata entrega como diccionario rompían `drop_duplicates`.
- Cruzar por `id_del_proceso` en vez de `id_del_portafolio` daba 0% de
  emparejamiento.
- Filtrar procesos por la misma ventana de fechas que los contratos dejaba sin
  proceso a los contratos del comienzo del periodo.
