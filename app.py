import streamlit as st
import pandas as pd
import requests
from datetime import datetime


st.set_page_config(
    page_title="Trading AI Monitor",
    page_icon="📈"
)


def obtener_datos(simbolo):
def obtener_datos(simbolo):

    url = "https://api.exchange.coinbase.com/products/" + simbolo + "/candles"

    parametros = {
        "granularity": 900
    }

    respuesta = requests.get(
        url,
        params=parametros
    )

    datos = respuesta.json()

    if isinstance(datos, dict):
        raise Exception(datos)

    df = pd.DataFrame(
        datos,
        columns=[
            "time",
            "low",
            "high",
            "open",
            "close",
            "volume"
        ]
    )

    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)

    df = df.sort_values("time")

    return df

def analizar(df):

    df["EMA20"] = df["close"].ewm(span=20).mean()
    df["EMA50"] = df["close"].ewm(span=50).mean()

    ultimo = df.iloc[-1]

    puntos = 0
    razones = []

    if ultimo["EMA20"] > ultimo["EMA50"]:
        puntos += 30
        razones.append("Tendencia alcista")
    else:
        puntos -= 30
        razones.append("Tendencia bajista")


    if ultimo["volume"] > df["volume"].mean():
        puntos += 20
        razones.append("Volumen elevado")


    if puntos >= 40:
        señal = "COMPRA 🟢"
    elif puntos <= -20:
        señal = "VENTA 🔴"
    else:
        señal = "ESPERAR ⚪"


    confianza = min(abs(puntos)+50,95)


    return {
        "precio": ultimo["close"],
        "señal": señal,
        "confianza": confianza,
        "razones": razones
    }



st.title("📈 Trading AI Monitor")

st.write(
    "Análisis automático BTC y SOL"
)


for nombre, simbolo in [
    ("Bitcoin ₿","BTCUSDT"),
    ("Solana ◎","SOLUSDT")
]:

    st.divider()

    st.header(nombre)

    try:

        datos = obtener_datos(simbolo)

        resultado = analizar(datos)


        st.metric(
            "Precio",
            "$"+str(round(resultado["precio"],2))
        )

        st.subheader(
            resultado["señal"]
        )

        st.write(
            "Confianza:",
            str(resultado["confianza"])+"%"
        )


        for r in resultado["razones"]:
            st.write("✅", r)


        st.line_chart(
            datos["close"]
        )


    except Exception as error:

        st.error(error)


st.caption(
    "Actualizado: " + str(datetime.now())
)
