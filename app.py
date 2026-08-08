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

# ------------------------------------------------------------
# KALSHI
# ------------------------------------------------------------

KALSHI_URL = "https://external-api.kalshi.com"

SERIES = "KXBTC15M"

# ------------------------------------------------------------
# HORA
# ------------------------------------------------------------

LOCAL_TZ = ZoneInfo("America/Chicago")

# ------------------------------------------------------------
# ARCHIVO DE HISTORIAL
# ------------------------------------------------------------

HISTORIAL_FILE = "historial_kalshi.json"

# ------------------------------------------------------------
# ACTUALIZACIÓN
# ------------------------------------------------------------

REFRESH_SECONDS = 5

# ------------------------------------------------------------
# PREDICCIÓN
#
# Se genera dentro de los últimos 90 segundos.
# Esto da margen suficiente para que Streamlit no pierda
# el momento exacto de los 60 segundos.
# ------------------------------------------------------------

PREDICCION_VENTANA = 90


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
# CARGAR CLAVE PRIVADA
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

    except Exception as error:

        raise Exception(
            "KALSHI_PRIVATE_KEY no tiene formato PEM válido."
        ) from error


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
# CONVERTIR FECHA
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
#
# IMPORTANTE:
#
# NO usamos únicamente status=open.
#
# Buscamos la serie completa para poder encontrar el contrato
# cuyo horario realmente contiene "ahora".
# ============================================================

def obtener_mercados_btc():

    data = kalshi_request(

        "GET",

        "/trade-api/v2/markets",

        params={

            "series_ticker":
                SERIES,

            "limit":
                1000
        }
    )

    return data.get(
        "markets",
        []
    )


# ============================================================
# OBTENER CONTRATO INDIVIDUAL
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
#
# Busca:
#
# open_time <= AHORA < close_time
#
# sin depender de status=open.
# ============================================================

def buscar_mercado_actual():

    mercados = obtener_mercados_btc()

    ahora = datetime.now(
        timezone.utc
    )

    candidatos = []

    for mercado in mercados:

        apertura = convertir_fecha(
            mercado.get(
                "open_time"
            )
        )

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

        # Si no hay open_time, aceptamos el mercado
        # siempre que todavía no haya cerrado.

        if apertura is None:

            apertura = (
                cierre -
                pd.Timedelta(minutes=15)
            ).to_pytimedelta()

            apertura = (
                datetime.now(
                    timezone.utc
                ) +
                (apertura - timedelta_zero())
            )

        # Contrato actualmente vigente

        if (

            apertura <= ahora
            and
            ahora < cierre

        ):

            mercado["_open"] = apertura
            mercado["_close"] = cierre

            candidatos.append(
                mercado
            )

    if not candidatos:

        return None

    # Si hay varios, elegimos el que cierre primero.

    candidatos.sort(
        key=lambda x: x["_close"]
    )

    return candidatos[0]


# ============================================================
# PEQUEÑA FUNCIÓN AUXILIAR
# ============================================================

def timedelta_zero():

    from datetime import timedelta

    return timedelta(0)


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
# BUSCAR TARGET RECURSIVAMENTE
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
                "strike",
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
        "event_ticker",
        "rules_primary",
        "rules_secondary"

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

            detallado = obtener_contrato(
                ticker
            )

            encontrados = buscar_targets_recursivo(
                detallado
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
                detallado
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
# BTC — BINANCE
# ============================================================

def obtener_btc_binance():

    response = requests.get(

        "https://api.binance.com/api/v3/klines",

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

    if not isinstance(data, list):

        raise Exception(
            "Binance no devolvió una lista."
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
# BTC — COINBASE RESPALDO
# ============================================================

def obtener_btc_coinbase():

    response = requests.get(

        "https://api.exchange.coinbase.com/products/BTC-USD/candles",

        params={

            "granularity":
                60

        },

        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):

        raise Exception(
            "Coinbase no devolvió datos válidos."
        )

    # Coinbase devuelve:
    # [time, low, high, open, close, volume]

    filas = []

    for fila in data:

        if len(fila) < 6:

            continue

        filas.append({

            "time":
                fila[0],

            "Low":
                float(fila[1]),

            "High":
                float(fila[2]),

            "Open":
                float(fila[3]),

            "Close":
                float(fila[4]),

            "Volume":
                float(fila[5])

        })

    df = pd.DataFrame(
        filas
    )

    if df.empty:

        raise Exception(
            "Coinbase no tiene velas."
        )

    df = df.sort_values(
        "time"
    )

    df = df.tail(
        120
    ).reset_index(
        drop=True
    )

    return df


# ============================================================
# OBTENER BTC CON RESPALDO
# ============================================================

def obtener_btc():

    try:

        df = obtener_btc_binance()

        if len(df) >= 30:

            return df, "Binance"

    except Exception:

        pass

    try:

        df = obtener_btc_coinbase()

        if len(df) >= 30:

            return df, "Coinbase"

    except Exception as error:

        raise Exception(
            "No pude obtener BTC desde Binance "
            "ni Coinbase."
        ) from error

    raise Exception(
        "No hay suficientes datos de BTC."
    )


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

    df["EMA50"] = (
        df["Close"]
        .ewm(
            span=50,
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

    df["MACD_SIGNAL"] = (
        df["MACD"]
        .ewm(
            span=9,
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

    # Momentum

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

    # Volatilidad

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
    # TARGET
    # ========================================================

    diferencia = (
        precio -
        target
    )

    diferencia_pct = (
        diferencia /
        target
    ) * 100

    # --------------------------------------------------------
    # Distancia al target
    # --------------------------------------------------------

    if diferencia > 0:

        score += 20

        razones.append(
            f"BTC está ${diferencia:,.2f} "
            f"({diferencia_pct:+.3f}%) "
            "por encima del Target."
        )

    elif diferencia < 0:

        score -= 20

        razones.append(
            f"BTC está ${abs(diferencia):,.2f} "
            f"({diferencia_pct:+.3f}%) "
            "por debajo del Target."
        )

    else:

        razones.append(
            "BTC está exactamente en el Target."
        )

    # ========================================================
    # FUERZA DE DISTANCIA AL TARGET
    #
    # Una distancia pequeña no debe dominar todo el modelo.
    # ========================================================

    distancia_pct_abs = abs(
        diferencia_pct
    )

    if distancia_pct_abs >= 0.08:

        if diferencia > 0:

            score += 8

            razones.append(
                "La distancia al Target es significativa "
                "a favor de ARRIBA."
            )

        elif diferencia < 0:

            score -= 8

            razones.append(
                "La distancia al Target es significativa "
                "a favor de ABAJO."
            )

    # ========================================================
    # EMA 9 / 21
    # ========================================================

    if ema9 > ema21:

        score += 12

        razones.append(
            "EMA9 > EMA21: tendencia alcista."
        )

    else:

        score -= 12

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

        score += 10

        razones.append(
            "MACD positivo."
        )

    else:

        score -= 10

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
    # MOMENTUM 1M
    # ========================================================

    if pd.notna(momentum1):

        momentum1 = float(
            momentum1
        )

        if momentum1 > 0:

            score += 6

            razones.append(
                f"Momentum 1m positivo "
                f"(+{momentum1:.3f}%)."
            )

        elif momentum1 < 0:

            score -= 6

            razones.append(
                f"Momentum 1m negativo "
                f"({momentum1:.3f}%)."
            )

    # ========================================================
    # MOMENTUM 3M
    # ========================================================

    if pd.notna(momentum3):

        momentum3 = float(
            momentum3
        )

        if momentum3 > 0:

            score += 8

            razones.append(
                f"Momentum 3m positivo "
                f"(+{momentum3:.3f}%)."
            )

        elif momentum3 < 0:

            score -= 8

            razones.append(
                f"Momentum 3m negativo "
                f"({momentum3:.3f}%)."
            )

    # ========================================================
    # MOMENTUM 5M
    # ========================================================

    if pd.notna(momentum5):

        momentum5 = float(
            momentum5
        )

        if momentum5 > 0:

            score += 8

            razones.append(
                f"Momentum 5m positivo "
                f"(+{momentum5:.3f}%)."
            )

        elif momentum5 < 0:

            score -= 8

            razones.append(
                f"Momentum 5m negativo "
                f"({momentum5:.3f}%)."
            )

    # ========================================================
    # MOMENTUM 10M
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
            80
        )

        confianza = int(
            round(
                50 +
                fuerza * 0.52
            )
        )

        confianza = max(
            50,
            min(
                92,
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

        return []

    return []


# ============================================================
# GUARDAR HISTORIAL
# ============================================================

def guardar_historial(historial):

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

    # Evitar duplicados.

    for registro in historial:

        if registro.get(
            "Ticker"
        ) == ticker:

            return False

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

    return True


# ============================================================
# RESULTADO OFICIAL DE KALSHI
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

    # --------------------------------------------------------
    # Kalshi normalmente devuelve yes/no
    # --------------------------------------------------------

    if resultado not in (
        None,
        "",
        "null"
    ):

        resultado = str(
            resultado
        ).lower()

        if resultado in (
            "yes",
            "up"
        ):

            return "UP", expiration

        if resultado in (
            "no",
            "down"
        ):

            return "DOWN", expiration

    # --------------------------------------------------------
    # Respaldo: expiration_value vs Target
    # --------------------------------------------------------

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
# ACTUALIZAR RESULTADOS PENDIENTES
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
# SESSION STATE
# ============================================================

if "historial" not in st.session_state:

    st.session_state.historial = (
        cargar_historial()
    )


if "ticker_actual" not in st.session_state:

    st.session_state.ticker_actual = None


if "prediccion_hecha" not in st.session_state:

    st.session_state.prediccion_hecha = False


if "prediccion" not in st.session_state:

    st.session_state.prediccion = None


if "confianza" not in st.session_state:

    st.session_state.confianza = 0


if "target_actual" not in st.session_state:

    st.session_state.target_actual = None


if "precio_prediccion" not in st.session_state:

    st.session_state.precio_prediccion = None


if "razones" not in st.session_state:

    st.session_state.razones = []


if "score" not in st.session_state:

    st.session_state.score = 0


if "ultimo_error_kalshi" not in st.session_state:

    st.session_state.ultimo_error_kalshi = None


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Predicción del contrato actualmente vigente "
    "usando Target de Kalshi + comportamiento del mercado."
)


# ============================================================
# CREDENCIALES
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ No se encontraron las credenciales de Kalshi."
    )

    st.info(
        "Revisa KALSHI_API_KEY_ID y "
        "KALSHI_PRIVATE_KEY en Streamlit Secrets."
    )

    st.stop()


# ============================================================
# ACTUALIZAR RESULTADOS
# ============================================================

try:

    actualizar_pendientes()

except Exception:

    pass


# ============================================================
# OBTENER CONTRATO ACTUAL
# ============================================================

actual = None

error_kalshi = None

try:

    actual = buscar_mercado_actual()

except Exception as error:

    error_kalshi = str(
        error
    )


# ============================================================
# SI KALSHI TEMPORALMENTE NO DEVUELVE CONTRATO
#
# NO REINICIAMOS NADA.
# ============================================================

if actual is None:

    st.warning(
        "⏳ Kalshi no está devolviendo en este momento "
        "el contrato actualmente vigente."
    )

    if error_kalshi:

        st.caption(
            f"Detalle: {error_kalshi}"
        )

    st.info(
        "La aplicación conservará el historial y "
        "volverá a intentarlo automáticamente."
    )

    # Mostrar historial aunque Kalshi falle.

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

        st.dataframe(
            tabla,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "Todavía no hay predicciones."
        )

else:

    # ========================================================
    # DATOS DEL CONTRATO
    # ========================================================

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

    # ========================================================
    # DETECTAR NUEVO CONTRATO
    #
    # IMPORTANTE:
    #
    # Solo cambiamos el estado de la PREDICCIÓN ACTUAL.
    # El historial jamás se borra.
    # ========================================================

    if (
        st.session_state.ticker_actual
        != ticker_actual
    ):

        # Antes de cambiar, intentamos actualizar
        # cualquier predicción anterior.

        try:

            actualizar_pendientes()

        except Exception:

            pass

        st.session_state.ticker_actual = (
            ticker_actual
        )

        st.session_state.prediccion_hecha = False

        st.session_state.prediccion = None

        st.session_state.confianza = 0

        st.session_state.target_actual = None

        st.session_state.precio_prediccion = None

        st.session_state.razones = []

        st.session_state.score = 0

    # ========================================================
    # TARGET DEL CONTRATO ACTUAL
    # ========================================================

    target_actual = None

    try:

        target_actual = obtener_target(
            actual
        )

        st.session_state.target_actual = (
            target_actual
        )

    except Exception as error:

        # Si ya teníamos el Target de este mismo contrato,
        # lo conservamos.

        if (
            st.session_state.ticker_actual
            == ticker_actual
            and
            st.session_state.target_actual
            is not None
        ):

            target_actual = (
                st.session_state.target_actual
            )

        else:

            st.warning(
                "⚠️ Todavía no pude leer el Target "
                "de este contrato. Reintentando..."
            )

    # ========================================================
    # BTC
    # ========================================================

    try:

        btc, fuente_btc = obtener_btc()

        btc = calcular_indicadores(
            btc
        )

        precio = float(
            btc["Close"].iloc[-1]
        )

    except Exception as error:

        st.error(
            f"❌ Error obteniendo BTC: {error}"
        )

        precio = None

        btc = None

        fuente_btc = "Sin datos"

    # ========================================================
    # TIEMPO
    # ========================================================

    ahora = datetime.now(
        timezone.utc
    )

    if close_actual is not None:

        segundos_restantes = max(

            0,

            int(
                (
                    close_actual -
                    ahora
                ).total_seconds()
            )
        )

    else:

        segundos_restantes = 0

    minutos = (
        segundos_restantes // 60
    )

    segundos = (
        segundos_restantes % 60
    )

    # ========================================================
    # CONTRATO ACTUAL
    # ========================================================

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

    elif actual.get(
        "yes_sub_title"
    ):

        st.write(
            actual.get(
                "yes_sub_title"
            )
        )

    if subtitulo:

        st.caption(
            subtitulo
        )

    # ========================================================
    # BTC / TARGET
    # ========================================================

    col1, col2 = st.columns(2)

    if precio is not None:

        col1.metric(
            "₿ BTC actual",
            f"${precio:,.2f}"
        )

    else:

        col1.metric(
            "₿ BTC actual",
            "Sin datos"
        )

    if target_actual is not None:

        col2.metric(
            "🎯 Target Kalshi",
            f"${target_actual:,.2f}"
        )

    else:

        col2.metric(
            "🎯 Target Kalshi",
            "Buscando..."
        )

    # ========================================================
    # DISTANCIA AL TARGET
    # ========================================================

    if (
        precio is not None
        and
        target_actual is not None
    ):

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
    # FUENTE BTC
    # ========================================================

    st.caption(
        f"Fuente BTC: {fuente_btc}"
    )

    # ========================================================
    # TEMPORIZADOR
    # ========================================================

    st.subheader(
        "⏳ Tiempo restante"
    )

    if segundos_restantes <= 60:

        st.error(
            f"🔴 ÚLTIMO MINUTO — "
            f"{minutos:02d}:{segundos:02d}"
        )

    elif segundos_restantes <= 180:

        st.warning(
            f"🟡 PREPARANDO PREDICCIÓN — "
            f"{minutos:02d}:{segundos:02d}"
        )

    else:

        st.info(
            f"⏱️ {minutos:02d}:{segundos:02d}"
        )

    if close_actual is not None:

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
    # PREDICCIÓN DEL CONTRATO ACTUAL
    # ========================================================

    st.divider()

    st.subheader(
        "🔮 Predicción del contrato actual"
    )

    # ========================================================
    # GENERAR PREDICCIÓN
    #
    # SE HACE ANTES DEL CIERRE.
    #
    # NO necesita conocer el siguiente contrato.
    # ========================================================

    if (
        not st.session_state.prediccion_hecha
        and
        segundos_restantes <= PREDICCION_VENTANA
        and
        segundos_restantes > 0
        and
        target_actual is not None
        and
        btc is not None
        and
        len(btc) >= 50
    ):

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

            guardar_prediccion(

                ticker=ticker_actual,

                target=target_actual,

                prediccion=prediccion,

                confianza=confianza,

                precio=precio,

                close_time=close_actual,

                score=score
            )

            st.session_state.prediccion_hecha = True

            st.session_state.prediccion = (
                prediccion
            )

            st.session_state.confianza = (
                confianza
            )

            st.session_state.target_actual = (
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

        except Exception as error:

            st.warning(
                f"⚠️ No se pudo generar la predicción "
                f"todavía: {error}"
            )

    # ========================================================
    # MOSTRAR PREDICCIÓN
    # ========================================================

    if st.session_state.prediccion is not None:

        st.write(
            f"# {st.session_state.prediccion}"
        )

        st.metric(
            "Confianza",
            f"{st.session_state.confianza}%"
        )

        st.write(
            f"**Ticker:** "
            f"`{ticker_actual}`"
        )

        st.write(
            f"**Target:** "
            f"${st.session_state.target_actual:,.2f}"
        )

        st.write(
            f"**BTC al realizar predicción:** "
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

        if segundos_restantes > PREDICCION_VENTANA:

            faltan = (
                segundos_restantes -
                PREDICCION_VENTANA
            )

            mm = (
                faltan // 60
            )

            ss = (
                faltan % 60
            )

            st.info(
                "⏱️ La predicción se generará "
                "antes del cierre del contrato. "
                f"Faltan aproximadamente "
                f"{mm:02d}:{ss:02d} para entrar "
                "en la ventana de predicción."
            )

        elif segundos_restantes > 0:

            st.warning(
                "🔎 Dentro de la ventana de predicción. "
                "Analizando Target + mercado..."
            )

        else:

            st.warning(
                "⏳ El contrato acaba de cerrar. "
                "Consultando resultado de Kalshi..."
            )

    # ========================================================
    # GRÁFICO
    # ========================================================

    if btc is not None:

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

        # Mostrar primero las más recientes.

        tabla = tabla.iloc[
            ::-1
        ]

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
    # INFORMACIÓN
    # ========================================================

    st.divider()

    st.caption(
        "El sistema analiza el contrato de Kalshi "
        "que está actualmente vigente. Durante la "
        "ventana final utiliza el Target del contrato "
        "junto con EMA, MACD, RSI, momentum y "
        "volatilidad de BTC. La predicción se guarda "
        "antes del cierre. Después del cierre se "
        "consulta el resultado oficial de Kalshi y "
        "se marca ACIERTO o FALLÓ. No necesita conocer "
        "el siguiente contrato para realizar la predicción."
    )


# ============================================================
# ACTUALIZACIÓN AUTOMÁTICA
#
# Importante:
# Nunca hacemos st.stop() por un fallo temporal de Kalshi.
# La aplicación continúa y vuelve a intentar.
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
