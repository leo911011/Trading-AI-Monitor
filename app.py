import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta


st.set_page_config(
    page_title="Trading AI Monitor V3",
    page_icon="📈"
)


# ==========================
# CONFIGURACIÓN
# ==========================

INTERVALO = 900  # 15 minutos
ARCHIVO_HISTORIAL = "historial.csv"


# ==========================
# OBTENER DATOS
# ==========================

def obtener_datos(simbolo):

    url = f"https://api.exchange.coinbase.com/products/{simbolo}/candles"

    parametros = {
        "granularity": INTERVALO
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

def indicadores(df):

    df["EMA20"] = df["close"].ewm(
        span=20
    ).mean()


    df["EMA50"] = df["close"].ewm(
        span=50
    ).mean()


    cambio = df["close"].diff()

    subida = cambio.where(
        cambio > 0,
        0
    )

    bajada = -cambio.where(
        cambio < 0,
        0
    )


    media_subida = subida.rolling(14).mean()

    media_bajada = bajada.rolling(14).mean()


    rs = media_subida / media_bajada


    df["RSI"] = 100 - (
        100 / (1 + rs)
    )


    ema12 = df["close"].ewm(
        span=12
    ).mean()


    ema26 = df["close"].ewm(
        span=26
    ).mean()


    df["MACD"] = ema12 - ema26


    return df
  # ==========================
# ANALISIS
# ==========================

def analizar(df):

    ultimo = df.iloc[-1]

    puntos = 50

    razones = []


    if ultimo["EMA20"] > ultimo["EMA50"]:

        puntos += 15
        razones.append("EMA tendencia alcista")

    else:

        puntos -= 15
        razones.append("EMA tendencia bajista")



    if ultimo["MACD"] > 0:

        puntos += 10
        razones.append("MACD positivo")

    else:

        puntos -= 10
        razones.append("MACD negativo")



    if ultimo["RSI"] < 30:

        puntos += 15
        razones.append("RSI zona de rebote")

    elif ultimo["RSI"] > 70:

        puntos -= 15
        razones.append("RSI sobrecomprado")



    if ultimo["volume"] > df["volume"].mean():

        puntos += 10
        razones.append("Volumen alto")


    puntos = max(0, min(100, puntos))


    if puntos >= 65:

        señal = "COMPRA 🟢"

    elif puntos <= 35:

        señal = "VENTA 🔴"

    else:

        señal = "ESPERAR ⚪"


    return señal, puntos, razones




# ==========================
# HISTORIAL
# ==========================

def guardar_historial(moneda, precio, señal, puntos):

    nuevo = pd.DataFrame([{

        "fecha": datetime.now(),

        "moneda": moneda,

        "precio": precio,

        "señal": señal,

        "confianza": puntos

    }])


    try:

        viejo = pd.read_csv(
            ARCHIVO_HISTORIAL
        )

        nuevo = pd.concat(
            [viejo, nuevo],
            ignore_index=True
        )


    except:

        pass


    nuevo.to_csv(
        ARCHIVO_HISTORIAL,
        index=False
    )




# ==========================
# TEMPORIZADOR
# ==========================

def tiempo_restante():

    ahora = datetime.now()

    minutos = ahora.minute

    siguiente = (
        (minutos // 15) + 1
    ) * 15


    if siguiente >= 60:

        cierre = (
            ahora.replace(
                hour=ahora.hour + 1,
                minute=0,
                second=0
            )
        )

    else:

        cierre = ahora.replace(
            minute=siguiente,
            second=0
        )


    return cierre - ahora





# ==========================
# APP
# ==========================


st.title(
    "📈 Trading AI Monitor V3"
)


st.write(
    "BTC y SOL análisis 15 minutos"
)


faltan = tiempo_restante()


st.info(
    f"⏱️ Próximo cierre de vela: {faltan}"
)



for nombre, simbolo in [

    ("Bitcoin ₿","BTC-USD"),

    ("Solana ◎","SOL-USD")

]:


    st.divider()

    st.header(nombre)


    try:

        df = obtener_datos(simbolo)


        df = indicadores(df)


        señal, puntos, razones = analizar(df)


        precio = df.iloc[-1]["close"]


        st.metric(
            "Precio",
            "$" + str(round(precio,2))
        )


        st.subheader(
            señal
        )


        st.progress(
            puntos / 100
        )


        st.write(
            "Fuerza:",
            str(puntos)+"/100"
        )


        for r in razones:

            st.write(
                "✅",
                r
            )


        guardar_historial(
            nombre,
            precio,
            señal,
            puntos
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


    except Exception as error:

        st.error(error)



st.divider()


st.subheader(
    "📒 Historial de señales"
)


try:

    historial = pd.read_csv(
        ARCHIVO_HISTORIAL
    )

    st.dataframe(
        historial.tail(20)
    )


except:

    st.write(
        "Sin historial todavía"
    )



st.caption(
    "Actualizado: " + str(datetime.now())
      )
