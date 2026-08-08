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
GITHUB_API = "https://api.github.com"

SERIES = "KXBTC15M"

LOCAL_TZ = ZoneInfo("America/Chicago")

HISTORIAL_FILE = "historial_kalshi.json"

REFRESH_SECONDS = 5

# Generar predicción dentro de los últimos 2 minutos
PREDICCION_SEGUNDOS = 120


# ============================================================
# GITHUB - CONFIGURACIÓN
# ============================================================

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
        str(branch).strip()
        if branch
        else GITHUB_DEFAULT_BRANCH
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
# CARGAR HISTORIAL DESDE GITHUB
# ============================================================

def cargar_historial_github():

    if not GITHUB_USERNAME:
        raise Exception(
            "Falta GITHUB_USERNAME."
        )

    if not GITHUB_REPO:
        raise Exception(
            "Falta GITHUB_REPO."
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

    texto = base64.b64decode(
        contenido
    ).decode("utf-8")

    historial = json.loads(texto)

    if isinstance(historial, list):
        return historial

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
            "No se pudo obtener SHA de GitHub. "
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json().get("sha")


# ============================================================
# GUARDAR HISTORIAL GITHUB
# ============================================================

def guardar_historial_github(historial):

    if not GITHUB_USERNAME:
        raise Exception(
            "Falta GITHUB_USERNAME."
        )

    if not GITHUB_TOKEN:
        raise Exception(
            "Falta GITHUB_TOKEN."
        )

    if not GITHUB_REPO:
        raise Exception(
            "Falta GITHUB_REPO."
        )

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
        historial = cargar_historial_github()

        # Copia local
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

    # Guardar GitHub
    guardar_historial_github(historial)

    # Copia local
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
            "KALSHI_PRIVATE_KEY no tiene "
            "formato PEM válido."
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
            salt_length=
                padding.PSS.DIGEST_LENGTH
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
# FECHA
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
# OBTENER CIERRE
# ============================================================

def obtener_cierre_mercado(mercado):

    cierre = convertir_fecha(
        mercado.get("close_time")
    )

    if cierre is None:

        cierre = convertir_fecha(
            mercado.get("expiration_time")
        )

    return cierre


# ============================================================
# CONTRATO ACTUAL
# ============================================================

def buscar_mercado_actual():

    mercados = obtener_mercados_btc(
        status="open",
        limit=100
    )

    ahora = datetime.now(
        timezone.utc
    )

    candidatos = []

    for mercado in mercados:

        cierre = obtener_cierre_mercado(
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
    ticker_base,
    cierre_base
):

    if not ticker_base or not cierre_base:
        return None

    candidatos = []

    # --------------------------------------------------------
    # PRIMERO ABIERTOS
    # --------------------------------------------------------

    try:

        mercados = obtener_mercados_btc(
            status="open",
            limit=100
        )

    except Exception:

        mercados = []

    for mercado in mercados:

        ticker = mercado.get("ticker")

        if not ticker:
            continue

        if ticker == ticker_base:
            continue

        cierre = obtener_cierre_mercado(
            mercado
        )

        if cierre is None:
            continue

        if cierre > cierre_base:

            candidatos.append(
                (
                    cierre,
                    mercado
                )
            )

    # --------------------------------------------------------
    # DESPUÉS CERRADOS
    # --------------------------------------------------------

    try:

        mercados_cerrados = (
            obtener_mercados_btc(
                status="closed",
                limit=100
            )
        )

    except Exception:

        mercados_cerrados = []

    for mercado in mercados_cerrados:

        ticker = mercado.get("ticker")

        if not ticker:
            continue

        if ticker == ticker_base:
            continue

        cierre = obtener_cierre_mercado(
            mercado
        )

        if cierre is None:
            continue

        if cierre > cierre_base:

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
# PRECIO
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
        pass

    return None


# ============================================================
# BUSCAR TARGET
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
# TARGET EN TEXTO
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

        valor = mercado.get(campo)

        if valor:
            textos.append(
                str(valor)
            )

    texto = " ".join(textos)

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
        return float(target_texto)

    ticker = mercado.get("ticker")

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

    raise Exception(
        "No pude encontrar el Target."
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

    return df.sort_values(
        "time"
    )


# ============================================================
# BINANCE
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

    return df.dropna(
        subset=["Close"]
    )


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

        precio = float(
            response.json()["price"]
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

        precio = float(
            response.json()["price"]
        )

        if precio > 1000:
            return precio, "Binance.US"

    except Exception:
        pass

    raise Exception(
        "No pude obtener precio BTC."
    )


# ============================================================
# BTC
# ============================================================

def obtener_btc():

    try:

        df = obtener_btc_coinbase()

        fuente_historico = "Coinbase"

    except Exception:

        df = obtener_btc_binance()

        fuente_historico = "Binance.US"

    precio_real, fuente_precio = (
        obtener_precio_btc()
    )

    df = df.drop_duplicates(
        subset=["time"]
    )

    df = df.sort_values(
        "time"
    )

    df = df.tail(120).copy()

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

    target = float(target)

    score = 0

    razones = []

    diferencia_pct = (
        (precio - target)
        / target
    ) * 100

    # --------------------------------------------------------
    # PRECIO VS TARGET
    # --------------------------------------------------------

    if diferencia_pct > 0.05:

        score += 30

        razones.append(
            f"BTC está claramente por encima "
            f"del Target ({diferencia_pct:+.3f}%)."
        )

    elif diferencia_pct > 0:

        score += 20

        razones.append(
            f"BTC está por encima del Target "
            f"({diferencia_pct:+.3f}%)."
        )

    elif diferencia_pct < -0.05:

        score -= 30

        razones.append(
            f"BTC está claramente por debajo "
            f"del Target ({diferencia_pct:+.3f}%)."
        )

    elif diferencia_pct < 0:

        score -= 20

        razones.append(
            f"BTC está por debajo del Target "
            f"({diferencia_pct:+.3f}%)."
        )

    else:

        razones.append(
            "BTC está prácticamente en el Target."
        )

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    ema9 = float(ultimo["EMA9"])
    ema21 = float(ultimo["EMA21"])
    ema50 = float(ultimo["EMA50"])

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

        score += 6
        razones.append(
            "MACD por encima de su señal."
        )

    else:

        score -= 6
        razones.append(
            "MACD por debajo de su señal."
        )

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    for nombre, puntos, etiqueta in [

        ("Momentum1", 5, "1m"),

        ("Momentum3", 7, "3m"),

        ("Momentum5", 7, "5m"),

        ("Momentum10", 6, "10m")
    ]:

        valor = ultimo[nombre]

        if pd.notna(valor):

            valor = float(valor)

            if valor > 0:

                score += puntos

                razones.append(
                    f"Momentum {etiqueta} positivo "
                    f"({valor:+.3f}%)."
                )

            elif valor < 0:

                score -= puntos

                razones.append(
                    f"Momentum {etiqueta} negativo "
                    f"({valor:.3f}%)."
                )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    rsi = ultimo["RSI"]

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

    volatilidad = ultimo["Volatilidad"]

    if pd.notna(volatilidad):

        razones.append(
            f"Volatilidad 15m: "
            f"{float(volatilidad):.4f}%."
        )

    # --------------------------------------------------------
    # PREDICCIÓN
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
            90
        )

        confianza = int(
            round(
                50 + fuerza * 0.45
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
# BUSCAR REGISTRO
# ============================================================

def buscar_registro_por_base(
    ticker_base
):

    for registro in st.session_state.historial:

        if (
            registro.get(
                "Contrato base"
            )
            == ticker_base
        ):

            return registro

    return None


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

    existente = (
        buscar_registro_por_base(
            ticker_base
        )
    )

    # IMPORTANTE:
    # Si ya existe, no crea otra.
    if existente is not None:
        return False

    registro = {

        "Contrato base":
            ticker_base,

        "Contrato predicho":
            None,

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
            close_time
            .astimezone(
                LOCAL_TZ
            )
            .strftime(
                "%Y-%m-%d %I:%M:%S %p"
            ),

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
# IDENTIFICAR SIGUIENTE CONTRATO
# ============================================================

def asignar_siguiente_contrato(
    registro
):

    if registro.get(
        "Contrato predicho"
    ):

        return False

    ticker_base = registro.get(
        "Contrato base"
    )

    cierre_texto = registro.get(
        "Cierre contrato base"
    )

    if not ticker_base or not cierre_texto:
        return False

    try:

        cierre_base = datetime.strptime(

            cierre_texto,

            "%Y-%m-%d %I:%M:%S %p"

        ).replace(

            tzinfo=LOCAL_TZ

        ).astimezone(
            timezone.utc
        )

    except Exception:

        return False

    siguiente = (
        buscar_siguiente_contrato(
            ticker_base,
            cierre_base
        )
    )

    if siguiente is None:
        return False

    ticker_siguiente = (
        siguiente.get("ticker")
    )

    if not ticker_siguiente:
        return False

    registro[
        "Contrato predicho"
    ] = ticker_siguiente

    registro[
        "Contrato predicho identificado"
    ] = datetime.now(
        LOCAL_TZ
    ).strftime(
        "%Y-%m-%d %I:%M:%S"
    )

    return True


# ============================================================
# ACTUALIZAR CONTRATO PREDICHO
# ============================================================

def actualizar_contrato_predicho(
    registro
):

    ticker_predicho = registro.get(
        "Contrato predicho"
    )

    if not ticker_predicho:

        asignado = (
            asignar_siguiente_contrato(
                registro
            )
        )

        if not asignado:
            return False

        ticker_predicho = (
            registro.get(
                "Contrato predicho"
            )
        )

    if not ticker_predicho:
        return False

    try:

        mercado = obtener_contrato(
            ticker_predicho
        )

    except Exception:

        return False

    try:

        target = obtener_target(
            mercado
        )

    except Exception:

        return False

    cambio = False

    target = round(
        float(target),
        2
    )

    if registro.get(
        "Target contrato predicho"
    ) != target:

        registro[
            "Target contrato predicho"
        ] = target

        cambio = True

    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    expiration = mercado.get(
        "expiration_value"
    )

    if expiration not in (
        None,
        "",
        "null"
    ):

        try:

            expiration = float(
                expiration
            )

        except Exception:

            expiration = None

    else:

        expiration = None

    if expiration is None:

        return cambio

    expiration = round(
        expiration,
        2
    )

    if registro.get(
        "Expiration Value"
    ) != expiration:

        registro[
            "Expiration Value"
        ] = expiration

        cambio = True

    # --------------------------------------------------------
    # COMPARACIÓN REAL KALSHI
    # --------------------------------------------------------

    if expiration > target:

        resultado_kalshi = "UP"

    elif expiration < target:

        resultado_kalshi = "DOWN"

    else:

        resultado_kalshi = "TIE"

    if registro.get(
        "Resultado Kalshi"
    ) != resultado_kalshi:

        registro[
            "Resultado Kalshi"
        ] = resultado_kalshi

        cambio = True

    # --------------------------------------------------------
    # COMPARAR CON PREDICCIÓN
    # --------------------------------------------------------

    prediccion = registro.get(
        "Predicción"
    )

    if resultado_kalshi == "TIE":

        resultado = "⚪ EMPATE"

    elif (
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

    elif prediccion == "⚪ NO APOSTAR":

        resultado = "⚪ NO APOSTAR"

    else:

        resultado = "❌ FALLÓ"

    if registro.get(
        "Resultado"
    ) != resultado:

        registro[
            "Resultado"
        ] = resultado

        cambio = True

    if resultado in (
        "✅ ACIERTO",
        "❌ FALLÓ",
        "⚪ EMPATE",
        "⚪ NO APOSTAR"
    ):

        registro[
            "Actualizado"
        ] = datetime.now(
            LOCAL_TZ
        ).strftime(
            "%Y-%m-%d %I:%M:%S"
        )

    return cambio


# ============================================================
# ACTUALIZAR TODO EL HISTORIAL
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
            None,
            ""
        ):

            continue

        try:

            actualizado = (
                actualizar_contrato_predicho(
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
# ÚLTIMA PREDICCIÓN
# ============================================================

def obtener_ultima_prediccion():

    historial = (
        st.session_state.historial
    )

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
# TÍTULO
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Predicción automática del siguiente "
    "contrato BTC 15M de Kalshi."
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


if not GITHUB_REPO:

    st.error(
        "❌ Falta GITHUB_REPO."
    )

    st.stop()


st.caption(
    f"☁️ Historial sincronizado con GitHub: "
    f"{GITHUB_USERNAME}/{GITHUB_REPO}"
)


# ============================================================
# ACTUALIZAR HISTORIAL ANTES DE TODO
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
# SI NO HAY CONTRATO
# ============================================================

if actual is None:

    st.warning(
        "⏳ Kalshi no está mostrando "
        "ahora mismo un contrato BTC 15M abierto."
    )

    ultima = obtener_ultima_prediccion()

    if ultima:

        st.divider()

        st.subheader(
            "🔔 Última predicción guardada"
        )

        st.write(
            f"**Contrato base:** "
            f"`{ultima.get('Contrato base')}`"
        )

        st.write(
            f"**Predicción:** "
            f"{ultima.get('Predicción')}"
        )

        st.write(
            f"**Contrato predicho:** "
            f"`{ultima.get('Contrato predicho')}`"
        )

        st.write(
            f"**Resultado:** "
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

close_actual = obtener_cierre_mercado(
    actual
)

if close_actual is None:

    st.error(
        "❌ El contrato no tiene cierre."
    )

    time.sleep(
        REFRESH_SECONDS
    )

    st.rerun()


st.session_state.ticker_actual = (
    ticker_actual
)


# ============================================================
# TARGET ACTUAL
# ============================================================

try:

    target_actual = obtener_target(
        actual
    )

except Exception as error:

    target_actual = None

    st.error(
        f"❌ No pude obtener Target: {error}"
    )


# ============================================================
# BTC
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

if actual.get("title"):

    st.write(
        actual.get("title")
    )

if actual.get("subtitle"):

    st.caption(
        actual.get("subtitle")
    )


# ============================================================
# BTC Y TARGET
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
            "BTC está exactamente en el Target."
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


st.write(
    "Cierre:",
    close_actual
    .astimezone(LOCAL_TZ)
    .strftime(
        "%I:%M:%S %p"
    )
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
#
# IMPORTANTE:
# NO NECESITAMOS QUE EL SIGUIENTE CONTRATO
# YA EXISTA.
# ============================================================

if (

    registro_actual is None

    and

    target_actual is not None

    and

    segundos_restantes <= PREDICCION_SEGUNDOS

    and

    segundos_restantes > 0

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

        guardada = guardar_prediccion(

            ticker_base=
                ticker_actual,

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

        if guardada:

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
                "🚨 PREDICCIÓN GENERADA "
                "Y GUARDADA AUTOMÁTICAMENTE"
            )

            registro_actual = (
                buscar_registro_por_base(
                    ticker_actual
                )
            )

    except Exception as error:

        st.error(
            f"❌ Error generando predicción: "
            f"{error}"
        )


# ============================================================
# RECARGAR REGISTRO DESPUÉS DE GUARDAR
# ============================================================

registro_actual = (
    buscar_registro_por_base(
        ticker_actual
    )
)


# ============================================================
# MOSTRAR PREDICCIÓN
# ============================================================

if registro_actual:

    prediccion = registro_actual.get(
        "Predicción"
    )

    confianza = registro_actual.get(
        "Confianza"
    )

    st.divider()

    st.subheader(
        "🔮 PREDICCIÓN AUTOMÁTICA"
    )

    st.success(
        f"{prediccion}"
    )

    st.metric(
        "Confianza",
        confianza
    )

    st.write(
        f"**Contrato analizado:** "
        f"`{registro_actual.get('Contrato base')}`"
    )

    st.write(
        f"**Target utilizado:** "
        f"${float(registro_actual.get('Target usado para predicción')):,.2f}"
    )

    st.write(
        f"**BTC al hacer predicción:** "
        f"${float(registro_actual.get('Precio BTC predicción')):,.2f}"
    )

    st.write(
        f"**Score:** "
        f"{registro_actual.get('Score'):+d}"
    )

    st.write(
        f"**Estado:** "
        f"{registro_actual.get('Resultado')}"
    )

    st.subheader(
        "📊 Análisis"
    )

    for razon in registro_actual.get(
        "Análisis",
        []
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

    mm = faltan // 60
    ss = faltan % 60

    st.info(
        "La predicción automática "
        "se generará durante los últimos "
        "2 minutos del contrato. "
        f"Faltan aproximadamente "
        f"{mm:02d}:{ss:02d}."
    )


# ============================================================
# ACTUALIZAR CONTRATOS PREDICHOS
# ============================================================

try:

    actualizar_pendientes()

except Exception:
    pass


# ============================================================
# RECARGAR REGISTRO
# ============================================================

registro_actual = (
    buscar_registro_por_base(
        ticker_actual
    )
)


# ============================================================
# MOSTRAR CONTRATO PREDICHO
# ============================================================

if registro_actual:

    st.divider()

    st.subheader(
        "🎯 Contrato que estamos evaluando"
    )

    ticker_predicho = (
        registro_actual.get(
            "Contrato predicho"
        )
    )

    if ticker_predicho:

        st.success(
            f"Contrato predicho: `{ticker_predicho}`"
        )

        target_predicho = (
            registro_actual.get(
                "Target contrato predicho"
            )
        )

        expiration = (
            registro_actual.get(
                "Expiration Value"
            )
        )

        if target_predicho is not None:

            st.write(
                f"**Target del contrato:** "
                f"${float(target_predicho):,.2f}"
            )

        if expiration is not None:

            st.write(
                f"**Expiration Value:** "
                f"${float(expiration):,.2f}"
            )

        resultado_kalshi = (
            registro_actual.get(
                "Resultado Kalshi"
            )
        )

        resultado = (
            registro_actual.get(
                "Resultado"
            )
        )

        st.write(
            f"**Resultado Kalshi:** "
            f"`{resultado_kalshi}`"
        )

        if resultado == "⏳ PENDIENTE":

            st.warning(
                "⏳ El contrato todavía no ha terminado."
            )

        elif resultado == "✅ ACIERTO":

            st.success(
                "✅ PREDICCIÓN CORRECTA — GANÓ"
            )

        elif resultado == "❌ FALLÓ":

            st.error(
                "❌ PREDICCIÓN INCORRECTA — PERDIÓ"
            )

        elif resultado == "⚪ EMPATE":

            st.warning(
                "⚪ EMPATE"
            )

    else:

        st.info(
            "⏳ El siguiente contrato todavía "
            "no aparece en Kalshi. "
            "La predicción ya está guardada. "
            "La app lo identificará automáticamente."
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
    "📜 Historial automático"
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

        "Contrato predicho identificado",

        "Actualizado"
    ]

    columnas_existentes = [

        c

        for c in columnas_preferidas

        if c in tabla.columns
    ]

    columnas_restantes = [

        c

        for c in tabla.columns

        if c not in columnas_existentes
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

    precision = (

        aciertos /
        evaluados *
        100

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
        "Todavía no hay predicciones."
    )


# ============================================================
# EXPLICACIÓN
# ============================================================

st.divider()

st.caption(
    "La aplicación genera automáticamente la predicción "
    "durante los últimos 2 minutos del contrato BTC 15M "
    "actual. No es necesario aceptar ni rechazar nada. "
    "La predicción se guarda inmediatamente en GitHub. "
    "El siguiente contrato se identifica automáticamente "
    "cuando aparece en Kalshi. Cuando ese contrato termina, "
    "la aplicación obtiene su Target y su Expiration Value. "
    "Si Expiration Value es mayor que el Target, Kalshi "
    "terminó ARRIBA. Si es menor, terminó ABAJO. "
    "Después se compara ese resultado con la predicción "
    "guardada y se marca automáticamente ACIERTO o FALLÓ."
)


# ============================================================
# ACTUALIZACIÓN AUTOMÁTICA
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
