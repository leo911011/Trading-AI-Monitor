import streamlit as st
import requests
import pandas as pd
import json
import os
import time
import base64

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="BTC Predictor - Kalshi 15M",
    page_icon="₿",
    layout="centered"
)

KALSHI_BASE = "https://external-api.kalshi.com"
SERIES_TICKER = "KXBTC15M"

LOCAL_TZ = ZoneInfo("America/Chicago")

HISTORIAL_FILE = "historial_kalshi.json"

REFRESH_SECONDS = 5


# ============================================================
# SECRETS
# ============================================================

try:
    API_KEY_ID = str(
        st.secrets["KALSHI_API_KEY_ID"]
    )

    PRIVATE_KEY = str(
        st.secrets["KALSHI_PRIVATE_KEY"]
    )

except Exception:

    API_KEY_ID = ""
    PRIVATE_KEY = ""


# ============================================================
# AUTENTICACIÓN KALSHI
# ============================================================

def cargar_private_key():

    if not PRIVATE_KEY:

        raise Exception(
            "Falta KALSHI_PRIVATE_KEY "
            "en Streamlit Secrets."
        )

    try:

        return serialization.load_pem_private_key(
            PRIVATE_KEY.encode("utf-8"),
            password=None
        )

    except Exception as e:

        raise Exception(
            "La KALSHI_PRIVATE_KEY no tiene "
            "un formato PEM válido."
        ) from e


def firmar_request(
    timestamp,
    method,
    path
):

    private_key = cargar_private_key()

    path = path.split("?")[0]

    mensaje = (
        str(timestamp)
        +
        method.upper()
        +
        path
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


def kalshi_get(
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

    signature = firmar_request(
        timestamp,
        "GET",
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

    response = requests.get(

        KALSHI_BASE + path,

        headers=headers,

        params=params,

        timeout=15
    )

    if response.status_code != 200:

        raise Exception(
            f"Kalshi HTTP "
            f"{response.status_code}\n\n"
            f"{response.text[:1000]}"
        )

    return response.json()


# ============================================================
# FECHAS
# ============================================================

def parse_fecha(valor):

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
# BUSCAR CONTRATOS BTC 15M
# ============================================================

def obtener_mercados():

    data = kalshi_get(

        "/trade-api/v2/markets",

        params={
            "series_ticker":
                SERIES_TICKER,

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


def buscar_contrato_actual():

    mercados = obtener_mercados()

    ahora = datetime.now(
        timezone.utc
    )

    candidatos = []


    for mercado in mercados:

        cierre = parse_fecha(
            mercado.get(
                "expiration_time"
            )
        )

        if cierre is None:

            cierre = parse_fecha(
                mercado.get(
                    "close_time"
                )
            )

        if cierre is None:

            continue

        if cierre <= ahora:

            continue

        mercado["_cierre"] = cierre

        candidatos.append(
            mercado
        )


    if not candidatos:

        raise Exception(
            "Kalshi no devolvió un "
            "contrato BTC 15M abierto."
        )


    candidatos.sort(
        key=lambda m:
        m["_cierre"]
    )


    return candidatos[0]


# ============================================================
# TARGET REAL
# ============================================================

def obtener_target(
    mercado
):

    valor = mercado.get(
        "functional_strike"
    )

    if valor not in (
        None,
        ""
    ):

        try:

            return float(valor)

        except Exception:

            pass


    valor = mercado.get(
        "floor_strike"
    )

    if valor not in (
        None,
        ""
    ):

        try:

            return float(valor)

        except Exception:

            pass


    raise Exception(
        "Kalshi no devolvió "
        "functional_strike/floor_strike "
        "para este mercado."
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

    datos = response.json()

    if not isinstance(
        datos,
        list
    ):

        raise Exception(
            "CoinGecko no devolvió "
            "una lista de datos."
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


    for columna in [
        "Open",
        "High",
        "Low",
        "Close"
    ]:

        df[columna] = pd.to_numeric(
            df[columna],
            errors="coerce"
        )


    df = df.dropna()

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
        ema12 - ema26
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


    # Momentum 3 velas

    df["Momentum"] = (
        df["Close"]
        .pct_change(3)
        * 100
    )


    return df


# ============================================================
# PREDICCIÓN
# ============================================================

def predecir(
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


    arriba = 0
    abajo = 0

    razones = []


    # --------------------------------------------------------
    # DISTANCIA AL TARGET
    # --------------------------------------------------------

    distancia = (
        precio -
        target
    )

    distancia_pct = (
        distancia /
        target
    ) * 100


    if distancia > 0:

        arriba += 20

        razones.append(
            f"BTC está "
            f"${distancia:,.2f} "
            f"({distancia_pct:+.3f}%) "
            "sobre el Target."
        )

    elif distancia < 0:

        abajo += 20

        razones.append(
            f"BTC está "
            f"${abs(distancia):,.2f} "
            f"({distancia_pct:+.3f}%) "
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

        arriba += 25

        razones.append(
            "EMA9 > EMA21: "
            "tendencia alcista."
        )

    else:

        abajo += 25

        razones.append(
            "EMA9 < EMA21: "
            "tendencia bajista."
        )


    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if macd > 0:

        arriba += 20

        razones.append(
            "MACD positivo."
        )

    else:

        abajo += 20

        razones.append(
            "MACD negativo."
        )


    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if pd.notna(rsi):

        rsi = float(rsi)

        if rsi < 35:

            arriba += 15

            razones.append(
                f"RSI {rsi:.1f}: "
                "posible rebote."
            )

        elif rsi > 65:

            abajo += 15

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

            arriba += 20

            razones.append(
                f"Momentum "
                f"+{momentum:.3f}%."
            )

        elif momentum < 0:

            abajo += 20

            razones.append(
                f"Momentum "
                f"{momentum:.3f}%."
            )


    total = (
        arriba +
        abajo
    )


    if total == 0:

        return (
            "⚪ NO APOSTAR",
            50,
            razones
        )


    if arriba > abajo:

        señal = "🟢 ARRIBA"

        confianza = (
            arriba /
            total
        ) * 100

    elif abajo > arriba:

        señal = "🔴 ABAJO"

        confianza = (
            abajo /
            total
        ) * 100

    else:

        señal = "⚪ NO APOSTAR"

        confianza = 50


    return (
        señal,
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
        ) as archivo:

            datos = json.load(
                archivo
            )

            if isinstance(
                datos,
                list
            ):

                return datos

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
    ) as archivo:

        json.dump(
            historial,
            archivo,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# RESOLUCIÓN REAL DE KALSHI
# ============================================================

def obtener_resultado_real(
    ticker
):

    data = kalshi_get(

        "/trade-api/v2/markets/"
        +
        ticker
    )

    mercado = data.get(
        "market",
        {}
    )


    result = mercado.get(
        "result"
    )


    expiration_value = mercado.get(
        "expiration_value"
    )


    return (
        mercado,
        result,
        expiration_value
    )


def determinar_resultado(
    prediccion,
    mercado,
    target
):

    result = mercado.get(
        "result"
    )


    expiration_value = mercado.get(
        "expiration_value"
    )


    # --------------------------------------------------------
    # SI KALSHI YA DIO RESULT
    # --------------------------------------------------------

    if result:

        result = str(
            result
        ).lower()


        if (
            prediccion ==
            "🟢 ARRIBA"
            and
            result == "yes"
        ):

            return (
                "✅ ACIERTO",
                "YES"
            )


        if (
            prediccion ==
            "🔴 ABAJO"
            and
            result == "no"
        ):

            return (
                "✅ ACIERTO",
                "NO"
            )


        if (
            prediccion ==
            "⚪ NO APOSTAR"
        ):

            return (
                "⚪ NO APOSTAR",
                result.upper()
            )


        return (
            "❌ FALLÓ",
            result.upper()
        )


    # --------------------------------------------------------
    # SI TODAVÍA NO HAY RESULT, USAR EXPIRATION VALUE
    # --------------------------------------------------------

    if expiration_value not in (
        None,
        ""
    ):

        try:

            valor = float(
                expiration_value
            )

            if valor > target:

                resultado = "YES"

            elif valor < target:

                resultado = "NO"

            else:

                resultado = "TIE"


            if (
                prediccion ==
                "🟢 ARRIBA"
                and
                resultado == "YES"
            ):

                return (
                    "✅ ACIERTO",
                    resultado
                )


            if (
                prediccion ==
                "🔴 ABAJO"
                and
                resultado == "NO"
            ):

                return (
                    "✅ ACIERTO",
                    resultado
                )


            if (
                prediccion ==
                "⚪ NO APOSTAR"
            ):

                return (
                    "⚪ NO APOSTAR",
                    resultado
                )


            if resultado == "TIE":

                return (
                    "⚪ EMPATE",
                    resultado
                )


            return (
                "❌ FALLÓ",
                resultado
            )


        except Exception:

            pass


    return (
        "⏳ ESPERANDO RESOLUCIÓN",
        "PENDING"
    )


# ============================================================
# ESTADO DE STREAMLIT
# ============================================================

if "historial" not in st.session_state:

    st.session_state.historial = (
        cargar_historial()
    )


if "ticker_actual" not in st.session_state:

    st.session_state.ticker_actual = None


if "prediccion_actual" not in st.session_state:

    st.session_state.prediccion_actual = None


if "confianza_actual" not in st.session_state:

    st.session_state.confianza_actual = 0


if "target_actual" not in st.session_state:

    st.session_state.target_actual = 0


if "precio_entrada" not in st.session_state:

    st.session_state.precio_entrada = 0


if "hora_entrada" not in st.session_state:

    st.session_state.hora_entrada = ""


if "razones_actuales" not in st.session_state:

    st.session_state.razones_actuales = []


if "cierre_actual" not in st.session_state:

    st.session_state.cierre_actual = None


# ============================================================
# TÍTULO
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15 Min"
)


st.caption(
    "Predicción: ¿BTC terminará ARRIBA "
    "o ABAJO del Target de Kalshi?"
)


# ============================================================
# VALIDAR SECRETS
# ============================================================

if not API_KEY_ID:

    st.error(
        "❌ Falta KALSHI_API_KEY_ID "
        "en Secrets."
    )

    st.stop()


if not PRIVATE_KEY:

    st.error(
        "❌ Falta KALSHI_PRIVATE_KEY "
        "en Secrets."
    )

    st.stop()


# ============================================================
# EJECUCIÓN
# ============================================================

try:

    # --------------------------------------------------------
    # MERCADO
    # --------------------------------------------------------

    mercado = (
        buscar_contrato_actual()
    )

    ticker = mercado.get(
        "ticker"
    )

    target = obtener_target(
        mercado
    )

    cierre = mercado["_cierre"]


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
    # NUEVO CONTRATO
    # --------------------------------------------------------

    if (
        st.session_state.ticker_actual
        !=
        ticker
    ):


        # ====================================================
        # INTENTAR RESOLVER EL CONTRATO ANTERIOR
        # ====================================================

        ticker_anterior = (
            st.session_state.ticker_actual
        )


        if ticker_anterior:

            try:

                (
                    mercado_anterior,
                    result_anterior,
                    expiration_anterior
                ) = obtener_resultado_real(
                    ticker_anterior
                )


                if (
                    st.session_state.prediccion_actual
                ):

                    (
                        resultado_texto,
                        resultado_kalshi
                    ) = determinar_resultado(

                        st.session_state
                        .prediccion_actual,

                        mercado_anterior,

                        st.session_state
                        .target_actual
                    )


                    registro = {

                        "Hora":
                            st.session_state
                            .hora_entrada,

                        "Ticker":
                            ticker_anterior,

                        "Target":
                            round(
                                st.session_state
                                .target_actual,
                                2
                            ),

                        "Precio entrada":
                            round(
                                st.session_state
                                .precio_entrada,
                                2
                            ),

                        "Predicción":
                            st.session_state
                            .prediccion_actual,

                        "Confianza":
                            f"{st.session_state.confianza_actual}%",

                        "Expiration Value":
                            expiration_anterior,

                        "Kalshi":
                            resultado_kalshi,

                        "Resultado":
                            resultado_texto
                    }


                    tickers_guardados = [

                        x.get(
                            "Ticker"
                        )

                        for x
                        in st.session_state.historial
                    ]


                    if (
                        ticker_anterior
                        not in
                        tickers_guardados
                    ):

                        st.session_state.historial.append(
                            registro
                        )

                        guardar_historial(
                            st.session_state
                            .historial
                        )


            except Exception:

                pass


        # ====================================================
        # CREAR PREDICCIÓN NUEVA
        # ====================================================

        (
            prediccion,
            confianza,
            razones
        ) = predecir(

            btc,

            target
        )


        st.session_state.ticker_actual = (
            ticker
        )

        st.session_state.prediccion_actual = (
            prediccion
        )

        st.session_state.confianza_actual = (
            confianza
        )

        st.session_state.target_actual = (
            target
        )

        st.session_state.precio_entrada = (
            precio
        )

        st.session_state.hora_entrada = (
            datetime.now(
                LOCAL_TZ
            ).strftime(
                "%I:%M:%S %p"
            )
        )

        st.session_state.razones_actuales = (
            razones
        )

        st.session_state.cierre_actual = (
            cierre
        )


    # ========================================================
    # CONTADOR
    # ========================================================

    ahora = datetime.now(
        timezone.utc
    )


    segundos = max(

        0,

        int(
            (
                cierre -
                ahora
            ).total_seconds()
        )
    )


    minutos_restantes = (
        segundos // 60
    )

    segundos_restantes = (
        segundos % 60
    )


    # ========================================================
    # INFORMACIÓN KALSHI
    # ========================================================

    st.subheader(
        "🎯 Contrato actual de Kalshi"
    )


    st.write(
        f"**Ticker:** `{ticker}`"
    )


    st.write(
        f"**Target:** "
        f"${target:,.2f}"
    )


    hora_cierre = (
        cierre.astimezone(
            LOCAL_TZ
        )
    )


    st.write(
        f"**Cierre:** "
        f"{hora_cierre.strftime('%I:%M:%S %p')}"
    )


    # ========================================================
    # PRECIO
    # ========================================================

    col1, col2 = st.columns(2)


    col1.metric(
        "₿ BTC actual",
        f"${precio:,.2f}"
    )


    diferencia = (
        precio -
        target
    )


    col2.metric(
        "🎯 Diferencia",
        f"${diferencia:+,.2f}"
    )


    if diferencia > 0:

        st.success(
            f"BTC está "
            f"${diferencia:,.2f} "
            "POR ENCIMA del Target."
        )

    elif diferencia < 0:

        st.error(
            f"BTC está "
            f"${abs(diferencia):,.2f} "
            "POR DEBAJO del Target."
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
        "🔮 Predicción para el cierre"
    )


    st.write(
        f"# {st.session_state.prediccion_actual}"
    )


    st.metric(
        "Confianza",
        f"{st.session_state.confianza_actual}%"
    )


    st.write(
        "Precio de entrada:",
        f"${st.session_state.precio_entrada:,.2f}"
    )


    # ========================================================
    # TEMPORIZADOR
    # ========================================================

    if segundos <= 60:

        st.warning(
            f"🚨 ÚLTIMO MINUTO — "
            f"{minutos_restantes:02d}:"
            f"{segundos_restantes:02d}"
        )

    else:

        st.info(
            f"⏳ Tiempo restante: "
            f"{minutos_restantes:02d}:"
            f"{segundos_restantes:02d}"
        )


    # ========================================================
    # ANÁLISIS
    # ========================================================

    st.subheader(
        "📊 Análisis"
    )


    for razon in (
        st.session_state
        .razones_actuales
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


        if "Resultado" in tabla.columns:

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


            if evaluados:

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
    # NOTA
    # ========================================================

    st.divider()


    st.caption(
        "La aplicación NO coloca apuestas. "
        "Solamente analiza los contratos "
        "BTC 15M de Kalshi y registra "
        "la predicción y su resultado."
    )


except Exception as error:

    st.error(
        "❌ Error"
    )

    st.code(
        str(error)
    )


# ============================================================
# ACTUALIZACIÓN AUTOMÁTICA
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
