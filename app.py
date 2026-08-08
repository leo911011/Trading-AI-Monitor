import streamlit as st
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

# API oficial de producción de Kalshi
KALSHI_BASE = "https://external-api.kalshi.com"

# Serie BTC 15 minutos
SERIES = "KXBTC15M"

# Omaha/Nebraska está en Central Time
LOCAL_TZ = ZoneInfo("America/Chicago")

HISTORIAL_FILE = "historial_kalshi.json"


# ============================================================
# CREDENCIALES
# ============================================================

def cargar_credenciales():

    try:
        key_id = st.secrets["KALSHI_API_KEY_ID"]
        private_key = st.secrets["KALSHI_PRIVATE_KEY"]

        return str(key_id).strip(), str(private_key).strip()

    except Exception:
        return None, None


API_KEY_ID, PRIVATE_KEY = cargar_credenciales()


# ============================================================
# FIRMA RSA-PSS
# ============================================================

def cargar_clave_privada():

    if not PRIVATE_KEY:
        raise Exception(
            "Falta KALSHI_PRIVATE_KEY en Streamlit Secrets."
        )

    key = PRIVATE_KEY.strip()

    # Aceptamos RSA PRIVATE KEY o PRIVATE KEY
    if "-----BEGIN RSA PRIVATE KEY-----" in key:
        inicio = key.index("-----BEGIN RSA PRIVATE KEY-----")
        fin = key.index("-----END RSA PRIVATE KEY-----") + len(
            "-----END RSA PRIVATE KEY-----"
        )
        key = key[inicio:fin]

    elif "-----BEGIN PRIVATE KEY-----" in key:
        inicio = key.index("-----BEGIN PRIVATE KEY-----")
        fin = key.index("-----END PRIVATE KEY-----") + len(
            "-----END PRIVATE KEY-----"
        )
        key = key[inicio:fin]

    else:
        raise Exception(
            "KALSHI_PRIVATE_KEY no contiene un bloque PEM válido."
        )

    try:

        return serialization.load_pem_private_key(
            key.encode("utf-8"),
            password=None
        )

    except Exception as e:

        raise Exception(
            "La KALSHI_PRIVATE_KEY no tiene un formato PEM válido. "
            f"{e}"
        )


def crear_firma(timestamp, method, path):

    private_key = cargar_clave_privada()

    # La firma se hace sobre el path completo de la API,
    # sin query parameters.
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

    return base64.b64encode(firma).decode("utf-8")


# ============================================================
# REQUEST KALSHI
# ============================================================

def kalshi_request(method, path, params=None):

    if not API_KEY_ID:
        raise Exception(
            "Falta KALSHI_API_KEY_ID en Streamlit Secrets."
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
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Content-Type": "application/json"
    }

    url = KALSHI_BASE + path

    response = requests.request(
        method=method.upper(),
        url=url,
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

    if valor is None:
        return None

    if isinstance(valor, datetime):

        if valor.tzinfo is None:
            return valor.replace(
                tzinfo=timezone.utc
            )

        return valor

    texto = str(valor).strip()

    if not texto:
        return None

    # Unix timestamp
    try:

        numero = float(texto)

        if numero > 100000000000:
            return datetime.fromtimestamp(
                numero / 1000,
                tz=timezone.utc
            )

        if numero > 1000000000:
            return datetime.fromtimestamp(
                numero,
                tz=timezone.utc
            )

    except Exception:
        pass

    # ISO/RFC3339
    try:

        fecha = datetime.fromisoformat(
            texto.replace(
                "Z",
                "+00:00"
            )
        )

        if fecha.tzinfo is None:
            fecha = fecha.replace(
                tzinfo=timezone.utc
            )

        return fecha

    except Exception:
        return None


# ============================================================
# OBTENER TODOS LOS MERCADOS DE LA SERIE
# ============================================================

def obtener_mercados_btc():

    # Primero intentamos abiertos.
    data = kalshi_request(
        "GET",
        "/trade-api/v2/markets",
        params={
            "series_ticker": SERIES,
            "status": "open",
            "limit": 100
        }
    )

    mercados = data.get(
        "markets",
        []
    )

    # Si por algún cambio temporal la respuesta viene vacía,
    # consultamos sin status.
    if not mercados:

        data = kalshi_request(
            "GET",
            "/trade-api/v2/markets",
            params={
                "series_ticker": SERIES,
                "limit": 100
            }
        )

        mercados = data.get(
            "markets",
            []
        )

    return mercados


# ============================================================
# OBTENER CIERRE DEL MERCADO
# ============================================================

def obtener_cierre(mercado):

    campos = [
        "close_time",
        "expiration_time",
        "close_ts",
        "expiration_ts"
    ]

    for campo in campos:

        valor = mercado.get(campo)

        fecha = convertir_fecha(valor)

        if fecha:
            return fecha

    return None


# ============================================================
# OBTENER APERTURA
# ============================================================

def obtener_apertura(mercado):

    campos = [
        "open_time",
        "created_time",
        "open_ts",
        "created_ts"
    ]

    for campo in campos:

        fecha = convertir_fecha(
            mercado.get(campo)
        )

        if fecha:
            return fecha

    return None


# ============================================================
# BUSCAR EL CONTRATO REALMENTE VIGENTE
# ============================================================

def buscar_mercado_actual():

    mercados = obtener_mercados_btc()

    ahora = datetime.now(
        timezone.utc
    )

    candidatos = []

    for mercado in mercados:

        ticker = mercado.get(
            "ticker",
            ""
        )

        # Solo BTC 15M
        if not ticker.startswith(
            SERIES
        ):
            continue

        cierre = obtener_cierre(
            mercado
        )

        if cierre is None:
            continue

        # Debe cerrar en el futuro
        if cierre <= ahora:
            continue

        apertura = obtener_apertura(
            mercado
        )

        # Si conocemos apertura, descartamos mercados
        # que todavía no comenzaron.
        if apertura and apertura > ahora:
            continue

        mercado["_close"] = cierre

        if apertura:
            mercado["_open"] = apertura

        candidatos.append(
            mercado
        )

    if not candidatos:

        raise Exception(
            "No encontré un contrato BTC 15M vigente. "
            "Kalshi puede estar entre ciclos o la serie "
            "puede haber cambiado."
        )

    # El contrato vigente debe ser el que cierre primero
    candidatos.sort(
        key=lambda x: x["_close"]
    )

    return candidatos[0]


# ============================================================
# TARGET
# ============================================================

def obtener_target(mercado):

    campos = [
        "functional_strike",
        "floor_strike",
        "cap_strike"
    ]

    for campo in campos:

        valor = mercado.get(campo)

        if valor not in (None, ""):

            try:
                return float(valor)
            except Exception:
                pass

    # Algunos mercados pueden tener el target
    # dentro de title/subtitle.
    texto = " ".join([
        str(mercado.get("title", "")),
        str(mercado.get("subtitle", "")),
        str(mercado.get("yes_sub_title", "")),
        str(mercado.get("no_sub_title", ""))
    ])

    numeros = re.findall(
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
        texto
    )

    valores = []

    for numero in numeros:

        try:

            valor = float(
                numero.replace(",", "")
            )

            if valor > 1000:
                valores.append(valor)

        except Exception:
            pass

    if valores:

        # En mercados BTC el strike suele ser el número
        # relevante del título.
        return valores[0]

    raise Exception(
        "No pude encontrar el Target del mercado."
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

    if not isinstance(data, list):
        raise Exception(
            "CoinGecko no devolvió datos válidos."
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

    if len(df) < 30:
        raise Exception(
            "No hay suficientes datos de BTC."
        )

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
# PREDICCIÓN RELACIONADA CON EL TARGET
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

    distancia = precio - target

    porcentaje_target = (
        distancia /
        target
    ) * 100

    if distancia > 0:

        subir += 20

        razones.append(
            f"BTC está ${distancia:,.2f} "
            f"({porcentaje_target:+.3f}%) "
            "sobre el Target."
        )

    elif distancia < 0:

        bajar += 20

        razones.append(
            f"BTC está ${abs(distancia):,.2f} "
            f"({porcentaje_target:+.3f}%) "
            "debajo del Target."
        )

    else:

        razones.append(
            "BTC está exactamente en el Target."
        )

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if ema9 > ema21:

        subir += 25

        razones.append(
            "EMA9 > EMA21: tendencia alcista."
        )

    else:

        bajar += 25

        razones.append(
            "EMA9 < EMA21: tendencia bajista."
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
                f"RSI {rsi:.1f}: posible rebote."
            )

        elif rsi > 65:

            bajar += 15

            razones.append(
                f"RSI {rsi:.1f}: presión bajista."
            )

        else:

            razones.append(
                f"RSI {rsi:.1f}: zona neutral."
            )

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if pd.notna(momentum):

        momentum = float(momentum)

        if momentum > 0:

            subir += 20

            razones.append(
                f"Momentum +{momentum:.3f}%."
            )

        elif momentum < 0:

            bajar += 20

            razones.append(
                f"Momentum {momentum:.3f}%."
            )

    total = subir + bajar

    if total <= 0:

        return (
            "⚪ NO APOSTAR",
            50,
            razones
        )

    if subir > bajar:

        prediccion = "🟢 ARRIBA"

        confianza = (
            subir / total
        ) * 100

    elif bajar > subir:

        prediccion = "🔴 ABAJO"

        confianza = (
            bajar / total
        ) * 100

    else:

        prediccion = "⚪ NO APOSTAR"

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

            if isinstance(data, list):
                return data

    except Exception:
        pass

    return []


def guardar_historial(historial):

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
# OBTENER RESULTADO REAL DE KALSHI
# ============================================================

def obtener_resultado_kalshi(ticker):

    data = kalshi_request(
        "GET",
        "/trade-api/v2/markets/" + ticker
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


# ============================================================
# INTERPRETAR RESULTADO
# ============================================================

def interpretar_resultado(
    mercado,
    result,
    expiration_value,
    target
):

    # Resultado oficial
    if result:

        resultado = str(
            result
        ).upper()

        if resultado in [
            "YES",
            "UP",
            "ABOVE"
        ]:
            return "UP"

        if resultado in [
            "NO",
            "DOWN",
            "BELOW"
        ]:
            return "DOWN"

    # Fallback: expiration value
    if expiration_value not in (
        None,
        ""
    ):

        try:

            valor = float(
                expiration_value
            )

            if valor > target:
                return "UP"

            if valor < target:
                return "DOWN"

            return "TIE"

        except Exception:
            pass

    return "UNKNOWN"


# ============================================================
# GUARDAR RESULTADO DE CONTRATO ANTERIOR
# ============================================================

def cerrar_contrato_anterior():

    ticker_anterior = (
        st.session_state.ticker
    )

    if not ticker_anterior:
        return

    # Evitar duplicados
    for item in st.session_state.historial:

        if item.get("Ticker") == ticker_anterior:
            return

    try:

        (
            mercado,
            result,
            expiration_value
        ) = obtener_resultado_kalshi(
            ticker_anterior
        )

        resultado_real = interpretar_resultado(
            mercado,
            result,
            expiration_value,
            st.session_state.target
        )

        pred = (
            st.session_state.prediccion
        )

        if (
            pred == "🟢 ARRIBA"
            and
            resultado_real == "UP"
        ):

            resultado = "✅ ACIERTO"

        elif (
            pred == "🔴 ABAJO"
            and
            resultado_real == "DOWN"
        ):

            resultado = "✅ ACIERTO"

        elif (
            pred == "⚪ NO APOSTAR"
        ):

            resultado = "⚪ NO APOSTAR"

        elif (
            resultado_real == "UNKNOWN"
        ):

            resultado = "⏳ SIN RESOLVER"

        elif (
            resultado_real == "TIE"
        ):

            resultado = "⚪ EMPATE"

        else:

            resultado = "❌ FALLÓ"

        registro = {

            "Hora local":
                st.session_state.hora_entrada,

            "Ticker":
                ticker_anterior,

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

        st.session_state.historial.append(
            registro
        )

        guardar_historial(
            st.session_state.historial
        )

    except Exception as e:

        # Guardamos el contrato como pendiente
        # para no perderlo.
        registro = {

            "Hora local":
                st.session_state.hora_entrada,

            "Ticker":
                ticker_anterior,

            "Target":
                round(
                    st.session_state.target,
                    2
                ),

            "Predicción":
                st.session_state.prediccion,

            "Confianza":
                f"{st.session_state.confianza}%",

            "Precio entrada":
                round(
                    st.session_state.precio_inicio,
                    2
                ),

            "Expiration Value":
                "",

            "Resultado Kalshi":
                "UNKNOWN",

            "Resultado":
                "⏳ SIN RESOLVER"
        }

        st.session_state.historial.append(
            registro
        )

        guardar_historial(
            st.session_state.historial
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

if "hora_entrada" not in st.session_state:
    st.session_state.hora_entrada = ""

if "razones" not in st.session_state:
    st.session_state.razones = []

if "ultima_actualizacion" not in st.session_state:
    st.session_state.ultima_actualizacion = ""


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15 Min"
)

st.caption(
    "Predicción: ¿BTC terminará ARRIBA o ABAJO "
    "del Target de Kalshi?"
)


# ============================================================
# CREDENCIALES
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ No se encontraron las credenciales de Kalshi."
    )

    st.info(
        "Revisa Streamlit → Settings → Secrets."
    )

    st.stop()


# ============================================================
# EJECUCIÓN
# ============================================================

try:

    # --------------------------------------------------------
    # BUSCAR CONTRATO ACTUAL
    # --------------------------------------------------------

    mercado = buscar_mercado_actual()

    ticker = mercado.get(
        "ticker"
    )

    target = obtener_target(
        mercado
    )

    close_time = mercado["_close"]

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
    # CAMBIO DE CONTRATO
    # --------------------------------------------------------

    if (
        st.session_state.ticker
        != ticker
    ):

        # Primero cerrar el anterior
        if (
            st.session_state.ticker
            and
            st.session_state.prediccion
        ):

            cerrar_contrato_anterior()

        # Nueva predicción
        (
            prediccion,
            confianza,
            razones
        ) = generar_prediccion(
            btc,
            target
        )

        st.session_state.ticker = ticker

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

        st.session_state.hora_entrada = (
            datetime.now(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S %p"
            )
        )

        st.session_state.razones = (
            razones
        )


    # --------------------------------------------------------
    # TIEMPO REAL DEL CONTRATO
    # --------------------------------------------------------

    ahora_utc = datetime.now(
        timezone.utc
    )

    segundos_restantes = int(
        (
            close_time -
            ahora_utc
        ).total_seconds()
    )

    # Nunca permitir tiempo negativo
    segundos_restantes = max(
        0,
        segundos_restantes
    )

    minutos = (
        segundos_restantes // 60
    )

    segundos = (
        segundos_restantes % 60
    )

    # --------------------------------------------------------
    # DATOS DE TIEMPO LOCAL
    # --------------------------------------------------------

    cierre_local = (
        close_time.astimezone(
            LOCAL_TZ
        )
    )

    # --------------------------------------------------------
    # CONTRATO
    # --------------------------------------------------------

    st.subheader(
        "🎯 Contrato actual de Kalshi"
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

    # --------------------------------------------------------
    # BTC / TARGET
    # --------------------------------------------------------

    col1, col2 = st.columns(2)

    col1.metric(
        "₿ BTC actual",
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
            f"BTC está ${diferencia:,.2f} "
            "POR ENCIMA del Target."
        )

    elif diferencia < 0:

        st.error(
            f"BTC está ${abs(diferencia):,.2f} "
            "POR DEBAJO del Target."
        )

    else:

        st.warning(
            "BTC está exactamente en el Target."
        )

    # --------------------------------------------------------
    # PREDICCIÓN
    # --------------------------------------------------------

    st.subheader(
        "🔮 Predicción para el cierre"
    )

    st.write(
        f"# {st.session_state.prediccion}"
    )

    st.metric(
        "Confianza",
        f"{st.session_state.confianza}%"
    )

    st.write(
        f"Precio de entrada: "
        f"${st.session_state.precio_inicio:,.2f}"
    )

    # --------------------------------------------------------
    # CONTADOR
    # --------------------------------------------------------

    if segundos_restantes <= 60:

        st.warning(
            f"⚠️ ÚLTIMO MINUTO — "
            f"{minutos:02d}:{segundos:02d}"
        )

    else:

        st.subheader(
            f"⏳ Tiempo restante: "
            f"{minutos:02d}:{segundos:02d}"
        )

    st.write(
        "🕐 Cierre del contrato:",
        cierre_local.strftime(
            "%I:%M:%S %p"
        )
    )

    st.write(
        "📅 Fecha:",
        cierre_local.strftime(
            "%m/%d/%Y"
        )
    )

    # --------------------------------------------------------
    # ANÁLISIS
    # --------------------------------------------------------

    st.subheader(
        "📊 Análisis"
    )

    for razon in st.session_state.razones:

        st.write(
            "•",
            razon
        )

    # --------------------------------------------------------
    # GRÁFICO
    # --------------------------------------------------------

    st.subheader(
        "📈 BTC"
    )

    st.line_chart(
        btc["Close"]
    )

    # --------------------------------------------------------
    # HISTORIAL
    # --------------------------------------------------------

    st.subheader(
        "📜 Historial de predicciones"
    )

    if st.session_state.historial:

        tabla = pd.DataFrame(
            st.session_state.historial
        )

        # Mostrar más reciente primero
        tabla = tabla.iloc[::-1]

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
            "Esperando terminar el primer contrato..."
        )

    # --------------------------------------------------------
    # INFORMACIÓN
    # --------------------------------------------------------

    st.divider()

    st.caption(
        "La aplicación analiza contratos BTC 15M "
        "de Kalshi y registra automáticamente "
        "la predicción y el resultado real. "
        "NO coloca apuestas automáticamente."
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

time.sleep(5)

st.rerun()
