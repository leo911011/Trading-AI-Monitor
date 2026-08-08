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
KALSHI_URL = "https://external-api.kalshi.com"

# Serie BTC 15 minutos
SERIES = "KXBTC15M"

# Hora local de Omaha / Chicago
LOCAL_TZ = ZoneInfo("America/Chicago")

HISTORIAL_FILE = "historial_kalshi.json"

# No apostamos automáticamente
NO_AUTO_BET = True


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
# CARGAR CLAVE RSA
# ============================================================

def cargar_clave_privada():

    if not PRIVATE_KEY:

        raise Exception(
            "No existe KALSHI_PRIVATE_KEY en Streamlit Secrets."
        )

    clave = PRIVATE_KEY.strip()

    # Permite Secrets con \n escritos literalmente
    clave = clave.replace("\\n", "\n")

    try:

        return serialization.load_pem_private_key(
            clave.encode("utf-8"),
            password=None
        )

    except Exception as e:

        raise Exception(
            "La KALSHI_PRIVATE_KEY no es una clave PEM válida. "
            "Debe comenzar con BEGIN RSA PRIVATE KEY y terminar "
            "con END RSA PRIVATE KEY."
        ) from e


# ============================================================
# FIRMA KALSHI
# ============================================================

def crear_firma(timestamp, method, path):

    private_key = cargar_clave_privada()

    # Nunca firmar query parameters
    path_sin_query = path.split("?")[0]

    mensaje = (
        f"{timestamp}"
        f"{method.upper()}"
        f"{path_sin_query}"
    ).encode("utf-8")

    firma = private_key.sign(

        mensaje,

        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
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

        if isinstance(valor, datetime):

            dt = valor

        else:

            texto = str(valor)

            dt = datetime.fromisoformat(
                texto.replace(
                    "Z",
                    "+00:00"
                )
            )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:

        return None


# ============================================================
# MERCADOS BTC 15M
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
# PARSEAR TICKER BTC 15M
#
# Ejemplo:
# KXBTC15M-26AUG072115-15
#
# 26AUG07 21:15 UTC
# ============================================================

def fecha_desde_ticker(ticker):

    if not ticker:

        return None

    patron = re.search(
        r"26[A-Z]{3}\d{6}",
        ticker
    )

    if not patron:

        return None

    texto = patron.group(0)

    try:

        dt = datetime.strptime(
            texto,
            "%y%b%d%H%M"
        )

        return dt.replace(
            tzinfo=timezone.utc
        )

    except Exception:

        return None


# ============================================================
# DETERMINAR EXPIRACIÓN REAL
# ============================================================

def obtener_expiracion_real(mercado):

    ahora = datetime.now(
        timezone.utc
    )

    ticker = mercado.get(
        "ticker",
        ""
    )

    candidatos = []

    # --------------------------------------------------------
    # expiration_time
    # --------------------------------------------------------

    for campo in [

        "expiration_time",
        "latest_expiration_time",
        "expected_expiration_time"

    ]:

        fecha = convertir_fecha(
            mercado.get(campo)
        )

        if fecha and fecha > ahora:

            candidatos.append(
                (fecha, campo)
            )

    # --------------------------------------------------------
    # close_time
    # --------------------------------------------------------

    close_time = convertir_fecha(
        mercado.get("close_time")
    )

    if close_time and close_time > ahora:

        candidatos.append(
            (close_time, "close_time")
        )

    # --------------------------------------------------------
    # TICKER
    #
    # Para BTC15M, el ticker contiene la hora
    # de inicio del intervalo.
    #
    # Añadimos 15 minutos como respaldo.
    # --------------------------------------------------------

    inicio_ticker = fecha_desde_ticker(
        ticker
    )

    if inicio_ticker:

        expiracion_ticker = (
            inicio_ticker +
            pd.Timedelta(minutes=15)
        ).to_pydatetime()

        if expiracion_ticker > ahora:

            candidatos.append(
                (
                    expiracion_ticker,
                    "ticker+15m"
                )
            )

    if not candidatos:

        raise Exception(
            "No pude determinar la hora real "
            "de expiración del contrato."
        )

    # ========================================================
    # MUY IMPORTANTE
    #
    # Para un contrato 15M no aceptamos una fecha
    # absurdamente lejana si existe una fecha razonable.
    #
    # Preferimos la fecha más próxima que todavía esté
    # en el futuro.
    # ========================================================

    candidatos.sort(
        key=lambda x: x[0]
    )

    expiracion, fuente = candidatos[0]

    return expiracion, fuente


# ============================================================
# BUSCAR CONTRATO ACTUAL
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

        if not ticker:

            continue

        try:

            expiracion, fuente = (
                obtener_expiracion_real(
                    mercado
                )
            )

        except Exception:

            continue

        if expiracion > ahora:

            mercado["_expiration_real"] = (
                expiracion
            )

            mercado["_expiration_source"] = (
                fuente
            )

            candidatos.append(
                mercado
            )

    if not candidatos:

        raise Exception(
            "No encontré un contrato BTC 15M "
            "abierto actualmente."
        )

    candidatos.sort(
        key=lambda x:
        x["_expiration_real"]
    )

    return candidatos[0]


# ============================================================
# TARGET
# ============================================================

def obtener_target(mercado):

    # Primero functional_strike
    functional = mercado.get(
        "functional_strike"
    )

    if functional not in (
        None,
        ""
    ):

        try:

            return float(
                functional
            )

        except Exception:

            pass

    # Después floor_strike
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

    # Después cap_strike
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

    # Último recurso: texto del mercado
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

    valores = []

    for numero in numeros:

        try:

            valor = float(
                numero.replace(
                    ",",
                    ""
                )
            )

            if valor > 1000:

                valores.append(
                    valor
                )

        except Exception:

            pass

    if valores:

        return valores[0]

    raise Exception(
        "No pude encontrar el Target del contrato."
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
        ema12 -
        ema26
    )

    # Momentum
    df["Momentum"] = (
        df["Close"]
        .pct_change(3)
        * 100
    )

    # Volatilidad aproximada
    df["Volatilidad"] = (
        df["Close"]
        .pct_change()
        .rolling(20)
        .std()
        * 100
    )

    return df


# ============================================================
# PREDICCIÓN
#
# Objetivo:
# ¿BTC terminará ARRIBA o ABAJO del TARGET?
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

    volatilidad = ultimo["Volatilidad"]

    razones = []

    subir = 0.0
    bajar = 0.0

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

    razones.append(
        f"BTC está "
        f"${abs(distancia):,.2f} "
        f"({'sobre' if distancia > 0 else 'debajo' if distancia < 0 else 'en'}) "
        f"el Target "
        f"({distancia_pct:+.3f}%)."
    )

    # No damos un peso enorme a la distancia.
    #
    # Estar $5 arriba no significa que vaya a terminar
    # $5 arriba dentro de 15 minutos.
    #
    # Solo sirve como contexto.

    if distancia_pct > 0:

        subir += 10

    elif distancia_pct < 0:

        bajar += 10


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

            subir += 12

            razones.append(
                f"RSI {rsi:.1f}: posible rebote."
            )

        elif rsi > 65:

            bajar += 12

            razones.append(
                f"RSI {rsi:.1f}: presión bajista."
            )

        else:

            # RSI neutral NO suma puntos
            razones.append(
                f"RSI {rsi:.1f}: zona neutral."
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
                f"Momentum +{momentum:.3f}%."
            )

        elif momentum < 0:

            bajar += 20

            razones.append(
                f"Momentum {momentum:.3f}%."
            )

        else:

            razones.append(
                "Momentum neutral."
            )


    # --------------------------------------------------------
    # VOLATILIDAD
    # --------------------------------------------------------

    if pd.notna(volatilidad):

        volatilidad = float(
            volatilidad
        )

        razones.append(
            f"Volatilidad reciente "
            f"{volatilidad:.3f}%."
        )


    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    total = (
        subir +
        bajar
    )

    if total <= 0:

        return (
            "⚪ NO APOSTAR",
            50,
            razones
        )

    if subir > bajar:

        prediccion = "🟢 ARRIBA"

        # Confianza basada en diferencia de señales
        ventaja = (
            subir -
            bajar
        ) / total

        confianza = (
            50 +
            ventaja * 50
        )

    elif bajar > subir:

        prediccion = "🔴 ABAJO"

        ventaja = (
            bajar -
            subir
        ) / total

        confianza = (
            50 +
            ventaja * 50
        )

    else:

        prediccion = "⚪ NO APOSTAR"

        confianza = 50

    # Evitamos mostrar falsamente 90-100%
    # con solamente unos pocos indicadores.

    confianza = max(
        50,
        min(
            85,
            confianza
        )
    )

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
# OBTENER RESULTADO REAL DE KALSHI
# ============================================================

def obtener_resultado_kalshi(
    ticker
):

    data = kalshi_request(

        "GET",

        "/trade-api/v2/markets/"
        +
        ticker
    )

    mercado = data.get(
        "market",
        {}
    )

    return mercado


# ============================================================
# INTERPRETAR RESULTADO
# ============================================================

def interpretar_resultado(
    mercado,
    target
):

    resultado = mercado.get(
        "result"
    )

    expiration_value = mercado.get(
        "expiration_value"
    )

    # Kalshi normalmente devuelve result
    # como "yes" / "no" cuando está resuelto.

    if resultado:

        resultado = str(
            resultado
        ).lower()

        if resultado == "yes":

            return (
                "ARRIBA",
                expiration_value
            )

        if resultado == "no":

            return (
                "ABAJO",
                expiration_value
            )

    # Respaldo mediante expiration_value
    if expiration_value not in (
        None,
        ""
    ):

        try:

            valor = float(
                expiration_value
            )

            if valor > target:

                return (
                    "ARRIBA",
                    valor
                )

            elif valor < target:

                return (
                    "ABAJO",
                    valor
                )

            else:

                return (
                    "IGUAL",
                    valor
                )

        except Exception:

            pass

    return (
        "PENDIENTE",
        expiration_value
    )


# ============================================================
# GUARDAR RESULTADO DE UN CONTRATO
# ============================================================

def registrar_resultado_anterior():

    ticker_anterior = (
        st.session_state.get(
            "ticker"
        )
    )

    prediccion = (
        st.session_state.get(
            "prediccion"
        )
    )

    if not ticker_anterior:

        return

    if not prediccion:

        return

    # No duplicar
    existentes = [

        x.get("Ticker")

        for x
        in st.session_state.historial
    ]

    if ticker_anterior in existentes:

        return

    try:

        mercado = (
            obtener_resultado_kalshi(
                ticker_anterior
            )
        )

        resultado_real, expiration_value = (
            interpretar_resultado(
                mercado,
                st.session_state.target
            )
        )

        # Si todavía no está resuelto,
        # no guardamos como fallo.
        if resultado_real == "PENDIENTE":

            return

        if (
            prediccion == "🟢 ARRIBA"
            and
            resultado_real == "ARRIBA"
        ):

            resultado = "✅ ACIERTO"

        elif (
            prediccion == "🔴 ABAJO"
            and
            resultado_real == "ABAJO"
        ):

            resultado = "✅ ACIERTO"

        elif prediccion == "⚪ NO APOSTAR":

            resultado = "⚪ NO APOSTAR"

        elif resultado_real == "IGUAL":

            resultado = "⚪ IGUAL"

        else:

            resultado = "❌ FALLÓ"

        registro = {

            "Ticker":
                ticker_anterior,

            "Target":
                round(
                    st.session_state.target,
                    2
                ),

            "Predicción":
                prediccion,

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
                resultado,

            "Hora":
                st.session_state.hora_prediccion
        }

        st.session_state.historial.append(
            registro
        )

        guardar_historial(
            st.session_state.historial
        )

    except Exception:

        # Puede tardar unos segundos en resolver.
        # No marcamos el contrato como fallido.
        return


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

if "expiration_time" not in st.session_state:

    st.session_state.expiration_time = None

if "expiration_source" not in st.session_state:

    st.session_state.expiration_source = ""

if "razones" not in st.session_state:

    st.session_state.razones = []

if "hora_prediccion" not in st.session_state:

    st.session_state.hora_prediccion = ""


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
        "❌ Faltan las credenciales de Kalshi."
    )

    st.info(
        "Ve a Streamlit → Settings → Secrets."
    )

    st.stop()


# ============================================================
# EJECUCIÓN
# ============================================================

try:

    # --------------------------------------------------------
    # MERCADO ACTUAL
    # --------------------------------------------------------

    mercado = buscar_mercado_actual()

    ticker = mercado.get(
        "ticker"
    )

    target = obtener_target(
        mercado
    )

    expiration_time = (
        mercado["_expiration_real"]
    )

    expiration_source = (
        mercado["_expiration_source"]
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
    # NUEVO CONTRATO
    # --------------------------------------------------------

    if (
        st.session_state.ticker
        !=
        ticker
    ):

        # Primero intentar resolver el anterior
        registrar_resultado_anterior()

        # Crear nueva predicción
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

        st.session_state.expiration_time = (
            expiration_time.isoformat()
        )

        st.session_state.expiration_source = (
            expiration_source
        )

        st.session_state.razones = (
            razones
        )

        st.session_state.hora_prediccion = (
            datetime.now(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S %p"
            )
        )


    # --------------------------------------------------------
    # SI EL MISMO CONTRATO SIGUE ACTIVO,
    # ACTUALIZAR LA HORA REAL DE EXPIRACIÓN
    # --------------------------------------------------------

    else:

        st.session_state.expiration_time = (
            expiration_time.isoformat()
        )

        st.session_state.expiration_source = (
            expiration_source
        )


    # ========================================================
    # CONTRATO
    # ========================================================

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


    # ========================================================
    # BTC / TARGET
    # ========================================================

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

    diferencia_pct = (
        diferencia /
        st.session_state.target
    ) * 100


    if diferencia > 0:

        st.success(
            f"BTC está "
            f"${diferencia:,.2f} "
            f"POR ENCIMA del Target "
            f"({diferencia_pct:+.3f}%)"
        )

    elif diferencia < 0:

        st.error(
            f"BTC está "
            f"${abs(diferencia):,.2f} "
            f"POR DEBAJO del Target "
            f"({diferencia_pct:+.3f}%)"
        )

    else:

        st.warning(
            "BTC está exactamente en el Target."
        )


    # ========================================================
    # PREDICCIÓN
    # ========================================================

    st.subheader(
        "🔮 Predicción para el cierre"
    )

    if st.session_state.prediccion == "🟢 ARRIBA":

        st.success(
            f"🟢 ARRIBA — "
            f"{st.session_state.confianza}%"
        )

    elif st.session_state.prediccion == "🔴 ABAJO":

        st.error(
            f"🔴 ABAJO — "
            f"{st.session_state.confianza}%"
        )

    else:

        st.warning(
            f"⚪ NO APOSTAR — "
            f"{st.session_state.confianza}%"
        )

    st.write(
        f"Precio de entrada: "
        f"${st.session_state.precio_inicio:,.2f}"
    )


    # ========================================================
    # TEMPORIZADOR
    # ========================================================

    expiration = convertir_fecha(
        st.session_state.expiration_time
    )

    ahora = datetime.now(
        timezone.utc
    )

    segundos_restantes = max(
        0,
        int(
            (
                expiration -
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


    st.subheader(
        "⏳ Tiempo restante"
    )

    # Protección: jamás mostrar miles de minutos
    if segundos_restantes <= 15 * 60:

        st.metric(
            "Cierre del contrato",
            f"{minutos:02d}:{segundos:02d}"
        )

    else:

        st.error(
            "⚠️ La hora de expiración recibida "
            "por Kalshi parece incorrecta para "
            "un contrato de 15 minutos."
        )

        st.write(
            f"Expiración detectada: "
            f"{expiration.astimezone(LOCAL_TZ).strftime('%I:%M:%S %p')}"
        )


    hora_local = expiration.astimezone(
        LOCAL_TZ
    )

    st.write(
        f"**Cierre:** "
        f"{hora_local.strftime('%I:%M:%S %p')}"
    )

    st.caption(
        f"Fuente del temporizador: "
        f"{st.session_state.expiration_source}"
    )


    # Último minuto
    if (
        segundos_restantes > 0
        and
        segundos_restantes <= 60
    ):

        st.warning(
            f"⚠️ ÚLTIMO MINUTO — "
            f"{minutos:02d}:{segundos:02d}"
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
            "El historial aparecerá después "
            "de que Kalshi resuelva el primer contrato."
        )


    # ========================================================
    # INFORMACIÓN
    # ========================================================

    st.divider()

    st.caption(
        "Esta aplicación NO coloca apuestas. "
        "Solamente analiza los contratos BTC 15M "
        "de Kalshi y registra la predicción y "
        "el resultado real."
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

time.sleep(3)

st.rerun()
