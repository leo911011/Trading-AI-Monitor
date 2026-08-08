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

PREDICCION_SEGUNDOS = 120


# ============================================================
# GITHUB
# ============================================================

GITHUB_API = "https://api.github.com"

GITHUB_DEFAULT_BRANCH = "main"


def cargar_config_github():

    username = None
    token = None
    repo = None
    branch = None

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
            or GITHUB_DEFAULT_BRANCH
        )

    except Exception:

        pass

    return (
        str(username).strip() if username else None,
        str(token).strip() if token else None,
        str(repo).strip() if repo else None,
        str(branch).strip() if branch else GITHUB_DEFAULT_BRANCH
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
        "X-GitHub-Api-Version": "2026-03-10",
        "Content-Type": "application/json"
    }


# ============================================================
# LEER HISTORIAL DESDE GITHUB
# ============================================================

def cargar_historial_github():

    if not GITHUB_USERNAME:

        raise Exception(
            "Falta GITHUB_USERNAME en Streamlit Secrets."
        )

    if not GITHUB_REPO:

        raise Exception(
            "Falta GITHUB_REPO en Streamlit Secrets."
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
            "GitHub no pudo leer el historial. "
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()

    contenido = data.get("content")

    if not contenido:

        return []

    contenido = contenido.replace("\n", "")

    try:

        texto = base64.b64decode(
            contenido
        ).decode("utf-8")

        historial = json.loads(texto)

    except Exception as error:

        raise Exception(
            f"No se pudo interpretar "
            f"{HISTORIAL_FILE}: {error}"
        )

    if isinstance(historial, list):

        return historial

    return []


# ============================================================
# OBTENER SHA
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
            "No se pudo obtener el SHA del historial. "
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json().get("sha")


# ============================================================
# GUARDAR HISTORIAL EN GITHUB
# ============================================================

def guardar_historial_github(historial):

    if not GITHUB_USERNAME:
        raise Exception("Falta GITHUB_USERNAME.")

    if not GITHUB_TOKEN:
        raise Exception("Falta GITHUB_TOKEN.")

    if not GITHUB_REPO:
        raise Exception("Falta GITHUB_REPO.")

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
        "message": "Actualizar historial Kalshi BTC",
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
            "GitHub no pudo guardar el historial. "
            f"HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    return True


# ============================================================
# CARGAR HISTORIAL
# ============================================================

def cargar_historial():

    try:

        return cargar_historial_github()

    except Exception:

        if os.path.exists(HISTORIAL_FILE):

            try:

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

        guardar_historial_github(
            historial
        )

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

        return True

    except Exception as error:

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

        raise error


# ============================================================
# CREDENCIALES KALSHI
# ============================================================

def cargar_credenciales():

    try:

        key_id = st.secrets[
            "KALSHI_API_KEY_ID"
        ]

        private_key = st.secrets[
            "KALSHI_PRIVATE_KEY"
        ]

        return (
            str(key_id),
            str(private_key)
        )

    except Exception:

        return None, None


API_KEY_ID, PRIVATE_KEY = (
    cargar_credenciales()
)


# ============================================================
# CLAVE PRIVADA
# ============================================================

def cargar_clave_privada():

    if not PRIVATE_KEY:

        raise Exception(
            "Falta KALSHI_PRIVATE_KEY "
            "en Streamlit Secrets."
        )

    try:

        return serialization.load_pem_private_key(
            PRIVATE_KEY.strip().encode("utf-8"),
            password=None
        )

    except Exception as error:

        raise Exception(
            "La KALSHI_PRIVATE_KEY "
            "no tiene formato PEM válido."
        ) from error


# ============================================================
# FIRMA KALSHI
# ============================================================

def crear_firma(
    timestamp,
    method,
    path
):

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
            f"Kalshi HTTP "
            f"{response.status_code}: "
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

            "series_ticker":
                SERIES,

            "status":
                status,

            "limit":
                limit
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

        "/trade-api/v2/markets/"
        + ticker
    )

    return data.get(
        "market",
        {}
    )


# ============================================================
# CONTRATO ACTUAL
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
# BUSCAR SIGUIENTE CONTRATO
# ============================================================

def buscar_siguiente_contrato(
    ticker_actual,
    cierre_actual
):

    if cierre_actual is None:
        return None

    candidatos = []

    # --------------------------------------------------------
    # Primero mercados abiertos
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

        if ticker == ticker_actual:
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

        if cierre > cierre_actual:

            candidatos.append(
                (
                    cierre,
                    ticker,
                    mercado
                )
            )

    # --------------------------------------------------------
    # Después cerrados
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

        if ticker == ticker_actual:
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

        if cierre > cierre_actual:

            candidatos.append(
                (
                    cierre,
                    ticker,
                    mercado
                )
            )

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda x: x[0]
    )

    return candidatos[0][2]


# ============================================================
# CONVERTIR PRECIO
# ============================================================

def convertir_numero_precio(valor):

    if valor is None:
        return None

    try:

        if isinstance(
            valor,
            str
        ):

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
# BUSCAR TARGET RECURSIVO
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

                numero = (
                    convertir_numero_precio(
                        valor
                    )
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

                numero = (
                    convertir_numero_precio(
                        valor
                    )
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
# TARGET ROBUSTO
# ============================================================

def obtener_target(mercado):

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

            detalle = (
                obtener_contrato(
                    ticker
                )
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

    raise Exception(
        "No pude encontrar el Target "
        f"del contrato "
        f"{ticker if ticker else ''}."
    )


# ============================================================
# COINBASE
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

    if not isinstance(data, list):

        raise Exception(
            "Coinbase no devolvió "
            "velas válidas."
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
            "Coinbase no devolvió "
            "datos BTC."
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
# BINANCE.US
# ============================================================

def obtener_btc_binance():

    url = (
        "https://api.binance.us/"
        "api/v3/klines"
    )

    response = requests.get(

        url,

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
            "Binance no devolvió "
            "datos válidos."
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
# PRECIO BTC
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
                "symbol":
                    "BTCUSDT"
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
        "No pude obtener el precio BTC "
        "en tiempo real."
    )


# ============================================================
# BTC COMPLETO
# ============================================================

def obtener_btc():

    try:

        df = obtener_btc_coinbase()

        fuente_historico = "Coinbase"

    except Exception:

        df = obtener_btc_binance()

        fuente_historico = "Binance.US"

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

    if len(df) > 0:

        df.loc[
            df.index[-1],
            "Close"
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
# PREDICCIÓN
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
            "BTC está prácticamente "
            "en el Target."
        )

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

        score += 6

        razones.append(
            "MACD por encima de su señal."
        )

    else:

        score -= 6

        razones.append(
            "MACD por debajo de su señal."
        )

    if pd.notna(momentum1):

        momentum1 = float(momentum1)

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

    if pd.notna(momentum3):

        momentum3 = float(momentum3)

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

    if pd.notna(momentum5):

        momentum5 = float(momentum5)

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

    if pd.notna(momentum10):

        momentum10 = float(momentum10)

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

    if pd.notna(rsi):

        rsi = float(rsi)

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

    if pd.notna(volatilidad):

        volatilidad = float(
            volatilidad
        )

        razones.append(
            f"Volatilidad 15m: "
            f"{volatilidad:.4f}%."
        )

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
# BUSCAR REGISTRO POR CONTRATO BASE
# ============================================================

def buscar_registro_por_base(
    ticker_base
):

    historial = (
        st.session_state.historial
    )

    for registro in reversed(historial):

        if registro.get(
            "Contrato base"
        ) == ticker_base:

            return registro

    return None


# ============================================================
# BUSCAR REGISTRO POR CONTRATO PREDICHO
# ============================================================

def buscar_registro_por_predicho(
    ticker_predicho
):

    historial = (
        st.session_state.historial
    )

    for registro in reversed(historial):

        if registro.get(
            "Contrato predicho"
        ) == ticker_predicho:

            return registro

    return None


# ============================================================
# GUARDAR PREDICCIÓN COMPLETA
# ============================================================

def guardar_prediccion_completa(

    ticker_base,

    mercado_predicho,

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

    existente = (
        buscar_registro_por_base(
            ticker_base
        )
    )

    if existente is not None:

        return False

    ticker_predicho = (
        mercado_predicho.get(
            "ticker"
        )
    )

    if not ticker_predicho:

        raise Exception(
            "No se pudo identificar "
            "el ticker del siguiente contrato."
        )

    # --------------------------------------------------------
    # Obtener target del contrato que realmente predecimos
    # --------------------------------------------------------

    try:

        target_predicho = (
            obtener_target(
                mercado_predicho
            )
        )

    except Exception:

        target_predicho = None

    cierre_predicho = convertir_fecha(
        mercado_predicho.get(
            "close_time"
        )
    )

    if cierre_predicho is None:

        cierre_predicho = convertir_fecha(
            mercado_predicho.get(
                "expiration_time"
            )
        )

    registro = {

        # ----------------------------------------------------
        # IDENTIFICACIÓN
        # ----------------------------------------------------

        "Contrato base":
            ticker_base,

        "Contrato predicho":
            ticker_predicho,

        # ----------------------------------------------------
        # DATOS UTILIZADOS PARA LA PREDICCIÓN
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # CONTRATO QUE SE ESTÁ PREDICIENDO
        # ----------------------------------------------------

        "Target contrato predicho":
            (
                round(
                    float(target_predicho),
                    2
                )
                if target_predicho is not None
                else None
            ),

        "Cierre contrato predicho":
            (
                cierre_predicho
                .astimezone(
                    LOCAL_TZ
                )
                .strftime(
                    "%Y-%m-%d %I:%M:%S %p"
                )
                if cierre_predicho
                else None
            ),

        # ----------------------------------------------------
        # CIERRE DEL CONTRATO BASE
        # ----------------------------------------------------

        "Cierre contrato base":
            close_time
            .astimezone(
                LOCAL_TZ
            )
            .strftime(
                "%Y-%m-%d %I:%M:%S %p"
            ),

        # ----------------------------------------------------
        # RESULTADO
        # ----------------------------------------------------

        "Expiration Value":
            None,

        "Resultado Kalshi":
            "PENDIENTE",

        "Resultado":
            "⏳ PENDIENTE",

        # ----------------------------------------------------
        # ANÁLISIS
        # ----------------------------------------------------

        "Análisis":
            razones,

        "Momento predicción":
            datetime.now(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S"
            ),

        "Actualizado":
            None
    }

    historial.append(
        registro
    )

    guardar_historial(
        historial
    )

    return True


# ============================================================
# OBTENER RESULTADO DEL CONTRATO PREDICHO
# ============================================================

def obtener_resultado_contrato(
    ticker_predicho,
    target_predicho
):

    try:

        mercado = obtener_contrato(
            ticker_predicho
        )

    except Exception:

        return (
            None,
            None,
            mercado if "mercado" in locals()
            else None
        )

    # --------------------------------------------------------
    # Expiration Value
    # --------------------------------------------------------

    expiration = mercado.get(
        "expiration_value"
    )

    # Algunos endpoints pueden devolverlo
    # dentro de settlement/resultados.
    if expiration in (
        None,
        "",
        "null"
    ):

        posibles = [
            mercado.get("settlement_value"),
            mercado.get("result"),
            mercado.get("final_value"),
            mercado.get("expiration_price")
        ]

        for valor in posibles:

            if valor not in (
                None,
                "",
                "null"
            ):

                expiration = valor

                break

    if expiration in (
        None,
        "",
        "null"
    ):

        return (
            None,
            None,
            mercado
        )

    try:

        expiration_num = float(
            expiration
        )

        target_num = float(
            target_predicho
        )

    except Exception:

        return (
            None,
            None,
            mercado
        )

    # --------------------------------------------------------
    # COMPARACIÓN REAL
    # --------------------------------------------------------

    if expiration_num > target_num:

        return (
            "UP",
            expiration_num,
            mercado
        )

    elif expiration_num < target_num:

        return (
            "DOWN",
            expiration_num,
            mercado
        )

    else:

        return (
            "TIE",
            expiration_num,
            mercado
        )


# ============================================================
# ACTUALIZAR UNA PREDICCIÓN
# ============================================================

def actualizar_registro_prediccion(
    registro
):

    ticker_predicho = registro.get(
        "Contrato predicho"
    )

    if not ticker_predicho:

        return False

    # --------------------------------------------------------
    # Target guardado originalmente
    # --------------------------------------------------------

    target_predicho = registro.get(
        "Target contrato predicho"
    )

    # --------------------------------------------------------
    # Si no estaba guardado, obtenerlo de Kalshi
    # --------------------------------------------------------

    try:

        mercado = obtener_contrato(
            ticker_predicho
        )

    except Exception:

        return False

    if target_predicho is None:

        try:

            target_predicho = obtener_target(
                mercado
            )

            registro[
                "Target contrato predicho"
            ] = round(
                float(target_predicho),
                2
            )

        except Exception:

            return False

    # --------------------------------------------------------
    # Resultado
    # --------------------------------------------------------

    try:

        (
            resultado_real,
            expiration,
            mercado
        ) = obtener_resultado_contrato(

            ticker_predicho,

            target_predicho
        )

    except Exception:

        return False

    # --------------------------------------------------------
    # Todavía no terminó
    # --------------------------------------------------------

    if resultado_real is None:

        return False

    # --------------------------------------------------------
    # Guardar cierre real
    # --------------------------------------------------------

    registro[
        "Expiration Value"
    ] = round(
        float(expiration),
        2
    )

    registro[
        "Resultado Kalshi"
    ] = resultado_real

    prediccion = registro.get(
        "Predicción"
    )

    # --------------------------------------------------------
    # COMPARAR PREDICCIÓN VS RESULTADO REAL
    # --------------------------------------------------------

    if resultado_real == "TIE":

        registro[
            "Resultado"
        ] = "⚪ EMPATE"

    elif (
        prediccion == "🟢 ARRIBA"
        and
        resultado_real == "UP"
    ):

        registro[
            "Resultado"
        ] = "✅ ACIERTO"

    elif (
        prediccion == "🔴 ABAJO"
        and
        resultado_real == "DOWN"
    ):

        registro[
            "Resultado"
        ] = "✅ ACIERTO"

    elif (
        prediccion == "⚪ NO APOSTAR"
    ):

        registro[
            "Resultado"
        ] = "⚪ NO APOSTAR"

    else:

        registro[
            "Resultado"
        ] = "❌ FALLÓ"

    registro[
        "Actualizado"
    ] = datetime.now(
        LOCAL_TZ
    ).strftime(
        "%Y-%m-%d %I:%M:%S"
    )

    return True


# ============================================================
# ACTUALIZAR TODAS LAS PREDICCIONES PENDIENTES
# ============================================================

def actualizar_pendientes():

    historial = (
        st.session_state.historial
    )

    cambio = False

    for registro in historial:

        if registro.get(
            "Resultado"
        ) not in (
            "⏳ PENDIENTE",
            "PENDIENTE",
            None
        ):

            continue

        ticker_predicho = registro.get(
            "Contrato predicho"
        )

        if not ticker_predicho:

            continue

        # ----------------------------------------------------
        # Saber si ya pasó el cierre
        # ----------------------------------------------------

        cierre_texto = registro.get(
            "Cierre contrato predicho"
        )

        puede_revisar = True

        if cierre_texto:

            try:

                cierre = datetime.strptime(

                    cierre_texto,

                    "%Y-%m-%d %I:%M:%S %p"

                ).replace(

                    tzinfo=LOCAL_TZ

                ).astimezone(
                    timezone.utc
                )

                ahora = datetime.now(
                    timezone.utc
                )

                # Esperar hasta después del cierre
                # antes de intentar resolver.

                if ahora < cierre:

                    puede_revisar = False

            except Exception:

                pass

        if not puede_revisar:

            continue

        try:

            actualizado = (
                actualizar_registro_prediccion(
                    registro
                )
            )

            if actualizado:

                cambio = True

        except Exception:

            continue

    if cambio:

        guardar_historial(
            historial
        )

    return cambio


# ============================================================
# MIGRAR HISTORIAL ANTIGUO
# ============================================================

def migrar_historial_antiguo():

    historial = (
        st.session_state.historial
    )

    cambio = False

    for registro in historial:

        # ----------------------------------------------------
        # Agregar campos que no existían
        # ----------------------------------------------------

        if "Contrato predicho" not in registro:

            registro[
                "Contrato predicho"
            ] = None

            cambio = True

        if "Target contrato predicho" not in registro:

            registro[
                "Target contrato predicho"
            ] = None

            cambio = True

        if "Cierre contrato predicho" not in registro:

            registro[
                "Cierre contrato predicho"
            ] = None

            cambio = True

        if "Expiration Value" not in registro:

            registro[
                "Expiration Value"
            ] = None

            cambio = True

        if "Resultado Kalshi" not in registro:

            registro[
                "Resultado Kalshi"
            ] = "PENDIENTE"

            cambio = True

        if "Resultado" not in registro:

            registro[
                "Resultado"
            ] = "⏳ PENDIENTE"

            cambio = True

    if cambio:

        guardar_historial(
            historial
        )


# ============================================================
# ÚLTIMA PREDICCIÓN
# ============================================================

def obtener_ultima_prediccion():

    historial = (
        st.session_state.historial
    )

    if not historial:
        return None

    for registro in reversed(
        historial
    ):

        if registro.get(
            "Predicción"
        ):

            return registro

    return None


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
# MIGRAR DATOS ANTIGUOS
# ============================================================

try:

    migrar_historial_antiguo()

except Exception:

    pass


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Predicción automática del siguiente "
    "contrato BTC 15M de Kalshi."
)


# ============================================================
# CREDENCIALES KALSHI
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ No se encontraron las "
        "credenciales de Kalshi."
    )

    st.info(
        "Debes tener en Streamlit Secrets:"
    )

    st.code(
        "KALSHI_API_KEY_ID\n"
        "KALSHI_PRIVATE_KEY"
    )

    st.stop()


# ============================================================
# CREDENCIALES GITHUB
# ============================================================

if not GITHUB_USERNAME:

    st.error(
        "❌ Falta GITHUB_USERNAME "
        "en Streamlit Secrets."
    )

    st.stop()


if not GITHUB_TOKEN:

    st.error(
        "❌ Falta GITHUB_TOKEN "
        "en Streamlit Secrets."
    )

    st.stop()


if not GITHUB_REPO:

    st.error(
        "❌ Falta GITHUB_REPO."
    )

    st.stop()


# ============================================================
# GITHUB
# ============================================================

st.caption(
    f"☁️ Historial sincronizado con "
    f"GitHub: "
    f"{GITHUB_USERNAME}/"
    f"{GITHUB_REPO}"
)


# ============================================================
# ACTUALIZAR PREDICCIONES PENDIENTES
# ============================================================

try:

    actualizar_pendientes()

except Exception as error:

    st.warning(
        "⚠️ No se pudieron actualizar "
        f"algunas predicciones: {error}"
    )


# ============================================================
# BUSCAR CONTRATO ACTUAL
# ============================================================

try:

    actual = (
        buscar_mercado_actual()
    )

except Exception as error:

    actual = None

    st.error(
        f"❌ Error consultando Kalshi: "
        f"{error}"
    )


# ============================================================
# SIN CONTRATO
# ============================================================

if actual is None:

    st.warning(
        "⏳ Kalshi no está mostrando "
        "temporalmente un contrato "
        "BTC 15M abierto."
    )

    ultima = (
        obtener_ultima_prediccion()
    )

    if ultima:

        st.divider()

        st.subheader(
            "🔔 Última predicción guardada"
        )

        st.write(
            f"**Contrato analizado:** "
            f"`{ultima.get('Contrato base')}`"
        )

        st.write(
            f"**Contrato predicho:** "
            f"`{ultima.get('Contrato predicho')}`"
        )

        st.write(
            f"**Predicción:** "
            f"{ultima.get('Predicción')}"
        )

        st.write(
            f"**Estado:** "
            f"{ultima.get('Resultado')}"
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
# TARGET
# ============================================================

try:

    target_actual = obtener_target(
        actual
    )

except Exception:

    target_actual = None


# ============================================================
# CAMBIO DE CONTRATO
# ============================================================

if (
    st.session_state.ticker_actual
    != ticker_actual
):

    st.session_state.ticker_actual = (
        ticker_actual
    )


# ============================================================
# BTC
# ============================================================

try:

    btc, precio, fuente = (
        obtener_btc()
    )

    btc = calcular_indicadores(
        btc
    )

except Exception as error:

    st.error(
        f"❌ Error obteniendo BTC: "
        f"{error}"
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
# DIFERENCIA
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
            "BTC está exactamente "
            "en el Target."
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

elif segundos_restantes <= 120:

    st.warning(
        f"🟡 VENTANA DE PREDICCIÓN — "
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
# PREDICCIÓN
# ============================================================

st.divider()

st.subheader(
    "🔮 Predicción del SIGUIENTE contrato"
)


# ============================================================
# BUSCAR PREDICCIÓN EXISTENTE
# ============================================================

registro_actual = (
    buscar_registro_por_base(
        ticker_actual
    )
)


# ============================================================
# GENERAR PREDICCIÓN
# ============================================================

if (

    segundos_restantes
    <= PREDICCION_SEGUNDOS

    and

    segundos_restantes > 0

    and

    registro_actual is None

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

            # ------------------------------------------------
            # ENCONTRAR EL SIGUIENTE CONTRATO
            # ------------------------------------------------

            siguiente = (
                buscar_siguiente_contrato(
                    ticker_actual,
                    close_actual
                )
            )

            if siguiente is None:

                st.warning(
                    "⏳ Todavía no puedo "
                    "identificar el siguiente "
                    "contrato de Kalshi. "
                    "Esperando..."
                )

            else:

                guardada = (
                    guardar_prediccion_completa(

                        ticker_base=
                            ticker_actual,

                        mercado_predicho=
                            siguiente,

                        target_base=
                            target_actual,

                        prediccion=
                            prediccion,

                        confianza=
                            confianza,

                        precio=
                            precio,

                        close_time=
                            close_actual,

                        score=
                            score,

                        razones=
                            razones
                    )
                )

                if guardada:

                    st.success(
                        "🚨 PREDICCIÓN GENERADA "
                        "Y GUARDADA EN GITHUB"
                    )

                    registro_actual = (
                        buscar_registro_por_base(
                            ticker_actual
                        )
                    )

        except Exception as error:

            st.error(
                "❌ No se pudo generar "
                f"la predicción: {error}"
            )

    else:

        st.warning(
            "⚠️ No se puede generar "
            "la predicción porque "
            "no se obtuvo el Target."
        )


# ============================================================
# MOSTRAR PREDICCIÓN
# ============================================================

registro_actual = (
    buscar_registro_por_base(
        ticker_actual
    )
)

if registro_actual is not None:

    prediccion_guardada = (
        registro_actual.get(
            "Predicción"
        )
    )

    confianza_guardada = (
        registro_actual.get(
            "Confianza"
        )
    )

    contrato_predicho = (
        registro_actual.get(
            "Contrato predicho"
        )
    )

    target_predicho = (
        registro_actual.get(
            "Target contrato predicho"
        )
    )

    resultado_actual = (
        registro_actual.get(
            "Resultado"
        )
    )

    st.success(
        "🔔 PREDICCIÓN GUARDADA"
    )

    st.write(
        f"# {prediccion_guardada}"
    )

    st.metric(
        "Confianza",
        confianza_guardada
    )

    st.write(
        f"**Contrato analizado:** "
        f"`{ticker_actual}`"
    )

    st.write(
        f"**Contrato que la app está prediciendo:** "
        f"`{contrato_predicho}`"
    )

    if target_predicho is not None:

        st.write(
            f"**Target del contrato predicho:** "
            f"${float(target_predicho):,.2f}"
        )

    st.write(
        f"**Estado:** "
        f"{resultado_actual}"
    )

    st.write(
        f"**Precio BTC al hacer predicción:** "
        f"${float(registro_actual.get('Precio BTC predicción')):,.2f}"
    )

    st.write(
        f"**Score:** "
        f"{registro_actual.get('Score'):+d}"
    )

    st.caption(
        "Predicción realizada: "
        f"{registro_actual.get('Momento predicción')}"
    )

    st.subheader(
        "📊 Análisis"
    )

    razones_guardadas = (
        registro_actual.get(
            "Análisis",
            []
        )
    )

    for razon in razones_guardadas:

        st.write(
            "•",
            razon
        )

    # --------------------------------------------------------
    # RESULTADO DEL CONTRATO
    # --------------------------------------------------------

    if resultado_actual == "⏳ PENDIENTE":

        st.info(
            "⏳ Esperando que termine "
            "el contrato predicho para "
            "comprobar el resultado real "
            "de Kalshi."
        )

    else:

        st.divider()

        st.subheader(
            "🏁 Resultado de la predicción"
        )

        expiration = (
            registro_actual.get(
                "Expiration Value"
            )
        )

        resultado_kalshi = (
            registro_actual.get(
                "Resultado Kalshi"
            )
        )

        if target_predicho is not None:

            st.write(
                f"**Target:** "
                f"${float(target_predicho):,.2f}"
            )

        if expiration is not None:

            st.write(
                f"**Expiration Value:** "
                f"${float(expiration):,.2f}"
            )

        st.write(
            f"**Kalshi cerró:** "
            f"`{resultado_kalshi}`"
        )

        if resultado_actual == "✅ ACIERTO":

            st.success(
                "🎯 ✅ ACIERTO — "
                "La predicción coincidió "
                "con el resultado de Kalshi."
            )

        elif resultado_actual == "❌ FALLÓ":

            st.error(
                "🎯 ❌ FALLÓ — "
                "La predicción NO coincidió "
                "con el resultado de Kalshi."
            )

        elif resultado_actual == "⚪ EMPATE":

            st.warning(
                "🎯 ⚪ EMPATE — "
                "El precio terminó exactamente "
                "en el Target."
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
        "La predicción automática "
        "se realizará durante los "
        "últimos 2 minutos del contrato. "
        f"Faltan aproximadamente "
        f"{mm:02d}:{ss:02d}."
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

    columnas_preferidas = [

        "Contrato base",

        "Contrato predicho",

        "Target usado para predicción",

        "Target contrato predicho",

        "Predicción",

        "Confianza",

        "Score",

        "Precio BTC predicción",

        "Expiration Value",

        "Resultado Kalshi",

        "Resultado",

        "Cierre contrato base",

        "Cierre contrato predicho",

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
    "La aplicación analiza el contrato BTC 15M "
    "actual durante los últimos 2 minutos. "
    "La predicción se guarda automáticamente "
    "junto con el ticker exacto del siguiente "
    "contrato que se está prediciendo. "
    "Cuando ese contrato termina, la aplicación "
    "consulta nuevamente Kalshi, obtiene su "
    "Expiration Value y lo compara con el Target "
    "del mismo contrato. Si Expiration Value es "
    "mayor que el Target, el resultado real es "
    "ARRIBA. Si es menor, el resultado real es "
    "ABAJO. Después compara ese resultado con la "
    "predicción original y marca automáticamente "
    "ACIerto o FALLÓ. El historial se guarda "
    "directamente en GitHub."
)


# ============================================================
# ACTUALIZACIÓN AUTOMÁTICA
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
