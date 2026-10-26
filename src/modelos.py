"""
Red neuronal para predecir si un contrato va a tener prórroga.

Sigue los cuadernos del curso Analítica Computacional para la Toma de
Decisiones (ACTD 2026-20):

- `actd_redes_clasif_dataset_heart_starter.ipynb` (clases 15-16): las
  funciones `dataframe_to_dataset`, `encode_numerical_feature` y
  `encode_categorical_feature`; una entrada por variable; una capa densa de 32
  neuronas con activación relu y una salida de 1 neurona con activación
  sigmoide; `adam`, `binary_crossentropy`, métricas `accuracy` y `recall`,
  lotes de 32 y 50 épocas; partición 80/20 con `random_state=100` y validación
  del 20% del entrenamiento.
- `actd_redes_reg_starter.ipynb` (clases 11-12): `dropna` para los NAs,
  `history` y `test_res` con `evaluate`.
- `actd_redes_clasif_init_iris_mnist_starter.ipynb`: `tf.random.set_seed(42)`
  y `clear_session()` antes de crear el modelo.

Lo único propio del proyecto es `preparar`, que arma la tabla a partir de
SECOP 2 (el equivalente a `heart.csv`).

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

OBJETIVO = "dias_adicionados"

# Columnas que SECOP 2 actualiza después de la firma. Cada una se comprobó
# contra los datos de ANT, UNP y ARN (2022 a 2026):
VARIABLES_PROHIBIDAS = {
    # El 66% de los "Modificado" tiene prórroga; ninguno de "En ejecución".
    "estado_contrato": "cambia a «Modificado» justamente cuando hay prórroga",
    # En la UNP, con prórroga el valor es 1,5 veces el precio base (mediana);
    # sin ella, 1,0. El valor del contrato ya incluye la adición.
    "valor_del_contrato": "se actualiza con las adiciones en valor",
    "dias_adicionados": "es la respuesta",
    "ultima_actualizacion": "fecha de la última modificación",
    "valor_pagado": "se conoce durante la ejecución",
    "valor_facturado": "se conoce durante la ejecución",
    "valor_pendiente_de_pago": "se conoce durante la ejecución",
    "valor_pendiente_de_ejecucion": "se conoce durante la ejecución",
    "liquidaci_n": "se conoce al final",
}

# Variables que sí se conocen al firmar. Las que la tabla no traiga se omiten.
CATEGORICAS = (
    "modalidad_de_contratacion",
    "tipo_de_contrato",
    "justificacion_modalidad_de",
    "nombre_entidad",
    "tipodocproveedor",            # cédula = persona natural
    "es_pyme",
    "destino_gasto",               # funcionamiento o inversión
    "origen_de_los_recursos",
    "el_contrato_puede_ser_prorrogado",
    "segmento_unspsc",             # se deriva del código de categoría
)
# Categóricas que vienen como número, como `sex`, `cp` o `ca` en el cuaderno heart.
CATEGORICAS_ENTERAS = ("mes_de_firma",)
NUMERICAS = (
    "log_precio_base",             # el valor estimado antes de firmar
    "duracion_planeada",           # días entre inicio y fin pactados
    "dias_firma_a_inicio",
    "respuestas_al_procedimiento",
)

def preparar(df: pd.DataFrame, fecha_corte=None) -> pd.DataFrame:
    """
    La tabla lista para modelar: variables al firmar, la respuesta y la fecha.

    Solo entran contratos cuyo fin pactado ya pasó a `fecha_corte` (hoy por
    defecto). Uno que sigue en ejecución todavía puede recibir su prórroga, y
    contarlo como "sin prórroga" sería decir algo que no se sabe. La fecha de
    fin sirve para esto porque SECOP no la mueve al prorrogar: se comprobó que
    la diferencia con la duración pactada es la misma con y sin prórroga.
    """
    necesarias = {OBJETIVO, "fecha_de_firma"}
    if df.empty or not necesarias.issubset(df.columns):
        return pd.DataFrame()

    firma = pd.to_datetime(df["fecha_de_firma"], errors="coerce")
    inicio = pd.to_datetime(df.get("fecha_de_inicio_del_contrato"), errors="coerce")
    fin = pd.to_datetime(df.get("fecha_de_fin_del_contrato"), errors="coerce")

    tabla = pd.DataFrame(index=df.index)
    for col in CATEGORICAS:
        if col in df.columns:
            # Texto plano (object), que es lo que tf.data convierte a string.
            tabla[col] = df[col].fillna("Sin dato").astype(str)
    if "codigo_de_categoria_principal" in df.columns:
        # "V1.80111701" -> "80": el segmento agrupa en decenas de familias lo
        # que el código completo reparte en miles.
        tabla["segmento_unspsc"] = (
            df["codigo_de_categoria_principal"].astype("string")
            .str.extract(r"(\d{2})", expand=False).fillna("Sin dato").astype(str)
        )

    if "precio_base" in df.columns:
        precio = pd.to_numeric(df["precio_base"], errors="coerce")
        tabla["log_precio_base"] = np.log10(precio.where(precio > 0))
    if inicio is not None and fin is not None:
        tabla["duracion_planeada"] = (fin - inicio).dt.days
    if inicio is not None:
        tabla["dias_firma_a_inicio"] = (inicio - firma).dt.days
    if "respuestas_al_procedimiento" in df.columns:
        tabla["respuestas_al_procedimiento"] = pd.to_numeric(
            df["respuestas_al_procedimiento"], errors="coerce")
    tabla["mes_de_firma"] = firma.dt.month

    tabla["fecha_de_firma"] = firma
    tabla["prorroga"] = (pd.to_numeric(df[OBJETIVO], errors="coerce") > 0).astype(int)

    corte = pd.Timestamp(fecha_corte) if fecha_corte else pd.Timestamp.today().normalize()
    terminado = fin <= corte if fin is not None else pd.Series(True, index=df.index)
    tabla = tabla.loc[terminado.fillna(False) & firma.notna()]
    # Sin fechas vacías el mes ya es entero; IntegerLookup lo necesita así.
    tabla["mes_de_firma"] = tabla["mes_de_firma"].astype("int64")

    logger.info("Tabla para modelar: %d contratos terminados, %.1f%% con prórroga",
                len(tabla), 100 * tabla["prorroga"].mean() if len(tabla) else 0)
    return tabla


def variables(tabla: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    """
    Las variables presentes, separadas como en el cuaderno heart:
    categóricas enteras, categóricas de texto y numéricas. Ninguna prohibida.
    """
    def presentes(nombres):
        return [c for c in nombres
                if c in tabla.columns and c not in VARIABLES_PROHIBIDAS
                # Una columna sin variación no enseña nada y a la red le estorba.
                and tabla[c].nunique(dropna=True) > 1]
    return presentes(CATEGORICAS_ENTERAS), presentes(CATEGORICAS), presentes(NUMERICAS)


EPOCAS = 50
batch_size = 32


def _keras():
    """
    TensorFlow se importa solo al entrenar: tarda varios segundos y el resto
    de la aplicación no lo necesita. Keras debe usar TensorFlow como backend
    para que el modelo acepte strings como entradas, como en el cuaderno.
    """
    os.environ.setdefault("KERAS_BACKEND", "tensorflow")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    import keras
    import tensorflow as tf
    return tf, keras


def dataframe_to_dataset(dataframe):
    """Convierte de dataframe (pandas) a dataset (tensorflow), separando características y etiquetas."""
    tf, _ = _keras()
    dataframe = dataframe.copy()
    labels = dataframe.pop("target")
    ds = tf.data.Dataset.from_tensor_slices((dict(dataframe), labels))
    ds = ds.shuffle(buffer_size=len(dataframe))
    return ds


def encode_numerical_feature(feature, name, dataset):
    """Función para codificar variables numéricas (Keras docs)."""
    tf, keras = _keras()
    # Crea capa de normalización para este feature
    normalizer = keras.layers.Normalization()

    # Prepara el dataset para considerar únicamente la feature de interés (name)
    feature_ds = dataset.map(lambda x, y: x[name]) # selecciona variable
    feature_ds = feature_ds.map(lambda x: tf.expand_dims(x, -1)) # deja el tensor de una dimensión

    # Aprende las estadísticas de los datos (media, varianza)
    normalizer.adapt(feature_ds)

    # Aplica la normalización a la variable
    encoded_feature = normalizer(feature)
    return encoded_feature


def encode_categorical_feature(feature, name, dataset, is_string):
    """Función para codificar variables categóricas (Keras docs)."""
    tf, keras = _keras()
    lookup_class = keras.layers.StringLookup if is_string else keras.layers.IntegerLookup
    # Crea una capa Lookup para retornar variables 0/1 (dummies)
    # lookup: busca el valor correspondiente de la variable categórica
    lookup = lookup_class(output_mode="binary")

    # Prepara el dataset para considerar únicamente la feature de interés (name)
    feature_ds = dataset.map(lambda x, y: x[name]) # selecciona variable
    feature_ds = feature_ds.map(lambda x: tf.expand_dims(x, -1)) # deja el tensor de una dimensión

    # Aprende el conjunto de posibles valores que toma la variable categórica y asigna enteros
    lookup.adapt(feature_ds)

    # Aplica la conversión de categorías a enteros
    encoded_feature = lookup(feature)
    return encoded_feature


def entrenar_red(tabla: pd.DataFrame, epocas: int = EPOCAS) -> dict:
    """
    Los pasos del cuaderno heart, en el mismo orden, sobre la tabla de `preparar`.

    Devuelve el modelo, el historial de entrenamiento, `test_res` (pérdida,
    accuracy y recall en prueba) y el tamaño de cada conjunto.
    """
    tf, keras = _keras()

    # Definimos listas para las variables categóricas enteras, categóricas string y numéricas
    cat_int_feats, cat_str_feats, num_feats = variables(tabla)
    feats_ordered = cat_int_feats+cat_str_feats+num_feats

    # Reordenamos el dataframe de acuerdo con el tipo de variable
    df = tabla.rename(columns={"prorroga": "target"})
    df = df[feats_ordered+["target"]]
    df = df.dropna()

    # Separamos los datos en entrenamiento, validación y prueba
    train = df.sample(frac=0.8, random_state=100)
    test = df.drop(train.index)
    val = train.sample(frac=0.2, random_state=100)
    train = train.drop(val.index)

    tf.random.set_seed(42)
    tf.keras.backend.clear_session()

    train_ds = dataframe_to_dataset(train)
    val_ds = dataframe_to_dataset(val)
    test_ds = dataframe_to_dataset(test)

    # Agrupamos los datos de entrenamiento, validación y prueba en lotes
    train_ds = train_ds.batch(batch_size)
    test_ds = test_ds.batch(batch_size)
    val_ds = val_ds.batch(batch_size)

    # Creamos una lista de inputs para el modelo, de acuerdo con cada tipo de variable
    inputs = []
    for i in cat_int_feats:
      inputs.append(keras.Input(shape=(1,), name=i, dtype="int64"))
    for i in cat_str_feats:
      inputs.append(keras.Input(shape=(1,), name=i, dtype="string"))
    for i in num_feats:
      inputs.append(keras.Input(shape=(1,), name=i))

    # Creamos una lista de variables codificadas/normalizadas de acuerdo con su tipo
    feats_encoded=[]
    for i,feat in enumerate(cat_int_feats):
      feats_encoded.append(
          encode_categorical_feature(inputs[i], feat, train_ds, False)
      )
    len_feats = len(feats_encoded)
    for i,feat in enumerate(cat_str_feats):
      feats_encoded.append(
          encode_categorical_feature(inputs[len_feats+i], feat, train_ds, True)
      )
    len_feats = len(feats_encoded)
    for i,feat in enumerate(num_feats):
      feats_encoded.append(
          encode_numerical_feature(inputs[len_feats+i], feat, train_ds)
      )

    # Creamos una capa concatenando todas las variables codificadas
    all_feats = keras.layers.concatenate(feats_encoded)

    # Capa densa con 32 neuronas y función de activación relu
    model_layers = keras.layers.Dense(32, activation='relu')(all_feats)

    # Capa de salida con 1 neurona y función de activación sigmoide
    model_layers = keras.layers.Dense(1, activation='sigmoid')(model_layers)

    # Creamos el modelo con las capas ya creadas y las variables de entrada
    model = keras.Model(inputs, model_layers)

    # Compilamos el modelo, definiendo optimizador, función de pérdida y métricas
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy', 'recall'])

    # Entrenamos el modelo con los datos en el formato tf.Dataset
    history = model.fit(train_ds, epochs=epocas, validation_data=val_ds, verbose=0)

    # Evaluamos en prueba
    test_res = model.evaluate(test_ds, verbose=0, return_dict=True)

    logger.info("Red entrenada: %d entrenamiento, %d validación, %d prueba; %s",
                len(train), len(val), len(test), test_res)
    return {"model": model, "history": history, "test_res": test_res,
            "train": len(train), "val": len(val), "test": len(test)}
