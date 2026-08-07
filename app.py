import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta

st.set_page_config(
    page_title="BTC Predictor 15 Min",
    page_icon="₿",
    layout="centered"
)

st.title("₿ Bitcoin Predictor - Ciclos de 15 minutos")

CICLO = 15
UMBRAL = 80


# -----------------------------
# MEMORIA DE LA APP
# -----------------------------

if "inicio" not in st.session_state:
    st.session_state.inicio = datetime.now()

if "historial" not in st.session_state:
    st.session_state.historial = []


# -----------------------------
# OBTENER BTC BINANCE
# -----------------------------

@st.cache_data(ttl=60)
@st.cache_data(ttl=60)
def obtener_btc():

    url = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc"

    parametros = {
        "vs_currency": "usd",
        "days": "1"
    }

    respuesta = requests.get(
        url,
        params=parametros,
        timeout=10
    )

    datos = respuesta.json()

    if not isinstance(datos, list) or len(datos) == 0:
        raise Exception("CoinGecko no devolvió datos")


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


    if len(df) < 30:
        raise Exception("No hay suficientes datos")


    df["Volume"] = 0

    return df


# -----------------------------
# INDICADORES
# -----------------------------

def indicadores(df):

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

    media_subida = subida.rolling(14).mean()
    media_bajada = bajada.rolling(14).mean()

    rs = media_subida / media_bajada

    df["RSI"] = 100 - (100 / (1 + rs))


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
  # -----------------------------
# SISTEMA DE SEÑAL
# -----------------------------

def analizar(df):

    ultimo = df.iloc[-1]

    puntos = 50
    razones = []

    # EMA
    if ultimo["EMA9"] > ultimo["EMA21"]:
        puntos += 15
        razones.append("EMA tendencia alcista")
    else:
        puntos -= 15
        razones.append("EMA tendencia bajista")


    # RSI
    if ultimo["RSI"] < 35:
        puntos += 10
        razones.append("RSI bajo posible rebote")

    elif ultimo["RSI"] > 65:
        puntos -= 10
        razones.append("RSI alto posible caída")


    # MACD
    if ultimo["MACD"] > 0:
        puntos += 15
        razones.append("MACD positivo")
    else:
        puntos -= 15
        razones.append("MACD negativo")


    puntos = max(0, min(100, puntos))


    if puntos >= UMBRAL:
        señal = "🟢 SUBIR"
        confianza = puntos

    elif puntos <= (100-UMBRAL):
        señal = "🔴 BAJAR"
        confianza = 100-puntos

    else:
        señal = "⚪ NO APOSTAR"
        confianza = abs(puntos-50)*2


    return señal, confianza, razones



# -----------------------------
# CARGAR DATOS
# -----------------------------

try:

    btc = obtener_btc()
    btc = indicadores(btc)

    señal, confianza, razones = analizar(btc)

    precio = btc["Close"].iloc[-1]


    st.metric(
        "Precio BTC",
        f"${precio:,.2f}"
    )


    st.subheader("Predicción próximos 15 minutos")

    st.write(señal)

    st.write(
        f"Confianza: {confianza:.0f}%"
    )


    st.write("Análisis:")

    for r in razones:
        st.write("✅", r)



except Exception as e:

    st.error(
        f"Error obteniendo datos: {e}"
    )



# -----------------------------
# TEMPORIZADOR
# -----------------------------

pasado = datetime.now() - st.session_state.inicio

restante = timedelta(minutes=CICLO) - pasado


if restante.total_seconds() <= 0:

    st.session_state.inicio = datetime.now()


    registro = {

        "Hora":
        datetime.now().strftime("%H:%M:%S"),

        "Señal":
        señal,

        "Confianza":
        f"{confianza:.0f}%"
    }


    st.session_state.historial.append(
        registro
    )


    restante = timedelta(minutes=CICLO)



minutos = int(restante.seconds / 60)
segundos = restante.seconds % 60


st.subheader(
    f"⏳ Nuevo ciclo en {minutos:02d}:{segundos:02d}"
)



# -----------------------------
# HISTORIAL
# -----------------------------

st.subheader("📜 Historial")


if len(st.session_state.historial) > 0:

    tabla = pd.DataFrame(
        st.session_state.historial
    )

    st.dataframe(tabla)

else:

    st.write(
        "Sin señales todavía"
    )


# Actualización automática

time.sleep(5)

st.rerun()
