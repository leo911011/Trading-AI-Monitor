import streamlit as st
import requests
import pandas as pd
import json
import os
import time
import base64
import re
import math

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

# Analizar exactamente los 15 minutos anteriores
VENTANA_BTC_MINUTOS = 15

# Usar los últimos 3 contratos cerrados
NUM_CONTRATOS_HISTORICOS = 3


# ============================================================
# GITHUB CONFIG
# ============================================================

def cargar_config_github():

    username = None
    token = None
    repo = "Trading-AI-Monitor"
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
        str(repo).strip() if repo else "Trading-AI-Monitor",
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
# GITHUB URL
# ============================================================

def github_file_url():

    return (
        f"{GITHUB_API}/repos/"
        f"{GITHUB_USERNAME}/"
        f"{GITHUB_REPO}/contents/"
        f"{HISTORIAL_FILE}"
    )


# ============================================================
# LEER HISTORIAL DE GITHUB
# ============================================================

def cargar_historial_github():

    if not GITHUB_USERNAME:
        raise Exception(
            "Falta GITHUB_USERNAME."
        )

    response = requests.get(
        github_file_url(),
        headers=github_headers(),
        params={
            "ref": GITHUB_BRANCH
        },
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

    texto = base64.b64decode(
        contenido.replace("\n", "")
    ).decode("utf-8")

    historial = json.loads(texto)

    if isinstance(historial, list):
        return historial

    return []


# ============================================================
# OBTENER SHA
# ============================================================

def obtener_sha_historial_github():

    response = requests.get(
        github_file_url(),
        headers=github_headers(),
        params={
            "ref": GITHUB_BRANCH
        },
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
# GUARDAR GITHUB
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

    sha = obtener_sha_historial_github()

    payload = {
        "message": "Actualizar historial BTC Kalshi 15M",
        "content": contenido_b64,
        "branch": GITHUB_BRANCH
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        github_file_url(),
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

        fecha = datetime.fromisoformat(
            str(valor).replace(
                "Z",
                "+00:00"
            )
        )

        if fecha.tzinfo is None:

            fecha = fecha.replace(
                tzinfo=timezone.utc
            )

        return fecha.astimezone(
            timezone.utc
        )

    except Exception:

        return None


# ============================================================
# CIERRE
# ============================================================

def cierre_de_mercado(mercado):

    cierre = convertir_fecha(
        mercado.get("close_time")
    )

    if cierre is None:

        cierre = convertir_fecha(
            mercado.get("expiration_time")
        )

    return cierre


# ============================================================
# INICIO
# ============================================================

def inicio_de_mercado(mercado):

    for campo in (
        "open_time",
        "start_time",
        "open_datetime"
    ):

        fecha = convertir_fecha(
            mercado.get(campo)
        )

        if fecha:
            return fecha

    cierre = cierre_de_mercado(
        mercado
    )

    if cierre:

        return cierre - timedelta(
            minutes=15
        )

    return None


# ============================================================
# MERCADOS
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
# CONTRATOS CERRADOS
# ============================================================

def obtener_contratos_cerrados():

    try:

        mercados = obtener_mercados_btc(
            status="closed",
            limit=100
        )

        return mercados

    except Exception:

        return []


# ============================================================
# ÚLTIMOS 3 CONTRATOS CERRADOS
# ============================================================

def buscar_ultimos_3_contratos():

    mercados = obtener_contratos_cerrados()

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

        if cierre < ahora:

            mercado["_close"] = cierre

            candidatos.append(
                mercado
            )

    candidatos.sort(
        key=lambda x: x["_close"],
        reverse=True
    )

    return candidatos[
        :NUM_CONTRATOS_HISTORICOS
    ]


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


def buscar_targets_recursivo(objeto):

    encontrados = []

    if isinstance(objeto, dict):

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

                numero = convertir_numero_precio(
                    valor
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

    elif isinstance(objeto, list):

        for elemento in objeto:

            encontrados.extend(
                buscar_targets_recursivo(
                    elemento
                )
            )

    return encontrados


def buscar_target_en_texto(mercado):

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
# EXPIRATION VALUE
# ============================================================

def obtener_expiration_value(
    mercado
):

    for campo in (
        "expiration_value",
        "result",
        "settlement_value",
        "settlement_price"
    ):

        valor = mercado.get(
            campo
        )

        if valor not in (
            None,
            "",
            "null"
        ):

            try:

                return float(
                    str(valor).replace(
                        ",",
                        ""
                    )
                )

            except Exception:
                pass

    return None


# ============================================================
# DETERMINAR RESULTADO REAL
# ============================================================

def determinar_resultado_kalshi(
    mercado
):

    target = obtener_target(
        mercado
    )

    expiration = (
        obtener_expiration_value(
            mercado
        )
    )

    if target is None:
        return None

    if expiration is None:
        return None

    if expiration > target:

        return (
            "UP",
            target,
            expiration
        )

    if expiration < target:

        return (
            "DOWN",
            target,
            expiration
        )

    return (
        "TIE",
        target,
        expiration
    )


# ============================================================
# BTC COINBASE
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
            "limit": 120
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

    return df


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
        "https://api.binance.us/api/v3/ticker/price",
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
# BTC
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

    df = df.tail(120).copy()

    precio, fuente_precio = (
        obtener_precio_btc()
    )

    if len(df) > 0:

        df.loc[
            df.index[-1],
            "Close"
        ] = precio

    return (
        df,
        precio,
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
# OBTENER DATOS BTC DEL CONTRATO ANTERIOR
# ============================================================

def obtener_btc_periodo(
    inicio,
    cierre,
    df_actual
):

    if inicio is None:
        return df_actual.tail(15).copy()

    if cierre is None:
        cierre = inicio + timedelta(
            minutes=15
        )

    datos = df_actual.copy()

    datos = datos[
        (
            datos["time"] >= inicio
        )
        &
        (
            datos["time"] <= cierre
        )
    ].copy()

    if len(datos) < 5:

        datos = df_actual.tail(
            VENTANA_BTC_MINUTOS
        ).copy()

    return datos


# ============================================================
# ANALIZAR LOS 3 CONTRATOS ANTERIORES
# ============================================================

def analizar_historial_kalshi(
    contratos
):

    resultados = []

    up = 0
    down = 0
    tie = 0

    for contrato in contratos:

        ticker = contrato.get(
            "ticker"
        )

        resultado = (
            determinar_resultado_kalshi(
                contrato
            )
        )

        if resultado is None:
            continue

        direccion, target, expiration = (
            resultado
        )

        if direccion == "UP":
            up += 1

        elif direccion == "DOWN":
            down += 1

        else:
            tie += 1

        resultados.append({
            "ticker": ticker,
            "resultado": direccion,
            "target": target,
            "expiration": expiration
        })

    return {
        "resultados": resultados,
        "up": up,
        "down": down,
        "tie": tie,
        "total": len(resultados)
    }


# ============================================================
# PREDICCIÓN INTELIGENTE
# ============================================================

def generar_prediccion(
    df,
    contratos_anteriores
):

    df = calcular_indicadores(
        df
    )

    if len(df) < 5:

        return (
            "⚪ NO APOSTAR",
            50,
            [
                "No hay suficientes datos BTC."
            ],
            0,
            None,
            {}
        )

    ultimo = df.iloc[-1]

    precio = float(
        ultimo["Close"]
    )

    score = 0

    razones = []

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    ema9 = float(
        ultimo["EMA9"]
    )

    ema21 = float(
        ultimo["EMA21"]
    )

    ema50 = float(
        ultimo["EMA50"]
    )

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

    if ema21 > ema50:

        score += 10

        razones.append(
            "EMA21 > EMA50: estructura alcista."
        )

    else:

        score -= 10

        razones.append(
            "EMA21 < EMA50: estructura bajista."
        )

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    macd = float(
        ultimo["MACD"]
    )

    signal = float(
        ultimo["MACD_SIGNAL"]
    )

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

    if macd > signal:

        score += 8

        razones.append(
            "MACD por encima de señal."
        )

    else:

        score -= 8

        razones.append(
            "MACD por debajo de señal."
        )

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    momentum_data = [
        (
            "1m",
            ultimo["Momentum1"],
            5
        ),
        (
            "3m",
            ultimo["Momentum3"],
            7
        ),
        (
            "5m",
            ultimo["Momentum5"],
            8
        ),
        (
            "10m",
            ultimo["Momentum10"],
            10
        )
    ]

    for nombre, valor, peso in momentum_data:

        if pd.isna(valor):
            continue

        valor = float(valor)

        if valor > 0:

            score += peso

            razones.append(
                f"Momentum {nombre} "
                f"positivo ({valor:+.3f}%)."
            )

        elif valor < 0:

            score -= peso

            razones.append(
                f"Momentum {nombre} "
                f"negativo ({valor:.3f}%)."
            )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    rsi = ultimo["RSI"]

    if pd.notna(rsi):

        rsi = float(rsi)

        if rsi >= 50:

            score += 5

            razones.append(
                f"RSI {rsi:.1f}: presión alcista."
            )

        else:

            score -= 5

            razones.append(
                f"RSI {rsi:.1f}: presión bajista."
            )

    # --------------------------------------------------------
    # ÚLTIMOS 3 CONTRATOS KALSHI
    # --------------------------------------------------------

    historial_kalshi = (
        analizar_historial_kalshi(
            contratos_anteriores
        )
    )

    up = historial_kalshi["up"]
    down = historial_kalshi["down"]
    total = historial_kalshi["total"]

    if total > 0:

        # El historial de Kalshi pesa bastante,
        # pero no domina completamente al BTC.
        if up > down:

            diferencia = up - down

            peso = min(
                18,
                diferencia * 7
            )

            score += peso

            razones.append(
                f"Kalshi últimos {total} "
                f"contratos: {up} UP vs "
                f"{down} DOWN."
            )

            razones.append(
                f"Historial Kalshi favorece UP "
                f"(+{peso} puntos)."
            )

        elif down > up:

            diferencia = down - up

            peso = min(
                18,
                diferencia * 7
            )

            score -= peso

            razones.append(
                f"Kalshi últimos {total} "
                f"contratos: {up} UP vs "
                f"{down} DOWN."
            )

            razones.append(
                f"Historial Kalshi favorece DOWN "
                f"(-{peso} puntos)."
            )

        else:

            razones.append(
                f"Kalshi últimos {total} "
                f"contratos: equilibrio UP/DOWN."
            )

    else:

        razones.append(
            "No se pudieron resolver todavía "
            "los últimos contratos de Kalshi."
        )

    # --------------------------------------------------------
    # CONTINUIDAD DE DIRECCIÓN
    # --------------------------------------------------------

    resultados = (
        historial_kalshi["resultados"]
    )

    if resultados:

        ultimo_resultado = (
            resultados[0]["resultado"]
        )

        if ultimo_resultado == "UP":

            score += 4

            razones.append(
                "El contrato Kalshi más reciente "
                "terminó UP."
            )

        elif ultimo_resultado == "DOWN":

            score -= 4

            razones.append(
                "El contrato Kalshi más reciente "
                "terminó DOWN."
            )

    # --------------------------------------------------------
    # VOLATILIDAD
    # --------------------------------------------------------

    volatilidad = ultimo[
        "Volatilidad"
    ]

    if pd.notna(volatilidad):

        razones.append(
            "Volatilidad BTC 15m: "
            f"{float(volatilidad):.4f}%."
        )

    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    if score >= 15:

        prediccion = "🟢 ARRIBA"

    elif score <= -15:

        prediccion = "🔴 ABAJO"

    else:

        prediccion = "⚪ NO APOSTAR"

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
                (
                    fuerza *
                    0.55
                )
            )
        )

        confianza = max(
            50,
            min(
                94,
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
        precio,
        historial_kalshi
    )


# ============================================================
# BUSCAR REGISTRO POR CONTRATO PREDICHO
# ============================================================

def buscar_registro_por_predicho(
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
# BUSCAR SI YA EXISTE PREDICCIÓN
# ============================================================

def ya_existe_prediccion(
    ticker_actual
):

    for registro in (
        st.session_state.historial
    ):

        if registro.get(
            "Contrato predicho"
        ) == ticker_actual:

            return registro

    return None


# ============================================================
# CREAR PREDICCIÓN PARA EL CONTRATO ACTUAL
# ============================================================

def crear_prediccion_para_actual(
    contrato_actual,
    btc_df,
    contratos_anteriores
):

    ticker_actual = contrato_actual.get(
        "ticker"
    )

    if not ticker_actual:
        return None

    # --------------------------------------------------------
    # MUY IMPORTANTE:
    # Si ya existe, NO vuelve a predecir.
    # Esto permite cerrar la app y regresar.
    # --------------------------------------------------------

    existente = ya_existe_prediccion(
        ticker_actual
    )

    if existente:

        return existente

    inicio_actual = inicio_de_mercado(
        contrato_actual
    )

    cierre_actual = cierre_de_mercado(
        contrato_actual
    )

    # --------------------------------------------------------
    # Usar los 15 minutos anteriores al contrato actual
    # --------------------------------------------------------

    datos_btc = obtener_btc_periodo(
        inicio_actual - timedelta(
            minutes=VENTANA_BTC_MINUTOS
        )
        if inicio_actual
        else None,
        inicio_actual
        if inicio_actual
        else None,
        btc_df
    )

    if len(datos_btc) < 5:

        datos_btc = btc_df.tail(
            VENTANA_BTC_MINUTOS
        ).copy()

    (
        prediccion,
        confianza,
        razones,
        score,
        precio,
        historial_kalshi
    ) = generar_prediccion(
        datos_btc,
        contratos_anteriores
    )

    # --------------------------------------------------------
    # Target del contrato actual
    # --------------------------------------------------------

    target_actual = obtener_target(
        contrato_actual
    )

    # --------------------------------------------------------
    # Datos de los últimos 3 contratos
    # --------------------------------------------------------

    resumen_historico = []

    for resultado in (
        historial_kalshi["resultados"]
    ):

        resumen_historico.append({
            "Ticker": resultado[
                "ticker"
            ],
            "Resultado": resultado[
                "resultado"
            ],
            "Target": resultado[
                "target"
            ],
            "Expiration": resultado[
                "expiration"
            ]
        })

    # --------------------------------------------------------
    # REGISTRO
    # --------------------------------------------------------

    registro = {

        "Contrato predicho":
            ticker_actual,

        "Contrato base":
            (
                contratos_anteriores[0].get(
                    "ticker"
                )
                if contratos_anteriores
                else None
            ),

        "Target contrato predicho":
            (
                round(
                    float(target_actual),
                    2
                )
                if target_actual is not None
                else None
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

        "Resultado":
            "⏳ PENDIENTE",

        "Resultado Kalshi":
            "PENDIENTE",

        "Expiration Value":
            None,

        "Análisis":
            razones,

        "Últimos 3 contratos Kalshi":
            resumen_historico,

        "Momento predicción":
            datetime.now(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S"
            ),

        "Inicio contrato predicho":
            (
                inicio_actual
                .astimezone(LOCAL_TZ)
                .strftime(
                    "%Y-%m-%d %I:%M:%S"
                )
                if inicio_actual
                else None
            ),

        "Cierre contrato predicho":
            (
                cierre_actual
                .astimezone(LOCAL_TZ)
                .strftime(
                    "%Y-%m-%d %I:%M:%S"
                )
                if cierre_actual
                else None
            ),

        "Estado predicción":
            "PREDICCIÓN GUARDADA"
    }

    st.session_state.historial.append(
        registro
    )

    # --------------------------------------------------------
    # GUARDAR INMEDIATAMENTE
    # --------------------------------------------------------

    guardar_historial(
        st.session_state.historial
    )

    return registro


# ============================================================
# ACTUALIZAR RESULTADOS
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

        cierre = cierre_de_mercado(
            mercado
        )

        if cierre:

            ahora = datetime.now(
                timezone.utc
            )

            # No resolver antes del cierre.
            if ahora < cierre:

                continue

        resultado_real = (
            determinar_resultado_kalshi(
                mercado
            )
        )

        if resultado_real is None:
            continue

        (
            resultado_kalshi,
            target,
            expiration
        ) = resultado_real

        registro[
            "Target contrato predicho"
        ] = round(
            float(target),
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
        ] = resultado_kalshi

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
            prediccion ==
            "⚪ NO APOSTAR"
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
# INTENTAR RECUPERAR PREDICCIONES ANTIGUAS
# ============================================================

def recuperar_y_resolver_historial():

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

        cierre = cierre_de_mercado(
            mercado
        )

        if cierre is None:
            continue

        ahora = datetime.now(
            timezone.utc
        )

        if ahora < cierre:
            continue

        resultado_real = (
            determinar_resultado_kalshi(
                mercado
            )
        )

        if resultado_real is None:
            continue

        (
            direccion,
            target,
            expiration
        ) = resultado_real

        registro[
            "Target contrato predicho"
        ] = round(
            float(target),
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
        ] = direccion

        pred = registro.get(
            "Predicción"
        )

        if (
            pred == "🟢 ARRIBA"
            and direccion == "UP"
        ):

            registro[
                "Resultado"
            ] = "✅ ACIERTO"

        elif (
            pred == "🔴 ABAJO"
            and direccion == "DOWN"
        ):

            registro[
                "Resultado"
            ] = "✅ ACIERTO"

        elif direccion == "TIE":

            registro[
                "Resultado"
            ] = "⚪ EMPATE"

        elif (
            pred == "⚪ NO APOSTAR"
        ):

            registro[
                "Resultado"
            ] = "⚪ NO APOSTAR"

        else:

            registro[
                "Resultado"
            ] = "❌ FALLÓ"

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


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Predicción automática basada en BTC "
    "y en los últimos 3 contratos de Kalshi."
)


# ============================================================
# CREDENCIALES
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
    f"☁️ Historial persistente: "
    f"{GITHUB_USERNAME}/{GITHUB_REPO}"
)


# ============================================================
# RECUPERAR RESULTADOS ANTERIORES
# ============================================================

try:

    recuperar_y_resolver_historial()

except Exception:
    pass


# ============================================================
# BUSCAR CONTRATO ACTUAL
# ============================================================

try:

    actual = buscar_contrato_actual()

except Exception as error:

    actual = None

    st.error(
        f"❌ Error consultando Kalshi: {error}"
    )


# ============================================================
# OBTENER BTC
# ============================================================

try:

    btc, precio, fuente = obtener_btc()

except Exception as error:

    st.error(
        f"❌ Error obteniendo BTC: {error}"
    )

    time.sleep(
        REFRESH_SECONDS
    )

    st.rerun()


# ============================================================
# SI EXISTE CONTRATO ACTUAL
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

    inicio_actual = (
        inicio_de_mercado(
            actual
        )
    )

    target_actual = obtener_target(
        actual
    )

    ahora = datetime.now(
        timezone.utc
    )

    if close_actual:

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
    # CONTRATO
    # ========================================================

    st.subheader(
        "🎯 Contrato actual de Kalshi"
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


    # ========================================================
    # BTC / TARGET
    # ========================================================

    col1, col2 = st.columns(2)

    col1.metric(
        "₿ BTC",
        f"${precio:,.2f}"
    )

    if target_actual is not None:

        col2.metric(
            "🎯 Target",
            f"${target_actual:,.2f}"
        )

    else:

        col2.metric(
            "🎯 Target",
            "No disponible"
        )

    st.caption(
        f"Fuente BTC: {fuente}"
    )


    # ========================================================
    # DIFERENCIA
    # ========================================================

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
                "BTC está exactamente en el Target."
            )


    # ========================================================
    # TEMPORIZADOR
    # ========================================================

    st.subheader(
        "⏳ Tiempo restante"
    )

    st.info(
        f"⏱️ {minutos:02d}:{segundos:02d}"
    )

    if close_actual:

        st.write(
            "Cierre:",
            close_actual
            .astimezone(LOCAL_TZ)
            .strftime(
                "%I:%M:%S %p"
            )
        )


    # ========================================================
    # ÚLTIMOS 3 CONTRATOS
    # ========================================================

    st.divider()

    st.subheader(
        "📊 Últimos 3 contratos de Kalshi"
    )

    try:

        contratos_anteriores = (
            buscar_ultimos_3_contratos()
        )

    except Exception:

        contratos_anteriores = []

    if contratos_anteriores:

        filas_hist = []

        for contrato in (
            contratos_anteriores
        ):

            ticker = contrato.get(
                "ticker"
            )

            resultado = (
                determinar_resultado_kalshi(
                    contrato
                )
            )

            if resultado:

                direccion, target, expiration = (
                    resultado
                )

                filas_hist.append({
                    "Contrato": ticker,
                    "Resultado": direccion,
                    "Target": (
                        f"${target:,.2f}"
                    ),
                    "Expiration": (
                        f"${expiration:,.2f}"
                    )
                })

            else:

                filas_hist.append({
                    "Contrato": ticker,
                    "Resultado": "PENDIENTE",
                    "Target": "-",
                    "Expiration": "-"
                })

        st.dataframe(
            pd.DataFrame(
                filas_hist
            ),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.warning(
            "No se pudieron obtener todavía "
            "los contratos anteriores."
        )


    # ========================================================
    # GENERAR PREDICCIÓN
    #
    # IMPORTANTE:
    #
    # NO depende de los últimos 2 minutos.
    #
    # Si la app estuvo cerrada, al regresar:
    #
    # 1. encuentra el contrato actual
    # 2. encuentra los 3 anteriores
    # 3. analiza BTC
    # 4. crea la predicción
    # 5. la guarda en GitHub
    #
    # ========================================================

    try:

        registro_actual = (
            crear_prediccion_para_actual(
                actual,
                btc,
                contratos_anteriores
            )
        )

    except Exception as error:

        registro_actual = None

        st.error(
            f"❌ Error creando predicción: "
            f"{error}"
        )


    # ========================================================
    # MOSTRAR PREDICCIÓN
    # ========================================================

    st.divider()

    st.subheader(
        "🔮 Predicción del contrato actual"
    )

    registro_actual = (
        ya_existe_prediccion(
            ticker_actual
        )
    )

    if registro_actual:

        pred = registro_actual.get(
            "Predicción"
        )

        confianza = registro_actual.get(
            "Confianza"
        )

        if pred == "🟢 ARRIBA":

            st.success(
                "🟢 PREDICCIÓN: ARRIBA"
            )

        elif pred == "🔴 ABAJO":

            st.error(
                "🔴 PREDICCIÓN: ABAJO"
            )

        else:

            st.warning(
                "⚪ PREDICCIÓN: NO APOSTAR"
            )

        st.metric(
            "Confianza",
            confianza
        )

        st.write(
            f"**Contrato:** "
            f"`{ticker_actual}`"
        )

        st.write(
            f"**Precio BTC utilizado:** "
            f"${float(registro_actual.get('Precio BTC predicción', 0)):,.2f}"
        )

        st.write(
            f"**Score:** "
            f"{registro_actual.get('Score'):+d}"
        )

        target_pred = (
            registro_actual.get(
                "Target contrato predicho"
            )
        )

        if target_pred is not None:

            st.write(
                f"**Target:** "
                f"${float(target_pred):,.2f}"
            )

        st.success(
            "☁️ Esta predicción está guardada "
            "en GitHub y no se perderá aunque "
            "cierres la aplicación."
        )

        st.subheader(
            "🧠 Análisis utilizado"
        )

        for razon in (
            registro_actual.get(
                "Análisis",
                []
            )
        ):

            st.write(
                "•",
                razon
            )

    else:

        st.warning(
            "⏳ Todavía no se pudo crear "
            "la predicción."
        )


# ============================================================
# SI NO HAY CONTRATO ACTUAL
# ============================================================

else:

    st.warning(
        "⏳ Kalshi no muestra actualmente "
        "un contrato BTC 15M abierto."
    )

    st.info(
        "La aplicación continuará buscando "
        "el siguiente contrato automáticamente."
    )


# ============================================================
# RESULTADOS
# ============================================================

try:

    actualizar_resultados()

except Exception:
    pass


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
        f"**Contrato:** "
        f"`{ultima.get('Contrato predicho')}`"
    )

    st.write(
        f"**Predicción:** "
        f"{ultima.get('Predicción')}"
    )

    st.write(
        f"**Confianza:** "
        f"{ultima.get('Confianza')}"
    )

    st.write(
        f"**Estado:** "
        f"{ultima.get('Resultado')}"
    )

    if ultima.get(
        "Resultado Kalshi"
    ):

        st.write(
            f"**Resultado real Kalshi:** "
            f"`{ultima.get('Resultado Kalshi')}`"
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


# ============================================================
# GRÁFICO BTC
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
# HISTORIAL COMPLETO
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

    columnas = [
        "Contrato predicho",
        "Target contrato predicho",
        "Predicción",
        "Confianza",
        "Score",
        "Precio BTC predicción",
        "Expiration Value",
        "Resultado Kalshi",
        "Resultado",
        "Estado predicción",
        "Contrato base",
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

    st.dataframe(
        tabla,
        use_container_width=True,
        hide_index=True
    )


    # ========================================================
    # ESTADÍSTICAS
    # ========================================================

    aciertos = sum(
        x.get(
            "Resultado"
        ) == "✅ ACIERTO"
        for x in historial
    )

    fallos = sum(
        x.get(
            "Resultado"
        ) == "❌ FALLÓ"
        for x in historial
    )

    pendientes = sum(
        x.get(
            "Resultado"
        ) == "⏳ PENDIENTE"
        for x in historial
    )

    empates = sum(
        x.get(
            "Resultado"
        ) == "⚪ EMPATE"
        for x in historial
    )

    no_apostar = sum(
        x.get(
            "Resultado"
        ) == "⚪ NO APOSTAR"
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
        "Todavía no hay predicciones."
    )


# ============================================================
# ESTADO GITHUB
# ============================================================

if st.session_state.github_error:

    st.warning(
        "⚠️ GitHub no pudo sincronizar "
        "en este momento. La aplicación "
        "mantiene una copia local y "
        "volverá a intentar sincronizar."
    )

else:

    st.success(
        "☁️ Historial sincronizado correctamente "
        "con GitHub."
    )


# ============================================================
# EXPLICACIÓN
# ============================================================

st.divider()

st.caption(
    "FUNCIONAMIENTO: la aplicación identifica "
    "el contrato BTC 15M actualmente vigente. "
    "Para ese contrato obtiene los 15 minutos "
    "anteriores de movimiento de BTC y analiza "
    "EMA, MACD, RSI, momentum y volatilidad. "
    "Además consulta los últimos 3 contratos "
    "cerrados de Kalshi y utiliza sus resultados "
    "reales UP/DOWN como parte del análisis. "
    "La predicción se guarda inmediatamente "
    "en GitHub. Si cierras Safari, Chrome o "
    "la aplicación durante el ciclo, al volver "
    "la aplicación recupera el historial desde "
    "GitHub y continúa sin comenzar desde cero. "
    "Cuando termina el contrato, obtiene el "
    "Target y Expiration Value reales de Kalshi "
    "y determina automáticamente si la predicción "
    "fue ACIERTO o FALLÓ."
)


# ============================================================
# REFRESH AUTOMÁTICO
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
