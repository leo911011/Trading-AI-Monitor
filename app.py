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

KALSHI_URL = "https://external-api.kalshi.com"

SERIES = "KXBTC15M"

LOCAL_TZ = ZoneInfo("America/Chicago")

HISTORIAL_FILE = "historial_kalshi.json"

REFRESH_SECONDS = 5

# La predicción se genera durante el último minuto
PREDICCION_SEGUNDOS = 60


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

    try:

        return serialization.load_pem_private_key(
            PRIVATE_KEY.strip().encode("utf-8"),
            password=None
        )

    except Exception as e:

        raise Exception(
            "La KALSHI_PRIVATE_KEY no tiene formato PEM válido."
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
# MERCADOS BTC
# ============================================================

def obtener_mercados_btc(
    status="open",
    limit=100
):

    data = kalshi_request(
        "GET",
        "/trade-api/v2/markets",
        params={
            "series_ticker": SERIES,
            "status": status,
            "limit": limit
        }
    )

    return data.get(
        "markets",
        []
    )


# ============================================================
# CONTRATO INDIVIDUAL
# ============================================================

def obtener_contrato(ticker):

    data = kalshi_request(
        "GET",
        "/trade-api/v2/markets/" + ticker
    )

    return data.get(
        "market",
        {}
    )


# ============================================================
# BUSCAR CONTRATO ACTUAL
# ============================================================

def buscar_mercado_actual():

    mercados = obtener_mercados_btc(
        status="open"
    )

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

        return None

    candidatos.sort(
        key=lambda x: x["_close"]
    )

    return candidatos[0]


# ============================================================
# BUSCAR EL SIGUIENTE CONTRATO REAL
#
# IMPORTANTE:
#
# No inventamos el ticker.
#
# Buscamos en Kalshi el contrato cuyo cierre
# sea inmediatamente posterior al cierre del
# contrato que usamos para hacer la predicción.
# ============================================================

def buscar_siguiente_contrato_real(
    contrato_base_ticker,
    cierre_base
):

    if cierre_base is None:

        return None

    ahora = datetime.now(
        timezone.utc
    )

    candidatos = []

    # --------------------------------------------------------
    # Primero buscamos contratos abiertos.
    # --------------------------------------------------------

    try:

        abiertos = obtener_mercados_btc(
            status="open",
            limit=100
        )

    except Exception:

        abiertos = []

    for mercado in abiertos:

        ticker = mercado.get(
            "ticker"
        )

        if not ticker:

            continue

        if ticker == contrato_base_ticker:

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

        # Debe ser posterior al cierre del contrato
        # que usamos para generar la predicción.

        if cierre > cierre_base:

            candidatos.append(
                (
                    cierre,
                    ticker,
                    mercado
                )
            )

    # --------------------------------------------------------
    # Si existe uno abierto, el más cercano es el siguiente.
    # --------------------------------------------------------

    if candidatos:

        candidatos.sort(
            key=lambda x: x[0]
        )

        return candidatos[0][2]

    # --------------------------------------------------------
    # Si ya cerró el siguiente contrato, buscamos entre
    # los contratos cerrados.
    # --------------------------------------------------------

    try:

        cerrados = obtener_mercados_btc(
            status="closed",
            limit=100
        )

    except Exception:

        cerrados = []

    for mercado in cerrados:

        ticker = mercado.get(
            "ticker"
        )

        if not ticker:

            continue

        if ticker == contrato_base_ticker:

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

        if cierre > cierre_base:

            candidatos.append(
                (
                    cierre,
                    ticker,
                    mercado
                )
            )

    if candidatos:

        candidatos.sort(
            key=lambda x: x[0]
        )

        return candidatos[0][2]

    return None


# ============================================================
# CONVERTIR PRECIO
# ============================================================

def convertir_numero_precio(valor):

    if valor is None:

        return None

    try:

        if isinstance(valor, str):

            texto = (
                valor
                .replace(",", "")
                .replace("$", "")
                .strip()
            )

        else:

            texto = str(valor)

        numero = float(texto)

        if numero > 1000:

            return numero

    except Exception:

        return None

    return None


# ============================================================
# BUSCADOR RECURSIVO DE TARGET
# ============================================================

def buscar_targets_recursivo(objeto):

    encontrados = []

    if isinstance(objeto, dict):

        for clave, valor in objeto.items():

            clave_lower = str(
                clave
            ).lower()

            prioridad_alta = (
                "functional_strike",
                "target_price",
                "target",
                "strike_price",
                "strike"
            )

            prioridad_media = (
                "floor_strike",
                "cap_strike"
            )

            if clave_lower in prioridad_alta:

                numero = convertir_numero_precio(
                    valor
                )

                if numero is not None:

                    encontrados.append(
                        (
                            100,
                            numero,
                            clave
                        )
                    )

            elif clave_lower in prioridad_media:

                numero = convertir_numero_precio(
                    valor
                )

                if numero is not None:

                    encontrados.append(
                        (
                            80,
                            numero,
                            clave
                        )
                    )

            encontrados.extend(
                buscar_targets_recursivo(
                    valor
                )
            )

    elif isinstance(objeto, list):

        for elemento in objeto:

            encontrados.extend(
                buscar_targets_recursivo(
                    elemento
                )
            )

    return encontrados


# ============================================================
# TARGET DESDE TEXTO
# ============================================================

def buscar_target_en_texto(mercado):

    textos = []

    campos = [
        "title",
        "subtitle",
        "yes_sub_title",
        "no_sub_title",
        "ticker",
        "event_ticker"
    ]

    for campo in campos:

        valor = mercado.get(
            campo
        )

        if valor:

            textos.append(
                str(valor)
            )

    texto = " ".join(
        textos
    )

    patrones = [

        r"\$([0-9][0-9,]*(?:\.[0-9]+)?)",

        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:USD|USDT)",

        r"target[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)",

        r"strike[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)"
    ]

    candidatos = []

    for patron in patrones:

        resultados = re.findall(
            patron,
            texto,
            flags=re.IGNORECASE
        )

        for resultado in resultados:

            try:

                numero = float(
                    resultado.replace(
                        ",",
                        ""
                    )
                )

                if numero > 1000:

                    candidatos.append(
                        numero
                    )

            except Exception:

                pass

    if candidatos:

        return candidatos[0]

    return None


# ============================================================
# OBTENER TARGET ROBUSTO
# ============================================================

def obtener_target(mercado):

    encontrados = buscar_targets_recursivo(
        mercado
    )

    if encontrados:

        encontrados.sort(
            key=lambda x: x[0],
            reverse=True
        )

        return float(
            encontrados[0][1]
        )

    target_texto = buscar_target_en_texto(
        mercado
    )

    if target_texto is not None:

        return float(
            target_texto
        )

    ticker = mercado.get(
        "ticker"
    )

    if ticker:

        try:

            detalle = obtener_contrato(
                ticker
            )

            encontrados = buscar_targets_recursivo(
                detalle
            )

            if encontrados:

                encontrados.sort(
                    key=lambda x: x[0],
                    reverse=True
                )

                return float(
                    encontrados[0][1]
                )

            target_texto = buscar_target_en_texto(
                detalle
            )

            if target_texto is not None:

                return float(
                    target_texto
                )

        except Exception:

            pass

    raise Exception(
        "No pude encontrar el Target del contrato "
        f"{ticker if ticker else ''}."
    )


# ============================================================
# BTC — COINBASE HISTÓRICO
# ============================================================

def obtener_btc_coinbase():

    url = (
        "https://api.exchange.coinbase.com/"
        "products/BTC-USD/candles"
    )

    response = requests.get(
        url,
        params={
            "granularity": 60
        },
        headers={
            "User-Agent":
                "BTC-Kalshi-Predictor/1.0"
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
            "Coinbase no devolvió velas válidas."
        )

    filas = []

    for fila in data:

        if len(fila) < 6:

            continue

        filas.append(
            [
                fila[0],
                fila[3],
                fila[2],
                fila[1],
                fila[4],
                fila[5]
            ]
        )

    if not filas:

        raise Exception(
            "Coinbase no devolvió datos BTC."
        )

    df = pd.DataFrame(
        filas,
        columns=[
            "time",
            "Low",
            "High",
            "Open",
            "Close",
            "Volume"
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

    df["time"] = pd.to_datetime(
        df["time"],
        unit="s",
        utc=True
    )

    df = df.dropna(
        subset=["Close"]
    )

    df = df.sort_values(
        "time"
    )

    return df


# ============================================================
# BTC — BINANCE.US RESPALDO
# ============================================================

def obtener_btc_binance():

    url = (
        "https://api.binance.us/"
        "api/v3/klines"
    )

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

    df["time"] = pd.to_datetime(
        df["time"],
        unit="ms",
        utc=True
    )

    df = df.dropna(
        subset=["Close"]
    )

    return df


# ============================================================
# BTC PRECIO EN TIEMPO REAL
# ============================================================

def obtener_precio_btc():

    try:

        response = requests.get(

            "https://api.exchange.coinbase.com/"
            "products/BTC-USD/ticker",

            headers={
                "User-Agent":
                    "BTC-Kalshi-Predictor/1.0"
            },

            timeout=5
        )

        response.raise_for_status()

        data = response.json()

        precio = float(
            data["price"]
        )

        if precio > 1000:

            return precio, "Coinbase"

    except Exception:

        pass

    try:

        response = requests.get(

            "https://api.binance.us/"
            "api/v3/ticker/price",

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

        if precio > 1000:

            return precio, "Binance.US"

    except Exception:

        pass

    raise Exception(
        "No pude obtener el precio BTC en tiempo real."
    )


# ============================================================
# BTC COMPLETO
# ============================================================

def obtener_btc():

    try:

        df = obtener_btc_coinbase()

    except Exception:

        df = obtener_btc_binance()

    fuente_historico = "Coinbase"

    if df is None or len(df) == 0:

        raise Exception(
            "No hay histórico BTC."
        )

    df = df.drop_duplicates(
        subset=["time"]
    )

    df = df.sort_values(
        "time"
    )

    df = df.tail(
        120
    ).copy()

    precio_real, fuente_precio = (
        obtener_precio_btc()
    )

    # Actualizar la última vela con el precio
    # REAL actual para evitar BTC congelado.

    if len(df) > 0:

        posicion_close = (
            df.columns.get_loc(
                "Close"
            )
        )

        df.iloc[
            -1,
            posicion_close
        ] = precio_real

    return (
        df,
        precio_real,
        fuente_precio
    )


# ============================================================
# INDICADORES
# ============================================================

def calcular_indicadores(df):

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

    df["EMA50"] = (
        df["Close"]
        .ewm(
            span=50,
            adjust=False
        )
        .mean()
    )

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

    df["MACD_SIGNAL"] = (
        df["MACD"]
        .ewm(
            span=9,
            adjust=False
        )
        .mean()
    )

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

    df["Volatilidad"] = (
        df["Close"]
        .pct_change()
        .rolling(15)
        .std()
        * 100
    )

    return df


# ============================================================
# PREDICCIÓN DEL SIGUIENTE CONTRATO
#
# Usa el contrato ACTUAL:
#
# Target actual
# +
# EMA
# +
# MACD
# +
# RSI
# +
# Momentum
# +
# Volatilidad
#
# No necesita conocer el Target del siguiente contrato.
# ============================================================

def generar_prediccion(
    df,
    target_actual
):

    ultimo = df.iloc[-1]

    precio = float(
        ultimo["Close"]
    )

    target_actual = float(
        target_actual
    )

    ema9 = float(
        ultimo["EMA9"]
    )

    ema21 = float(
        ultimo["EMA21"]
    )

    ema50 = float(
        ultimo["EMA50"]
    )

    macd = float(
        ultimo["MACD"]
    )

    macd_signal = float(
        ultimo["MACD_SIGNAL"]
    )

    rsi = ultimo["RSI"]

    momentum1 = ultimo["Momentum1"]

    momentum3 = ultimo["Momentum3"]

    momentum5 = ultimo["Momentum5"]

    momentum10 = ultimo["Momentum10"]

    volatilidad = ultimo["Volatilidad"]

    score = 0

    razones = []

    # ========================================================
    # TARGET ACTUAL
    # ========================================================

    diferencia = (
        precio -
        target_actual
    )

    diferencia_pct = (
        diferencia /
        target_actual
    ) * 100

    if diferencia_pct > 0.05:

        score += 30

        razones.append(
            f"BTC está claramente por encima "
            f"del Target actual "
            f"({diferencia_pct:+.3f}%)."
        )

    elif diferencia_pct > 0:

        score += 20

        razones.append(
            f"BTC está por encima del Target "
            f"actual ({diferencia_pct:+.3f}%)."
        )

    elif diferencia_pct < -0.05:

        score -= 30

        razones.append(
            f"BTC está claramente por debajo "
            f"del Target actual "
            f"({diferencia_pct:+.3f}%)."
        )

    elif diferencia_pct < 0:

        score -= 20

        razones.append(
            f"BTC está por debajo del Target "
            f"actual ({diferencia_pct:+.3f}%)."
        )

    else:

        razones.append(
            "BTC está prácticamente en el Target."
        )

    # ========================================================
    # EMA 9 / 21
    # ========================================================

    if ema9 > ema21:

        score += 10

        razones.append(
            "EMA9 > EMA21: tendencia alcista."
        )

    else:

        score -= 10

        razones.append(
            "EMA9 < EMA21: tendencia bajista."
        )

    # ========================================================
    # EMA 21 / 50
    # ========================================================

    if ema21 > ema50:

        score += 8

        razones.append(
            "EMA21 > EMA50: estructura alcista."
        )

    else:

        score -= 8

        razones.append(
            "EMA21 < EMA50: estructura bajista."
        )

    # ========================================================
    # MACD
    # ========================================================

    if macd > 0:

        score += 8

        razones.append(
            "MACD positivo."
        )

    else:

        score -= 8

        razones.append(
            "MACD negativo."
        )

    # ========================================================
    # MACD VS SEÑAL
    # ========================================================

    if macd > macd_signal:

        score += 6

        razones.append(
            "MACD por encima de su señal."
        )

    else:

        score -= 6

        razones.append(
            "MACD por debajo de su señal."
        )

    # ========================================================
    # MOMENTUM 1
    # ========================================================

    if pd.notna(momentum1):

        momentum1 = float(
            momentum1
        )

        if momentum1 > 0:

            score += 5

            razones.append(
                f"Momentum 1m positivo "
                f"(+{momentum1:.3f}%)."
            )

        elif momentum1 < 0:

            score -= 5

            razones.append(
                f"Momentum 1m negativo "
                f"({momentum1:.3f}%)."
            )

    # ========================================================
    # MOMENTUM 3
    # ========================================================

    if pd.notna(momentum3):

        momentum3 = float(
            momentum3
        )

        if momentum3 > 0:

            score += 7

            razones.append(
                f"Momentum 3m positivo "
                f"(+{momentum3:.3f}%)."
            )

        elif momentum3 < 0:

            score -= 7

            razones.append(
                f"Momentum 3m negativo "
                f"({momentum3:.3f}%)."
            )

    # ========================================================
    # MOMENTUM 5
    # ========================================================

    if pd.notna(momentum5):

        momentum5 = float(
            momentum5
        )

        if momentum5 > 0:

            score += 7

            razones.append(
                f"Momentum 5m positivo "
                f"(+{momentum5:.3f}%)."
            )

        elif momentum5 < 0:

            score -= 7

            razones.append(
                f"Momentum 5m negativo "
                f"({momentum5:.3f}%)."
            )

    # ========================================================
    # MOMENTUM 10
    # ========================================================

    if pd.notna(momentum10):

        momentum10 = float(
            momentum10
        )

        if momentum10 > 0:

            score += 6

            razones.append(
                f"Momentum 10m positivo "
                f"(+{momentum10:.3f}%)."
            )

        elif momentum10 < 0:

            score -= 6

            razones.append(
                f"Momentum 10m negativo "
                f"({momentum10:.3f}%)."
            )

    # ========================================================
    # RSI
    # ========================================================

    if pd.notna(rsi):

        rsi = float(
            rsi
        )

        if rsi < 30:

            score += 5

            razones.append(
                f"RSI {rsi:.1f}: sobreventa."
            )

        elif rsi > 70:

            score -= 5

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

    # ========================================================
    # VOLATILIDAD
    # ========================================================

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

    if score >= 10:

        prediccion = "🟢 ARRIBA"

    elif score <= -10:

        prediccion = "🔴 ABAJO"

    else:

        prediccion = "⚪ NO APOSTAR"

    # ========================================================
    # CONFIANZA
    # ========================================================

    if prediccion == "⚪ NO APOSTAR":

        confianza = 50

    else:

        fuerza = min(
            abs(score),
            90
        )

        confianza = int(
            round(
                50 +
                fuerza * 0.45
            )
        )

        confianza = max(
            50,
            min(
                91,
                confianza
            )
        )

    razones.append(
        f"Score final: {score:+d}."
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


# ============================================================
# GUARDAR HISTORIAL
# ============================================================

def guardar_historial(
    historial
):

    archivo_temporal = (
        HISTORIAL_FILE +
        ".tmp"
    )

    with open(
        archivo_temporal,
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
        archivo_temporal,
        HISTORIAL_FILE
    )


# ============================================================
# BUSCAR SI YA EXISTE PREDICCIÓN PARA CONTRATO BASE
# ============================================================

def existe_prediccion_para_contrato_base(
    ticker_base
):

    historial = (
        st.session_state.historial
    )

    for registro in historial:

        if registro.get(
            "Contrato base"
        ) == ticker_base:

            return True

    return False


# ============================================================
# GUARDAR PREDICCIÓN
# ============================================================

def guardar_prediccion(

    ticker_base,

    target_base,

    prediccion,

    confianza,

    precio,

    close_time,

    score,

    razones

):

    historial = (
        st.session_state.historial
    )

    # --------------------------------------------------------
    # Evitar duplicados.
    # --------------------------------------------------------

    for registro in historial:

        if registro.get(
            "Contrato base"
        ) == ticker_base:

            return False

    registro = {

        # Contrato que estaba terminando cuando
        # se generó la predicción.
        "Contrato base":
            ticker_base,

        # Se rellena cuando Kalshi permita
        # identificar el siguiente contrato real.
        "Contrato predicho":
            None,

        # Target usado para hacer la predicción.
        "Target usado para predicción":
            round(
                float(target_base),
                2
            ),

        "Predicción":
            prediccion,

        "Confianza":
            f"{confianza}%",

        "Score":
            int(score),

        "Precio BTC predicción":
            round(
                float(precio),
                2
            ),

        "Cierre contrato base":
            close_time.astimezone(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S %p"
            ),

        # Estos tres se completan posteriormente.
        "Target contrato predicho":
            None,

        "Expiration Value":
            None,

        "Resultado Kalshi":
            "PENDIENTE",

        "Resultado":
            "⏳ PENDIENTE",

        "Análisis":
            razones,

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

    return True


# ============================================================
# RESOLVER CONTRATO PREDICHO
# ============================================================

def resolver_contrato_predicho(
    registro
):

    ticker_base = registro.get(
        "Contrato base"
    )

    ticker_predicho = registro.get(
        "Contrato predicho"
    )

    # Si ya tenemos ticker, no hace falta buscarlo.
    if ticker_predicho:

        try:

            mercado = obtener_contrato(
                ticker_predicho
            )

            return mercado

        except Exception:

            return None

    cierre_base_texto = registro.get(
        "Cierre contrato base"
    )

    if not cierre_base_texto:

        return None

    try:

        cierre_base = datetime.strptime(
            cierre_base_texto,
            "%Y-%m-%d %I:%M:%S %p"
        ).replace(
            tzinfo=LOCAL_TZ
        ).astimezone(
            timezone.utc
        )

    except Exception:

        return None

    mercado_siguiente = (
        buscar_siguiente_contrato_real(
            ticker_base,
            cierre_base
        )
    )

    if mercado_siguiente is None:

        return None

    ticker_siguiente = (
        mercado_siguiente.get(
            "ticker"
        )
    )

    if not ticker_siguiente:

        return None

    registro[
        "Contrato predicho"
    ] = ticker_siguiente

    return mercado_siguiente


# ============================================================
# RESULTADO REAL DE KALSHI
#
# MUY IMPORTANTE:
#
# NO confiamos en "result" para decidir ARRIBA/ABAJO.
#
# El resultado se determina comparando:
#
# expiration_value
#       VS
# target del contrato predicho
# ============================================================

def obtener_resultado_por_target(
    ticker,
    target
):

    try:

        mercado = obtener_contrato(
            ticker
        )

    except Exception:

        return None, None, None

    expiration = mercado.get(
        "expiration_value"
    )

    if expiration in (
        None,
        "",
        "null"
    ):

        return None, None, mercado

    try:

        expiration_num = float(
            expiration
        )

        target_num = float(
            target
        )

    except Exception:

        return None, None, mercado

    if expiration_num > target_num:

        return (
            "UP",
            expiration_num,
            mercado
        )

    if expiration_num < target_num:

        return (
            "DOWN",
            expiration_num,
            mercado
        )

    return (
        "TIE",
        expiration_num,
        mercado
    )


# ============================================================
# ACTUALIZAR PENDIENTES
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

        # ----------------------------------------------------
        # 1. Identificar el contrato REAL predicho.
        # ----------------------------------------------------

        try:

            mercado_predicho = (
                resolver_contrato_predicho(
                    registro
                )
            )

        except Exception:

            mercado_predicho = None

        if mercado_predicho is None:

            continue

        ticker_predicho = (
            mercado_predicho.get(
                "ticker"
            )
        )

        if not ticker_predicho:

            continue

        # ----------------------------------------------------
        # 2. Obtener el Target REAL del contrato predicho.
        # ----------------------------------------------------

        try:

            target_predicho = obtener_target(
                mercado_predicho
            )

        except Exception:

            continue

        # ----------------------------------------------------
        # 3. Obtener expiration_value.
        # ----------------------------------------------------

        try:

            resultado_real, expiration, mercado = (
                obtener_resultado_por_target(
                    ticker_predicho,
                    target_predicho
                )
            )

        except Exception:

            continue

        # El contrato todavía no terminó.
        if resultado_real is None:

            # Guardamos que ya sabemos cuál es
            # el contrato real que debemos comprobar.

            if registro.get(
                "Contrato predicho"
            ) != ticker_predicho:

                registro[
                    "Contrato predicho"
                ] = ticker_predicho

                cambio = True

            if registro.get(
                "Target contrato predicho"
            ) != round(
                float(target_predicho),
                2
            ):

                registro[
                    "Target contrato predicho"
                ] = round(
                    float(target_predicho),
                    2
                )

                cambio = True

            continue

        # ----------------------------------------------------
        # 4. Guardar Target y expiration_value.
        # ----------------------------------------------------

        registro[
            "Contrato predicho"
        ] = ticker_predicho

        registro[
            "Target contrato predicho"
        ] = round(
            float(target_predicho),
            2
        )

        registro[
            "Expiration Value"
        ] = round(
            float(expiration),
            2
        )

        registro[
            "Resultado Kalshi"
        ] = resultado_real

        # ----------------------------------------------------
        # 5. Comparar predicción contra resultado real.
        # ----------------------------------------------------

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

        elif resultado_real == "TIE":

            resultado = "⚪ EMPATE"

        elif (
            prediccion == "⚪ NO APOSTAR"
        ):

            resultado = "⚪ NO APOSTAR"

        else:

            resultado = "❌ FALLÓ"

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
# SESSION STATE
# ============================================================

if "historial" not in st.session_state:

    st.session_state.historial = (
        cargar_historial()
    )

if "ticker_actual" not in st.session_state:

    st.session_state.ticker_actual = None

if "prediccion_hecha_para" not in st.session_state:

    st.session_state.prediccion_hecha_para = None

if "prediccion" not in st.session_state:

    st.session_state.prediccion = None

if "confianza" not in st.session_state:

    st.session_state.confianza = 0

if "target_usado" not in st.session_state:

    st.session_state.target_usado = None

if "precio_prediccion" not in st.session_state:

    st.session_state.precio_prediccion = None

if "razones" not in st.session_state:

    st.session_state.razones = []

if "score" not in st.session_state:

    st.session_state.score = 0

if "prediccion_timestamp" not in st.session_state:

    st.session_state.prediccion_timestamp = None


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Predicción del SIGUIENTE contrato utilizando "
    "el contrato actual que está terminando."
)


# ============================================================
# CREDENCIALES
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ No se encontraron las credenciales de Kalshi."
    )

    st.info(
        "Mantén en Streamlit Secrets:"
    )

    st.code(
        "KALSHI_API_KEY_ID\n"
        "KALSHI_PRIVATE_KEY"
    )

    st.stop()


# ============================================================
# ACTUALIZAR RESULTADOS ANTERIORES
# ============================================================

try:

    actualizar_pendientes()

except Exception:

    pass


# ============================================================
# BUSCAR CONTRATO ACTUAL
# ============================================================

try:

    actual = buscar_mercado_actual()

except Exception as error:

    actual = None

    st.error(
        f"❌ Error consultando Kalshi: {error}"
    )


# ============================================================
# SI NO HAY CONTRATO ABIerto TEMPORALMENTE
# ============================================================

if actual is None:

    st.warning(
        "⏳ Kalshi no está mostrando temporalmente "
        "un contrato BTC 15M abierto."
    )

    st.info(
        "El historial NO se borra. "
        "La aplicación continuará intentando."
    )

    historial = (
        st.session_state.historial
    )

    if historial:

        st.subheader(
            "📜 Historial"
        )

        st.dataframe(
            pd.DataFrame(historial),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "Todavía no hay predicciones."
        )

    time.sleep(
        REFRESH_SECONDS
    )

    st.rerun()


# ============================================================
# DATOS CONTRATO ACTUAL
# ============================================================

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

if close_actual is None:

    close_actual = convertir_fecha(
        actual.get(
            "expiration_time"
        )
    )


# ============================================================
# TARGET ACTUAL
# ============================================================

try:

    target_actual = obtener_target(
        actual
    )

except Exception:

    target_actual = None


# ============================================================
# CAMBIO DE CONTRATO
#
# IMPORTANTE:
#
# No borramos historial.
#
# Solo reiniciamos la pantalla de predicción
# para el NUEVO contrato actual.
# ============================================================

if (
    st.session_state.ticker_actual
    != ticker_actual
):

    st.session_state.ticker_actual = (
        ticker_actual
    )

    st.session_state.prediccion_hecha_para = (
        None
    )

    st.session_state.prediccion = None

    st.session_state.confianza = 0

    st.session_state.target_usado = None

    st.session_state.precio_prediccion = None

    st.session_state.razones = []

    st.session_state.score = 0

    st.session_state.prediccion_timestamp = None


# ============================================================
# BTC EN TIEMPO REAL
# ============================================================

try:

    btc, precio, fuente = obtener_btc()

    btc = calcular_indicadores(
        btc
    )

except Exception as error:

    st.error(
        f"❌ Error obteniendo BTC: {error}"
    )

    time.sleep(
        REFRESH_SECONDS
    )

    st.rerun()


# ============================================================
# TIEMPO
# ============================================================

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


# ============================================================
# CONTRATO ACTUAL
# ============================================================

st.subheader(
    "🎯 Contrato actualmente vigente"
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


# ============================================================
# BTC + TARGET
# ============================================================

col1, col2 = st.columns(2)

col1.metric(
    "₿ BTC actual",
    f"${precio:,.2f}"
)

if target_actual is not None:

    col2.metric(
        "🎯 Target Kalshi",
        f"${target_actual:,.2f}"
    )

else:

    col2.metric(
        "🎯 Target Kalshi",
        "No disponible"
    )

st.caption(
    f"Fuente BTC: {fuente}"
)


# ============================================================
# DIFERENCIA CON TARGET
# ============================================================

if target_actual is not None:

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

else:

    st.warning(
        "⚠️ No se pudo obtener el Target."
    )


# ============================================================
# TEMPORIZADOR
# ============================================================

st.subheader(
    "⏳ Tiempo restante"
)

if segundos_restantes <= 60:

    st.error(
        f"🔴 ÚLTIMO MINUTO — "
        f"{minutos:02d}:{segundos:02d}"
    )

else:

    st.info(
        f"⏱️ {minutos:02d}:{segundos:02d}"
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


# ============================================================
# PREDICCIÓN DEL SIGUIENTE
# ============================================================

st.divider()

st.subheader(
    "🔮 Predicción del SIGUIENTE contrato"
)


# ============================================================
# GENERAR PREDICCIÓN EN ÚLTIMO MINUTO
# ============================================================

if (
    segundos_restantes <= PREDICCION_SEGUNDOS
    and
    segundos_restantes > 0
    and
    st.session_state.prediccion_hecha_para
    != ticker_actual
):

    if target_actual is not None:

        try:

            (
                prediccion,
                confianza,
                razones,
                score
            ) = generar_prediccion(
                btc,
                target_actual
            )

            guardada = guardar_prediccion(

                ticker_base=ticker_actual,

                target_base=target_actual,

                prediccion=prediccion,

                confianza=confianza,

                precio=precio,

                close_time=close_actual,

                score=score,

                razones=razones
            )

            if guardada:

                st.session_state.prediccion_hecha_para = (
                    ticker_actual
                )

                st.session_state.prediccion = (
                    prediccion
                )

                st.session_state.confianza = (
                    confianza
                )

                st.session_state.target_usado = (
                    target_actual
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

                st.session_state.prediccion_timestamp = (
                    datetime.now(
                        LOCAL_TZ
                    ).strftime(
                        "%Y-%m-%d %I:%M:%S"
                    )
                )

                st.success(
                    "✅ Predicción del siguiente "
                    "contrato guardada."
                )

            else:

                # Puede ocurrir si el Streamlit
                # se actualizó después de guardarla.

                st.session_state.prediccion_hecha_para = (
                    ticker_actual
                )

                for registro in (
                    st.session_state.historial
                ):

                    if registro.get(
                        "Contrato base"
                    ) == ticker_actual:

                        st.session_state.prediccion = (
                            registro.get(
                                "Predicción"
                            )
                        )

                        st.session_state.confianza = int(
                            str(
                                registro.get(
                                    "Confianza",
                                    "0%"
                                )
                            ).replace(
                                "%",
                                ""
                            )
                        )

                        st.session_state.target_usado = (
                            registro.get(
                                "Target usado para predicción"
                            )
                        )

                        st.session_state.precio_prediccion = (
                            registro.get(
                                "Precio BTC predicción"
                            )
                        )

                        st.session_state.razones = (
                            registro.get(
                                "Análisis",
                                []
                            )
                        )

                        st.session_state.score = (
                            registro.get(
                                "Score",
                                0
                            )
                        )

                        st.session_state.prediccion_timestamp = (
                            registro.get(
                                "Momento predicción"
                            )
                        )

                        break

        except Exception as error:

            st.error(
                f"❌ No se pudo generar la predicción: "
                f"{error}"
            )

    else:

        st.warning(
            "⚠️ No se puede generar la predicción "
            "porque no se obtuvo el Target actual."
        )


# ============================================================
# MOSTRAR PREDICCIÓN
# ============================================================

if (
    st.session_state.prediccion_hecha_para
    == ticker_actual
):

    st.write(
        f"# {st.session_state.prediccion}"
    )

    st.metric(
        "Confianza",
        f"{st.session_state.confianza}%"
    )

    st.write(
        f"**Contrato usado para analizar:** "
        f"`{ticker_actual}`"
    )

    st.write(
        "**Predicción:** SIGUIENTE contrato "
        "de 15 minutos."
    )

    if st.session_state.target_usado is not None:

        st.write(
            f"**Target usado:** "
            f"${st.session_state.target_usado:,.2f}"
        )

    if st.session_state.precio_prediccion is not None:

        st.write(
            f"**BTC al realizar predicción:** "
            f"${st.session_state.precio_prediccion:,.2f}"
        )

    st.write(
        f"**Score:** "
        f"{st.session_state.score:+d}"
    )

    if st.session_state.prediccion_timestamp:

        st.caption(
            "Predicción realizada: "
            f"{st.session_state.prediccion_timestamp}"
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

    faltan = max(
        0,
        segundos_restantes -
        PREDICCION_SEGUNDOS
    )

    mm = (
        faltan // 60
    )

    ss = (
        faltan % 60
    )

    st.info(
        "La predicción del siguiente contrato "
        "se generará durante el último minuto "
        "del contrato actual. "
        f"Faltan aproximadamente {mm:02d}:{ss:02d}."
    )


# ============================================================
# INFORMACIÓN DEL CONTRATO PREDICHO
#
# Una vez que Kalshi publique el siguiente contrato,
# mostramos su ticker real.
# ============================================================

historial_actual = (
    st.session_state.historial
)

registro_actual = None

for registro in historial_actual:

    if registro.get(
        "Contrato base"
    ) == ticker_actual:

        registro_actual = registro
        break

if registro_actual:

    ticker_predicho = registro_actual.get(
        "Contrato predicho"
    )

    if ticker_predicho:

        st.divider()

        st.subheader(
            "🎯 Contrato predicho real"
        )

        st.write(
            f"`{ticker_predicho}`"
        )

        target_predicho = registro_actual.get(
            "Target contrato predicho"
        )

        expiration_predicho = registro_actual.get(
            "Expiration Value"
        )

        if target_predicho is not None:

            st.write(
                f"**Target del contrato predicho:** "
                f"${float(target_predicho):,.2f}"
            )

        if expiration_predicho is not None:

            st.write(
                f"**Expiration Value de Kalshi:** "
                f"${float(expiration_predicho):,.2f}"
            )


# ============================================================
# GRÁFICO
# ============================================================

st.divider()

st.subheader(
    "📈 BTC — últimos 120 minutos"
)

grafico = btc[
    ["time", "Close"]
].copy()

grafico = grafico.set_index(
    "time"
)

grafico = grafico.rename(
    columns={
        "Close": "BTC"
    }
)

st.line_chart(
    grafico,
    height=350
)


# ============================================================
# ACTUALIZAR RESULTADOS
# ============================================================

try:

    actualizar_pendientes()

except Exception:

    pass


# ============================================================
# HISTORIAL
# ============================================================

st.divider()

st.subheader(
    "📜 Historial de predicciones"
)

historial = (
    st.session_state.historial
)


if historial:

    tabla = pd.DataFrame(
        historial
    )

    # --------------------------------------------------------
    # Ordenamos primero las columnas importantes.
    # --------------------------------------------------------

    columnas_preferidas = [

        "Contrato base",

        "Contrato predicho",

        "Target usado para predicción",

        "Predicción",

        "Confianza",

        "Score",

        "Precio BTC predicción",

        "Target contrato predicho",

        "Expiration Value",

        "Resultado Kalshi",

        "Resultado",

        "Cierre contrato base",

        "Momento predicción",

        "Actualizado"
    ]

    columnas_existentes = [

        columna
        for columna in columnas_preferidas
        if columna in tabla.columns
    ]

    columnas_restantes = [

        columna
        for columna in tabla.columns
        if columna not in columnas_existentes
    ]

    tabla = tabla[
        columnas_existentes +
        columnas_restantes
    ]

    st.dataframe(
        tabla,
        use_container_width=True,
        hide_index=True
    )

    # ========================================================
    # ESTADÍSTICAS
    # ========================================================

    aciertos = sum(

        1

        for x in historial

        if x.get(
            "Resultado"
        ) == "✅ ACIERTO"
    )

    fallos = sum(

        1

        for x in historial

        if x.get(
            "Resultado"
        ) == "❌ FALLÓ"
    )

    pendientes = sum(

        1

        for x in historial

        if x.get(
            "Resultado"
        ) == "⏳ PENDIENTE"
    )

    empates = sum(

        1

        for x in historial

        if x.get(
            "Resultado"
        ) == "⚪ EMPATE"
    )

    no_apostar = sum(

        1

        for x in historial

        if x.get(
            "Resultado"
        ) == "⚪ NO APOSTAR"
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

    a, b, c, d = st.columns(4)

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

    if empates > 0:

        st.caption(
            f"⚪ Empates: {empates}"
        )

    if no_apostar > 0:

        st.caption(
            f"⚪ No apostar: {no_apostar}"
        )

else:

    st.info(
        "Todavía no hay predicciones."
    )


# ============================================================
# EXPLICACIÓN
# ============================================================

st.divider()

st.caption(
    "Funcionamiento: el sistema observa el contrato "
    "BTC 15M actualmente vigente. Durante su último "
    "minuto utiliza el Target de ESE contrato y el "
    "comportamiento reciente de BTC para predecir "
    "si el SIGUIENTE contrato terminará ARRIBA o ABAJO. "
    "La predicción se guarda antes del cierre. "
    "Cuando el siguiente contrato existe, se identifica "
    "su ticker REAL de Kalshi. Después de su cierre, "
    "el sistema obtiene el Target REAL y el "
    "Expiration Value REAL de Kalshi. "
    "Si Expiration Value > Target, el resultado es ARRIBA. "
    "Si Expiration Value < Target, el resultado es ABAJO. "
    "Luego compara ese resultado con la predicción "
    "y marca ACIERTO o FALLÓ. "
    "El historial nunca se reinicia al cambiar de contrato."
)


# ============================================================
# ACTUALIZACIÓN AUTOMÁTICA
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
