import streamlit as st
import requests
import pandas as pd
import json
import os
import time
import base64
import re

from datetime import datetime, timezone, timedelta
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
GITHUB_API = "https://api.github.com"

SERIES = "KXBTC15M"

LOCAL_TZ = ZoneInfo("America/Chicago")

HISTORIAL_FILE = "historial_kalshi.json"

REFRESH_SECONDS = 5

# Cuántos minutos de BTC usar para cada predicción
VENTANA_ANALISIS_MINUTOS = 15

# Ventana de tolerancia para buscar contratos históricos
HORAS_HISTORIAL = 48


# ============================================================
# GITHUB CONFIG
# ============================================================

def cargar_config_github():

    username = None
    token = None
    repo = None
    branch = "main"

    try:

        username = (
            st.secrets.get("GITHUB_USERNAME")
            or st.secrets.get("GITHUB_USER")
            or st.secrets.get("GH_USERNAME")
        )

        token = (
            st.secrets.get("GITHUB_TOKEN")
            or st.secrets.get("GITHUB_PAT")
            or st.secrets.get("GH_TOKEN")
        )

        repo = (
            st.secrets.get("GITHUB_REPO")
            or st.secrets.get("GH_REPO")
            or "Trading-AI-Monitor"
        )

        branch = (
            st.secrets.get("GITHUB_BRANCH")
            or "main"
        )

    except Exception:
        pass

    return (
        str(username).strip() if username else None,
        str(token).strip() if token else None,
        str(repo).strip() if repo else None,
        str(branch).strip() if branch else "main"
    )


(
    GITHUB_USERNAME,
    GITHUB_TOKEN,
    GITHUB_REPO,
    GITHUB_BRANCH
) = cargar_config_github()


# ============================================================
# GITHUB HEADERS
# ============================================================

def github_headers():

    if not GITHUB_TOKEN:
        raise Exception(
            "Falta GITHUB_TOKEN en Streamlit Secrets."
        )

    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json"
    }


# ============================================================
# LEER HISTORIAL DE GITHUB
# ============================================================

def cargar_historial_github():

    if not GITHUB_USERNAME:
        raise Exception(
            "Falta GITHUB_USERNAME."
        )

    url = (
        f"{GITHUB_API}/repos/"
        f"{GITHUB_USERNAME}/"
        f"{GITHUB_REPO}/contents/"
        f"{HISTORIAL_FILE}"
    )

    response = requests.get(
        url,
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=15
    )

    if response.status_code == 404:
        return []

    if response.status_code >= 400:

        raise Exception(
            f"GitHub HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()

    contenido = data.get("content")

    if not contenido:
        return []

    try:

        texto = base64.b64decode(
            contenido.replace("\n", "")
        ).decode("utf-8")

        historial = json.loads(texto)

        if isinstance(historial, list):
            return historial

    except Exception as error:

        raise Exception(
            f"Error leyendo historial GitHub: {error}"
        )

    return []


# ============================================================
# SHA GITHUB
# ============================================================

def obtener_sha_historial_github():

    url = (
        f"{GITHUB_API}/repos/"
        f"{GITHUB_USERNAME}/"
        f"{GITHUB_REPO}/contents/"
        f"{HISTORIAL_FILE}"
    )

    response = requests.get(
        url,
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=15
    )

    if response.status_code == 404:
        return None

    if response.status_code >= 400:

        raise Exception(
            f"Error obteniendo SHA: "
            f"{response.status_code}"
        )

    return response.json().get("sha")


# ============================================================
# GUARDAR EN GITHUB
# ============================================================

def guardar_historial_github(historial):

    contenido = json.dumps(
        historial,
        indent=2,
        ensure_ascii=False
    )

    contenido_b64 = base64.b64encode(
        contenido.encode("utf-8")
    ).decode("utf-8")

    url = (
        f"{GITHUB_API}/repos/"
        f"{GITHUB_USERNAME}/"
        f"{GITHUB_REPO}/contents/"
        f"{HISTORIAL_FILE}"
    )

    sha = obtener_sha_historial_github()

    payload = {
        "message": "Actualizar historial BTC Kalshi",
        "content": contenido_b64,
        "branch": GITHUB_BRANCH
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=github_headers(),
        json=payload,
        timeout=20
    )

    if response.status_code not in (200, 201):

        raise Exception(
            f"GitHub no pudo guardar. "
            f"HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    return True


# ============================================================
# CARGAR HISTORIAL
# ============================================================

def cargar_historial():

    try:

        historial = cargar_historial_github()

        try:

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

        except Exception:
            pass

        return historial

    except Exception:

        try:

            if os.path.exists(HISTORIAL_FILE):

                with open(
                    HISTORIAL_FILE,
                    "r",
                    encoding="utf-8"
                ) as archivo:

                    datos = json.load(archivo)

                if isinstance(datos, list):
                    return datos

        except Exception:
            pass

    return []


# ============================================================
# GUARDAR HISTORIAL
# ============================================================

def guardar_historial(historial):

    try:

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

    except Exception:
        pass

    try:

        guardar_historial_github(historial)

        st.session_state.github_error = None

        return True

    except Exception as error:

        st.session_state.github_error = str(error)

        return False


# ============================================================
# CREDENCIALES KALSHI
# ============================================================

def cargar_credenciales():

    try:

        key_id = st.secrets["KALSHI_API_KEY_ID"]
        private_key = st.secrets["KALSHI_PRIVATE_KEY"]

        return (
            str(key_id),
            str(private_key)
        )

    except Exception:

        return None, None


API_KEY_ID, PRIVATE_KEY = cargar_credenciales()


# ============================================================
# CLAVE PRIVADA
# ============================================================

def cargar_clave_privada():

    if not PRIVATE_KEY:

        raise Exception(
            "Falta KALSHI_PRIVATE_KEY."
        )

    try:

        return serialization.load_pem_private_key(
            PRIVATE_KEY.strip().encode("utf-8"),
            password=None
        )

    except Exception as error:

        raise Exception(
            "KALSHI_PRIVATE_KEY inválida."
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
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Content-Type": "application/json"
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
            f"{response.text[:600]}"
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


def fecha_cierre_texto(fecha):

    if not fecha:
        return None

    return (
        fecha
        .astimezone(LOCAL_TZ)
        .strftime(
            "%Y-%m-%d %I:%M:%S %p"
        )
    )


def parsear_fecha_cierre_texto(texto):

    if not texto:
        return None

    try:

        return datetime.strptime(
            texto,
            "%Y-%m-%d %I:%M:%S %p"
        ).replace(
            tzinfo=LOCAL_TZ
        ).astimezone(
            timezone.utc
        )

    except Exception:

        return None


# ============================================================
# MERCADOS ABIERTOS
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
# MERCADOS CERRADOS
# ============================================================

def obtener_mercados_cerrados():

    try:

        data = kalshi_request(
            "GET",
            "/trade-api/v2/markets",
            params={
                "series_ticker": SERIES,
                "status": "closed",
                "limit": 100
            }
        )

        return data.get(
            "markets",
            []
        )

    except Exception:

        return []


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
# FECHA CIERRE
# ============================================================

def cierre_de_mercado(mercado):

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

    return cierre


# ============================================================
# TODAS LAS VENTANAS DISPONIBLES
# ============================================================

def obtener_mercados_disponibles():

    mercados = []

    try:

        mercados.extend(
            obtener_mercados_btc(
                status="open",
                limit=100
            )
        )

    except Exception:
        pass

    try:

        mercados.extend(
            obtener_mercados_cerrados()
        )

    except Exception:
        pass

    unicos = {}

    for mercado in mercados:

        ticker = mercado.get(
            "ticker"
        )

        if ticker:

            unicos[ticker] = mercado

    resultado = list(
        unicos.values()
    )

    for mercado in resultado:

        cierre = cierre_de_mercado(
            mercado
        )

        if cierre:

            mercado["_close"] = cierre

    resultado.sort(
        key=lambda x: x.get(
            "_close",
            datetime.min.replace(
                tzinfo=timezone.utc
            )
        )
    )

    return resultado


# ============================================================
# CONTRATO ACTUAL
# ============================================================

def buscar_contrato_actual():

    mercados = obtener_mercados_btc(
        status="open",
        limit=100
    )

    ahora = datetime.now(
        timezone.utc
    )

    candidatos = []

    for mercado in mercados:

        cierre = cierre_de_mercado(
            mercado
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
# SIGUIENTE CONTRATO
# ============================================================

def buscar_siguiente_contrato(
    cierre_actual,
    ticker_actual,
    mercados=None
):

    if cierre_actual is None:
        return None

    if mercados is None:

        mercados = (
            obtener_mercados_disponibles()
        )

    candidatos = []

    for mercado in mercados:

        ticker = mercado.get(
            "ticker"
        )

        if not ticker:
            continue

        if ticker == ticker_actual:
            continue

        cierre = cierre_de_mercado(
            mercado
        )

        if cierre is None:
            continue

        if cierre > cierre_actual:

            candidatos.append(
                (
                    cierre,
                    mercado
                )
            )

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda x: x[0]
    )

    return candidatos[0][1]


# ============================================================
# TARGET
# ============================================================

def convertir_numero_precio(valor):

    if valor is None:
        return None

    try:

        texto = (
            str(valor)
            .replace(",", "")
            .replace("$", "")
            .strip()
        )

        numero = float(texto)

        if numero > 1000:
            return numero

    except Exception:
        pass

    return None


def buscar_targets_recursivo(
    objeto
):

    encontrados = []

    if isinstance(
        objeto,
        dict
    ):

        for clave, valor in objeto.items():

            clave_lower = str(
                clave
            ).lower()

            prioridad = 0

            if clave_lower in (
                "functional_strike",
                "target_price",
                "target",
                "strike_price",
                "strike"
            ):

                prioridad = 100

            elif clave_lower in (
                "floor_strike",
                "cap_strike"
            ):

                prioridad = 80

            if prioridad:

                numero = (
                    convertir_numero_precio(
                        valor
                    )
                )

                if numero is not None:

                    encontrados.append(
                        (
                            prioridad,
                            numero,
                            clave
                        )
                    )

            encontrados.extend(
                buscar_targets_recursivo(
                    valor
                )
            )

    elif isinstance(
        objeto,
        list
    ):

        for elemento in objeto:

            encontrados.extend(
                buscar_targets_recursivo(
                    elemento
                )
            )

    return encontrados


def buscar_target_en_texto(
    mercado
):

    textos = []

    for campo in (
        "title",
        "subtitle",
        "yes_sub_title",
        "no_sub_title",
        "ticker",
        "event_ticker"
    ):

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
        r"target[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"strike[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)"
    ]

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
                    return numero

            except Exception:
                pass

    return None


def obtener_target(
    mercado
):

    encontrados = (
        buscar_targets_recursivo(
            mercado
        )
    )

    if encontrados:

        encontrados.sort(
            key=lambda x: x[0],
            reverse=True
        )

        return float(
            encontrados[0][1]
        )

    target_texto = (
        buscar_target_en_texto(
            mercado
        )
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

            encontrados = (
                buscar_targets_recursivo(
                    detalle
                )
            )

            if encontrados:

                encontrados.sort(
                    key=lambda x: x[0],
                    reverse=True
                )

                return float(
                    encontrados[0][1]
                )

            target_texto = (
                buscar_target_en_texto(
                    detalle
                )
            )

            if target_texto is not None:

                return float(
                    target_texto
                )

        except Exception:
            pass

    return None


# ============================================================
# COINBASE — DATOS BTC
# ============================================================

def obtener_btc_coinbase():

    response = requests.get(
        "https://api.exchange.coinbase.com/"
        "products/BTC-USD/candles",
        params={
            "granularity": 60
        },
        headers={
            "User-Agent":
                "BTC-Kalshi-Predictor/3.0"
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    filas = []

    for fila in data:

        if len(fila) < 6:
            continue

        filas.append([
            fila[0],
            fila[3],
            fila[2],
            fila[1],
            fila[4],
            fila[5]
        ])

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

    for columna in (
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ):

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
# BINANCE BACKUP
# ============================================================

def obtener_btc_binance():

    response = requests.get(
        "https://api.binance.us/api/v3/klines",
        params={
            "symbol": "BTCUSDT",
            "interval": "1m",
            "limit": 300
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

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

    for columna in (
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ):

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

    df = df.sort_values(
        "time"
    )

    return df


# ============================================================
# BTC COMPLETO
# ============================================================

def obtener_btc():

    try:

        df = obtener_btc_coinbase()

        fuente = "Coinbase"

    except Exception:

        df = obtener_btc_binance()

        fuente = "Binance.US"

    df = df.drop_duplicates(
        subset=["time"]
    )

    df = df.sort_values(
        "time"
    )

    precio, fuente_precio = (
        obtener_precio_btc()
    )

    return (
        df,
        precio,
        fuente_precio
    )


# ============================================================
# PRECIO BTC
# ============================================================

def obtener_precio_btc():

    try:

        response = requests.get(
            "https://api.exchange.coinbase.com/"
            "products/BTC-USD/ticker",
            timeout=5
        )

        response.raise_for_status()

        precio = float(
            response.json()["price"]
        )

        return (
            precio,
            "Coinbase"
        )

    except Exception:
        pass

    response = requests.get(
        "https://api.binance.us/api/v3/"
        "ticker/price",
        params={
            "symbol": "BTCUSDT"
        },
        timeout=5
    )

    response.raise_for_status()

    precio = float(
        response.json()["price"]
    )

    return (
        precio,
        "Binance.US"
    )


# ============================================================
# INDICADORES
# ============================================================

def calcular_indicadores(
    df
):

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
        ema12 - ema26
    )

    df["MACD_SIGNAL"] = (
        df["MACD"]
        .ewm(
            span=9,
            adjust=False
        )
        .mean()
    )

    cambio = (
        df["Close"].diff()
    )

    ganancias = (
        cambio.clip(lower=0)
    )

    perdidas = (
        -cambio.clip(upper=0)
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
        (100 / (1 + rs))
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
# OBTENER VENTANA EXACTA DE 15 MINUTOS
#
# Esta es una parte MUY importante.
#
# Para predecir el siguiente contrato:
#
#   cierre del contrato base
#              ↓
#      ┌───────────────┐
#      │ últimos 15 min│
#      └───────────────┘
#              ↓
#        PREDICCIÓN
#
# No utilizamos el resultado del contrato siguiente.
# ============================================================

def obtener_ventana_prediccion(
    df,
    cierre_base
):

    if cierre_base is None:
        return None

    inicio = (
        cierre_base -
        timedelta(
            minutes=VENTANA_ANALISIS_MINUTOS
        )
    )

    # Para datos históricos:
    # solamente usamos velas que ya habían
    # comenzado antes del cierre.
    ventana = df[
        (df["time"] >= inicio)
        &
        (df["time"] <= cierre_base)
    ].copy()

    if len(ventana) < 5:

        # Segunda oportunidad:
        # tolerancia de algunos minutos.
        inicio_tolerancia = (
            inicio -
            timedelta(minutes=2)
        )

        ventana = df[
            (df["time"] >= inicio_tolerancia)
            &
            (df["time"] <= cierre_base)
        ].copy()

    if len(ventana) < 5:
        return None

    ventana = ventana.sort_values(
        "time"
    )

    return ventana


# ============================================================
# PREDICCIÓN
# ============================================================

def generar_prediccion(
    df
):

    if df is None or len(df) < 5:

        return (
            "⚪ NO APOSTAR",
            50,
            [
                "No hubo suficientes datos BTC "
                "para realizar un análisis confiable."
            ],
            0,
            None
        )

    df = calcular_indicadores(
        df
    )

    ultimo = df.iloc[-1]

    score = 0

    razones = []

    precio = float(
        ultimo["Close"]
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

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if ema9 > ema21:

        score += 12

        razones.append(
            "EMA9 > EMA21: "
            "tendencia alcista."
        )

    else:

        score -= 12

        razones.append(
            "EMA9 < EMA21: "
            "tendencia bajista."
        )

    if ema21 > ema50:

        score += 10

        razones.append(
            "EMA21 > EMA50: "
            "estructura alcista."
        )

    else:

        score -= 10

        razones.append(
            "EMA21 < EMA50: "
            "estructura bajista."
        )

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

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

    if macd > macd_signal:

        score += 8

        razones.append(
            "MACD por encima de la señal."
        )

    else:

        score -= 8

        razones.append(
            "MACD por debajo de la señal."
        )

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    for nombre, valor, peso in [
        ("1m", momentum1, 5),
        ("3m", momentum3, 7),
        ("5m", momentum5, 8),
        ("10m", momentum10, 10)
    ]:

        if pd.isna(valor):
            continue

        valor = float(valor)

        if valor > 0:

            score += peso

            razones.append(
                f"Momentum {nombre} "
                f"positivo "
                f"({valor:+.3f}%)."
            )

        elif valor < 0:

            score -= peso

            razones.append(
                f"Momentum {nombre} "
                f"negativo "
                f"({valor:.3f}%)."
            )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if pd.notna(rsi):

        rsi = float(rsi)

        if rsi >= 50:

            score += 5

            razones.append(
                f"RSI {rsi:.1f}: "
                "presión alcista."
            )

        else:

            score -= 5

            razones.append(
                f"RSI {rsi:.1f}: "
                "presión bajista."
            )

    # --------------------------------------------------------
    # VOLATILIDAD
    # --------------------------------------------------------

    if pd.notna(
        volatilidad
    ):

        razones.append(
            f"Volatilidad reciente: "
            f"{float(volatilidad):.4f}%."
        )

    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    if score >= 10:

        prediccion = "🟢 ARRIBA"

    elif score <= -10:

        prediccion = "🔴 ABAJO"

    else:

        prediccion = "⚪ NO APOSTAR"

    if prediccion == "⚪ NO APOSTAR":

        confianza = 50

    else:

        fuerza = min(
            abs(score),
            60
        )

        confianza = int(
            round(
                50 +
                fuerza * 0.65
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
        score,
        precio
    )


# ============================================================
# BUSCAR REGISTRO POR CONTRATO BASE
# ============================================================

def buscar_registro_base(
    ticker
):

    if not ticker:
        return None

    for registro in (
        st.session_state.historial
    ):

        if registro.get(
            "Contrato base"
        ) == ticker:

            return registro

    return None


# ============================================================
# BUSCAR REGISTRO POR CONTRATO PREDICHO
# ============================================================

def buscar_registro_predicho(
    ticker
):

    if not ticker:
        return None

    for registro in (
        st.session_state.historial
    ):

        if registro.get(
            "Contrato predicho"
        ) == ticker:

            return registro

    return None


# ============================================================
# CREAR PREDICCIÓN
#
# Esta función es la pieza central.
#
# Contrato BASE terminado
#          ↓
# últimos 15 minutos de BTC
#          ↓
# predicción
#          ↓
# siguiente contrato
#          ↓
# guardar TODO en GitHub
#
# IMPORTANTE:
# el resultado del siguiente contrato NO se conoce
# al momento de crear esta predicción.
# ============================================================

def crear_prediccion_para_base(
    contrato_base,
    df_btc,
    mercados
):

    ticker_base = contrato_base.get(
        "ticker"
    )

    if not ticker_base:
        return None

    # --------------------------------------------------------
    # NO DUPLICAR
    # --------------------------------------------------------

    existente = (
        buscar_registro_base(
            ticker_base
        )
    )

    if existente is not None:

        return existente

    cierre_base = (
        cierre_de_mercado(
            contrato_base
        )
    )

    if cierre_base is None:
        return None

    # --------------------------------------------------------
    # BUSCAR SIGUIENTE CONTRATO
    # --------------------------------------------------------

    siguiente = (
        buscar_siguiente_contrato(
            cierre_base,
            ticker_base,
            mercados
        )
    )

    if siguiente is None:

        return None

    ticker_siguiente = (
        siguiente.get(
            "ticker"
        )
    )

    if not ticker_siguiente:

        return None

    # --------------------------------------------------------
    # TARGET DEL SIGUIENTE CONTRATO
    # --------------------------------------------------------

    try:

        target_siguiente = (
            obtener_target(
                siguiente
            )
        )

    except Exception:

        target_siguiente = None

    # --------------------------------------------------------
    # DATOS BTC DE LOS 15 MINUTOS ANTERIORES
    # --------------------------------------------------------

    ventana = (
        obtener_ventana_prediccion(
            df_btc,
            cierre_base
        )
    )

    if ventana is None:

        return None

    (
        prediccion,
        confianza,
        razones,
        score,
        precio
    ) = generar_prediccion(
        ventana
    )

    # --------------------------------------------------------
    # REGISTRO PERMANENTE
    # --------------------------------------------------------

    ahora_local = datetime.now(
        LOCAL_TZ
    )

    registro = {

        "ID": (
            f"{ticker_base}"
            f"__PREDICE__"
            f"{ticker_siguiente}"
        ),

        "Contrato base":
            ticker_base,

        "Cierre contrato base":
            fecha_cierre_texto(
                cierre_base
            ),

        "Contrato predicho":
            ticker_siguiente,

        "Cierre contrato predicho":
            fecha_cierre_texto(
                cierre_de_mercado(
                    siguiente
                )
            ),

        "Target contrato predicho":
            (
                round(
                    float(
                        target_siguiente
                    ),
                    2
                )
                if target_siguiente is not None
                else None
            ),

        "Predicción":
            prediccion,

        "Confianza":
            f"{confianza}%",

        "Score":
            int(score),

        "Precio BTC predicción":
            (
                round(
                    float(precio),
                    2
                )
                if precio is not None
                else None
            ),

        "Ventana análisis":
            "15 minutos anteriores al cierre "
            "del contrato base",

        "Inicio ventana análisis":
            fecha_cierre_texto(
                cierre_base -
                timedelta(
                    minutes=15
                )
            ),

        "Fin ventana análisis":
            fecha_cierre_texto(
                cierre_base
            ),

        "Expiration Value":
            None,

        "Resultado Kalshi":
            "PENDIENTE",

        "Resultado":
            "⏳ PENDIENTE",

        "Estado predicción":
            "PREDICCIÓN GUARDADA",

        "Análisis":
            razones,

        "Momento predicción":
            ahora_local.strftime(
                "%Y-%m-%d %I:%M:%S"
            ),

        "Actualizado":
            ahora_local.strftime(
                "%Y-%m-%d %I:%M:%S"
            )
    }

    # --------------------------------------------------------
    # GUARDAR INMEDIATAMENTE
    # --------------------------------------------------------

    st.session_state.historial.append(
        registro
    )

    guardar_historial(
        st.session_state.historial
    )

    return registro


# ============================================================
# RECUPERACIÓN AUTOMÁTICA
#
# Esta función soluciona el problema principal:
#
# Si el usuario cerró la app durante 15, 30, 45...
# minutos, al regresar se buscan los contratos que
# faltan en el historial.
#
# No depende de session_state anterior.
# GitHub contiene la memoria.
# ============================================================

def recuperar_contratos_faltantes(
    df_btc,
    mercados
):

    if df_btc is None or len(df_btc) < 5:
        return 0

    ahora = datetime.now(
        timezone.utc
    )

    limite = (
        ahora -
        timedelta(
            hours=HORAS_HISTORIAL
        )
    )

    contratos = []

    for mercado in mercados:

        cierre = (
            cierre_de_mercado(
                mercado
            )
        )

        ticker = mercado.get(
            "ticker"
        )

        if not ticker:
            continue

        if cierre is None:
            continue

        # Solo contratos ya cerrados
        # dentro de la ventana histórica.
        if (
            cierre <= ahora
            and
            cierre >= limite
        ):

            contratos.append(
                (
                    cierre,
                    mercado
                )
            )

    contratos.sort(
        key=lambda x: x[0]
    )

    creados = 0

    for cierre, contrato in contratos:

        ticker = contrato.get(
            "ticker"
        )

        if buscar_registro_base(
            ticker
        ) is not None:

            continue

        try:

            registro = (
                crear_prediccion_para_base(
                    contrato,
                    df_btc,
                    mercados
                )
            )

            if registro is not None:

                creados += 1

        except Exception:
            continue

    return creados


# ============================================================
# RESOLVER RESULTADOS
# ============================================================

def actualizar_resultados():

    cambio = False

    for registro in (
        st.session_state.historial
    ):

        if registro.get(
            "Resultado"
        ) != "⏳ PENDIENTE":

            continue

        ticker = registro.get(
            "Contrato predicho"
        )

        if not ticker:
            continue

        try:

            mercado = obtener_contrato(
                ticker
            )

        except Exception:

            continue

        # ----------------------------------------------------
        # TARGET REAL
        # ----------------------------------------------------

        target = registro.get(
            "Target contrato predicho"
        )

        if target is None:

            try:

                target = obtener_target(
                    mercado
                )

                if target is not None:

                    registro[
                        "Target contrato predicho"
                    ] = round(
                        float(target),
                        2
                    )

                    cambio = True

            except Exception:

                continue

        if target is None:
            continue

        # ----------------------------------------------------
        # EXPIRATION VALUE
        # ----------------------------------------------------

        expiration = mercado.get(
            "expiration_value"
        )

        if expiration in (
            None,
            "",
            "null"
        ):

            # Todavía no terminó.
            continue

        try:

            expiration = float(
                expiration
            )

            target = float(
                target
            )

        except Exception:

            continue

        # ----------------------------------------------------
        # GUARDAR DATOS REALES
        # ----------------------------------------------------

        registro[
            "Expiration Value"
        ] = round(
            expiration,
            2
        )

        registro[
            "Target contrato predicho"
        ] = round(
            target,
            2
        )

        # ----------------------------------------------------
        # RESULTADO REAL
        # ----------------------------------------------------

        if expiration > target:

            resultado_kalshi = "UP"

        elif expiration < target:

            resultado_kalshi = "DOWN"

        else:

            resultado_kalshi = "TIE"

        registro[
            "Resultado Kalshi"
        ] = resultado_kalshi

        # ----------------------------------------------------
        # COMPARAR PREDICCIÓN
        # ----------------------------------------------------

        prediccion = registro.get(
            "Predicción"
        )

        if (
            prediccion == "🟢 ARRIBA"
            and
            resultado_kalshi == "UP"
        ):

            resultado = "✅ ACIERTO"

        elif (
            prediccion == "🔴 ABAJO"
            and
            resultado_kalshi == "DOWN"
        ):

            resultado = "✅ ACIERTO"

        elif (
            resultado_kalshi == "TIE"
        ):

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
            "Estado predicción"
        ] = "FINALIZADA"

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
            st.session_state.historial
        )


# ============================================================
# SESSION STATE
# ============================================================

if "historial" not in st.session_state:

    st.session_state.historial = (
        cargar_historial()
    )

if "github_error" not in st.session_state:

    st.session_state.github_error = None

if "recuperacion_realizada" not in st.session_state:

    st.session_state.recuperacion_realizada = False


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Predicción automática y memoria persistente "
    "por ciclos de 15 minutos."
)


# ============================================================
# VALIDACIONES
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ Faltan las credenciales de Kalshi."
    )

    st.code(
        "KALSHI_API_KEY_ID\n"
        "KALSHI_PRIVATE_KEY"
    )

    st.stop()


if not GITHUB_USERNAME:

    st.error(
        "❌ Falta GITHUB_USERNAME."
    )

    st.stop()


if not GITHUB_TOKEN:

    st.error(
        "❌ Falta GITHUB_TOKEN."
    )

    st.stop()


st.caption(
    f"☁️ Memoria permanente: "
    f"{GITHUB_USERNAME}/{GITHUB_REPO}/"
    f"{HISTORIAL_FILE}"
)


# ============================================================
# OBTENER BTC
# ============================================================

try:

    btc, precio, fuente = (
        obtener_btc()
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
# OBTENER MERCADOS
# ============================================================

try:

    mercados_disponibles = (
        obtener_mercados_disponibles()
    )

except Exception as error:

    mercados_disponibles = []

    st.warning(
        f"⚠️ No se pudieron recuperar "
        f"todos los contratos: {error}"
    )


# ============================================================
# RECUPERACIÓN AUTOMÁTICA
#
# AL ABRIR LA APP:
#
# GitHub → historial anterior
#        ↓
# contratos cerrados
#        ↓
# detectar faltantes
#        ↓
# generar predicciones faltantes
#        ↓
# guardar GitHub
#        ↓
# resolver resultados
# ============================================================

if not st.session_state.recuperacion_realizada:

    try:

        recuperados = (
            recuperar_contratos_faltantes(
                btc,
                mercados_disponibles
            )
        )

        if recuperados > 0:

            st.success(
                f"🔄 Se recuperaron "
                f"{recuperados} predicción(es) "
                f"que faltaban mientras la app "
                f"estaba cerrada."
            )

    except Exception as error:

        st.warning(
            "⚠️ No se pudo completar toda "
            f"la recuperación automática: {error}"
        )

    st.session_state.recuperacion_realizada = True


# ============================================================
# ACTUALIZAR RESULTADOS
# ============================================================

try:

    actualizar_resultados()

except Exception:
    pass


# ============================================================
# CONTRATO ACTUAL
# ============================================================

try:

    actual = (
        buscar_contrato_actual()
    )

except Exception as error:

    actual = None

    st.error(
        f"❌ Error consultando Kalshi: {error}"
    )


# ============================================================
# SI HAY CONTRATO ACTUAL
# ============================================================

if actual is not None:

    ticker_actual = actual.get(
        "ticker"
    )

    close_actual = (
        cierre_de_mercado(
            actual
        )
    )

    # --------------------------------------------------------
    # TARGET
    # --------------------------------------------------------

    try:

        target_actual = (
            obtener_target(
                actual
            )
        )

    except Exception:

        target_actual = None

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

    # --------------------------------------------------------
    # CONTRATO
    # --------------------------------------------------------

    st.subheader(
        "🎯 Contrato actualmente vigente"
    )

    st.write(
        f"**Ticker:** `{ticker_actual}`"
    )

    if actual.get("title"):

        st.write(
            actual.get("title")
        )

    if actual.get("subtitle"):

        st.caption(
            actual.get("subtitle")
        )

    # --------------------------------------------------------
    # BTC / TARGET
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # DIFERENCIA
    # --------------------------------------------------------

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
                f"BTC está "
                f"${diferencia:,.2f} "
                f"({diferencia_pct:+.3f}%) "
                "POR ENCIMA del Target."
            )

        elif diferencia < 0:

            st.error(
                f"BTC está "
                f"${abs(diferencia):,.2f} "
                f"({diferencia_pct:+.3f}%) "
                "POR DEBAJO del Target."
            )

        else:

            st.warning(
                "BTC está exactamente "
                "en el Target."
            )

    # --------------------------------------------------------
    # TEMPORIZADOR
    # --------------------------------------------------------

    st.subheader(
        "⏳ Tiempo restante"
    )

    if segundos_restantes <= 60:

        st.error(
            f"🔴 ÚLTIMO MINUTO — "
            f"{minutos:02d}:{segundos:02d}"
        )

    elif segundos_restantes <= 120:

        st.warning(
            f"🟡 PREPARANDO SIGUIENTE "
            f"PREDICCIÓN — "
            f"{minutos:02d}:{segundos:02d}"
        )

    else:

        st.info(
            f"⏱️ {minutos:02d}:{segundos:02d}"
        )

    st.write(
        "Cierre:",
        close_actual
        .astimezone(LOCAL_TZ)
        .strftime(
            "%I:%M:%S %p"
        )
    )

    # ========================================================
    # MOSTRAR PREDICCIÓN QUE YA EXISTE
    # ========================================================

    registro_actual = (
        buscar_registro_predicho(
            ticker_actual
        )
    )

    # ========================================================
    # ENCONTRAR PREDICCIÓN PARA EL SIGUIENTE
    #
    # Si el contrato actual ya es el contrato predicho
    # de una predicción anterior, mostramos esa predicción.
    # ========================================================

    st.divider()

    st.subheader(
        "🔮 Predicción para este contrato"
    )

    if registro_actual:

        pred = registro_actual.get(
            "Predicción"
        )

        confianza = registro_actual.get(
            "Confianza"
        )

        st.success(
            "PREDICCIÓN GUARDADA"
        )

        st.write(
            f"# {pred}"
        )

        st.metric(
            "Confianza",
            confianza
        )

        st.write(
            f"**Contrato base utilizado:** "
            f"`{registro_actual.get('Contrato base')}`"
        )

        target_pred = registro_actual.get(
            "Target contrato predicho"
        )

        if target_pred is not None:

            st.write(
                f"**Target:** "
                f"${float(target_pred):,.2f}"
            )

        st.write(
            f"**Precio BTC al realizar "
            f"el análisis:** "
            f"${float(registro_actual.get('Precio BTC predicción', 0)):,.2f}"
        )

        st.write(
            f"**Score:** "
            f"{registro_actual.get('Score')}"
        )

        st.write(
            f"**Estado:** "
            f"{registro_actual.get('Resultado')}"
        )

    else:

        # ----------------------------------------------------
        # Si no existe, creamos la predicción para el SIGUIENTE
        # contrato cuando estamos suficientemente cerca del
        # cierre del actual.
        # ----------------------------------------------------

        if segundos_restantes <= 120:

            try:

                registro_nuevo = (
                    crear_prediccion_para_base(
                        actual,
                        btc,
                        mercados_disponibles
                    )
                )

                if registro_nuevo:

                    st.success(
                        "🚨 PREDICCIÓN GENERADA "
                        "Y GUARDADA AUTOMÁTICAMENTE."
                    )

                    st.write(
                        f"# "
                        f"{registro_nuevo.get('Predicción')}"
                    )

                    st.metric(
                        "Confianza",
                        registro_nuevo.get(
                            "Confianza"
                        )
                    )

            except Exception as error:

                st.error(
                    f"❌ Error generando "
                    f"predicción: {error}"
                )

        else:

            faltan = max(
                0,
                segundos_restantes - 120
            )

            mm = faltan // 60
            ss = faltan % 60

            st.info(
                "La predicción del siguiente "
                "contrato se genera automáticamente "
                "durante los últimos 2 minutos "
                "del contrato actual."
            )

            st.caption(
                f"Faltan aproximadamente "
                f"{mm:02d}:{ss:02d} para entrar "
                "en la ventana de generación."
            )


# ============================================================
# SI NO HAY CONTRATO ACTUAL
# ============================================================

else:

    st.warning(
        "⏳ Kalshi no muestra en este momento "
        "un contrato BTC 15M abierto."
    )


# ============================================================
# ÚLTIMA PREDICCIÓN
# ============================================================

if st.session_state.historial:

    ultima = (
        st.session_state.historial[-1]
    )

    st.divider()

    st.subheader(
        "🔔 Última predicción registrada"
    )

    st.write(
        f"**Predicción:** "
        f"{ultima.get('Predicción')}"
    )

    st.write(
        f"**Estado:** "
        f"{ultima.get('Resultado')}"
    )

    st.write(
        f"**Contrato base:** "
        f"`{ultima.get('Contrato base')}`"
    )

    st.write(
        f"**Contrato predicho:** "
        f"`{ultima.get('Contrato predicho')}`"
    )

    if ultima.get(
        "Target contrato predicho"
    ) is not None:

        st.write(
            f"**Target:** "
            f"${float(ultima.get('Target contrato predicho')):,.2f}"
        )

    if ultima.get(
        "Expiration Value"
    ) is not None:

        st.write(
            f"**Expiration Value:** "
            f"${float(ultima.get('Expiration Value')):,.2f}"
        )

    if ultima.get(
        "Resultado Kalshi"
    ):

        st.write(
            f"**Resultado Kalshi:** "
            f"`{ultima.get('Resultado Kalshi')}`"
        )


# ============================================================
# GRÁFICO
# ============================================================

st.divider()

st.subheader(
    "📈 BTC — datos recientes"
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
# HISTORIAL
# ============================================================

st.divider()

st.subheader(
    "📜 Historial completo"
)

historial = (
    st.session_state.historial
)

if historial:

    tabla = pd.DataFrame(
        historial
    )

    columnas = [
        "Contrato base",
        "Cierre contrato base",
        "Contrato predicho",
        "Cierre contrato predicho",
        "Target contrato predicho",
        "Predicción",
        "Confianza",
        "Score",
        "Precio BTC predicción",
        "Expiration Value",
        "Resultado Kalshi",
        "Resultado",
        "Estado predicción",
        "Momento predicción",
        "Actualizado"
    ]

    existentes = [
        c
        for c in columnas
        if c in tabla.columns
    ]

    restantes = [
        c
        for c in tabla.columns
        if c not in existentes
    ]

    tabla = tabla[
        existentes +
        restantes
    ]

    # Más recientes primero
    tabla = tabla.iloc[
        ::-1
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
        x.get("Resultado")
        == "✅ ACIERTO"
        for x in historial
    )

    fallos = sum(
        x.get("Resultado")
        == "❌ FALLÓ"
        for x in historial
    )

    pendientes = sum(
        x.get("Resultado")
        == "⏳ PENDIENTE"
        for x in historial
    )

    empates = sum(
        x.get("Resultado")
        == "⚪ EMPATE"
        for x in historial
    )

    no_apostar = sum(
        x.get("Resultado")
        == "⚪ NO APOSTAR"
        for x in historial
    )

    evaluados = (
        aciertos +
        fallos
    )

    precision = (
        (
            aciertos /
            evaluados
        ) * 100
        if evaluados > 0
        else 0
    )

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

    if empates:

        st.caption(
            f"⚪ Empates: {empates}"
        )

    if no_apostar:

        st.caption(
            f"⚪ No apostar: {no_apostar}"
        )

else:

    st.info(
        "Todavía no hay predicciones guardadas."
    )


# ============================================================
# ESTADO GITHUB
# ============================================================

if st.session_state.github_error:

    st.warning(
        "⚠️ GitHub no pudo sincronizar "
        "en el último intento."
    )

    st.caption(
        "La aplicación mantiene una copia local "
        "y volverá a intentar sincronizar."
    )


# ============================================================
# EXPLICACIÓN
# ============================================================

st.divider()

st.caption(
    "MEMORIA PERMANENTE: la aplicación guarda cada "
    "predicción en historial_kalshi.json dentro de "
    "GitHub. Al volver a abrir la aplicación, carga "
    "ese historial y busca contratos BTC 15M que "
    "terminaron mientras la aplicación estaba cerrada. "
    "Para cada contrato faltante reconstruye la "
    "predicción utilizando los 15 minutos anteriores "
    "al cierre del contrato base. Después asocia la "
    "predicción al siguiente contrato de Kalshi. "
    "Cuando ese contrato termina, obtiene el Target y "
    "el Expiration Value reales y determina "
    "automáticamente ACIERTO o FALLÓ. El sistema evita "
    "crear dos predicciones para el mismo contrato."
)


# ============================================================
# REFRESH
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
