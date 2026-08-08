import streamlit as st
import requests
import pandas as pd
import json
import os
import time
import base64
import re
import math

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="BTC Kalshi Predictor 15M",
    page_icon="₿",
    layout="centered"
)

KALSHI_URL = "https://external-api.kalshi.com"
SERIES = "KXBTC15M"

LOCAL_TZ = ZoneInfo("America/Chicago")

HISTORIAL_FILE = "historial_kalshi.json"

REFRESH_SECONDS = 5

PREDICT_SECONDS_BEFORE_CLOSE = 60


# ============================================================
# CREDENCIALES
# ============================================================

def cargar_credenciales():

    try:

        key_id = st.secrets["KALSHI_API_KEY_ID"]
        private_key = st.secrets["KALSHI_PRIVATE_KEY"]

        return str(key_id), str(private_key)

    except Exception:

        return None, None


API_KEY_ID, PRIVATE_KEY = cargar_credenciales()


# ============================================================
# CLAVE PRIVADA
# ============================================================

def cargar_clave_privada():

    if not PRIVATE_KEY:

        raise Exception(
            "Falta KALSHI_PRIVATE_KEY en Streamlit Secrets."
        )

    return serialization.load_pem_private_key(
        PRIVATE_KEY.strip().encode("utf-8"),
        password=None
    )


# ============================================================
# FIRMA
# ============================================================

def crear_firma(timestamp, method, path):

    private_key = cargar_clave_privada()

    path_sin_query = path.split("?")[0]

    mensaje = (
        f"{timestamp}"
        f"{method.upper()}"
        f"{path_sin_query}"
    ).encode("utf-8")

    firma = private_key.sign(

        mensaje,

        padding.PSS(
            mgf=padding.MGF1(
                hashes.SHA256()
            ),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),

        hashes.SHA256()
    )

    return base64.b64encode(
        firma
    ).decode("utf-8")


# ============================================================
# REQUEST KALSHI
# ============================================================

def kalshi_request(
    method,
    path,
    params=None
):

    if not API_KEY_ID:

        raise Exception(
            "Falta KALSHI_API_KEY_ID."
        )

    timestamp = str(
        int(time.time() * 1000)
    )

    signature = crear_firma(
        timestamp,
        method,
        path
    )

    headers = {

        "KALSHI-ACCESS-KEY":
            API_KEY_ID,

        "KALSHI-ACCESS-TIMESTAMP":
            timestamp,

        "KALSHI-ACCESS-SIGNATURE":
            signature,

        "Content-Type":
            "application/json"
    }

    response = requests.request(

        method=method.upper(),

        url=KALSHI_URL + path,

        headers=headers,

        params=params,

        timeout=15
    )

    if response.status_code >= 400:

        raise Exception(
            f"Kalshi HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json()


# ============================================================
# FECHAS
# ============================================================

def convertir_fecha(valor):

    if not valor:
        return None

    try:

        return datetime.fromisoformat(
            str(valor).replace(
                "Z",
                "+00:00"
            )
        )

    except Exception:

        return None


# ============================================================
# OBTENER MERCADOS
# ============================================================

def obtener_mercados_btc():

    data = kalshi_request(

        "GET",

        "/trade-api/v2/markets",

        params={

            "series_ticker":
                SERIES,

            "status":
                "open",

            "limit":
                100
        }
    )

    return data.get(
        "markets",
        []
    )


# ============================================================
# CONTRATO ACTUAL
# ============================================================

def buscar_mercado_actual():

    mercados = obtener_mercados_btc()

    ahora = datetime.now(
        timezone.utc
    )

    candidatos = []


    for mercado in mercados:

        cierre = convertir_fecha(
            mercado.get(
                "close_time"
            )
        )

        if cierre is None:

            cierre = convertir_fecha(
                mercado.get(
                    "expiration_time"
                )
            )

        if cierre is None:
            continue


        if cierre > ahora:

            mercado["_close"] = cierre

            candidatos.append(
                mercado
            )


    if not candidatos:

        raise Exception(
            "No encontré un contrato BTC 15M abierto."
        )


    candidatos.sort(
        key=lambda x: x["_close"]
    )

    return candidatos[0]


# ============================================================
# CONTRATO POR TICKER
# ============================================================

def obtener_contrato(
    ticker
):

    data = kalshi_request(

        "GET",

        "/trade-api/v2/markets/" + ticker
    )

    return data.get(
        "market",
        {}
    )


# ============================================================
# TARGET
# ============================================================

def obtener_target(
    mercado
):

    campos = [

        "functional_strike",

        "floor_strike",

        "cap_strike",

        "strike",

        "target"
    ]


    for campo in campos:

        valor = mercado.get(
            campo
        )

        if valor in (
            None,
            ""
        ):
            continue

        try:

            numero = float(
                valor
            )

            if numero > 1000:

                return numero

        except Exception:

            pass


    texto = " ".join([

        str(
            mercado.get(
                "title",
                ""
            )
        ),

        str(
            mercado.get(
                "subtitle",
                ""
            )
        ),

        str(
            mercado.get(
                "yes_sub_title",
                ""
            )
        ),

        str(
            mercado.get(
                "no_sub_title",
                ""
            )
        )
    ])


    numeros = re.findall(

        r"([0-9][0-9,]*(?:\.[0-9]+)?)",

        texto
    )


    for numero in numeros:

        try:

            valor = float(
                numero.replace(
                    ",",
                    ""
                )
            )

            if valor > 1000:

                return valor

        except Exception:

            pass


    raise Exception(
        "No pude encontrar el Target."
    )


# ============================================================
# BTC BINANCE
# ============================================================

def obtener_btc():

    response = requests.get(

        "https://api.binance.us/api/v3/klines",

        params={

            "symbol":
                "BTCUSDT",

            "interval":
                "1m",

            "limit":
                120
        },

        timeout=10
    )

    response.raise_for_status()

    data = response.json()


    if not isinstance(
        data,
        list
    ):

        raise Exception(
            "Binance no devolvió datos válidos."
        )


    df = pd.DataFrame(

        data,

        columns=[

            "time",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "close_time",
            "quote_volume",
            "trades",
            "buy_volume",
            "buy_quote_volume",
            "ignore"
        ]
    )


    for columna in [

        "Open",
        "High",
        "Low",
        "Close",
        "Volume"

    ]:

        df[columna] = pd.to_numeric(

            df[columna],

            errors="coerce"
        )


    df = df.dropna(
        subset=["Close"]
    )


    return df


# ============================================================
# INDICADORES
# ============================================================

def calcular_indicadores(
    df
):

    df = df.copy()


    # EMA 9

    df["EMA9"] = (

        df["Close"]

        .ewm(
            span=9,
            adjust=False
        )

        .mean()
    )


    # EMA 21

    df["EMA21"] = (

        df["Close"]

        .ewm(
            span=21,
            adjust=False
        )

        .mean()
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
        ema12 -
        ema26
    )


    # RSI

    cambio = df["Close"].diff()

    ganancias = cambio.clip(
        lower=0
    )

    perdidas = -cambio.clip(
        upper=0
    )


    avg_gain = (
        ganancias
        .rolling(14)
        .mean()
    )


    avg_loss = (
        perdidas
        .rolling(14)
        .mean()
    )


    rs = (

        avg_gain /

        avg_loss.replace(
            0,
            pd.NA
        )
    )


    df["RSI"] = (

        100 -

        (
            100 /
            (1 + rs)
        )
    )


    # MOMENTUM

    df["Momentum1"] = (

        df["Close"]
        .pct_change(1)
        * 100
    )


    df["Momentum3"] = (

        df["Close"]
        .pct_change(3)
        * 100
    )


    df["Momentum5"] = (

        df["Close"]
        .pct_change(5)
        * 100
    )


    df["Momentum10"] = (

        df["Close"]
        .pct_change(10)
        * 100
    )


    # VOLATILIDAD

    df["Volatilidad"] = (

        df["Close"]
        .pct_change()
        .rolling(15)
        .std()
        * 100
    )


    return df


# ============================================================
# PREDICCIÓN
# ============================================================

def generar_prediccion(
    df,
    target
):

    ultimo = df.iloc[-1]


    precio = float(
        ultimo["Close"]
    )


    target = float(
        target
    )


    ema9 = float(
        ultimo["EMA9"]
    )


    ema21 = float(
        ultimo["EMA21"]
    )


    macd = float(
        ultimo["MACD"]
    )


    rsi = ultimo["RSI"]


    momentum1 = ultimo[
        "Momentum1"
    ]


    momentum3 = ultimo[
        "Momentum3"
    ]


    momentum5 = ultimo[
        "Momentum5"
    ]


    momentum10 = ultimo[
        "Momentum10"
    ]


    volatilidad = ultimo[
        "Volatilidad"
    ]


    razones = []


    # ========================================================
    # DISTANCIA AL TARGET
    # ========================================================

    diferencia = (
        precio -
        target
    )


    distancia_pct = (

        diferencia /
        target
    ) * 100


    # ========================================================
    # SCORE DE MERCADO
    # ========================================================

    score = 0


    # --------------------------------------------------------
    # TARGET
    # --------------------------------------------------------

    # El Target tiene peso importante,
    # pero NO decide por sí solo.

    if diferencia > 0:

        score += 15

        razones.append(

            f"BTC está ${diferencia:,.2f} "
            f"({distancia_pct:+.3f}%) "
            "por encima del Target."
        )

    elif diferencia < 0:

        score -= 15

        razones.append(

            f"BTC está ${abs(diferencia):,.2f} "
            f"({distancia_pct:+.3f}%) "
            "por debajo del Target."
        )

    else:

        razones.append(
            "BTC está exactamente en el Target."
        )


    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if ema9 > ema21:

        score += 15

        razones.append(
            "EMA9 > EMA21: tendencia alcista."
        )

    else:

        score -= 15

        razones.append(
            "EMA9 < EMA21: tendencia bajista."
        )


    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if macd > 0:

        score += 12

        razones.append(
            "MACD positivo."
        )

    else:

        score -= 12

        razones.append(
            "MACD negativo."
        )


    # --------------------------------------------------------
    # MOMENTUM 1M
    # --------------------------------------------------------

    if pd.notna(momentum1):

        if momentum1 > 0:

            score += 8

            razones.append(
                f"Momentum 1m positivo "
                f"(+{float(momentum1):.3f}%)."
            )

        elif momentum1 < 0:

            score -= 8

            razones.append(
                f"Momentum 1m negativo "
                f"({float(momentum1):.3f}%)."
            )


    # --------------------------------------------------------
    # MOMENTUM 3M
    # --------------------------------------------------------

    if pd.notna(momentum3):

        if momentum3 > 0:

            score += 10

            razones.append(
                f"Momentum 3m positivo "
                f"(+{float(momentum3):.3f}%)."
            )

        elif momentum3 < 0:

            score -= 10

            razones.append(
                f"Momentum 3m negativo "
                f"({float(momentum3):.3f}%)."
            )


    # --------------------------------------------------------
    # MOMENTUM 5M
    # --------------------------------------------------------

    if pd.notna(momentum5):

        if momentum5 > 0:

            score += 10

            razones.append(
                f"Momentum 5m positivo "
                f"(+{float(momentum5):.3f}%)."
            )

        elif momentum5 < 0:

            score -= 10

            razones.append(
                f"Momentum 5m negativo "
                f"({float(momentum5):.3f}%)."
            )


    # --------------------------------------------------------
    # MOMENTUM 10M
    # --------------------------------------------------------

    if pd.notna(momentum10):

        if momentum10 > 0:

            score += 8

            razones.append(
                f"Momentum 10m positivo "
                f"(+{float(momentum10):.3f}%)."
            )

        elif momentum10 < 0:

            score -= 8

            razones.append(
                f"Momentum 10m negativo "
                f"({float(momentum10):.3f}%)."
            )


    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if pd.notna(rsi):

        rsi = float(rsi)


        if rsi < 30:

            score += 6

            razones.append(
                f"RSI {rsi:.1f}: sobreventa."
            )

        elif rsi > 70:

            score -= 6

            razones.append(
                f"RSI {rsi:.1f}: sobrecompra."
            )

        elif rsi >= 50:

            score += 3

            razones.append(
                f"RSI {rsi:.1f}: ligeramente alcista."
            )

        else:

            score -= 3

            razones.append(
                f"RSI {rsi:.1f}: ligeramente bajista."
            )


    # --------------------------------------------------------
    # VOLATILIDAD
    # --------------------------------------------------------

    if pd.notna(volatilidad):

        volatilidad = float(
            volatilidad
        )

        razones.append(
            f"Volatilidad 15m: "
            f"{volatilidad:.4f}%."
        )


    # ========================================================
    # DECISIÓN
    # ========================================================

    # Score máximo aproximado:
    # 15+15+12+8+10+10+8+6 = 84


    if score >= 10:

        prediccion = "🟢 ARRIBA"

    elif score <= -10:

        prediccion = "🔴 ABAJO"

    else:

        prediccion = "⚪ NO APOSTAR"


    # ========================================================
    # CONFIANZA
    # ========================================================

    fuerza = min(
        abs(score),
        70
    )


    if prediccion == "⚪ NO APOSTAR":

        confianza = 50

    else:

        confianza = 50 + (
            fuerza *
            0.60
        )


    confianza = int(
        round(
            max(
                50,
                min(
                    92,
                    confianza
                )
            )
        )
    )


    # ========================================================
    # EXPLICACIÓN DEL SCORE
    # ========================================================

    razones.append(
        f"Score final del modelo: {score:+d}."
    )


    return (
        prediccion,
        confianza,
        razones,
        score
    )


# ============================================================
# HISTORIAL
# ============================================================

def cargar_historial():

    if not os.path.exists(
        HISTORIAL_FILE
    ):

        return []


    try:

        with open(
            HISTORIAL_FILE,
            "r",
            encoding="utf-8"
        ) as archivo:

            data = json.load(
                archivo
            )


            if isinstance(
                data,
                list
            ):

                return data


    except Exception:

        pass


    return []


def guardar_historial(
    historial
):

    temporal = (
        HISTORIAL_FILE +
        ".tmp"
    )


    with open(
        temporal,
        "w",
        encoding="utf-8"
    ) as archivo:

        json.dump(
            historial,
            archivo,
            indent=2,
            ensure_ascii=False
        )


    os.replace(
        temporal,
        HISTORIAL_FILE
    )


# ============================================================
# GUARDAR PREDICCIÓN
# ============================================================

def guardar_prediccion(
    ticker,
    target,
    prediccion,
    confianza,
    precio,
    close_time,
    score
):

    historial = (
        st.session_state.historial
    )


    for registro in historial:

        if (
            registro.get(
                "Ticker"
            )
            == ticker
        ):

            return


    registro = {

        "Ticker":
            ticker,

        "Target":
            round(
                float(target),
                2
            ),

        "Predicción":
            prediccion,

        "Confianza":
            f"{confianza}%",

        "Score":
            score,

        "Precio predicción":
            round(
                float(precio),
                2
            ),

        "Cierre":
            close_time.astimezone(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S %p"
            ),

        "Expiration Value":
            None,

        "Resultado Kalshi":
            "PENDIENTE",

        "Resultado":
            "⏳ PENDIENTE",

        "Momento predicción":
            datetime.now(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S"
            )
    }


    historial.append(
        registro
    )


    guardar_historial(
        historial
    )


# ============================================================
# RESULTADO KALSHI
# ============================================================

def obtener_resultado_kalshi(
    ticker,
    target
):

    try:

        mercado = obtener_contrato(
            ticker
        )

    except Exception:

        return None, None


    resultado = mercado.get(
        "result"
    )


    expiration = mercado.get(
        "expiration_value"
    )


    if resultado not in (
        None,
        "",
        "null"
    ):

        resultado = str(
            resultado
        ).upper()


        if resultado in (
            "UP",
            "YES"
        ):

            return "UP", expiration


        if resultado in (
            "DOWN",
            "NO"
        ):

            return "DOWN", expiration


    if expiration not in (
        None,
        ""
    ):

        try:

            exp = float(
                expiration
            )

            target = float(
                target
            )


            if exp > target:

                return "UP", exp


            if exp < target:

                return "DOWN", exp


            return "TIE", exp


        except Exception:

            pass


    return None, expiration


# ============================================================
# ACTUALIZAR RESULTADOS
# ============================================================

def actualizar_pendientes():

    historial = (
        st.session_state.historial
    )


    cambio = False


    for registro in historial:

        if registro.get(
            "Resultado"
        ) != "⏳ PENDIENTE":

            continue


        ticker = registro.get(
            "Ticker"
        )


        target = registro.get(
            "Target"
        )


        if not ticker or target is None:

            continue


        resultado_real, expiration = (
            obtener_resultado_kalshi(
                ticker,
                target
            )
        )


        if resultado_real is None:

            continue


        prediccion = registro.get(
            "Predicción"
        )


        if (

            prediccion == "🟢 ARRIBA"

            and

            resultado_real == "UP"

        ):

            resultado = "✅ ACIERTO"


        elif (

            prediccion == "🔴 ABAJO"

            and

            resultado_real == "DOWN"

        ):

            resultado = "✅ ACIERTO"


        elif (

            prediccion == "⚪ NO APOSTAR"

        ):

            resultado = "⚪ NO APOSTAR"


        elif resultado_real == "TIE":

            resultado = "⚪ EMPATE"


        else:

            resultado = "❌ FALLÓ"


        registro[
            "Expiration Value"
        ] = expiration


        registro[
            "Resultado Kalshi"
        ] = resultado_real


        registro[
            "Resultado"
        ] = resultado


        registro[
            "Actualizado"
        ] = datetime.now(
            LOCAL_TZ
        ).strftime(
            "%Y-%m-%d %I:%M:%S"
        )


        cambio = True


    if cambio:

        guardar_historial(
            historial
        )


# ============================================================
# BUSCAR SIGUIENTE CONTRATO
# ============================================================

def buscar_siguiente_contrato(
    contrato_actual
):

    mercados = obtener_mercados_btc()


    cierre_actual = convertir_fecha(
        contrato_actual.get(
            "close_time"
        )
    )


    if cierre_actual is None:

        cierre_actual = convertir_fecha(
            contrato_actual.get(
                "expiration_time"
            )
        )


    candidatos = []


    for mercado in mercados:

        ticker = mercado.get(
            "ticker"
        )


        if ticker == contrato_actual.get(
            "ticker"
        ):

            continue


        cierre = convertir_fecha(
            mercado.get(
                "close_time"
            )
        )


        if cierre is None:

            cierre = convertir_fecha(
                mercado.get(
                    "expiration_time"
                )
            )


        if cierre is None:

            continue


        if (
            cierre_actual
            and
            cierre > cierre_actual
        ):

            mercado["_close"] = cierre

            candidatos.append(
                mercado
            )


    if not candidatos:

        return None


    candidatos.sort(
        key=lambda x: x["_close"]
    )


    return candidatos[0]


# ============================================================
# SESSION STATE
# ============================================================

if "historial" not in st.session_state:

    st.session_state.historial = (
        cargar_historial()
    )


if "contrato_observado" not in st.session_state:

    st.session_state.contrato_observado = None


if "prediccion_hecha" not in st.session_state:

    st.session_state.prediccion_hecha = False


if "ticker_predicho" not in st.session_state:

    st.session_state.ticker_predicho = None


if "prediccion" not in st.session_state:

    st.session_state.prediccion = None


if "confianza" not in st.session_state:

    st.session_state.confianza = 0


if "target_predicho" not in st.session_state:

    st.session_state.target_predicho = None


if "precio_prediccion" not in st.session_state:

    st.session_state.precio_prediccion = None


if "razones" not in st.session_state:

    st.session_state.razones = []


if "score" not in st.session_state:

    st.session_state.score = 0


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Predicción del siguiente contrato usando "
    "Target de Kalshi + comportamiento del mercado."
)


# ============================================================
# CREDENCIALES
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ Faltan las credenciales de Kalshi."
    )

    st.stop()


# ============================================================
# ACTUALIZAR HISTORIAL
# ============================================================

try:

    actualizar_pendientes()

except Exception as error:

    st.warning(
        f"No se pudieron actualizar resultados: "
        f"{error}"
    )


# ============================================================
# EJECUCIÓN
# ============================================================

try:

    # --------------------------------------------------------
    # CONTRATO ACTUAL
    # --------------------------------------------------------

    actual = buscar_mercado_actual()


    ticker_actual = actual.get(
        "ticker"
    )


    close_actual = actual.get(
        "_close"
    )


    if close_actual is None:

        close_actual = convertir_fecha(
            actual.get(
                "close_time"
            )
        )


    target_actual = obtener_target(
        actual
    )


    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    btc = obtener_btc()

    btc = calcular_indicadores(
        btc
    )


    precio = float(
        btc["Close"].iloc[-1]
    )


    # --------------------------------------------------------
    # CAMBIO DE CONTRATO
    # --------------------------------------------------------

    if (
        st.session_state.contrato_observado
        != ticker_actual
    ):

        st.session_state.contrato_observado = (
            ticker_actual
        )

        st.session_state.prediccion_hecha = (
            False
        )

        st.session_state.ticker_predicho = None

        st.session_state.prediccion = None

        st.session_state.confianza = 0

        st.session_state.target_predicho = None

        st.session_state.precio_prediccion = None

        st.session_state.razones = []

        st.session_state.score = 0


    # --------------------------------------------------------
    # TIEMPO
    # --------------------------------------------------------

    ahora = datetime.now(
        timezone.utc
    )


    segundos_restantes = max(

        0,

        int(
            (
                close_actual -
                ahora
            ).total_seconds()
        )
    )


    minutos = (
        segundos_restantes // 60
    )


    segundos = (
        segundos_restantes % 60
    )


    # ========================================================
    # PREDICCIÓN 1 MINUTO ANTES
    # ========================================================

    if (

        segundos_restantes <=
        PREDICT_SECONDS_BEFORE_CLOSE

        and

        segundos_restantes > 0

        and

        not st.session_state.prediccion_hecha

    ):


        siguiente = (
            buscar_siguiente_contrato(
                actual
            )
        )


        if siguiente is not None:


            ticker_siguiente = (
                siguiente.get(
                    "ticker"
                )
            )


            target_siguiente = (
                obtener_target(
                    siguiente
                )
            )


            close_siguiente = (
                siguiente.get(
                    "_close"
                )
            )


            if close_siguiente is None:

                close_siguiente = convertir_fecha(
                    siguiente.get(
                        "close_time"
                    )
                )


            (
                prediccion,
                confianza,
                razones,
                score

            ) = generar_prediccion(

                btc,

                target_siguiente
            )


            guardar_prediccion(

                ticker_siguiente,

                target_siguiente,

                prediccion,

                confianza,

                precio,

                close_siguiente,

                score
            )


            st.session_state.prediccion_hecha = True


            st.session_state.ticker_predicho = (
                ticker_siguiente
            )


            st.session_state.prediccion = (
                prediccion
            )


            st.session_state.confianza = (
                confianza
            )


            st.session_state.target_predicho = (
                target_siguiente
            )


            st.session_state.precio_prediccion = (
                precio
            )


            st.session_state.razones = (
                razones
            )


            st.session_state.score = (
                score
            )


    # ========================================================
    # CONTRATO ACTUAL
    # ========================================================

    st.subheader(
        "🎯 Contrato actual"
    )


    st.write(
        f"**Ticker:** `{ticker_actual}`"
    )


    titulo = actual.get(
        "title",
        ""
    )


    subtitulo = actual.get(
        "subtitle",
        ""
    )


    if titulo:

        st.write(
            titulo
        )


    if subtitulo:

        st.caption(
            subtitulo
        )


    # ========================================================
    # BTC / TARGET
    # ========================================================

    c1, c2 = st.columns(2)


    c1.metric(

        "₿ BTC actual",

        f"${precio:,.2f}"
    )


    c2.metric(

        "🎯 Target actual",

        f"${target_actual:,.2f}"
    )


    diferencia = (

        precio -
        target_actual
    )


    diferencia_pct = (

        diferencia /
        target_actual
    ) * 100


    if diferencia > 0:

        st.success(

            f"BTC está ${diferencia:,.2f} "

            f"({diferencia_pct:+.3f}%) "

            "POR ENCIMA del Target."
        )


    elif diferencia < 0:

        st.error(

            f"BTC está ${abs(diferencia):,.2f} "

            f"({diferencia_pct:+.3f}%) "

            "POR DEBAJO del Target."
        )


    else:

        st.warning(
            "BTC está exactamente en el Target."
        )


    # ========================================================
    # TEMPORIZADOR
    # ========================================================

    if segundos_restantes <= 60:

        st.warning(

            f"⚠️ ÚLTIMO MINUTO — "
            f"{minutos:02d}:{segundos:02d}"
        )

    else:

        st.info(

            f"⏳ Tiempo restante: "
            f"{minutos:02d}:{segundos:02d}"
        )


    hora_cierre = (
        close_actual.astimezone(
            LOCAL_TZ
        )
    )


    st.write(

        "Cierre:",

        hora_cierre.strftime(
            "%I:%M:%S %p"
        )
    )


    # ========================================================
    # PREDICCIÓN
    # ========================================================

    st.divider()


    st.subheader(
        "🔮 Predicción del SIGUIENTE contrato"
    )


    if st.session_state.prediccion is not None:


        st.write(
            f"# {st.session_state.prediccion}"
        )


        st.metric(

            "Confianza",

            f"{st.session_state.confianza}%"
        )


        st.write(

            f"**Siguiente contrato:** "

            f"`{st.session_state.ticker_predicho}`"
        )


        st.write(

            f"**Target siguiente:** "

            f"${st.session_state.target_predicho:,.2f}"
        )


        st.write(

            f"**BTC al realizar la predicción:** "

            f"${st.session_state.precio_prediccion:,.2f}"
        )


        st.write(

            f"**Score:** "

            f"{st.session_state.score:+d}"
        )


        st.subheader(
            "📊 Análisis"
        )


        for razon in (
            st.session_state.razones
        ):

            st.write(
                "•",
                razon
            )


    else:


        segundos_para_prediccion = (

            segundos_restantes -
            PREDICT_SECONDS_BEFORE_CLOSE
        )


        if segundos_para_prediccion > 0:


            pm = (
                segundos_para_prediccion
                // 60
            )


            ps = (
                segundos_para_prediccion
                % 60
            )


            st.info(

                "La predicción se realizará "
                "cuando falte 1 minuto. "

                f"Faltan aproximadamente "
                f"{pm:02d}:{ps:02d}."
            )


        else:

            st.warning(

                "⏳ Esperando información "
                "del siguiente contrato..."
            )


    # ========================================================
    # GRÁFICO
    # ========================================================

    st.divider()


    st.subheader(
        "📈 BTC — últimos 120 minutos"
    )


    grafico = btc[
        ["Close"]
    ].copy()


    grafico.index = range(
        len(grafico)
    )


    st.line_chart(
        grafico,
        height=350
    )


    # ========================================================
    # HISTORIAL
    # ========================================================

    st.divider()


    st.subheader(
        "📜 Historial de predicciones"
    )


    try:

        actualizar_pendientes()

    except Exception:

        pass


    historial = (
        st.session_state.historial
    )


    if historial:


        tabla = pd.DataFrame(
            historial
        )


        st.dataframe(

            tabla,

            use_container_width=True,

            hide_index=True
        )


        aciertos = sum(

            1

            for x in historial

            if x.get(
                "Resultado"
            )
            == "✅ ACIERTO"
        )


        fallos = sum(

            1

            for x in historial

            if x.get(
                "Resultado"
            )
            == "❌ FALLÓ"
        )


        pendientes = sum(

            1

            for x in historial

            if x.get(
                "Resultado"
            )
            == "⏳ PENDIENTE"
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


        a, b, c, d = (
            st.columns(4)
        )


        a.metric(
            "✅ Aciertos",
            aciertos
        )


        b.metric(
            "❌ Fallos",
            fallos
        )


        c.metric(
            "⏳ Pendientes",
            pendientes
        )


        d.metric(

            "🎯 Precisión",

            f"{precision:.1f}%"
        )


    else:

        st.info(
            "Todavía no hay predicciones."
        )


    # ========================================================
    # AVISO
    # ========================================================

    st.divider()


    st.caption(

        "El modelo combina el Target del contrato "
        "de Kalshi con tendencia, MACD, RSI, momentum "
        "y volatilidad de BTC. La predicción se intenta "
        "generar 1 minuto antes del cierre del contrato "
        "actual para el siguiente contrato."
    )


except Exception as error:

    st.error(
        "❌ Error de ejecución"
    )

    st.code(
        str(error)
    )


# ============================================================
# REFRESH
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
