# Guía del pipeline de SECOP 2

Explicación detallada de cómo está construido el proyecto y por qué. Documento
de referencia para retomar el trabajo o para entender una parte específica sin
tener que leer todo el código.

---

## 1. Qué es y qué no es

Es un **ETL**: un proceso que **E**xtrae datos de una fuente, los **T**ransforma
para dejarlos usables y los **L**oad (carga/guarda) en un destino.

- **Fuente:** el portal de datos abiertos de Colombia (datos.gov.co), donde
  Colombia Compra Eficiente publica los datos de SECOP 2.
- **Transformación:** limpieza de tipos y construcción de variables derivadas.
- **Destino:** archivos CSV en `data/processed/`.

**No es** un modelo de machine learning. Los modelos e índices de riesgo de
VigIA (Salazar, Pérez y Gallego, 2024) serían una fase posterior; esto construye
la base de datos limpia sobre la que se pararían.

---

## 2. Mapa del repositorio

```
secop2-pipeline/
├── app.py                    Interfaz web (Streamlit)
├── config/config.yaml        Parámetros: qué extraer y cómo limpiarlo
├── src/
│   ├── extraccion.py         Todo lo que habla con la API  (E)
│   ├── procesamiento.py      Todo lo que transforma datos  (T)
│   ├── pipeline.py           Orquestador + configuración   (L)
│   ├── procesar_csv.py       Variante: procesa un CSV local
│   └── flujo_vigia.py        Variante: une contratos + procesos
├── notebooks/                Exploración
├── logs/                     Registro de las corridas (no se versiona)
├── data/raw, data/processed  Datos (no se versionan)
└── requirements.txt          Librerías necesarias
```

**El criterio de organización:** `extraccion.py` y `procesamiento.py` son
**librerías** — colecciones de funciones que no hacen nada por sí solas.
`pipeline.py`, `procesar_csv.py`, `flujo_vigia.py` y `app.py` son **puntos de
entrada** — se ejecutan y llaman a las librerías.

Esto importa porque significa que la lógica vive en un solo lugar. Cuando se
corrigió el error de las fechas, se corrigió en `procesamiento.py` y quedó
arreglado a la vez en la consola y en la interfaz.

---

## 3. El recorrido de los datos

```
config.yaml  ──►  extraer_dataset()  ──►  procesar()  ──►  CSV
   (qué)            (traer)               (limpiar)      (guardar)
```

1. Se lee la configuración: qué tabla, qué filtros, cuántas filas.
2. Se construye una consulta y se descarga por páginas desde la API.
3. Se normalizan nombres, se convierten tipos y se calculan las duraciones.
4. Se guarda un CSV con la fecha y hora en el nombre.

---

## 4. `src/extraccion.py` — traer los datos

### Las tablas

SECOP 2 no es una sola tabla. El diccionario `DATASETS` registra las cinco
relevantes con su identificador en el portal:

| Clave | Contenido | ID |
|---|---|---|
| `contratos` | Contratos electrónicos. Tabla principal, unidad = contrato | `jbjy-vk9h` |
| `procesos` | Procesos de contratación (ofertas, publicación) | `p6dx-8zbt` |
| `proveedores` | Proveedores registrados (tipo, antigüedad) | `qmzu-gj57` |
| `adiciones` | Adiciones: sobrecostos y prórrogas | `cb9c-h8sn` |
| `integrado` | SECOP I + II unificado | `rpmr-utcd` |

Las cuatro primeras son las que usa VigIA.

### `crear_cliente(app_token, timeout)`

Abre la conexión con el portal y devuelve el objeto con el que se consulta.

El `app_token` es opcional: sin él el acceso funciona igual, pero el portal
limita las peticiones por dirección IP y ese cupo se comparte con otros
usuarios. Con token el límite es por aplicación y más alto. Importa cuando se
descargan muchas páginas seguidas.

### `_construir_where(filtros)`

Traduce un diccionario de filtros a la sintaxis de consulta del portal (SoQL,
parecida a SQL). Soporta dos formas:

```python
{"ciudad": "Bogotá"}                                  ->  ciudad = 'Bogotá'
{"fecha_de_firma": {"desde": "2025-01-01"}}           ->  fecha_de_firma >= '2025-01-01'
```

Varias claves se combinan con `AND`. El guion bajo inicial del nombre indica,
por convención de Python, que es una función interna del módulo.

**Limitación actual:** solo igualdad exacta sobre texto y rangos de fecha. No
soporta búsqueda parcial (`LIKE`), listas de valores (`IN`) ni comparaciones
numéricas.

### `extraer_dataset(...)`

Descarga una tabla. El portal limita cuántas filas devuelve por petición, así
que la función recorre los resultados por páginas: pide un bloque, lo guarda,
pide el siguiente desde donde quedó, y así hasta agotar el filtro o llegar al
tope configurado. Entre página y página espera 0,2 segundos para no chocar con
los límites del portal.

### `listar_columnas(tabla)` y `valores_distintos(...)`

No traen datos: preguntan por la estructura.

`listar_columnas()` consulta los metadatos del dataset y devuelve, por cada
columna, el nombre técnico que acepta la consulta, el nombre visible en la web,
el tipo, y algunos valores frecuentes que el portal tiene precalculados.

Existen por un problema concreto: **el nombre que muestra el portal no es el que
acepta la API**. En la web se ve "Fecha de Firma"; la consulta necesita
`fecha_de_firma`. Y si el nombre o el valor no coinciden exactamente —incluidas
tildes y mayúsculas— la consulta devuelve cero filas sin explicar por qué.

`valores_distintos()` va más allá: consulta la lista completa de valores de una
columna con su frecuencia. Es exacto pero pesado, porque recorre toda la tabla.

---

## 5. `src/procesamiento.py` — limpiar los datos

Este módulo no toca la red ni el disco: recibe una tabla y devuelve otra. Es
donde viven las decisiones metodológicas del proyecto.

### `normalizar_nombres_columnas(df)`

`"Valor del Contrato"` → `valor_del_contrato`. Minúsculas, sin tildes, con guion
bajo. Sin esto no se podrían referenciar las columnas de forma estable desde la
configuración.

### `convertir_columnas_fecha(df, columnas, formato)`

Convierte texto a fechas reales, que es lo que permite restarlas.

**Por qué tiene un reintento:** el formato depende de la fuente. La API entrega
`2025-01-15T00:00:00.000` (formato ISO); el CSV que se descarga del portal
entrega `01/15/2025`. Al forzar el formato equivocado, pandas convierte todo en
nulo *sin lanzar ningún error*. Eso pasó en la primera prueba real: se
descargaron 2.396 contratos correctamente y las tres columnas de fecha quedaron
vacías, junto con las duraciones que dependen de ellas.

La función ahora detecta ese caso —formato indicado, columna con datos,
resultado 100% nulo— y reintenta dejando que pandas infiera el formato, dejando
constancia con una advertencia. Así el pipeline sirve para ambas fuentes.

### `limpiar_columnas_moneda(df, columnas)`

Convierte montos a números.

En el CSV del portal los valores vienen como `"$13.339.049"`: texto, con símbolo
de peso y punto como separador de miles. Convertir eso directamente a número da
nulo, así que hay que quitar el `$` y los puntos primero.

**Por qué no se limpia todo por igual:** desde la API los montos ya vienen como
número plano. Si se le quitaran los puntos sin mirar, un valor como `1234.56` se
convertiría en `123456` — cien veces más grande. La función revisa primero si el
valor ya es un número y solo limpia lo que no lo es.

### `calcular_duraciones(df, pares_fechas)`

Crea variables de días entre pares de fechas. Con la configuración actual:

- `dias_firma_a_inicio` = inicio − firma
- `dias_inicio_a_fin` = fin − inicio

**Las duraciones negativas se conservan a propósito.** Un valor negativo en
`dias_firma_a_inicio` significa que el contrato se firmó *después* de su fecha
de inicio. No es un error de datos: VigIA lo reporta como una práctica frecuente
y como señal de riesgo. Si se borraran o corrigieran, se estaría eliminando
justamente lo que interesa medir.

### `reconciliar_por_llave(df, llave, fecha_mas_antigua)`

Un mismo proceso de contratación puede aparecer en varias filas con datos que no
coinciden entre sí. Esta función deja un solo registro por proceso: elimina los
duplicados exactos y, cuando hay conflicto en una fecha, conserva la más
antigua. El resto de columnas toma el primer valor disponible.

Replica el tratamiento que aplica VigIA a la tabla de procesos.

### `unir_tablas(izquierda, derecha, ...)`

Une dos tablas por sus identificadores. Sirve para llevar al nivel de contrato
las variables que viven en la tabla de procesos.

Si alguna de las llaves no existe, no falla: registra una advertencia y devuelve
la tabla izquierda intacta.

### `procesar(...)`

Encadena todo lo anterior en una sola llamada. Cada paso es opcional: si no se
le pasan columnas de moneda, se salta ese paso.

**Un detalle importante:** si una columna configurada no existe en los datos, se
ignora en silencio. Es lo razonable para una función genérica, pero significa
que una configuración equivocada produce datos sin limpiar sin avisar. La
interfaz compensa esto mostrando en pantalla qué columnas configuradas no se
encontraron.

---

## 6. `src/pipeline.py` — el orquestador

Punto de entrada principal. No implementa nada propio: llama a las librerías en
orden según la configuración.

```powershell
python -m src.pipeline --config config/config.yaml
```

`ejecutar()` hace: abrir cliente → extraer → verificar que vino algo → traducir
las duraciones del formato del YAML al que espera `procesar()` → procesar →
guardar el CSV con marca de tiempo en el nombre, para no pisar corridas
anteriores.

También contiene las tres funciones de configuración:

- `cargar_config()` — lee el YAML.
- `guardar_config()` — lo reescribe. Vuelca cada clave precedida de su
  comentario, porque el volcado automático de YAML los borraría y el archivo
  dejaría de explicarse solo. **Nunca escribe el app token**, aunque venga con
  valor: el repositorio es público.
- `token_efectivo()` — decide qué token usar: el del archivo, o la variable de
  entorno `SECOP_APP_TOKEN`.

---

## 7. Las otras dos formas de correrlo

### `src/procesar_csv.py`

Aplica la misma limpieza a un CSV ya descargado a mano del portal, sin usar la
API. Útil para descargas grandes, donde bajar el archivo filtrado desde la web
resulta más práctico.

```powershell
python -m src.procesar_csv --entrada data/raw/archivo.csv
```

### `src/flujo_vigia.py`

Construye la base al nivel de contrato uniendo contratos con procesos: extrae
ambas tablas, calcula duraciones, reconcilia los procesos y une por el
identificador del proceso. Es el insumo del reporte descriptivo.

**La llave se llama distinto en cada tabla, y no es la evidente:**
`proceso_de_compra` en contratos (`CO1.BDOS.*`) e **`id_del_portafolio`** en
procesos. La columna `id_del_proceso` guarda otro identificador (`CO1.REQ.*`)
que no aparece en contratos; unir por ahí da cero coincidencias.

**Los filtros se adaptan, no se copian.** `filtros_para_procesos()` toma los
filtros escritos para contratos y hace dos ajustes:

- El rango de fechas se traslada a la fecha de publicación del proceso y **se
  corre hacia atrás** los meses que indique `margen_meses_procesos` (6 por
  defecto). Un proceso publicado en noviembre puede producir un contrato firmado
  en enero; filtrar ambas tablas al mismo periodo dejaría sin proceso a los
  contratos del comienzo de la ventana, y ese sesgo no sería aleatorio.
- Los demás filtros se traducen antes de aplicarse, porque algunas columnas
  equivalentes se llaman distinto en cada tabla: la entidad es `nombre_entidad`
  en contratos y `entidad` en procesos. Si no existe equivalente, el filtro se
  descarta — pedir una columna inexistente hace fallar la consulta. Perder el
  filtro de entidad es grave: la consulta de procesos sale sin acotar y trae
  registros de todo el país que no cruzan con nada.

**Antes de unir se cuenta cuántos contratos encuentran su proceso**, y se avisa
si son cero. Sin esa cuenta, una llave equivocada pasa desapercibida: la unión
devuelve los contratos intactos y el resultado parece correcto.

Queda pendiente una mejora: en vez de una ventana con margen, extraer los
contratos primero y consultar únicamente los procesos cuyos identificadores
aparezcan ahí. Es exacto y no descarta nada, pero necesita una cláusula `IN` que
el constructor de filtros todavía no soporta.

---

## 8. `app.py` — la interfaz

Formulario web sobre los mismos módulos. No implementa lógica propia.

Lo que aporta sobre el YAML:

- **Desplegables poblados desde el portal**, en vez de escribir nombres a
  ciegas. Cuando el portal no tiene valores en caché para una columna —pasa en
  las tablas grandes—, hay un botón que los consulta solo para esa columna.
- **Muestra la consulta antes de ejecutarla.** Cuando un filtro devuelve cero
  filas, ver la consulta generada dice de inmediato si el problema es el nombre
  de la columna o el valor.
- **Avisa de columnas inexistentes** tras procesar.
- **Guarda la configuración** de vuelta al YAML o la descarga aparte.

```powershell
streamlit run app.py
```

Nota práctica: Streamlit vuelve a ejecutar `app.py` en cada interacción, pero
**no recarga los módulos importados**. Si se modifica algo en `src/`, hay que
detener el servidor y volver a lanzarlo.

---

## 8bis. El registro de ejecución (logs)

Cada corrida deja constancia en `logs/secop2.log`: qué consulta se lanzó,
cuántas filas llegaron, qué columnas se convirtieron, qué advertencias
aparecieron. Se conserva también la traza completa de cualquier error.

Existe porque los avisos que aparecen en la terminal se pierden al cerrarla, y
son justo los que hacen falta cuando hay que entender por qué una extracción
salió mal. El caso del formato de fechas es el ejemplo: la advertencia estaba
ahí, pero solo mientras la ventana siguiera abierta.

`configurar_logging()`, en `pipeline.py`, monta dos destinos: la consola, con
formato corto, y el archivo, con formato completo incluyendo el módulo que
emitió cada mensaje. El archivo rota al llegar a 1 MB y se conservan cinco
anteriores, para que no crezca sin límite.

La carpeta `logs/` no se versiona: son registros de cada máquina, no del
proyecto.

Un ejemplo de lo que queda guardado:

```
2026-09-01 00:30:13,215 | WARNING  | src.procesamiento | Columna 'fecha_de_firma': el formato '%m/%d/%Y' no coincide con los datos; se infirió el formato.
2026-09-01 00:30:13,233 | INFO     | src.procesamiento | Columna de moneda 'valor_del_contrato' convertida
2026-09-01 00:30:13,238 | INFO     | src.procesamiento | Procesamiento finalizado: 2 filas, 7 columnas
```

---

## 9. La configuración

| Clave | Para qué |
|---|---|
| `app_token` | Token de Socrata. Se deja vacío; se usa la variable de entorno |
| `tabla` | Cuál de las cinco tablas |
| `tamano_pagina` | Filas por petición a la API |
| `limite_total` | Tope de filas. `null` = todo lo que devuelva el filtro |
| `filtros` | Qué filas traer |
| `columnas_fecha` | Cuáles convertir a fecha |
| `formato_fecha` | Formato de la fuente; se infiere si no coincide |
| `columnas_moneda` | Cuáles limpiar como monto |
| `duraciones` | Qué variables de días construir |
| `margen_meses_procesos` | Solo para `flujo_vigia`: cuántos meses antes buscar los procesos |

**Advertencia:** las claves de limpieza están escritas para la tabla de
contratos. Al cambiar `tabla` hay que revisarlas, porque las columnas de
`procesos` o `proveedores` se llaman distinto.

---

## 10. Lo que se aprendió de los datos de SECOP 2

Cosas que no están documentadas en el portal y costaron tiempo:

- **Los nombres de columna del portal no son los de la API.** "Fecha de Firma"
  se consulta como `fecha_de_firma`.
- **Las fechas llegan en formatos distintos según la fuente**: ISO por la API,
  MM/DD/YYYY por el CSV.
- **Los montos también**: número plano por la API, texto con `$` y puntos de
  miles por el CSV.
- **Los filtros son sensibles a tildes y mayúsculas.** `Bogotá` y `BOGOTA` no
  son lo mismo.
- **Algunas columnas llegan como diccionarios**, no como texto: las de tipo URL
  y ubicación. No se pueden comparar entre sí, así que quedan fuera del cotejo
  de filas idénticas.
- **La API omite las columnas totalmente vacías**, así que el número de columnas
  varía según el filtro. Dos extracciones de la misma tabla pueden traer 86 y 87
  columnas.
- **El portal no cachea valores de ejemplo para todas las columnas.** En la
  tabla de contratos casi ninguna los trae; en procesos, varias sí.
- **La llave que relaciona contratos con procesos** es `proceso_de_compra` en
  contratos e `id_del_portafolio` en procesos. Ambas guardan `CO1.BDOS.*`. El
  `id_del_proceso` de la tabla de procesos es otra cosa (`CO1.REQ.*`).
- **Procesos tiene dos fechas de publicación con nombres casi iguales**:
  `fecha_de_publicacion` está poblada en menos del 1% de los registros y
  `fecha_de_publicacion_del` en el 99%. Filtrar por la primera devuelve casi
  nada sin que parezca un error.
- **La entidad se escribe distinto según la tabla**: en procesos aparecen
  nombres completos, aunque algunas entidades sí usan sigla.

---

## 11. Estado y limitaciones conocidas

**Funciona y está probado contra datos reales:**

- Extracción por API con filtros y paginación.
- Limpieza de fechas, montos, duplicados y duraciones.
- Parametrización por YAML y por interfaz.
- Ruta de CSV local.

**Decisión metodológica: no se eliminan duplicados.** El pipeline tuvo en algún
momento un paso que descartaba filas repetidas por identificador de contrato. Se
retiró por indicación del asesor: en SECOP 2 una fila repetida no es
necesariamente un error, y descartarla puede eliminar información legítima. El
tratamiento de registros repetidos queda para el análisis, donde se puede
decidir con criterio caso por caso. La reconciliación de la tabla de procesos,
que sí resuelve conflictos, se conserva porque responde a otro problema.

**Sin resolver:**

1. **`flujo_vigia.py` falta terminar de validar.** La llave (`id_del_portafolio`)
   y la fecha (`fecha_de_publicacion_del`) están confirmadas contra los datos,
   pero falta una corrida completa que muestre qué porcentaje de contratos
   encuentra su proceso.
2. **No hay pruebas automatizadas.** El error de las fechas se habría detectado
   con unas pocas líneas de prueba.
3. **El constructor de filtros es limitado**: sin `LIKE`, sin `IN`, sin
   comparaciones numéricas.

---

## 12. Relación con los entregables

| Entregable | Estado |
|---|---|
| 1. Pipeline de extracción y procesamiento | Funcionando y probado |
| 2. Parametrización | YAML + interfaz web |
| 3. Reporte descriptivo | Primeras cifras obtenidas; falta el análisis |

### Primeras cifras (UNP, Bogotá, 2025 — 3.273 contratos)

- **Firma posterior al inicio: 0 casos.** Contrasta con el 5,8% medido en
  Bogotá/sector Transporte, lo que sugiere que el indicador discrimina entre
  entidades.
- **Contratación directa: 98,0%.** Pero 3.207 de los 3.273 son prestación de
  servicios, figura que se contrata directamente por norma. El dato refleja el
  tipo de entidad más que una anomalía; un índice que no distinga esto produce
  falsos positivos.
- **Prórrogas: 41,9%** con días adicionados (hasta 326 días). Es la señal más
  fuerte del conjunto.
- **Concentración de proveedores: nula.** 2.498 proveedores para 3.273
  contratos; el mayor con 3.
- **Valores:** total $1,26 billones, mediana $36 millones. Hay un contrato de
  $158.001.612.800 que concentra el 12,6% del total y está cinco órdenes de
  magnitud por encima de la mediana. Hay que verificarlo antes de calcular
  cualquier estadística de valor.
