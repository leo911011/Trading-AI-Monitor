import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta


# -----------------------------
# CONFIGURACIÓN
# -----------------------------

st.set_page_config(
    page_title="BTC Predictor 15 Min",
    page_icon="₿",
    layout="centered"
)

CICLO = 15
UMBRAL = 80


# -----------------------------
# MEMORIA DE LA APP
# -----------------------------

if "inicio_ciclo" not in st.session_state:
    st.session_state.inicio_ciclo = datetime.now()

if "senal_actual" not in st.session_state:
    st.session_state.senal_actual = None

if "precio_entrada" not in st.session_state:
    st.session_state.precio_entrada = 0

if "hora_entrada" not in st.session_state:
    st.session_state.hora_entrada = ""

if "resultados" not in st.session_state:
    st.session_state.resultados = []


st.title("₿ Bitcoin Predictor - Ciclos de 15 minutos")


# -----------------------------
# DATOS BTC
# -----------------------------

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

    if not isinstance(datos, list):
        raise Exception("No hay datos de BTC")


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

    df["Volume"] = 0


    if len(df) < 30:
        raise Exception("Datos insuficientes")


    return df
  # -----------------------------
# INDICADORES
# -----------------------------

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



# -----------------------------
# ANALISIS
# -----------------------------

def analizar(df):

    ultimo = df.iloc[-1]


    puntos = 50
    razones = []


    # EMA

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



    # RSI

    if ultimo["RSI"] < 35:

        puntos += 10
        razones.append(
            "RSI bajo posible rebote"
        )


    elif ultimo["RSI"] > 65:

        puntos -= 10
        razones.append(
            "RSI alto posible corrección"
        )



    # MACD

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



    puntos = max(
        0,
        min(100, puntos)
    )


    if puntos >= UMBRAL:

        senal = "🟢 SUBIR"
        confianza = puntos


    elif puntos <= (100 - UMBRAL):

        senal = "🔴 BAJAR"
        confianza = 100 - puntos


    else:

        senal = "⚪ NO APOSTAR"
        confianza = abs(puntos - 50) * 2



    return senal, confianza, razones
  # -----------------------------
# EJECUCIÓN PRINCIPAL
# -----------------------------

# -----------------------------
# EJECUCIÓN PRINCIPAL
# -----------------------------

try:

    btc = obtener_btc()

    btc = calcular_indicadores(btc)

    precio_actual = btc["Close"].iloc[-1]


    nueva_senal, confianza, razones = analizar(btc)



    # Crear señal solo al inicio de ciclo

    if st.session_state.senal_actual is None:

        st.session_state.senal_actual = nueva_senal

        st.session_state.precio_entrada = precio_actual

        st.session_state.hora_entrada = (
            datetime.now()
            .strftime("%H:%M:%S")
        )



    # Mostrar precio

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
        f"Confianza: {confianza:.0f}%"
    )


    st.write("Análisis:")

    for razon in razones:

        st.write(
            "✅",
            razon
        )



    # Gráfico

    st.subheader("📈 Movimiento BTC")

    grafico = btc[["Close"]]

    st.line_chart(grafico)



    # Temporizador

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

            acertado = (
                precio_salida >
                st.session_state.precio_entrada
            )


        elif st.session_state.senal_actual == "🔴 BAJAR":

            acertado = (
                precio_salida <
                st.session_state.precio_entrada
            )

        else:

            acertado = False



        diferencia = (
            precio_salida -
            st.session_state.precio_entrada
        )


        st.session_state.resultados.append({

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
            if acertado
            else
            "❌ FALLÓ"

        })


        # Nuevo ciclo

        st.session_state.senal_actual = nueva_senal

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



    # Historial

    st.subheader(
        "📜 Historial"
    )


    if len(st.session_state.resultados) > 0:


        tabla = pd.DataFrame(
            st.session_state.resultados
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
            aciertos /
            total
        ) * 100



        st.metric(
            "Precisión",
            f"{precision:.1f}%"
        )


    else:

        st.write(
            "Esperando primer resultado..."
        )



except Exception as error:

    st.error(
        f"Error: {error}"
    )



time.sleep(5)

st.rerun()


    # -----------------------------
    # NUEVO CICLO
    # -----------------------------

    tiempo = (
        datetime.now()
        -
        st.session_state.inicio_ciclo
    )


    restante = (
        timedelta(minutes=CICLO)
        -
        tiempo
    )



    if restante.total_seconds() <= 0:


        # Cerrar ciclo anterior

        if st.session_state.senal_actual is not None:


            precio_salida = precio_actual


            if st.session_state.senal_actual == "🟢 SUBIR":

                acertado = (
                    precio_salida >
                    st.session_state.precio_entrada
                )


            elif st.session_state.senal_actual == "🔴 BAJAR":

                acertado = (
                    precio_salida <
                    st.session_state.precio_entrada
                )


            else:

                acertado = False



            resultado = {

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

                "Resultado":
                "✅ ACIERTO"
                if acertado
                else
                "❌ FALLÓ"
            }


            st.session_state.resultados.append(
                resultado
            )



        # Crear nueva señal


        st.session_state.senal_actual = senal

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


    # -----------------------------
    # HISTORIAL
    # -----------------------------

    st.subheader("📜 Historial de ciclos")


    if len(st.session_state.resultados) > 0:

        tabla = pd.DataFrame(
            st.session_state.resultados
        )

        st.dataframe(tabla)


        total = len(tabla)

        aciertos = len(
            tabla[
                tabla["Resultado"] == "✅ ACIERTO"
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


except Exception as error:

    st.error(
        f"Error obteniendo datos: {error}"
    )


time.sleep(5)

st.rerun()

    
    
