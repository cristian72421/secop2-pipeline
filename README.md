# Pipeline de extracción y procesamiento de datos de SECOP 2

Pipeline en Python para extraer, procesar y analizar datos de contratación
pública de **SECOP 2** (Sistema Electrónico de Contratación Pública), a partir
del portal de datos abiertos de Colombia ([datos.gov.co](https://www.datos.gov.co))
mediante la **Socrata Open Data API (SODA)**.

Monitoría de investigación — Beca Avanza, Maestría en Ingeniería Industrial,
Universidad de los Andes. Asesor: prof. Juan Fernando Pérez.

## Objetivo

Sentar las bases para el análisis de datos de contratación pública con miras a
la **detección temprana de riesgos**. Este repositorio corresponde a los
primeros entregables de la monitoría:

1. **Extracción y procesamiento inicial** de datos de SECOP 2, considerando las
   diferentes tablas disponibles.
2. **Parametrización** del pipeline (entidad, periodo de tiempo, entre otros).
3. **Reporte descriptivo** de contratación a partir de los datos procesados.

## Estructura del repositorio

```
secop2-pipeline/
├── config/
│   └── config.yaml         # Parámetros de extracción (tabla, filtros, columnas)
├── src/
│   ├── extraccion.py       # Conexión y descarga desde la API de Socrata
│   ├── procesamiento.py    # Limpieza y estandarización de los datos
│   ├── pipeline.py         # Orquestador: extrae -> procesa -> guarda
│   ├── procesar_csv.py     # Procesa un CSV ya descargado (sin API)
│   └── flujo_vigia.py      # Flujo multi-tabla: contratos + procesos
├── app.py                  # Interfaz web (Streamlit) para armar la consulta
├── data/
│   ├── raw/                # Datos crudos (no se versionan)
│   └── processed/          # Datos procesados de salida (no se versionan)
├── notebooks/
│   └── 01_exploracion.ipynb  # Exploración inicial de las tablas
├── requirements.txt
└── README.md
```

## Tablas de SECOP 2 disponibles

El pipeline reconoce estas tablas (identificadores de dataset en Socrata):

| Clave         | Dataset                              | ID Socrata  |
|---------------|--------------------------------------|-------------|
| `contratos`   | SECOP II - Contratos Electrónicos    | `jbjy-vk9h` |
| `procesos`    | SECOP II - Procesos de Contratación  | `p6dx-8zbt` |
| `proveedores` | SECOP II - Proveedores Registrados   | `qmzu-gj57` |
| `adiciones`   | SECOP II - Adiciones                 | `cb9c-h8sn` |
| `integrado`   | SECOP Integrado (SECOP I + II)       | `rpmr-utcd` |

Estas son las tablas que usa **VigIA** (Salazar, Pérez & Gallego, 2024) para
construir los modelos e índices de riesgo: contratos es la tabla principal
(unidad = contrato); procesos aporta variables del proceso (ofertas, período
de publicación); proveedores aporta el tipo y antigüedad del contratista; y
adiciones registra sobrecostos y prórrogas (base de las variables objetivo).

> Los identificadores pueden cambiar; verifícalos en
> [datos.gov.co](https://www.datos.gov.co) si una tabla deja de responder.

## Instalación

```bash
# 1. Clonar el repositorio
git clone <url-del-repo>
cd secop2-pipeline

# 2. (Recomendado) crear un entorno virtual
python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

## Uso

### 1. Configurar la extracción

Edita `config/config.yaml` para definir qué extraer, **sin tocar el código**:

```yaml
tabla: contratos               # contratos | procesos | integrado
limite_total: 5000             # usa un tope pequeño para pruebas; null = todo
filtros:
  nombre_entidad: "INSTITUTO NACIONAL DE VIAS (INVIAS)"
  # fecha_de_firma:
  #   desde: "2024-01-01"
  #   hasta: "2024-12-31"
```

### 2. Ejecutar el pipeline

```bash
python -m src.pipeline --config config/config.yaml
```

El resultado se guarda en `data/processed/` como un CSV con marca de tiempo,
por ejemplo `secop2_contratos_20260825_140501.csv`.

### App token (opcional pero recomendado)

El acceso es público, pero registrar un
[app token de Socrata](https://dev.socrata.com/docs/app-tokens.html) mejora los
límites de la API. Una vez lo tengas, ponlo en `config.yaml`:

```yaml
app_token: "TU_TOKEN_AQUI"
```

### Interfaz web

Para armar la consulta sin editar el YAML:

```bash
streamlit run app.py
```

Se abre en el navegador con los valores de `config/config.yaml` como punto de
partida. Permite elegir la tabla, agregar filtros, definir un rango de fechas y
fijar el tope de filas; muestra la consulta SoQL resultante antes de lanzarla,
y al terminar deja descargar el CSV procesado y el YAML equivalente a lo
seleccionado.

### Flujo multi-tabla (estilo VigIA)

Además del pipeline de una sola tabla, `src/flujo_vigia.py` demuestra cómo
combinar varias tablas para dejar todo al nivel de contrato, replicando el
tratamiento del artículo VigIA:

```bash
python -m src.flujo_vigia --config config/config.yaml --limite 5000
```

Este flujo:
1. Extrae **contratos** y **procesos**.
2. Calcula **duraciones** entre las fechas clave del contrato (firma→inicio,
   inicio→fin). Nota: una firma posterior a la fecha de inicio produce una
   duración negativa, que se conserva porque es una señal de riesgo.
3. **Reconcilia** los procesos duplicados conservando la fecha de publicación
   más antigua ante conflictos.
4. **Une** contratos con procesos por el ID de proceso.

El resultado (`data/processed/base_contratos_vigia.csv`) es la base sobre la
que se construyen el reporte descriptivo (Entregable 3) y, más adelante, los
modelos e índices de riesgo.

## Notas sobre los datos

- En **SECOP II**, procesos y contratos son entidades distintas: un contrato es
  resultado de un proceso de contratación. Se relacionan por sus identificadores
  (`id_proceso` en procesos, `id_contrato` en contratos).
- Los nombres exactos de las columnas se verifican explorando cada dataset
  (ver `notebooks/01_exploracion.ipynb`), ya que pueden variar entre tablas.
- La API de Socrata omite columnas totalmente vacías, lo que puede generar
  diferencias con lo descrito en el portal.

## Próximos pasos

- Enriquecer el reporte descriptivo con indicadores de contratación.
- Sentar las bases para modelos de **detección temprana de riesgos**.
