import streamlit as st
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import request

st.set_page_config(
    page_title="BTC 15 Min Predictor",
    page_icon="₿",
    layout="centered"
)

st.title("₿ Bitcoin Predictor - Ciclos de 15 minutos")

# -----------------------------
# CONFIGURACIÓN
# -----------------------------

CICLO_MINUTOS = 15
UMBRAL_CONF = 80

# -----------------------------
# HISTORIAL
# -----------------------------

if "historial" not in st.session_state:
    st.session_state.historial = []

if "inicio_ciclo" not in st.session_state:
    st.session_state.inicio_ciclo = datetime.now()

# -----------------------------
# DATOS BTC
# -----------------------------

@st.cache_data(ttl=60)
def obtener_btc():

    datos = yf.download(
        "BTC-USD",
        period="2d",
        interval="1m",
        progress=False
    )

    datos.dropna(inplace=True)

    return datos


# -----------------------------
# INDICADORES
# -----------------------------

def calcular_indicadores(df):

    cierre = df["Close"]

    df["EMA9"] = cierre.ewm(span=9).mean()
    df["EMA21"] = cierre.ewm(span=21).mean()

    cambio = cierre.diff()

    ganancia = cambio.clip(lower=0)
    perdida = -cambio.clip(upper=0)

    media_ganancia = ganancia.rolling(14).mean()
    media_perdida = perdida.rolling(14).mean()

    rs = media_ganancia / media_perdida

    df["RSI"] = 100 - (100/(1+rs))

    ema12 = cierre.ewm(span=12).mean()
    ema26 = cierre.ewm(span=26).mean()

    df["MACD"] = ema12 - ema26

    return df
  # -----------------------------
# MOTOR DE PREDICCIÓN
# -----------------------------

def analizar_mercado(df):

    ultimo = df.iloc[-1]

    puntos = 50
    razones = []

    # Tendencia EMA
    if ultimo["EMA9"] > ultimo["EMA21"]:
        puntos += 15
        razones.append("EMA indica tendencia alcista")
    else:
        puntos -= 15
        razones.append("EMA indica tendencia bajista")

    # RSI
    if ultimo["RSI"] < 35:
        puntos += 10
        razones.append("RSI bajo, posible rebote")
    elif ultimo["RSI"] > 65:
        puntos -= 10
        razones.append("RSI alto, posible corrección")

    # MACD
    if ultimo["MACD"] > 0:
        puntos += 15
        razones.append("MACD positivo")
    else:
        puntos -= 15
        razones.append("MACD negativo")

    # Normalizar
    puntos = max(0, min(100, puntos))

    if puntos >= UMBRAL_CONF:
        señal = "🟢 SUBIR"
        confianza = puntos

    elif puntos <= (100 - UMBRAL_CONF):
        señal = "🔴 BAJAR"
        confianza = 100 - puntos

    else:
        señal = "⚪ NO APOSTAR"
        confianza = abs(puntos-50)*2

    return señal, confianza, razones


# -----------------------------
# CICLO DE 15 MINUTOS
# -----------------------------

ahora = datetime.now()

tiempo_pasado = ahora - st.session_state.inicio_ciclo

if tiempo_pasado >= timedelta(minutes=CICLO_MINUTOS):

    st.session_state.inicio_ciclo = ahora

    try:
        datos = obtener_btc()
        datos = calcular_indicadores(datos)

        señal, confianza, razones = analizar_mercado(datos)

        registro = {
            "Hora": ahora.strftime("%H:%M:%S"),
            "Señal": señal,
            "Confianza": f"{confianza:.0f}%"
        }

        st.session_state.historial.append(registro)

    except Exception:
        pass


# -----------------------------
# MOSTRAR INFORMACIÓN
# -----------------------------

try:

import requests

@st.cache_data(ttl=60)
def obtener_btc():

    url = "https://api.binance.com/api/v3/klines"

    parametros = {
        "symbol": "BTCUSDT",
        "interval": "1m",
        "limit": 200
    }

    respuesta = requests.get(url, params=parametros)

    datos = respuesta.json()

    df = pd.DataFrame(datos, columns=[
        "time",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "close_time",
        "qav",
        "trades",
        "tb_base",
        "tb_quote",
        "ignore"
    ])

    df["Close"] = df["Close"].astype(float)
    df["Volume"] = df["Volume"].astype(float)

    return df   

    


# -----------------------------
# TEMPORIZADOR
# -----------------------------

restante = timedelta(minutes=CICLO_MINUTOS) - (datetime.now() - st.session_state.inicio_ciclo)

minutos = int(restante.seconds / 60)
segundos = restante.seconds % 60

st.subheader(
    f"⏳ Próximo ciclo en: {minutos:02d}:{segundos:02d}"
)


# -----------------------------
# HISTORIAL
# -----------------------------

st.subheader("📜 Historial")

if st.session_state.historial:

    historial_df = pd.DataFrame(
        st.session_state.historial
    )

    st.dataframe(historial_df)

else:

    st.write("Sin señales todavía")


# Actualización automática

time.sleep(5)
st.rerun()
