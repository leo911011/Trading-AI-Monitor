import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta


# =============================
# CONFIGURACIÓN
# =============================

st.set_page_config(
    page_title="BTC Predictor 15 Min",
    page_icon="₿",
    layout="centered"
)

CICLO = 15
UMBRAL = 80
import json
import os

ARCHIVO_CICLO = "ciclo_btc.json"


def cargar_inicio():
    if os.path.exists(ARCHIVO_CICLO):
        with open(ARCHIVO_CICLO, "r") as f:
            datos = json.load(f)
            return datetime.fromisoformat(datos["inicio"])
    else:
        inicio = datetime.now()
        guardar_inicio(inicio)
        return inicio


def guardar_inicio(inicio):
    with open(ARCHIVO_CICLO, "w") as f:
        json.dump(
            {"inicio": inicio.isoformat()},
            f
        )


# =============================
# MEMORIA
# =============================

if "inicio_ciclo" not in st.session_state:
    st.session_state.inicio_ciclo = datetime.now()

if "senal_actual" not in st.session_state:
    st.session_state.senal_actual = None

if "confianza_actual" not in st.session_state:
    st.session_state.confianza_actual = 0

if "precio_entrada" not in st.session_state:
    st.session_state.precio_entrada = 0

if "hora_entrada" not in st.session_state:
    st.session_state.hora_entrada = ""

if "historial" not in st.session_state:
    st.session_state.historial = []


st.title("₿ Bitcoin Predictor - Ciclos de 15 minutos")


# =============================
# DATOS BTC
# =============================

@st.cache_data(ttl=60)
def obtener_btc():

    url = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc"

    params = {
        "vs_currency": "usd",
        "days": "1"
    }

    respuesta = requests.get(
        url,
        params=params,
        timeout=10
    )

    datos = respuesta.json()

    if not isinstance(datos, list):
        raise Exception("Binance/CoinGecko no devolvió datos")


    df = pd.DataFrame(
        datos,
        columns=[
            "time",
            "Open",
            "High",
            "Low",
            "Close"
        ]
    )

    df["Close"] = pd.to_numeric(
        df["Close"],
        errors="coerce"
    )

    df = df.dropna()

    return df
  # =============================
# INDICADORES
# =============================

def calcular_indicadores(df):

    df["EMA9"] = (
        df["Close"]
        .ewm(span=9)
        .mean()
    )

    df["EMA21"] = (
        df["Close"]
        .ewm(span=21)
        .mean()
    )


    cambio = df["Close"].diff()

    subida = cambio.clip(lower=0)
    bajada = -cambio.clip(upper=0)


    media_subida = (
        subida
        .rolling(14)
        .mean()
    )

    media_bajada = (
        bajada
        .rolling(14)
        .mean()
    )


    rs = media_subida / media_bajada


    df["RSI"] = (
        100 -
        (100 / (1 + rs))
    )


    ema12 = (
        df["Close"]
        .ewm(span=12)
        .mean()
    )

    ema26 = (
        df["Close"]
        .ewm(span=26)
        .mean()
    )


    df["MACD"] = ema12 - ema26


    return df



# =============================
# ANALISIS DE MERCADO
# =============================

def analizar(df):

    ultimo = df.iloc[-1]

    puntos = 50

    razones = []


    if ultimo["EMA9"] > ultimo["EMA21"]:

        puntos += 15

        razones.append(
            "EMA tendencia alcista"
        )

    else:

        puntos -= 15

        razones.append(
            "EMA tendencia bajista"
        )



    if ultimo["MACD"] > 0:

        puntos += 15

        razones.append(
            "MACD positivo"
        )

    else:

        puntos -= 15

        razones.append(
            "MACD negativo"
        )



    if ultimo["RSI"] < 35:

        puntos += 10

        razones.append(
            "RSI indica posible rebote"
        )


    elif ultimo["RSI"] > 65:

        puntos -= 10

        razones.append(
            "RSI alto posible caída"
        )



    puntos = max(
        0,
        min(100, puntos)
    )


    if puntos >= UMBRAL:

        señal = "🟢 SUBIR"

    elif puntos <= (100 - UMBRAL):

        señal = "🔴 BAJAR"

    else:

        señal = "⚪ NO APOSTAR"


    return señal, puntos, razones
  # =============================
# APP PRINCIPAL
# =============================

try:

    btc = obtener_btc()

    btc = calcular_indicadores(btc)


    precio_actual = btc["Close"].iloc[-1]


    nueva_señal, confianza, razones = analizar(btc)



    # Crear nueva operación solamente al inicio

    if st.session_state.senal_actual is None:

        st.session_state.senal_actual = nueva_señal

        st.session_state.confianza_actual = confianza

        st.session_state.precio_entrada = precio_actual

        st.session_state.hora_entrada = (
            datetime.now()
            .strftime("%H:%M:%S")
        )



    # =============================
    # PRECIO Y SEÑAL
    # =============================

    st.metric(
        "Precio BTC",
        f"${precio_actual:,.2f}"
    )


    st.subheader(
        "Predicción próximos 15 minutos"
    )


    st.write(
        st.session_state.senal_actual
    )


    st.write(
        f"Confianza: {st.session_state.confianza_actual}%"
    )


    st.write("Análisis:")

    for r in razones:

        st.write(
            "✅",
            r
        )



    # =============================
    # GRÁFICO
    # =============================

    st.subheader("📈 Gráfico BTC")

    st.line_chart(
        btc["Close"]
    )



    # =============================
    # TEMPORIZADOR
    # =============================

    pasado = (
        datetime.now()
        -
        st.session_state.inicio_ciclo
    )


    restante = (
        timedelta(minutes=CICLO)
        -
        pasado
    )



    if restante.total_seconds() <= 0:


        precio_salida = precio_actual


        if st.session_state.senal_actual == "🟢 SUBIR":

            correcto = (
                precio_salida >
                st.session_state.precio_entrada
            )


        elif st.session_state.senal_actual == "🔴 BAJAR":

            correcto = (
                precio_salida <
                st.session_state.precio_entrada
            )

        else:

            correcto = False



        diferencia = (
            precio_salida
            -
            st.session_state.precio_entrada
        )


        st.session_state.historial.append({

            "Hora":
            st.session_state.hora_entrada,

            "Señal":
            st.session_state.senal_actual,

            "Entrada":
            round(
                st.session_state.precio_entrada,
                2
            ),

            "Salida":
            round(
                precio_salida,
                2
            ),

            "Cambio":
            round(
                diferencia,
                2
            ),

            "Resultado":
            "✅ ACIERTO"
            if correcto
            else
            "❌ FALLÓ"

        })



        # Nuevo ciclo

        st.session_state.senal_actual = nueva_señal

        st.session_state.confianza_actual = confianza

        st.session_state.precio_entrada = precio_actual

        st.session_state.hora_entrada = (
            datetime.now()
            .strftime("%H:%M:%S")
        )

        st.session_state.inicio_ciclo = datetime.now()



        restante = timedelta(minutes=CICLO)



    minutos = int(
        restante.seconds / 60
    )

    segundos = (
        restante.seconds % 60
    )


    st.subheader(
        f"⏳ Nuevo ciclo en {minutos:02d}:{segundos:02d}"
    )



    # =============================
    # HISTORIAL
    # =============================

    st.subheader(
        "📜 Historial"
    )


    if len(st.session_state.historial) > 0:


        tabla = pd.DataFrame(
            st.session_state.historial
        )

        st.dataframe(tabla)


        total = len(tabla)

        aciertos = len(
            tabla[
                tabla["Resultado"]
                ==
                "✅ ACIERTO"
            ]
        )


        precision = (
            aciertos / total
        ) * 100


        st.metric(
            "Precisión",
            f"{precision:.1f}%"
        )


    else:

        st.write(
            "Esperando terminar el primer ciclo..."
        )



except Exception as e:

    st.error(
        f"Error obteniendo datos: {e}"
    )



time.sleep(5)

st.rerun()
  
