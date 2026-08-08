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

# A partir de aquí comienza la prepredicción del siguiente
SEGUNDOS_PREVISION = 60


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
            "No existe KALSHI_PRIVATE_KEY en Streamlit Secrets."
        )

    key_text = PRIVATE_KEY.strip()

    try:

        return serialization.load_pem_private_key(
            key_text.encode("utf-8"),
            password=None
        )

    except Exception as e:

        raise Exception(
            "La KALSHI_PRIVATE_KEY no tiene un formato PEM válido."
        ) from e


# ============================================================
# FIRMA KALSHI
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
# MERCADOS BTC
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
# FECHAS
# ============================================================

def convertir_fecha(texto):

    if not texto:
        return None

    try:

        return datetime.fromisoformat(
            str(texto).replace(
                "Z",
                "+00:00"
            )
        )

    except Exception:

        return None


# ============================================================
# MERCADOS ABIERTOS ORDENADOS
# ============================================================

def obtener_mercados_ordenados():

    mercados = obtener_mercados_btc()

    ahora = datetime.now(
        timezone.utc
    )

    candidatos = []

    for mercado in mercados:

        cierre = convertir_fecha(
            mercado.get("close_time")
        )

        if cierre is None:

            cierre = convertir_fecha(
                mercado.get("expiration_time")
            )

        if cierre is None:
            continue

        if cierre > ahora:

            mercado["_close"] = cierre

            candidatos.append(
                mercado
            )

    candidatos.sort(
        key=lambda x: x["_close"]
    )

    return candidatos


# ============================================================
# CONTRATO ACTUAL
# ============================================================

def buscar_mercado_actual():

    candidatos = obtener_mercados_ordenados()

    if not candidatos:

        raise Exception(
            "No encontré un contrato BTC 15M abierto."
        )

    return candidatos[0]


# ============================================================
# SIGUIENTE CONTRATO
# ============================================================

def buscar_siguiente_mercado(ticker_actual):

    candidatos = obtener_mercados_ordenados()

    for mercado in candidatos:

        ticker = mercado.get(
            "ticker"
        )

        if ticker != ticker_actual:

            return mercado

    return None


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

        valor = mercado.get(
            campo
        )

        if valor not in (
            None,
            ""
        ):

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


    candidatos = []

    for numero in numeros:

        try:

            valor = float(
                numero.replace(
                    ",",
                    ""
                )
            )

            if valor > 1000:

                candidatos.append(
                    valor
                )

        except Exception:

            pass


    if candidatos:

        return candidatos[0]


    raise Exception(
        "No pude encontrar el Target del contrato."
    )


# ============================================================
# PRECIO BTC EN TIEMPO REAL
# ============================================================

def obtener_precio_btc_tiempo_real():

    urls = [

        "https://api.binance.us/api/v3/ticker/price",

        "https://api.binance.com/api/v3/ticker/price"

    ]

    errores = []

    for url in urls:

        try:

            response = requests.get(

                url,

                params={
                    "symbol": "BTCUSDT"
                },

                timeout=5
            )

            response.raise_for_status()

            data = response.json()

            precio = float(
                data["price"]
            )

            if precio > 0:

                return precio

        except Exception as e:

            errores.append(
                str(e)
            )

    raise Exception(
        "No pude obtener BTC en tiempo real. "
        + " | ".join(errores)
    )


# ============================================================
# VELAS BTC
# ============================================================

def obtener_btc_binance():

    urls = [

        "https://api.binance.us/api/v3/klines",

        "https://api.binance.com/api/v3/klines"

    ]

    errores = []

    for url in urls:

        try:

            response = requests.get(

                url,

                params={
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "limit": 120
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
                    "Respuesta inválida."
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
                "Close"

            ]:

                df[columna] = pd.to_numeric(
                    df[columna],
                    errors="coerce"
                )

            df = df.dropna(
                subset=["Close"]
            )

            return df[
                [
                    "time",
                    "Open",
                    "High",
                    "Low",
                    "Close"
                ]
            ]

        except Exception as e:

            errores.append(
                str(e)
            )

    raise Exception(
        "No pude obtener las velas BTC. "
        + " | ".join(errores)
    )


# ============================================================
# INDICADORES
# ============================================================

def indicadores(df):

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

    # Momentum 3 minutos
    df["Momentum3"] = (
        df["Close"]
        .pct_change(3)
        * 100
    )

    # Momentum 5 minutos
    df["Momentum5"] = (
        df["Close"]
        .pct_change(5)
        * 100
    )

    # Momentum 10 minutos
    df["Momentum10"] = (
        df["Close"]
        .pct_change(10)
        * 100
    )

    return df


# ============================================================
# PREDICCIÓN NORMAL
# ============================================================

def generar_prediccion(
    df,
    target,
    precio_real=None
):

    ultimo = df.iloc[-1]

    if precio_real is None:

        precio = float(
            ultimo["Close"]
        )

    else:

        precio = float(
            precio_real
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

    momentum3 = ultimo["Momentum3"]

    momentum5 = ultimo["Momentum5"]

    momentum10 = ultimo["Momentum10"]


    subir = 0.0
    bajar = 0.0

    razones = []


    # --------------------------------------------------------
    # DISTANCIA AL TARGET
    # --------------------------------------------------------

    distancia = (
        precio -
        target
    )

    porcentaje = (
        distancia /
        target
    ) * 100


    # La distancia al target es importante,
    # pero NO determina por sí sola el resultado.

    if distancia > 0:

        subir += 12

        razones.append(
            f"BTC está ${distancia:,.2f} "
            f"({porcentaje:+.3f}%) sobre el Target."
        )

    elif distancia < 0:

        bajar += 12

        razones.append(
            f"BTC está ${abs(distancia):,.2f} "
            f"({porcentaje:+.3f}%) debajo del Target."
        )

    else:

        razones.append(
            "BTC está exactamente en el Target."
        )


    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if ema9 > ema21:

        subir += 22

        razones.append(
            "EMA9 > EMA21: tendencia alcista."
        )

    else:

        bajar += 22

        razones.append(
            "EMA9 < EMA21: tendencia bajista."
        )


    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if macd > 0:

        subir += 18

        razones.append(
            "MACD positivo."
        )

    else:

        bajar += 18

        razones.append(
            "MACD negativo."
        )


    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if pd.notna(rsi):

        rsi = float(rsi)

        if rsi < 30:

            # Sobreventa: posible rebote,
            # pero no damos una señal exagerada.

            subir += 12

            razones.append(
                f"RSI {rsi:.1f}: zona de sobreventa, "
                "posible rebote."
            )

        elif rsi > 70:

            bajar += 12

            razones.append(
                f"RSI {rsi:.1f}: zona de sobrecompra."
            )

        else:

            razones.append(
                f"RSI {rsi:.1f}: zona neutral."
            )


    # --------------------------------------------------------
    # MOMENTUM 3
    # --------------------------------------------------------

    if pd.notna(momentum3):

        momentum3 = float(
            momentum3
        )

        if momentum3 > 0:

            subir += 14

            razones.append(
                f"Momentum 3m +{momentum3:.3f}%."
            )

        elif momentum3 < 0:

            bajar += 14

            razones.append(
                f"Momentum 3m {momentum3:.3f}%."
            )


    # --------------------------------------------------------
    # MOMENTUM 5
    # --------------------------------------------------------

    if pd.notna(momentum5):

        momentum5 = float(
            momentum5
        )

        if momentum5 > 0:

            subir += 8

        elif momentum5 < 0:

            bajar += 8


    # --------------------------------------------------------
    # MOMENTUM 10
    # --------------------------------------------------------

    if pd.notna(momentum10):

        momentum10 = float(
            momentum10
        )

        if momentum10 > 0:

            subir += 6

        elif momentum10 < 0:

            bajar += 6


    total = subir + bajar


    if total <= 0:

        return (
            "⚪ NO APOSTAR",
            50,
            razones
        )


    diferencia_puntos = abs(
        subir - bajar
    )

    confianza = (
        50 +
        (
            diferencia_puntos /
            total
        ) * 50
    )

    confianza = min(
        90,
        max(
            50,
            confianza
        )
    )


    if subir > bajar:

        prediccion = "🟢 ARRIBA"

    elif bajar > subir:

        prediccion = "🔴 ABAJO"

    else:

        prediccion = "⚪ NO APOSTAR"


    return (
        prediccion,
        round(confianza),
        razones
    )


# ============================================================
# PREDICCIÓN DEL SIGUIENTE CONTRATO
# ============================================================

def generar_preprediccion_siguiente(
    df,
    precio,
    target_siguiente=None
):

    ultimo = df.iloc[-1]

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

    momentum3 = ultimo["Momentum3"]

    momentum5 = ultimo["Momentum5"]

    momentum10 = ultimo["Momentum10"]


    subir = 0.0
    bajar = 0.0

    razones = []


    # ========================================================
    # TARGET DEL SIGUIENTE
    # ========================================================

    if target_siguiente is not None:

        diferencia = (
            precio -
            target_siguiente
        )

        porcentaje = (
            diferencia /
            target_siguiente
        ) * 100


        # Tiene peso, pero no domina la predicción.

        if diferencia > 0:

            subir += 18

            razones.append(
                f"BTC está ${diferencia:,.2f} "
                f"({porcentaje:+.3f}%) sobre el Target "
                "del siguiente contrato."
            )

        elif diferencia < 0:

            bajar += 18

            razones.append(
                f"BTC está ${abs(diferencia):,.2f} "
                f"({porcentaje:+.3f}%) debajo del Target "
                "del siguiente contrato."
            )

        else:

            razones.append(
                "BTC está exactamente en el Target "
                "del siguiente contrato."
            )


    # ========================================================
    # TENDENCIA
    # ========================================================

    if ema9 > ema21:

        subir += 20

        razones.append(
            "EMA9 > EMA21: tendencia actual alcista."
        )

    else:

        bajar += 20

        razones.append(
            "EMA9 < EMA21: tendencia actual bajista."
        )


    # ========================================================
    # MACD
    # ========================================================

    if macd > 0:

        subir += 16

        razones.append(
            "MACD positivo."
        )

    else:

        bajar += 16

        razones.append(
            "MACD negativo."
        )


    # ========================================================
    # MOMENTUM 3
    # ========================================================

    if pd.notna(momentum3):

        momentum3 = float(
            momentum3
        )

        if momentum3 > 0:

            subir += 18

            razones.append(
                f"Momentum 3m positivo "
                f"(+{momentum3:.3f}%)."
            )

        elif momentum3 < 0:

            bajar += 18

            razones.append(
                f"Momentum 3m negativo "
                f"({momentum3:.3f}%)."
            )


    # ========================================================
    # MOMENTUM 5
    # ========================================================

    if pd.notna(momentum5):

        momentum5 = float(
