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
│   └── pipeline.py         # Orquestador: extrae -> procesa -> guarda
├── data/
│   ├── raw/                # Datos crudos (no se versionan)
│   └── processed/          # Datos procesados de salida (no se versionan)
├── requirements.txt
└── README.md
```

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

Edita `config/config.yaml` para definir qué extraer y ejecuta:

```bash
python -m src.pipeline --config config/config.yaml
```

El resultado se guarda en `data/processed/` como un CSV con marca de tiempo.
