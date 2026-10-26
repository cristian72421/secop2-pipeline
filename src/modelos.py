"""
Modelos para predecir si un contrato va a tener prórroga.

Es la tarea de VigIA (Salazar, Pérez y Gallego, 2024): anticipar retrasos al
nivel de contrato para priorizar la vigilancia. Aquí se comparan tres cosas con
los mismos datos y la misma división:

1. **Línea base**: decir siempre que no habrá prórroga. Es lo que hay que
   superar; si un modelo no lo hace, no aporta.
2. **Regresión logística**: el modelo clásico, cuyos coeficientes se leen.
3. **Red neuronal**: la misma del cuaderno de clasificación del curso
   (ACTD, clases 15-16, datos `heart`): una entrada por variable, `Normalization`
   para las numéricas, `IntegerLookup`/`StringLookup` para las categóricas, una
   capa densa de 32 neuronas con ReLU y una salida sigmoide. Adam, entropía
   cruzada binaria, lotes de 32 y 50 épocas. Las funciones
   `dataframe_to_dataset`, `encode_numerical_feature` y
   `encode_categorical_feature` son las de ese cuaderno.

Dos decisiones sostienen que el resultado sea creíble:

- **Solo variables que se conocen al firmar.** Varias columnas de SECOP 2 se
  actualizan después: medidas contra los datos, dejarlas dentro haría que el
  modelo "adivinara" con información del futuro (ver `VARIABLES_PROHIBIDAS`).
- **Se entrena con contratos viejos y se evalúa con nuevos**, no mezclados al
  azar. Es como se usaría de verdad, y si el modelo empeora con el tiempo eso
  también dice que el comportamiento cambió.

Monitoría de investigación - Beca Avanza, Universidad de los Andes.
"""

from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

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
# Categóricas que vienen como número. El mes no es una cantidad: enero y
# diciembre no están "lejos" en el sentido que importa, así que cada mes lleva
# su propia columna, como `slope` y `ca` en el cuaderno heart.
CATEGORICAS_ENTERAS = ("mes_de_firma",)
NUMERICAS = (
    "log_precio_base",             # el valor estimado antes de firmar
    "duracion_planeada",           # días entre inicio y fin pactados
    "dias_firma_a_inicio",
    "respuestas_al_procedimiento",
)

MODELOS = ("Línea base", "Regresión logística", "Red neuronal")

# Cómo se llaman las variables en las gráficas, para no enseñar nombres de columna.
NOMBRES = {
    "modalidad_de_contratacion": "Modalidad",
    "tipo_de_contrato": "Tipo de contrato",
    "justificacion_modalidad_de": "Causal invocada",
    "nombre_entidad": "Entidad",
    "tipodocproveedor": "Persona natural o jurídica",
    "es_pyme": "Es pyme",
    "destino_gasto": "Funcionamiento o inversión",
    "origen_de_los_recursos": "Origen de los recursos",
    "el_contrato_puede_ser_prorrogado": "Cláusula de prórroga",
    "segmento_unspsc": "Segmento del bien o servicio",
    "log_precio_base": "Precio base",
    "duracion_planeada": "Duración pactada",
    "dias_firma_a_inicio": "Días de la firma al inicio",
    "respuestas_al_procedimiento": "Ofertas recibidas",
    "mes_de_firma": "Mes de firma",
}


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


def dividir_en_el_tiempo(tabla: pd.DataFrame, fecha_division) -> tuple[pd.Series, pd.Series]:
    """Entrena con lo firmado antes de la fecha; evalúa con lo firmado después."""
    division = pd.Timestamp(fecha_division)
    return tabla["fecha_de_firma"] < division, tabla["fecha_de_firma"] >= division


def _preprocesador(cat: list[str], num: list[str]) -> ColumnTransformer:
    return ColumnTransformer([
        # Las categorías raras se agrupan: con pocas filas no hay qué aprender.
        ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist",
                              min_frequency=20, sparse_output=False), cat),
        ("num", Pipeline([("imputar", SimpleImputer(strategy="median")),
                          ("escalar", StandardScaler())]), num),
    ])


def logistica(cat_int: list[str], cat_str: list[str], num: list[str]) -> Pipeline:
    """La regresión logística, con las mismas variables que la red."""
    return Pipeline([
        ("preparar", _preprocesador(cat_int + cat_str, num)),
        ("modelo", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])


# ----------------------------------------------------------------------------
# La red neuronal, como en el cuaderno de clasificación del curso
# ----------------------------------------------------------------------------

NEURONAS = 32
TAMANO_LOTE = 32
EPOCAS = 50


def _keras():
    """
    TensorFlow se importa solo cuando se usa la red: tarda varios segundos y
    el resto de la aplicación no lo necesita. El backend tiene que ser
    TensorFlow para que el modelo acepte texto como entrada, igual que en clase.
    """
    os.environ.setdefault("KERAS_BACKEND", "tensorflow")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    import keras
    import tensorflow as tf
    return tf, keras


def dataframe_to_dataset(dataframe: pd.DataFrame, barajar: bool = True,
                         semilla: int = 100):
    """
    Convierte de dataframe (pandas) a dataset (tensorflow), separando
    características y etiquetas. Solo el de entrenamiento se baraja; validación
    y prueba quedan en orden para que las predicciones coincidan con las
    etiquetas.
    """
    tf, _ = _keras()
    dataframe = dataframe.copy()
    labels = dataframe.pop("prorroga")
    ds = tf.data.Dataset.from_tensor_slices((dict(dataframe), labels))
    if barajar:
        ds = ds.shuffle(buffer_size=len(dataframe), seed=semilla)
    return ds


def encode_numerical_feature(feature, name, dataset):
    """Variable numérica: resta la media y divide por la desviación estándar."""
    tf, keras = _keras()
    # Crea capa de normalización para este feature
    normalizer = keras.layers.Normalization()
    # Prepara el dataset para considerar únicamente la feature de interés (name)
    feature_ds = dataset.map(lambda x, y: x[name])
    feature_ds = feature_ds.map(lambda x: tf.expand_dims(x, -1))
    # Aprende las estadísticas de los datos (media, varianza)
    normalizer.adapt(feature_ds)
    # Aplica la normalización a la variable
    return normalizer(feature)


def encode_categorical_feature(feature, name, dataset, is_string):
    """Variable categórica: una columna 0/1 por categoría (dummies)."""
    tf, keras = _keras()
    lookup_class = keras.layers.StringLookup if is_string else keras.layers.IntegerLookup
    # Crea una capa Lookup para retornar variables 0/1 (dummies)
    lookup = lookup_class(output_mode="binary")
    # Prepara el dataset para considerar únicamente la feature de interés (name)
    feature_ds = dataset.map(lambda x, y: x[name])
    feature_ds = feature_ds.map(lambda x: tf.expand_dims(x, -1))
    # Aprende el conjunto de posibles valores que toma la variable categórica
    lookup.adapt(feature_ds)
    # Aplica la conversión de categorías a dummies
    return lookup(feature)


class RedNeuronal:
    """
    La red del cuaderno heart, con `fit` y `predict_proba` para usarla igual
    que la logística.

    Arquitectura: una entrada por variable, cada una codificada según su tipo,
    todas concatenadas, una capa densa de 32 neuronas con ReLU y una neurona de
    salida sigmoide (la probabilidad de prórroga). Adam, entropía cruzada
    binaria, lotes de 32 y 50 épocas.

    La validación sale como en clase: el 20% del entrenamiento al azar con
    `random_state=100`. Lo único que cambia frente al cuaderno es la prueba,
    que aquí son los contratos posteriores y no un 20% al azar.
    """

    def __init__(self, cat_int: list[str], cat_str: list[str], num: list[str],
                 epocas: int = EPOCAS, semilla: int = 0, verbose: int = 0):
        self.cat_int, self.cat_str, self.num = list(cat_int), list(cat_str), list(num)
        self.feats = self.cat_int + self.cat_str + self.num
        self.epocas, self.semilla, self.verbose = epocas, semilla, verbose

    def _formato(self, X: pd.DataFrame) -> pd.DataFrame:
        """Cada columna con el tipo que espera su entrada."""
        X = X[self.feats].copy()
        for c in self.cat_int:
            X[c] = X[c].fillna(0).astype("int64")
        for c in self.cat_str:
            X[c] = X[c].astype(str)
        for c in self.num:
            # El cuaderno no tenía vacíos; aquí sí. Se llenan con la mediana
            # de entrenamiento, para no usar nada de la prueba.
            X[c] = X[c].astype("float64").fillna(self.medianas_[c]).astype("float32")
        return X

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "RedNeuronal":
        tf, keras = _keras()
        self.medianas_ = X[self.num].median()
        datos = self._formato(X).assign(prorroga=np.asarray(y, dtype="int64"))

        # Separamos los datos en entrenamiento y validación
        val = datos.sample(frac=0.2, random_state=100)
        train = datos.drop(val.index)

        train_ds = dataframe_to_dataset(train).batch(TAMANO_LOTE)
        val_ds = dataframe_to_dataset(val, barajar=False).batch(TAMANO_LOTE)

        keras.utils.set_random_seed(self.semilla)
        keras.backend.clear_session()

        # Creamos una lista de inputs para el modelo, de acuerdo con cada tipo de variable
        inputs = ([keras.Input(shape=(1,), name=c, dtype="int64") for c in self.cat_int]
                  + [keras.Input(shape=(1,), name=c, dtype="string") for c in self.cat_str]
                  + [keras.Input(shape=(1,), name=c) for c in self.num])

        # Codificamos cada variable con los datos de entrenamiento
        feats_encoded = []
        for entrada, c in zip(inputs, self.feats):
            if c in self.cat_int:
                feats_encoded.append(encode_categorical_feature(entrada, c, train_ds, False))
            elif c in self.cat_str:
                feats_encoded.append(encode_categorical_feature(entrada, c, train_ds, True))
            else:
                feats_encoded.append(encode_numerical_feature(entrada, c, train_ds))

        # Concatenamos, capa densa de 32 con relu y salida sigmoide
        all_feats = keras.layers.concatenate(feats_encoded)
        model_layers = keras.layers.Dense(NEURONAS, activation="relu")(all_feats)
        model_layers = keras.layers.Dense(1, activation="sigmoid")(model_layers)
        self.model = keras.Model(inputs, model_layers)

        self.model.compile(optimizer="adam", loss="binary_crossentropy",
                           metrics=["accuracy", keras.metrics.Recall(name="recall")])
        self.history = self.model.fit(train_ds, epochs=self.epocas,
                                      validation_data=val_ds, verbose=self.verbose)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        tf, _ = _keras()
        ds = tf.data.Dataset.from_tensor_slices(dict(self._formato(X))).batch(256)
        p = self.model.predict(ds, verbose=0).ravel()
        return np.column_stack([1 - p, p])

    def historial(self) -> pd.DataFrame:
        """Pérdida de entrenamiento y de validación por época."""
        h = self.history.history
        return pd.DataFrame({"época": range(1, len(h["loss"]) + 1),
                             "entrenamiento": h["loss"], "validación": h["val_loss"]})


def _metricas(y: pd.Series, prob: np.ndarray, fraccion: float = 0.10) -> dict:
    """Las métricas que se pueden explicar en una frase cada una."""
    y = np.asarray(y)
    tasa = y.mean()
    if np.ptp(prob) == 0:
        # Un modelo que da a todos la misma probabilidad no ordena nada: elegir
        # su "10% más riesgoso" es elegir al azar, y al azar se acierta la tasa.
        precision_top = tasa
    else:
        n_top = max(1, int(round(len(y) * fraccion)))
        orden = np.argsort(-prob, kind="stable")
        precision_top = y[orden[:n_top]].mean()
    return {
        "auc": roc_auc_score(y, prob) if 0 < tasa < 1 else np.nan,
        "precision_top": 100 * precision_top,
        "veces_la_tasa": precision_top / tasa if tasa else np.nan,
        "exactitud": 100 * ((prob >= 0.5).astype(int) == y).mean(),
    }


def comparar(tabla: pd.DataFrame, fecha_division, semilla: int = 0,
             fraccion: float = 0.10, epocas: int = EPOCAS,
             con_red: bool = True) -> tuple[pd.DataFrame, dict]:
    """
    Los tres modelos sobre la misma división. Devuelve la tabla y los modelos.

    - `auc`: si se toma al azar un contrato con prórroga y uno sin ella, la
      probabilidad de que el modelo ponga más alto al primero. 50 es azar.
    - `precision_top`: de los contratos que el modelo pone en el `fraccion`
      más riesgoso, cuántos de verdad tuvieron prórroga. Es la medida que
      importa para priorizar la vigilancia, que es para lo que existe VigIA.
    - `veces_la_tasa`: esa precisión dividida por la tasa general. 1 es lo que
      se lograría revisando contratos al azar.
    - `exactitud`: se muestra para enseñar por qué no sirve. La línea base
      saca la más alta sin detectar una sola prórroga.
    """
    entrenar, evaluar = dividir_en_el_tiempo(tabla, fecha_division)
    if entrenar.sum() == 0 or evaluar.sum() == 0:
        return pd.DataFrame(), {}

    cat_int, cat_str, num = variables(tabla.loc[entrenar])
    feats = cat_int + cat_str + num
    X_tr, y_tr = tabla.loc[entrenar, feats], tabla.loc[entrenar, "prorroga"]
    X_te, y_te = tabla.loc[evaluar, feats], tabla.loc[evaluar, "prorroga"]
    if y_tr.nunique() < 2:
        return pd.DataFrame(), {}

    filas, modelos = [], {}
    for nombre in MODELOS:
        if nombre == "Línea base":
            prob = np.zeros(len(y_te))
        elif nombre == "Regresión logística":
            modelos[nombre] = logistica(cat_int, cat_str, num).fit(X_tr, y_tr)
            prob = modelos[nombre].predict_proba(X_te)[:, 1]
        elif con_red:
            modelos[nombre] = RedNeuronal(cat_int, cat_str, num, epocas=epocas,
                                          semilla=semilla).fit(X_tr, y_tr)
            prob = modelos[nombre].predict_proba(X_te)[:, 1]
        else:
            continue
        filas.append({"modelo": nombre, **_metricas(y_te, prob, fraccion)})

    resultado = pd.DataFrame(filas).set_index("modelo")
    resultado.attrs.update({
        "entrenamiento": int(entrenar.sum()), "evaluacion": int(evaluar.sum()),
        "tasa_entrenamiento": 100 * y_tr.mean(), "tasa_evaluacion": 100 * y_te.mean(),
        "variables": feats, "X_eval": X_te, "y_eval": y_te,
    })
    return resultado, modelos


def importancia(modelo, X: pd.DataFrame, y: pd.Series,
                repeticiones: int = 3, semilla: int = 0) -> pd.Series:
    """
    Cuánto empeora el AUC si se revuelve una variable al azar.

    Funciona igual para la logística y para la red, y responde la pregunta que
    hace cualquiera ante un modelo: ¿en qué se fija? Si revolver una columna no
    cambia nada, el modelo no la estaba usando.
    """
    rng = np.random.default_rng(semilla)
    base = roc_auc_score(y, modelo.predict_proba(X)[:, 1])
    caidas = {}
    for col in X.columns:
        perdidas = []
        for _ in range(repeticiones):
            revuelto = X.copy()
            revuelto[col] = rng.permutation(revuelto[col].to_numpy())
            perdidas.append(base - roc_auc_score(y, modelo.predict_proba(revuelto)[:, 1]))
        caidas[col] = 100 * float(np.mean(perdidas))
    return pd.Series(caidas).sort_values(ascending=False)
