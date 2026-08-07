import streamlit as st
import pandas as pd
import requests
from datetime import datetime


st.set_page_config(
    page_title="Trading AI Monitor V2",
    page_icon="📈"
)


# ==========================
# DATOS 15 MINUTOS
# ==========================

def obtener_datos(simbolo):

    url = f"https://api.exchange.coinbase.com/products/{simbolo}/candles"

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

    df = df.sort_values("time")

    for columna in [
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]:
        df[columna] = df[columna].astype(float)

    return df



# ==========================
# INDICADORES
# ==========================

def calcular_indicadores(df):

    df["EMA20"] = df["close"].ewm(span=20).mean()

    df["EMA50"] = df["close"].ewm(span=50).mean()


    # RSI

    cambio = df["close"].diff()

    ganancia = cambio.where(cambio > 0, 0)

    perdida = -cambio.where(cambio < 0, 0)


    promedio_ganancia = ganancia.rolling(14).mean()

    promedio_perdida = perdida.rolling(14).mean()


    rs = promedio_ganancia / promedio_perdida

    df["RSI"] = 100 - (100 / (1 + rs))


    # MACD

    ema12 = df["close"].ewm(span=12).mean()

    ema26 = df["close"].ewm(span=26).mean()

    df["MACD"] = ema12 - ema26


    return df



# ==========================
# ANALISIS IA SIMPLE
# ==========================

def analizar(df):

    ultimo = df.iloc[-1]

    puntos = 50

    razones = []


    # Tendencia EMA

    if ultimo["EMA20"] > ultimo["EMA50"]:

        puntos += 15

        razones.append(
            "Tendencia alcista EMA"
        )

    else:

        puntos -= 15

        razones.append(
            "Tendencia bajista EMA"
        )


    # RSI

    if ultimo["RSI"] < 30:

        puntos += 15

        razones.append(
            "RSI indica posible rebote"
        )

    elif ultimo["RSI"] > 70:

        puntos -= 15

        razones.append(
            "RSI sobrecomprado"
        )


    # MACD

    if ultimo["MACD"] > 0:

        puntos += 10

        razones.append(
            "MACD positivo"
        )

    else:

        puntos -= 10

        razones.append(
            "MACD negativo"
        )


    # Volumen

    if ultimo["volume"] > df["volume"].mean():

        puntos += 10

        razones.append(
            "Volumen alto"
        )


    puntos = max(0, min(100, puntos))


    if puntos >= 65:

        señal = "COMPRA 🟢"

    elif puntos <= 35:

        señal = "VENTA 🔴"

    else:

        señal = "ESPERAR ⚪"



    return señal, puntos, razones



# ==========================
# APP
# ==========================


st.title(
    "📈 Trading AI Monitor V2"
)


st.write(
    "BTC y SOL - análisis automático 15 minutos"
)



for nombre, simbolo in [

    ("Bitcoin ₿","BTC-USD"),

    ("Solana ◎","SOL-USD")

]:


    st.divider()

    st.header(nombre)


    try:


        df = obtener_datos(simbolo)


        df = calcular_indicadores(df)


        señal, puntos, razones = analizar(df)


        precio = df.iloc[-1]["close"]


        st.metric(
            "Precio actual",
            "$" + str(round(precio,2))
        )


        st.subheader(
            señal
        )


        st.progress(
            puntos/100
        )


        st.write(
            "Probabilidad técnica:",
            str(puntos) + "/100"
        )


        st.write("Análisis:")


        for razon in razones:

            st.write(
                "✅",
                razon
            )


        st.line_chart(
            df[
                [
                "close",
                "EMA20",
                "EMA50"
                ]
            ]
        )


        st.write(
            "RSI:",
            round(df.iloc[-1]["RSI"],2)
        )


        st.write(
            "MACD:",
            round(df.iloc[-1]["MACD"],4)
        )



    except Exception as error:

        st.error(error)



st.caption(
    "Actualizado: " + str(datetime.now())
)
