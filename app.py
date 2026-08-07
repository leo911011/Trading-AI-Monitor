import streamlit as st
import pandas as pd
import requests
import time
import json
import os
import math

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="BTC Predictor Kalshi 15 Min",
    page_icon="₿",
    layout="centered"
)

CICLO = 15
ZONA = ZoneInfo("America/Chicago")

ARCHIVO_HISTORIAL = "historial_kalshi_btc.json"

KALSHI_SERIES = "KXBTC15M"


# ============================================================
# HORA LOCAL
# ============================================================

def ahora():

    return datetime.now(ZONA)


def inicio_ciclo():

    t = ahora()

    minuto = (t.minute // CICLO) * CICLO

    return t.replace(
        minute=minuto,
        second=0,
        microsecond=0
    )


def fin_ciclo():

    return inicio_ciclo() + timedelta(
        minutes=CICLO
    )


# ============================================================
# HISTORIAL
# ============================================================

def cargar_historial():

    if not os.path.exists(
        ARCHIVO_HISTORIAL
    ):
        return []

    try:

        with open(
            ARCHIVO_HISTORIAL,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except:

        return []


def guardar_historial():

    with open(
        ARCHIVO_HISTORIAL,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            st.session_state.historial,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# MEMORIA
# ============================================================

if "ciclo_id" not in st.session_state:
    st.session_state.ciclo_id = None

if "senal" not in st.session_state:
    st.session_state.senal = None

if "confianza" not in st.session_state:
    st.session_state.confianza = 0

if "precio_inicio" not in st.session_state:
    st.session_state.precio_inicio = 0.0

if "target" not in st.session_state:
    st.session_state.target = None

if "market_ticker" not in st.session_state:
    st.session_state.market_ticker = ""

if "razones" not in st.session_state:
    st.session_state.razones = []

if "historial" not in st.session_state:
    st.session_state.historial = cargar_historial()


# ============================================================
# TÍTULO
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15 Min"
)


# ============================================================
# DATOS BTC
# ============================================================

@st.cache_data(ttl=10)
def obtener_btc():

    url = (
        "https://api.coingecko.com/api/v3/"
        "coins/bitcoin/ohlc"
    )

    params = {
        "vs_currency": "usd",
        "days": "1"
    }

    r = requests.get(
        url,
        params=params,
        timeout=10
    )

    r.raise_for_status()

    datos = r.json()

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

def indicadores(df):

    df = df.copy()

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

    subida = cambio.clip(
        lower=0
    )

    bajada = -cambio.clip(
        upper=0
    )

    media_up = (
        subida
        .rolling(14)
        .mean()
    )

    media_down = (
        bajada
        .rolling(14)
        .mean()
    )

    rs = (
        media_up /
        media_down.replace(
            0,
            pd.NA
        )
    )

    df["RSI"] = (
        100 -
        100 / (1 + rs)
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

    df["MACD"] = (
        ema12 - ema26
    )

    # Momentum

    df["Momentum"] = (
        df["Close"]
        .pct_change(3)
        * 100
    )

    return df


# ============================================================
# TARGET MANUAL
# ============================================================

st.sidebar.header(
    "🎯 Target de Kalshi"
)

st.sidebar.write(
    "Introduce el Target Price que aparece "
    "en tu mercado BTC 15 min de Kalshi."
)

target_manual = st.sidebar.number_input(
    "Target Price",
    min_value=0.0,
    value=0.0,
    step=0.01,
    format="%.2f"
)


# ============================================================
# PREDICTOR
# ============================================================

def predecir(
    df,
    target
):

    precio = float(
        df["Close"].iloc[-1]
    )

    ema9 = float(
        df["EMA9"].iloc[-1]
    )

    ema21 = float(
        df["EMA21"].iloc[-1]
    )

    macd = float(
        df["MACD"].iloc[-1]
    )

    rsi = df["RSI"].iloc[-1]

    momentum = df["Momentum"].iloc[-1]


    # ========================================================
    # DISTANCIA AL TARGET
    # ========================================================

    distancia = (
        target - precio
    )

    distancia_pct = (
        distancia /
        precio
    ) * 100


    subir = 0
    bajar = 0

    razones = []


    # ========================================================
    # TARGET
    # ========================================================

    if precio > target:

        subir += 20

        razones.append(
            f"BTC ya está ${precio-target:,.2f} "
            "por encima del Target"
        )

    else:

        bajar += 20

        razones.append(
            f"BTC está ${target-precio:,.2f} "
            "por debajo del Target"
        )


    # ========================================================
    # EMA
    # ========================================================

    if ema9 > ema21:

        subir += 25

        razones.append(
            "EMA9 > EMA21: tendencia alcista"
        )

    else:

        bajar += 25

        razones.append(
            "EMA9 < EMA21: tendencia bajista"
        )


    # ========================================================
    # MACD
    # ========================================================

    if macd > 0:

        subir += 20

        razones.append(
            "MACD positivo"
        )

    else:

        bajar += 20

        razones.append(
            "MACD negativo"
        )


    # ========================================================
    # RSI
    # ========================================================

    if pd.notna(rsi):

        if rsi < 35:

            subir += 15

            razones.append(
                f"RSI {rsi:.1f}: posible rebote"
            )

        elif rsi > 65:

            bajar += 15

            razones.append(
                f"RSI {rsi:.1f}: presión bajista"
            )

        else:

            razones.append(
                f"RSI {rsi:.1f}: neutral"
            )


    # ========================================================
    # MOMENTUM
    # ========================================================

    if pd.notna(momentum):

        if momentum > 0:

            subir += 20

            razones.append(
                f"Momentum +{momentum:.3f}%"
            )

        elif momentum < 0:

            bajar += 20

            razones.append(
                f"Momentum {momentum:.3f}%"
            )


    # ========================================================
    # RESULTADO
    # ========================================================

    total = subir + bajar


    if subir > bajar:

        señal = "🟢 SUBIR"

        confianza = (
            subir /
            total
        ) * 100

    elif bajar > subir:

        señal = "🔴 BAJAR"

        confianza = (
            bajar /
            total
        ) * 100

    else:

        señal = "⚪ NO APOSTAR"

        confianza = 50


    confianza = round(
        max(
            50,
            min(
                95,
                confianza
            )
        )
    )


    return (
        señal,
        confianza,
        razones,
        distancia,
        distancia_pct
    )


# ============================================================
# OBTENER BTC
# ============================================================

try:

    btc = obtener_btc()

    btc = indicadores(btc)

    precio = float(
        btc["Close"].iloc[-1]
    )


    # ========================================================
    # TARGET
    # ========================================================

    if target_manual > 0:

        target = target_manual

    else:

        target = None


    # ========================================================
    # PANTALLA
    # ========================================================

    st.metric(
        "Precio BTC",
        f"${precio:,.2f}"
    )


    if target is None:

        st.warning(
            "⚠️ Introduce el Target Price "
            "que muestra Kalshi en la barra lateral."
        )

        st.stop()


    # ========================================================
    # PREDICCIÓN
    # ========================================================

    señal, confianza, razones, distancia, distancia_pct = (
        predecir(
            btc,
            target
        )
    )


    inicio = inicio_ciclo()

    fin = (
        inicio +
        timedelta(
            minutes=CICLO
        )
    )

    ciclo_id = inicio.isoformat()


    # ========================================================
    # CREAR PREDICCIÓN SOLO AL INICIO
    # ========================================================

    if (
        st.session_state.ciclo_id
        !=
        ciclo_id
    ):


        # ----------------------------------------------------
        # CERRAR CICLO ANTERIOR
        # ----------------------------------------------------

        if (
            st.session_state.ciclo_id
            is not None
            and
            st.session_state.senal
            is not None
            and
            st.session_state.target
            is not None
        ):

            inicio_anterior = (
                datetime.fromisoformat(
                    st.session_state.ciclo_id
                )
            )

            fin_anterior = (
                inicio_anterior
                +
                timedelta(
                    minutes=CICLO
                )
            )


            precio_final = precio

            target_anterior = (
                st.session_state.target
            )

            señal_anterior = (
                st.session_state.senal
            )


            # ------------------------------------------------
            # RESULTADO CONTRA TARGET
            # ------------------------------------------------

            if precio_final > target_anterior:

                resultado_real = "🟢 SUBIÓ"

            elif precio_final < target_anterior:

                resultado_real = "🔴 BAJÓ"

            else:

                resultado_real = "⚪ IGUAL"


            # ------------------------------------------------
            # ¿ACERTÓ EL PREDICTOR?
            # ------------------------------------------------

            if (
                señal_anterior
                == "🟢 SUBIR"
                and
                resultado_real
                == "🟢 SUBIÓ"
            ):

                resultado = "✅ ACIERTO"


            elif (
                señal_anterior
                == "🔴 BAJAR"
                and
                resultado_real
                == "🔴 BAJÓ"
            ):

                resultado = "✅ ACIERTO"


            elif (
                señal_anterior
                == "⚪ NO APOSTAR"
            ):

                resultado = "⚪ NO APOSTAR"


            else:

                resultado = "❌ FALLÓ"


            nombre_ciclo = (
                f"{inicio_anterior.strftime('%H:%M')}"
                f" - "
                f"{fin_anterior.strftime('%H:%M')}"
            )


            ciclos_guardados = [

                x.get("Ciclo")

                for x
                in st.session_state.historial
            ]


            if (
                nombre_ciclo
                not in
                ciclos_guardados
            ):

                st.session_state.historial.append({

                    "Ciclo":
                    nombre_ciclo,

                    "Target":
                    round(
                        target_anterior,
                        2
                    ),

                    "Predicción":
                    señal_anterior,

                    "Confianza":
                    f"{st.session_state.confianza}%",

                    "Entrada":
                    round(
                        st.session_state.precio_inicio,
                        2
                    ),

                    "Final":
                    round(
                        precio_final,
                        2
                    ),

                    "Resultado BTC":
                    resultado_real,

                    "Resultado":
                    resultado
                })


                guardar_historial()


        # ----------------------------------------------------
        # NUEVO CICLO
        # ----------------------------------------------------

        st.session_state.ciclo_id = ciclo_id

        st.session_state.senal = señal

        st.session_state.confianza = confianza

        st.session_state.precio_inicio = precio

        st.session_state.target = target

        st.session_state.razones = razones


    # ========================================================
    # TARGET
    # ========================================================

    st.subheader(
        "🎯 Target Price de Kalshi"
    )

    st.metric(
        "Target",
        f"${st.session_state.target:,.2f}"
    )


    diferencia_actual = (
        precio -
        st.session_state.target
    )


    if diferencia_actual > 0:

        st.success(
            f"BTC está "
            f"${diferencia_actual:,.2f} "
            f"POR ENCIMA del Target"
        )

    else:

        st.error(
            f"BTC está "
            f"${abs(diferencia_actual):,.2f} "
            f"POR DEBAJO del Target"
        )


    # ========================================================
    # PREDICCIÓN
    # ========================================================

    st.subheader(
        "Predicción próximos 15 minutos"
    )


    st.write(
        f"## {st.session_state.senal}"
    )


    st.write(
        f"**Confianza: "
        f"{st.session_state.confianza}%**"
    )


    st.write(
        f"Precio actual: "
        f"${precio:,.2f}"
    )


    st.write(
        f"Target: "
        f"${st.session_state.target:,.2f}"
    )


    st.write(
        f"Ciclo: "
        f"{inicio.strftime('%H:%M')} → "
        f"{fin.strftime('%H:%M')}"
    )


    # ========================================================
    # ANÁLISIS
    # ========================================================

    st.subheader(
        "Análisis"
    )


    for r in st.session_state.razones:

        st.write(
            "✅",
            r
        )


    # ========================================================
    # TEMPORIZADOR
    # ========================================================

    restante = (
        fin -
        ahora()
    )


    segundos_restantes = max(
        0,
        int(
            restante.total_seconds()
        )
    )


    minutos = (
        segundos_restantes //
        60
    )

    segundos = (
        segundos_restantes %
        60
    )


    if segundos_restantes <= 60:

        st.warning(
            f"⚠️ ÚLTIMO MINUTO: "
            f"{minutos:02d}:{segundos:02d}"
        )


    st.subheader(
        f"⏳ Próximo ciclo en "
        f"{minutos:02d}:{segundos:02d}"
    )


    # ========================================================
    # GRÁFICO
    # ========================================================

    st.subheader(
        "📈 BTC"
    )

    st.line_chart(
        btc["Close"]
    )


    # ========================================================
    # HISTORIAL
    # ========================================================

    st.subheader(
        "📜 Historial Kalshi"
    )


    if st.session_state.historial:

        tabla = pd.DataFrame(
            st.session_state.historial
        )


        st.dataframe(
            tabla,
            use_container_width=True,
            hide_index=True
        )


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


        evaluados = (
            aciertos +
            fallos
        )


        if evaluados > 0:

            precision = (
                aciertos /
                evaluados
            ) * 100

        else:

            precision = 0


        c1, c2, c3 = st.columns(3)


        c1.metric(
            "Aciertos",
            aciertos
        )

        c2.metric(
            "Fallos",
            fallos
        )

        c3.metric(
            "Precisión",
            f"{precision:.1f}%"
        )


    else:

        st.info(
            "El historial aparecerá "
            "al terminar el primer ciclo."
        )


    # ========================================================
    # AVISO
    # ========================================================

    st.divider()

    st.caption(
        "Esta aplicación predice la dirección respecto "
        "al Target Price. No garantiza ganancias ni "
        "reproduce necesariamente el precio de liquidación "
        "de Kalshi."
    )


except Exception as e:

    st.error(
        f"Error: {e}"
    )


# ============================================================
# ACTUALIZACIÓN AUTOMÁTICA
# ============================================================

time.sleep(5)

st.rerun()        except:
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
        f"Error: {e}"
    )


# ============================================================
# ACTUALIZACIÓN AUTOMÁTICA
# ============================================================

time.sleep(5)

st.rerun()
