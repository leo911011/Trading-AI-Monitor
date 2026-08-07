import streamlit as st
import pandas as pd
import requests
import time
import json
import os
from datetime import datetime, timedelta


# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="BTC Predictor 15 Min",
    page_icon="₿",
    layout="centered"
)

CICLO = 15

ARCHIVO_HISTORIAL = "historial_btc.json"


# ============================================================
# ARCHIVOS
# ============================================================

def cargar_historial():

    if os.path.exists(ARCHIVO_HISTORIAL):

        try:
            with open(ARCHIVO_HISTORIAL, "r") as f:
                return json.load(f)

        except:
            return []

    return []


def guardar_historial(historial):

    with open(ARCHIVO_HISTORIAL, "w") as f:

        json.dump(
            historial,
            f,
            indent=2
        )


# ============================================================
# CICLOS FIJOS DE 15 MINUTOS
# ============================================================

def obtener_inicio_ciclo():

    ahora = datetime.now()

    minuto = (ahora.minute // CICLO) * CICLO

    inicio = ahora.replace(
        minute=minuto,
        second=0,
        microsecond=0
    )

    return inicio


def obtener_fin_ciclo():

    return (
        obtener_inicio_ciclo()
        + timedelta(minutes=CICLO)
    )


# ============================================================
# MEMORIA STREAMLIT
# ============================================================

if "ciclo_actual" not in st.session_state:

    st.session_state.ciclo_actual = None


if "senal_actual" not in st.session_state:

    st.session_state.senal_actual = None


if "confianza_actual" not in st.session_state:

    st.session_state.confianza_actual = 0


if "precio_entrada" not in st.session_state:

    st.session_state.precio_entrada = 0


if "hora_entrada" not in st.session_state:

    st.session_state.hora_entrada = ""


if "razones_actuales" not in st.session_state:

    st.session_state.razones_actuales = []


if "historial" not in st.session_state:

    st.session_state.historial = cargar_historial()


# ============================================================
# TÍTULO
# ============================================================

st.title("₿ Bitcoin Predictor - Ciclos de 15 minutos")


# ============================================================
# DATOS BTC
# ============================================================

@st.cache_data(ttl=15)
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

    respuesta.raise_for_status()

    datos = respuesta.json()

    if not isinstance(datos, list):

        raise Exception(
            "CoinGecko no devolvió datos válidos"
        )


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


# ============================================================
# INDICADORES
# ============================================================

def calcular_indicadores(df):

    df = df.copy()


    # EMA

    df["EMA9"] = (
        df["Close"]
        .ewm(
            span=9,
            adjust=False
        )
        .mean()
    )


    df["EMA21"] = (
        df["Close"]
        .ewm(
            span=21,
            adjust=False
        )
        .mean()
    )


    # RSI

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


    rs = (
        media_subida /
        media_bajada.replace(0, pd.NA)
    )


    df["RSI"] = (
        100 -
        (100 / (1 + rs))
    )


    # MACD

    ema12 = (
        df["Close"]
        .ewm(
            span=12,
            adjust=False
        )
        .mean()
    )


    ema26 = (
        df["Close"]
        .ewm(
            span=26,
            adjust=False
        )
        .mean()
    )


    df["MACD"] = ema12 - ema26


    return df


# ============================================================
# ANÁLISIS
# ============================================================

def analizar(df):

    ultimo = df.iloc[-1]


    # ========================================================
    # PUNTUACIÓN
    # ========================================================

    subir = 0
    bajar = 0

    razones = []


    # EMA

    if ultimo["EMA9"] > ultimo["EMA21"]:

        subir += 25

        razones.append(
            "EMA9 > EMA21: tendencia alcista"
        )

    else:

        bajar += 25

        razones.append(
            "EMA9 < EMA21: tendencia bajista"
        )


    # MACD

    if ultimo["MACD"] > 0:

        subir += 25

        razones.append(
            "MACD positivo"
        )

    else:

        bajar += 25

        razones.append(
            "MACD negativo"
        )


    # RSI

    rsi = ultimo["RSI"]


    if pd.notna(rsi):

        if rsi < 35:

            subir += 20

            razones.append(
                f"RSI {rsi:.1f}: posible rebote"
            )

        elif rsi > 65:

            bajar += 20

            razones.append(
                f"RSI {rsi:.1f}: posible presión bajista"
            )

        else:

            razones.append(
                f"RSI {rsi:.1f}: zona neutral"
            )


    # Momentum

    if len(df) >= 4:

        precio_actual = df["Close"].iloc[-1]

        precio_anterior = df["Close"].iloc[-4]

        cambio = (
            (precio_actual - precio_anterior)
            / precio_anterior
        ) * 100


        if cambio > 0:

            subir += 30

            razones.append(
                f"Momentum positivo: +{cambio:.3f}%"
            )

        elif cambio < 0:

            bajar += 30

            razones.append(
                f"Momentum negativo: {cambio:.3f}%"
            )

        else:

            razones.append(
                "Momentum neutral"
            )


    # ========================================================
    # DECISIÓN
    # ========================================================

    total = subir + bajar


    if total == 0:

        return (
            "⚪ NO APOSTAR",
            50,
            razones
        )


    if subir > bajar:

        confianza = (
            subir / total
        ) * 100

        señal = "🟢 SUBIR"

    elif bajar > subir:

        confianza = (
            bajar / total
        ) * 100

        señal = "🔴 BAJAR"

    else:

        confianza = 50

        señal = "⚪ NO APOSTAR"


    confianza = round(
        max(50, min(99, confianza))
    )


    # Si la ventaja es muy pequeña,
    # mejor no apostar.

    diferencia = abs(
        subir - bajar
    )


    if diferencia < 15:

        señal = "⚪ NO APOSTAR"


    return (
        señal,
        confianza,
        razones
    )


# ============================================================
# FUNCIÓN PARA GUARDAR RESULTADO
# ============================================================

def guardar_resultado(
    señal,
    confianza,
    entrada,
    salida,
    inicio,
    fin
):

    cambio = salida - entrada


    if señal == "🟢 SUBIR":

        correcto = salida > entrada

    elif señal == "🔴 BAJAR":

        correcto = salida < entrada

    else:

        correcto = None


    if correcto is True:

        resultado = "✅ ACIERTO"

    elif correcto is False:

        resultado = "❌ FALLÓ"

    else:

        resultado = "⚪ NO APOSTAR"


    registro = {

        "Ciclo":
        f"{inicio.strftime('%H:%M')} - {fin.strftime('%H:%M')}",

        "Predicción":
        señal,

        "Confianza":
        f"{confianza}%",

        "Entrada":
        round(entrada, 2),

        "Salida":
        round(salida, 2),

        "Cambio":
        round(cambio, 2),

        "Resultado":
        resultado
    }


    st.session_state.historial.append(
        registro
    )


    guardar_historial(
        st.session_state.historial
    )


# ============================================================
# APP PRINCIPAL
# ============================================================

try:

    btc = obtener_btc()

    btc = calcular_indicadores(btc)


    precio_actual = float(
        btc["Close"].iloc[-1]
    )


    ahora = datetime.now()

    inicio_ciclo = obtener_inicio_ciclo()

    fin_ciclo = inicio_ciclo + timedelta(
        minutes=CICLO
    )


    # ========================================================
    # DETECTAR NUEVO CICLO
    # ========================================================

    ciclo_id = inicio_ciclo.isoformat()


    if st.session_state.ciclo_actual != ciclo_id:


        # ----------------------------------------------------
        # CERRAR CICLO ANTERIOR
        # ----------------------------------------------------

        if (
            st.session_state.ciclo_actual is not None
            and
            st.session_state.senal_actual is not None
        ):

            inicio_anterior = (
                datetime.fromisoformat(
                    st.session_state.ciclo_actual
                )
            )


            fin_anterior = (
                inicio_anterior
                + timedelta(minutes=CICLO)
            )


            # Evitar duplicados

            ciclos_guardados = [

                x.get("Ciclo")
                for x in st.session_state.historial
            ]


            nombre_ciclo = (
                f"{inicio_anterior.strftime('%H:%M')} - "
                f"{fin_anterior.strftime('%H:%M')}"
            )


            if nombre_ciclo not in ciclos_guardados:

                guardar_resultado(

                    st.session_state.senal_actual,

                    st.session_state.confianza_actual,

                    st.session_state.precio_entrada,

                    precio_actual,

                    inicio_anterior,

                    fin_anterior
                )


        # ----------------------------------------------------
        # CREAR NUEVO CICLO
        # ----------------------------------------------------

        nueva_señal, confianza, razones = analizar(
            btc
        )


        st.session_state.ciclo_actual = ciclo_id

        st.session_state.senal_actual = nueva_señal

        st.session_state.confianza_actual = confianza

        st.session_state.precio_entrada = precio_actual

        st.session_state.hora_entrada = (
            inicio_ciclo.strftime("%H:%M:%S")
        )

        st.session_state.razones_actuales = razones


    # ========================================================
    # PRECIO
    # ========================================================

    st.metric(
        "Precio BTC",
        f"${precio_actual:,.2f}"
    )


    # ========================================================
    # PREDICCIÓN
    # ========================================================

    st.subheader(
        "Predicción próximos 15 minutos"
    )


    st.write(
        f"### {st.session_state.senal_actual}"
    )


    st.write(
        f"**Confianza: "
        f"{st.session_state.confianza_actual}%**"
    )


    st.write(
        f"Entrada: "
        f"${st.session_state.precio_entrada:,.2f}"
    )


    st.write(
        f"Ciclo: "
        f"{inicio_ciclo.strftime('%H:%M')} → "
        f"{fin_ciclo.strftime('%H:%M')}"
    )


    # ========================================================
    # ANÁLISIS
    # ========================================================

    st.write("### Análisis")


    for razon in st.session_state.razones_actuales:

        st.write(
            "✅",
            razon
        )


    # ========================================================
    # TEMPORIZADOR
    # ========================================================

    restante = (
        fin_ciclo - ahora
    )


    segundos_restantes = max(
        0,
        int(
            restante.total_seconds()
        )
    )


    minutos = (
        segundos_restantes // 60
    )


    segundos = (
        segundos_restantes % 60
    )


    if segundos_restantes <= 60:

        st.warning(
            f"⚠️ ¡ATENCIÓN! "
            f"Queda {minutos:02d}:{segundos:02d} "
            f"para cerrar el ciclo."
        )


    st.subheader(
        f"⏳ Próximo ciclo en "
        f"{minutos:02d}:{segundos:02d}"
    )


    # ========================================================
    # GRÁFICO
    # ========================================================

    st.subheader("📈 Gráfico BTC")


    st.line_chart(
        btc["Close"]
    )


    # ========================================================
    # HISTORIAL
    # ========================================================

    st.subheader(
        "📜 Historial de predicciones"
    )


    if len(st.session_state.historial) > 0:


        tabla = pd.DataFrame(
            st.session_state.historial
        )


        st.dataframe(
            tabla,
            use_container_width=True,
            hide_index=True
        )


        # ====================================================
        # ESTADÍSTICAS
        # ====================================================

        resultados = tabla["Resultado"]


        total = len(tabla)


        aciertos = len(
            tabla[
                tabla["Resultado"]
                ==
                "✅ ACIERTO"
            ]
        )


        fallos = len(
            tabla[
                tabla["Resultado"]
                ==
                "❌ FALLÓ"
            ]
        )


        precision = (
            aciertos /
            total
        ) * 100


        col1, col2, col3 = st.columns(3)


        col1.metric(
            "Ciclos",
            total
        )


        col2.metric(
            "Aciertos",
            aciertos
        )


        col3.metric(
            "Precisión",
            f"{precision:.1f}%"
        )


        st.write(
            f"❌ Fallos: **{fallos}**"
        )


    else:

        st.info(
            "El historial aparecerá "
            "cuando termine el primer ciclo."
        )


    # ========================================================
    # INFORMACIÓN KALSHI
    # ========================================================

    st.divider()

    st.caption(
        "⚠️ El resultado mostrado por esta aplicación "
        "compara el precio de entrada y salida de BTC. "
        "Esto no garantiza que coincida exactamente con "
        "la resolución del contrato de Kalshi."
    )


except Exception as e:

    st.error(
        f"Error obteniendo datos: {e}"
    )


# ============================================================
# ACTUALIZACIÓN AUTOMÁTICA
# ============================================================

time.sleep(5)

st.rerun()
