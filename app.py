impimport streamlit as st
import requests
import pandas as pd
import json
import os
import time
import base64
import re

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
# FIRMA KALSHI
# ============================================================

def cargar_clave_privada():

    if not PRIVATE_KEY:

        raise Exception(
            "No existe KALSHI_PRIVATE_KEY "
            "en Streamlit Secrets."
        )

    return serialization.load_pem_private_key(
        PRIVATE_KEY.encode("utf-8"),
        password=None
    )


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
            "Falta KALSHI_API_KEY_ID "
            "en Streamlit Secrets."
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
            f"Kalshi HTTP "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json()


# ============================================================
# MERCADOS BTC 15 MIN
# ============================================================

def obtener_mercados_btc():

    data = kalshi_request(

        "GET",

        "/trade-api/v2/markets",

        params={
            "series_ticker": SERIES,
            "status": "open",
            "limit": 100
        }
    )

    return data.get(
        "markets",
        []
    )


# ============================================================
# FECHA
# ============================================================

def convertir_fecha(texto):

    if not texto:

        return None

    try:

        return datetime.fromisoformat(
            texto.replace(
                "Z",
                "+00:00"
            )
        )

    except Exception:

        return None


# ============================================================
# BUSCAR MERCADO ACTUAL
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
            "No encontré un mercado "
            "BTC 15M abierto."
        )


    candidatos.sort(
        key=lambda x:
        x["_close"]
    )


    return candidatos[0]


# ============================================================
# TARGET
# ============================================================

def obtener_target(mercado):

    funcional = mercado.get(
        "functional_strike"
    )

    if funcional not in (
        None,
        ""
    ):

        try:

            return float(
                funcional
            )

        except Exception:

            pass


    floor = mercado.get(
        "floor_strike"
    )

    if floor not in (
        None,
        ""
    ):

        try:

            return float(
                floor
            )

        except Exception:

            pass


    cap = mercado.get(
        "cap_strike"
    )

    if cap not in (
        None,
        ""
    ):

        try:

            return float(
                cap
            )

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
        "No pude encontrar "
        "el Target del mercado."
    )


# ============================================================
# BTC
# ============================================================

@st.cache_data(ttl=5)
def obtener_btc():

    url = (
        "https://api.coingecko.com/api/v3/"
        "coins/bitcoin/ohlc"
    )

    response = requests.get(

        url,

        params={
            "vs_currency": "usd",
            "days": "1"
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
            "CoinGecko no devolvió "
            "datos válidos."
        )

    df = pd.DataFrame(

        data,

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

    momentum = ultimo["Momentum"]


    subir = 0
    bajar = 0

    razones = []


    # --------------------------------------------------------
    # DISTANCIA AL TARGET
    # --------------------------------------------------------

    distancia = (
        precio -
        target
    )


    if distancia > 0:

        subir += 20

        razones.append(
            f"BTC está "
            f"${distancia:,.2f} "
            "sobre el Target."
        )

    elif distancia < 0:

        bajar += 20

        razones.append(
            f"BTC está "
            f"${abs(distancia):,.2f} "
            "debajo del Target."
        )

    else:

        razones.append(
            "BTC está exactamente "
            "en el Target."
        )


    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if ema9 > ema21:

        subir += 25

        razones.append(
            "EMA9 > EMA21: "
            "tendencia alcista."
        )

    else:

        bajar += 25

        razones.append(
            "EMA9 < EMA21: "
            "tendencia bajista."
        )


    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if macd > 0:

        subir += 20

        razones.append(
            "MACD positivo."
        )

    else:

        bajar += 20

        razones.append(
            "MACD negativo."
        )


    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if pd.notna(rsi):

        rsi = float(rsi)


        if rsi < 35:

            subir += 15

            razones.append(
                f"RSI {rsi:.1f}: "
                "posible rebote."
            )

        elif rsi > 65:

            bajar += 15

            razones.append(
                f"RSI {rsi:.1f}: "
                "presión bajista."
            )

        else:

            razones.append(
                f"RSI {rsi:.1f}: "
                "zona neutral."
            )


    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if pd.notna(momentum):

        momentum = float(
            momentum
        )


        if momentum > 0:

            subir += 20

            razones.append(
                f"Momentum "
                f"+{momentum:.3f}%."
            )

        elif momentum < 0:

            bajar += 20

            razones.append(
                f"Momentum "
                f"{momentum:.3f}%."
            )


    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    total = (
        subir +
        bajar
    )


    if subir > bajar:

        prediccion = "🟢 SUBIR"

        confianza = (
            subir /
            total
        ) * 100

    elif bajar > subir:

        prediccion = "🔴 BAJAR"

        confianza = (
            bajar /
            total
        ) * 100

    else:

        prediccion = (
            "⚪ NO APOSTAR"
        )

        confianza = 50


    return (
        prediccion,
        round(confianza),
        razones
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
        ) as f:

            data = json.load(f)

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

    with open(
        HISTORIAL_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            historial,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# ESTADO
# ============================================================

if "historial" not in st.session_state:

    st.session_state.historial = (
        cargar_historial()
    )


if "ticker" not in st.session_state:

    st.session_state.ticker = None


if "prediccion" not in st.session_state:

    st.session_state.prediccion = None


if "confianza" not in st.session_state:

    st.session_state.confianza = 0


if "precio_inicio" not in st.session_state:

    st.session_state.precio_inicio = 0


if "target" not in st.session_state:

    st.session_state.target = 0


if "close_time" not in st.session_state:

    st.session_state.close_time = None


if "razones" not in st.session_state:

    st.session_state.razones = []


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15 Min"
)


# ============================================================
# COMPROBAR CREDENCIALES
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ No se encontraron "
        "las credenciales de Kalshi."
    )

    st.info(
        "Revisa Streamlit → "
        "Settings → Secrets."
    )

    st.stop()


# ============================================================
# EJECUCIÓN
# ============================================================

try:

    # --------------------------------------------------------
    # MERCADO KALSHI
    # --------------------------------------------------------

    mercado = (
        buscar_mercado_actual()
    )


    ticker = mercado.get(
        "ticker"
    )


    target = obtener_target(
        mercado
    )


    close_time = (
        mercado["_close"]
    )


    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    btc = obtener_btc()

    btc = indicadores(
        btc
    )


    precio = float(
        btc["Close"].iloc[-1]
    )


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
                close_time -
                ahora
            ).total_seconds()
        )
    )


    # --------------------------------------------------------
    # NUEVO CONTRATO
    # --------------------------------------------------------

    if (
        st.session_state.ticker
        !=
        ticker
    ):


        # ====================================================
        # CERRAR CONTRATO ANTERIOR
        # ====================================================

        if (
            st.session_state.ticker
            and
            st.session_state.prediccion
        ):

            try:

                anterior = (
                    kalshi_request(

                        "GET",

                        "/trade-api/v2/markets/"
                        +
                        st.session_state.ticker
                    )
                )


                mercado_anterior = (
                    anterior.get(
                        "market",
                        {}
                    )
                )


                expiration_value = (
                    mercado_anterior.get(
                        "expiration_value"
                    )
                )


                resultado_kalshi = (
                    mercado_anterior.get(
                        "result"
                    )
                )


                if resultado_kalshi:

                    resultado_real = (
                        resultado_kalshi.upper()
                    )

                elif (
                    expiration_value
                    not in
                    (None, "")
                ):

                    try:

                        exp = float(
                            expiration_value
                        )

                        if (
                            exp >
                            st.session_state.target
                        ):

                            resultado_real = (
                                "UP"
                            )

                        elif (
                            exp <
                            st.session_state.target
                        ):

                            resultado_real = (
                                "DOWN"
                            )

                        else:

                            resultado_real = (
                                "TIE"
                            )

                    except Exception:

                        resultado_real = (
                            "UNKNOWN"
                        )

                else:

                    resultado_real = (
                        "UNKNOWN"
                    )


                pred = (
                    st.session_state.prediccion
                )


                if (
                    pred == "🟢 SUBIR"
                    and
                    resultado_real == "UP"
                ):

                    resultado = (
                        "✅ ACIERTO"
                    )

                elif (
                    pred == "🔴 BAJAR"
                    and
                    resultado_real == "DOWN"
                ):

                    resultado = (
                        "✅ ACIERTO"
                    )

                elif (
                    pred ==
                    "⚪ NO APOSTAR"
                ):

                    resultado = (
                        "⚪ NO APOSTAR"
                    )

                elif (
                    resultado_real ==
                    "UNKNOWN"
                ):

                    resultado = (
                        "⏳ SIN RESOLVER"
                    )

                else:

                    resultado = (
                        "❌ FALLÓ"
                    )


                registro = {

                    "Ticker":
                        st.session_state.ticker,

                    "Target":
                        round(
                            st.session_state.target,
                            2
                        ),

                    "Predicción":
                        pred,

                    "Confianza":
                        f"{st.session_state.confianza}%",

                    "Precio entrada":
                        round(
                            st.session_state.precio_inicio,
                            2
                        ),

                    "Expiration Value":
                        expiration_value,

                    "Resultado Kalshi":
                        resultado_real,

                    "Resultado":
                        resultado
                }


                tickers = [

                    x.get(
                        "Ticker"
                    )

                    for x
                    in st.session_state.historial
                ]


                if (
                    st.session_state.ticker
                    not in tickers
                ):

                    st.session_state.historial.append(
                        registro
                    )

                    guardar_historial(
                        st.session_state.historial
                    )


            except Exception as cierre_error:

                st.warning(
                    "No pude verificar "
                    "todavía el resultado "
                    "del contrato anterior: "
                    +
                    str(cierre_error)
                )


        # ====================================================
        # NUEVA PREDICCIÓN
        # ====================================================

        prediccion, confianza, razones = (
            generar_prediccion(
                btc,
                target
            )
        )


        st.session_state.ticker = (
            ticker
        )

        st.session_state.prediccion = (
            prediccion
        )

        st.session_state.confianza = (
            confianza
        )

        st.session_state.precio_inicio = (
            precio
        )

        st.session_state.target = (
            target
        )

        st.session_state.close_time = (
            close_time.isoformat()
        )

        st.session_state.razones = (
            razones
        )


    # ========================================================
    # MERCADO
    # ========================================================

    st.subheader(
        "🎯 Contrato Kalshi"
    )


    st.write(
        f"**Ticker:** `{ticker}`"
    )


    titulo = mercado.get(
        "title",
        ""
    )


    subtitulo = mercado.get(
        "subtitle",
        ""
    )


    if titulo:

        st.write(
            f"**{titulo}**"
        )


    if subtitulo:

        st.caption(
            subtitulo
        )


    # ========================================================
    # PRECIO / TARGET
    # ========================================================

    col1, col2 = st.columns(2)


    col1.metric(
        "₿ BTC",
        f"${precio:,.2f}"
    )


    col2.metric(
        "🎯 Target",
        f"${st.session_state.target:,.2f}"
    )


    diferencia = (
        precio -
        st.session_state.target
    )


    if diferencia > 0:

        st.success(
            f"BTC está "
            f"${diferencia:,.2f} "
            "POR ENCIMA del Target"
        )

    elif diferencia < 0:

        st.error(
            f"BTC está "
            f"${abs(diferencia):,.2f} "
            "POR DEBAJO del Target"
        )

    else:

        st.warning(
            "BTC está exactamente "
            "en el Target."
        )


    # ========================================================
    # PREDICCIÓN
    # ========================================================

    st.subheader(
        "🔮 Predicción"
    )


    st.write(
        f"# {st.session_state.prediccion}"
    )


    st.metric(
        "Confianza",
        f"{st.session_state.confianza}%"
    )


    st.write(
        f"Precio al entrar: "
        f"${st.session_state.precio_inicio:,.2f}"
    )


    # ========================================================
    # TIEMPO
    # ========================================================

    minutos = (
        segundos_restantes // 60
    )

    segundos = (
        segundos_restantes % 60
    )


    if segundos_restantes <= 60:

        st.warning(
            f"⚠️ ÚLTIMO MINUTO "
            f"{minutos:02d}:{segundos:02d}"
        )


    st.subheader(
        f"⏳ Cierra en "
        f"{minutos:02d}:{segundos:02d}"
    )


    hora_cierre_local = (
        close_time.astimezone(
            LOCAL_TZ
        )
    )


    st.write(
        "Cierre:",
        hora_cierre_local.strftime(
            "%I:%M:%S %p"
        )
    )


    # ========================================================
    # ANÁLISIS
    # ========================================================

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
        "📜 Historial"
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


        a, b, c = st.columns(3)


        a.metric(
            "✅ Aciertos",
            aciertos
        )


        b.metric(
            "❌ Fallos",
            fallos
        )


        c.metric(
            "🎯 Precisión",
            f"{precision:.1f}%"
        )


    else:

        st.info(
            "El historial aparecerá "
            "cuando termine el primer "
            "contrato."
        )


    # ========================================================
    # INFORMACIÓN
    # ========================================================

    st.divider()


    st.caption(
        "Esta aplicación solamente "
        "analiza el mercado. "
        "NO coloca apuestas automáticamente."
    )


except Exception as error:

    st.error(
        "❌ Error de ejecución"
    )

    st.code(
        str(error)
    )


# ============================================================
# ACTUALIZACIÓN
# ============================================================

time.sleep(5)

st.rerun()
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
