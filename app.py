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

# Ventana normal para generar una predicción
PREDICCION_SEGUNDOS = 120

# Cantidad de contratos cerrados de Kalshi
CONTRATOS_ANTERIORES = 3


# ============================================================
# GITHUB
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
            or repo
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
# CREDENCIALES KALSHI
# ============================================================

def cargar_credenciales_kalshi():

    try:

        key_id = st.secrets["KALSHI_API_KEY_ID"]
        private_key = st.secrets["KALSHI_PRIVATE_KEY"]

        return str(key_id), str(private_key)

    except Exception:

        return None, None


API_KEY_ID, PRIVATE_KEY = cargar_credenciales_kalshi()


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
# LEER HISTORIAL REMOTO
# ============================================================

def github_leer_historial():

    if not GITHUB_USERNAME:
        raise Exception("Falta GITHUB_USERNAME.")

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
        return [], None

    if response.status_code >= 400:

        raise Exception(
            f"GitHub HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()

    contenido = data.get("content")

    if not contenido:
        return [], data.get("sha")

    texto = base64.b64decode(
        contenido.replace("\n", "")
    ).decode("utf-8")

    historial = json.loads(texto)

    if not isinstance(historial, list):
        historial = []

    return historial, data.get("sha")


# ============================================================
# CARGAR HISTORIAL
# ============================================================

def cargar_historial_inicial():

    # --------------------------------------------------------
    # GitHub es la fuente principal.
    # --------------------------------------------------------

    try:

        historial, _ = github_leer_historial()

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

        return historial

    except Exception as error:

        st.session_state.github_error = str(error)

    # --------------------------------------------------------
    # Backup local si GitHub no responde.
    # --------------------------------------------------------

    try:

        if os.path.exists(HISTORIAL_FILE):

            with open(
                HISTORIAL_FILE,
                "r",
                encoding="utf-8"
            ) as archivo:

                historial = json.load(archivo)

            if isinstance(historial, list):
                return historial

    except Exception:
        pass

    return []


# ============================================================
# IDENTIFICADOR ÚNICO DEL REGISTRO
# ============================================================

def id_registro(registro):

    # Preferimos el contrato predicho.
    ticker = registro.get("Contrato predicho")

    if ticker:
        return f"PRED:{ticker}"

    # Compatibilidad con registros anteriores.
    base = registro.get("Contrato base")

    if base:
        return f"BASE:{base}"

    momento = registro.get("Momento predicción")

    if momento:
        return f"TIME:{momento}"

    return None


# ============================================================
# MERGE DE HISTORIALES
# ============================================================

def fusionar_historiales(remoto, local):

    resultado = {}

    # Primero remoto.
    for registro in remoto:

        if not isinstance(registro, dict):
            continue

        identificador = id_registro(registro)

        if identificador:
            resultado[identificador] = registro

    # Luego local.
    for registro in local:

        if not isinstance(registro, dict):
            continue

        identificador = id_registro(registro)

        if not identificador:
            continue

        if identificador not in resultado:

            resultado[identificador] = registro

        else:

            # ------------------------------------------------
            # Nunca reemplazar información real por vacía.
            # ------------------------------------------------

            existente = resultado[identificador]

            for clave, valor in registro.items():

                if valor not in (
                    None,
                    "",
                    "PENDIENTE"
                ):

                    existente[clave] = valor

            # ------------------------------------------------
            # Si uno de los dos ya tiene resultado final,
            # conservarlo.
            # ------------------------------------------------

            if registro.get("Resultado") not in (
                None,
                "",
                "⏳ PENDIENTE"
            ):

                existente["Resultado"] = registro[
                    "Resultado"
                ]

    lista = list(resultado.values())

    # Más reciente primero internamente no es necesario;
    # aquí dejamos orden cronológico.
    lista.sort(
        key=lambda x: str(
            x.get(
                "Momento predicción",
                ""
            )
        )
    )

    return lista


# ============================================================
# GUARDAR HISTORIAL EN GITHUB
# ============================================================

def guardar_historial_github(historial):

    if not GITHUB_USERNAME:
        raise Exception("Falta GITHUB_USERNAME.")

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

    # --------------------------------------------------------
    # Intentamos varias veces por si otro proceso actualizó
    # GitHub al mismo tiempo.
    # --------------------------------------------------------

    for intento in range(3):

        remoto, sha = github_leer_historial()

        # Fusionar para evitar sobrescribir datos.
        fusionado = fusionar_historiales(
            remoto,
            historial
        )

        contenido = json.dumps(
            fusionado,
            indent=2,
            ensure_ascii=False
        )

        contenido_b64 = base64.b64encode(
            contenido.encode("utf-8")
        ).decode("utf-8")

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

        if response.status_code in (200, 201):

            return fusionado

        # 409 = SHA cambiado.
        if response.status_code == 409:

            time.sleep(1)

            continue

        raise Exception(
            f"GitHub no pudo guardar. "
            f"HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    raise Exception(
        "GitHub cambió mientras se guardaba. "
        "Se agotaron los reintentos."
    )


# ============================================================
# GUARDADO SEGURO
# ============================================================

def guardar_historial(historial):

    # --------------------------------------------------------
    # Primero backup local.
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Después GitHub.
    # --------------------------------------------------------

    try:

        historial_final = guardar_historial_github(
            historial
        )

        st.session_state.historial = historial_final

        st.session_state.github_error = None

        return True

    except Exception as error:

        st.session_state.github_error = str(error)

        return False


# ============================================================
# SINCRONIZAR AHORA DESDE GITHUB
# ============================================================

def sincronizar_historial():

    try:

        remoto, _ = github_leer_historial()

        local = st.session_state.historial

        fusionado = fusionar_historiales(
            remoto,
            local
        )

        st.session_state.historial = fusionado

        try:

            with open(
                HISTORIAL_FILE,
                "w",
                encoding="utf-8"
            ) as archivo:

                json.dump(
                    fusionado,
                    archivo,
                    indent=2,
                    ensure_ascii=False
                )

        except Exception:
            pass

        return True

    except Exception as error:

        st.session_state.github_error = str(error)

        return False


# ============================================================
# CLAVE PRIVADA KALSHI
# ============================================================

def cargar_clave_privada():

    if not PRIVATE_KEY:

        raise Exception(
            "Falta KALSHI_PRIVATE_KEY."
        )

    return serialization.load_pem_private_key(
        PRIVATE_KEY.strip().encode("utf-8"),
        password=None
    )


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

def obtener_ultimos_3_contratos_cerrados():

    try:

        mercados = obtener_mercados_btc(
            status="closed",
            limit=100
        )

    except Exception:

        return []

    ahora = datetime.now(
        timezone.utc
    )

    contratos = []

    for mercado in mercados:

        ticker = mercado.get("ticker")

        if not ticker:
            continue

        cierre = cierre_de_mercado(
            mercado
        )

        if cierre is None:
            continue

        if cierre > ahora:
            continue

        contratos.append(
            (
                cierre,
                mercado
            )
        )

    contratos.sort(
        key=lambda x: x[0],
        reverse=True
    )

    resultado = []

    vistos = set()

    for cierre, mercado in contratos:

        ticker = mercado.get("ticker")

        if ticker in vistos:
            continue

        vistos.add(ticker)

        try:

            detalle = obtener_contrato(
                ticker
            )

            if detalle:
                mercado = detalle

        except Exception:
            pass

        resultado.append(
            mercado
        )

        if len(resultado) >= CONTRATOS_ANTERIORES:
            break

    return resultado


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

        valor = mercado.get(campo)

        if valor:
            textos.append(str(valor))

    texto = " ".join(textos)

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
        return float(target_texto)

    ticker = mercado.get("ticker")

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
                return float(target_texto)

        except Exception:
            pass

    return None


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
                "BTC-Kalshi-Predictor/4.0"
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

    return df.sort_values("time")


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

    return df.dropna(
        subset=["Close"]
    ).sort_values("time")


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

        return (
            float(
                response.json()["price"]
            ),
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

    return (
        float(
            response.json()["price"]
        ),
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
    ).sort_values("time").tail(120)

    precio, fuente_precio = obtener_precio_btc()

    if len(df) > 0:

        df.loc[
            df.index[-1],
            "Close"
        ] = precio

    return df, precio, fuente_precio


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

    df["MACD"] = ema12 - ema26

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

    avg_gain = ganancias.rolling(
        14
    ).mean()

    avg_loss = perdidas.rolling(
        14
    ).mean()

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
        df["Close"].pct_change(1)
        * 100
    )

    df["Momentum3"] = (
        df["Close"].pct_change(3)
        * 100
    )

    df["Momentum5"] = (
        df["Close"].pct_change(5)
        * 100
    )

    df["Momentum10"] = (
        df["Close"].pct_change(10)
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
# RESULTADO REAL KALSHI
# ============================================================

def resultado_kalshi(mercado):

    target = obtener_target(
        mercado
    )

    expiration = mercado.get(
        "expiration_value"
    )

    if target is None:
        return None, None, None

    if expiration in (
        None,
        "",
        "null"
    ):

        return (
            target,
            None,
            None
        )

    try:

        target = float(target)
        expiration = float(expiration)

    except Exception:

        return None, None, None

    if expiration > target:

        resultado = "UP"

    elif expiration < target:

        resultado = "DOWN"

    else:

        resultado = "TIE"

    return (
        target,
        expiration,
        resultado
    )


# ============================================================
# ANÁLISIS DE LOS ÚLTIMOS 3 CONTRATOS
# ============================================================

def analizar_ultimos_contratos():

    contratos = (
        obtener_ultimos_3_contratos_cerrados()
    )

    informacion = []

    score = 0

    for contrato in contratos:

        ticker = contrato.get(
            "ticker"
        )

        target, expiration, resultado = (
            resultado_kalshi(
                contrato
            )
        )

        if resultado is None:
            continue

        if resultado == "UP":
            score += 4

        elif resultado == "DOWN":
            score -= 4

        informacion.append({
            "ticker": ticker,
            "target": target,
            "expiration": expiration,
            "resultado": resultado
        })

    return informacion, score


# ============================================================
# PREDICCIÓN
# ============================================================

def generar_prediccion(
    df,
    contratos_kalshi=None,
    score_kalshi=0
):

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

    momentum1 = ultimo["Momentum1"]
    momentum3 = ultimo["Momentum3"]
    momentum5 = ultimo["Momentum5"]
    momentum10 = ultimo["Momentum10"]

    volatilidad = ultimo["Volatilidad"]

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

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
                f"Momentum {nombre} positivo "
                f"({valor:+.3f}%)."
            )

        elif valor < 0:

            score -= peso

            razones.append(
                f"Momentum {nombre} negativo "
                f"({valor:+.3f}%)."
            )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

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
    # CONTRATOS ANTERIORES
    # --------------------------------------------------------

    if score_kalshi > 0:

        score += score_kalshi

        razones.append(
            f"Últimos 3 contratos de Kalshi "
            f"favorecen ARRIBA "
            f"(aporte {score_kalshi:+d})."
        )

    elif score_kalshi < 0:

        score += score_kalshi

        razones.append(
            f"Últimos 3 contratos de Kalshi "
            f"favorecen ABAJO "
            f"(aporte {score_kalshi:+d})."
        )

    else:

        razones.append(
            "Últimos contratos de Kalshi "
            "sin señal dominante."
        )

    # --------------------------------------------------------
    # VOLATILIDAD
    # --------------------------------------------------------

    if pd.notna(volatilidad):

        razones.append(
            f"Volatilidad: "
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

        # Para que la app no se quede constantemente
        # sin predicción.
        if score >= 0:
            prediccion = "🟢 ARRIBA"
        else:
            prediccion = "🔴 ABAJO"

    fuerza = min(
        abs(score),
        65
    )

    confianza = int(
        round(
            50 + fuerza * 0.62
        )
    )

    confianza = max(
        51,
        min(
            90,
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
# BUSCAR PREDICCIÓN DEL CONTRATO
# ============================================================

def buscar_prediccion(ticker):

    if not ticker:
        return None

    for registro in st.session_state.historial:

        if registro.get(
            "Contrato predicho"
        ) == ticker:

            return registro

    return None


# ============================================================
# CREAR PREDICCIÓN PARA EL CONTRATO ACTUAL
# ============================================================

def crear_prediccion_para_contrato(
    contrato_actual,
    df
):

    ticker = contrato_actual.get(
        "ticker"
    )

    if not ticker:
        return None

    # --------------------------------------------------------
    # MUY IMPORTANTE:
    # Si ya existe, NO crear otra.
    # --------------------------------------------------------

    existente = buscar_prediccion(
        ticker
    )

    if existente:

        return existente

    # --------------------------------------------------------
    # Obtener contratos anteriores de Kalshi.
    # --------------------------------------------------------

    try:

        anteriores, score_kalshi = (
            analizar_ultimos_contratos()
        )

    except Exception:

        anteriores = []
        score_kalshi = 0

    # --------------------------------------------------------
    # Generar predicción.
    # --------------------------------------------------------

    (
        prediccion,
        confianza,
        razones,
        score,
        precio
    ) = generar_prediccion(
        df,
        anteriores,
        score_kalshi
    )

    target = obtener_target(
        contrato_actual
    )

    cierre = cierre_de_mercado(
        contrato_actual
    )

    registro = {

        # ID lógico
        "ID":
            f"PRED:{ticker}",

        # Contrato al que corresponde
        "Contrato predicho":
            ticker,

        "Target contrato predicho":
            (
                round(
                    float(target),
                    2
                )
                if target is not None
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

        "Cierre contrato predicho":
            (
                cierre
                .astimezone(LOCAL_TZ)
                .strftime(
                    "%Y-%m-%d %I:%M:%S %p"
                )
                if cierre
                else None
            ),

        "Expiration Value":
            None,

        "Resultado Kalshi":
            "PENDIENTE",

        "Resultado":
            "⏳ PENDIENTE",

        "Estado predicción":
            "PENDIENTE",

        "Análisis":
            razones,

        "Contratos Kalshi anteriores":
            anteriores,

        "Momento predicción":
            datetime.now(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S"
            ),

        "Actualizado":
            datetime.now(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S"
            )
    }

    # --------------------------------------------------------
    # GUARDAR INMEDIATAMENTE.
    # --------------------------------------------------------

    st.session_state.historial.append(
        registro
    )

    guardar_historial(
        st.session_state.historial
    )

    return registro


# ============================================================
# ACTUALIZAR RESULTADOS
# ============================================================

def actualizar_resultados():

    cambio = False

    for registro in st.session_state.historial:

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

        target = registro.get(
            "Target contrato predicho"
        )

        if target is None:

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

        expiration = mercado.get(
            "expiration_value"
        )

        # ----------------------------------------------------
        # Todavía no terminó.
        # ----------------------------------------------------

        if expiration in (
            None,
            "",
            "null"
        ):

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
        # Resultado real de Kalshi.
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

        elif resultado_kalshi == "TIE":

            resultado = "⚪ EMPATE"

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
        cargar_historial_inicial()
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
    "Predicción automática de cada contrato "
    "BTC 15 minutos."
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
    f"☁️ Memoria permanente: "
    f"{GITHUB_USERNAME}/{GITHUB_REPO}/"
    f"{HISTORIAL_FILE}"
)


# ============================================================
# SINCRONIZACIÓN INICIAL
# ============================================================

sincronizar_historial()


# ============================================================
# ACTUALIZAR RESULTADOS ANTES DE CREAR NUEVO
# ============================================================

try:

    actualizar_resultados()

except Exception as error:

    st.warning(
        f"No se pudieron actualizar algunos "
        f"resultados: {error}"
    )


# ============================================================
# CONTRATO ACTUAL
# ============================================================

try:

    actual = buscar_contrato_actual()

except Exception as error:

    actual = None

    st.error(
        f"❌ Error consultando Kalshi: {error}"
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
# CONTRATO ACTUAL
# ============================================================

if actual:

    ticker_actual = actual.get(
        "ticker"
    )

    cierre_actual = cierre_de_mercado(
        actual
    )

    target_actual = obtener_target(
        actual
    )

    ahora = datetime.now(
        timezone.utc
    )

    segundos_restantes = max(
        0,
        int(
            (
                cierre_actual -
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
    # ENCABEZADO
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
    # PRECIO
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
                f"POR ENCIMA del Target."
            )

        elif diferencia < 0:

            st.error(
                f"BTC está "
                f"${abs(diferencia):,.2f} "
                f"({diferencia_pct:+.3f}%) "
                f"POR DEBAJO del Target."
            )

        else:

            st.warning(
                "BTC está exactamente en el Target."
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
            f"🟡 ÚLTIMOS 2 MINUTOS — "
            f"{minutos:02d}:{segundos:02d}"
        )

    else:

        st.info(
            f"⏱️ {minutos:02d}:{segundos:02d}"
        )

    st.write(
        "Cierre:",
        cierre_actual
        .astimezone(LOCAL_TZ)
        .strftime(
            "%I:%M:%S %p"
        )
    )

    # ========================================================
    # PREDICCIÓN DEL CONTRATO ACTUAL
    #
    # Esta es la parte importante:
    #
    # Si la app estaba cerrada y se perdió el momento exacto
    # de generación, al abrirse busca el contrato actual.
    #
    # Si todavía no existe una predicción para ese ticker,
    # crea una automáticamente.
    #
    # Así el ciclo NO depende de que Streamlit haya estado
    # abierto exactamente durante los últimos 2 minutos.
    # ========================================================

    registro_actual = buscar_prediccion(
        ticker_actual
    )

    if registro_actual is None:

        try:

            registro_actual = (
                crear_prediccion_para_contrato(
                    actual,
                    btc
                )
            )

            if registro_actual:

                st.success(
                    "🚨 PREDICCIÓN GENERADA "
                    "Y GUARDADA EN GITHUB"
                )

        except Exception as error:

            st.error(
                f"❌ Error generando predicción: "
                f"{error}"
            )

    # --------------------------------------------------------
    # PREDICCIÓN
    # --------------------------------------------------------

    st.divider()

    st.subheader(
        "🔮 Predicción para ESTE contrato"
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
                f"# {pred}"
            )

        else:

            st.error(
                f"# {pred}"
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
            f"**BTC al generar:** "
            f"${float(registro_actual.get('Precio BTC predicción', 0)):,.2f}"
        )

        st.write(
            f"**Score:** "
            f"{registro_actual.get('Score', 0):+d}"
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

        # ----------------------------------------------------
        # ÚLTIMOS 3 CONTRATOS
        # ----------------------------------------------------

        anteriores = registro_actual.get(
            "Contratos Kalshi anteriores",
            []
        )

        if anteriores:

            st.subheader(
                "📚 Últimos 3 contratos de Kalshi"
            )

            for contrato in anteriores:

                resultado = contrato.get(
                    "resultado"
                )

                if resultado == "UP":

                    icono = "🟢"

                elif resultado == "DOWN":

                    icono = "🔴"

                else:

                    icono = "⚪"

                st.write(
                    f"{icono} "
                    f"`{contrato.get('ticker')}` — "
                    f"{resultado} — "
                    f"Target: "
                    f"${float(contrato.get('target', 0)):,.2f} — "
                    f"Expiration: "
                    f"${float(contrato.get('expiration', 0)):,.2f}"
                )

    # ========================================================
    # RESOLUCIÓN
    # ========================================================

    resultado_actual = registro_actual.get(
        "Resultado"
    ) if registro_actual else None

    if resultado_actual == "⏳ PENDIENTE":

        st.info(
            "⏳ Esta predicción está guardada "
            "en GitHub y será evaluada "
            "automáticamente cuando termine "
            "el contrato."
        )

    elif resultado_actual == "✅ ACIERTO":

        st.success(
            "✅ ACIERTO — Resultado confirmado "
            "por Kalshi."
        )

    elif resultado_actual == "❌ FALLÓ":

        st.error(
            "❌ FALLÓ — Resultado confirmado "
            "por Kalshi."
        )


# ============================================================
# SIN CONTRATO
# ============================================================

else:

    st.warning(
        "⏳ No se encontró un contrato BTC 15M abierto."
    )


# ============================================================
# ACTUALIZAR RESULTADOS OTRA VEZ
# ============================================================

try:

    actualizar_resultados()

except Exception:
    pass


# ============================================================
# ÚLTIMO REGISTRO
# ============================================================

if st.session_state.historial:

    ultima = st.session_state.historial[-1]

    st.divider()

    st.subheader(
        "🔔 Última predicción guardada"
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
        f"**Resultado:** "
        f"{ultima.get('Resultado')}"
    )

    if ultima.get(
        "Expiration Value"
    ) is not None:

        st.write(
            f"**Expiration Value:** "
            f"${float(ultima.get('Expiration Value')):,.2f}"
        )

    if ultima.get(
        "Target contrato predicho"
    ) is not None:

        st.write(
            f"**Target:** "
            f"${float(ultima.get('Target contrato predicho')):,.2f}"
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
    "📜 Historial permanente"
)

historial = st.session_state.historial

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
        "Cierre contrato predicho",
        "Momento predicción",
        "Actualizado"
    ]

    existentes = [
        columna
        for columna in columnas
        if columna in tabla.columns
    ]

    restantes = [
        columna
        for columna in tabla.columns
        if columna not in existentes
    ]

    tabla = tabla[
        existentes + restantes
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

else:

    st.info(
        "No hay predicciones guardadas."
    )


# ============================================================
# ESTADO GITHUB
# ============================================================

if st.session_state.github_error:

    st.warning(
        "⚠️ GitHub presenta un problema de sincronización. "
        "La app conserva una copia local y volverá "
        "a intentar sincronizar."
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
    "La aplicación genera una predicción para cada "
    "contrato BTC 15M de Kalshi. La predicción se "
    "guarda inmediatamente en GitHub. Al volver a "
    "abrir la aplicación, el historial se recupera "
    "desde GitHub y no depende del estado de Streamlit. "
    "La aplicación también analiza los últimos 3 "
    "contratos cerrados de Kalshi y utiliza sus "
    "resultados como una señal adicional. Cuando un "
    "contrato termina, se obtiene el Target y "
    "Expiration Value reales y se determina "
    "automáticamente ARRIBA o ABAJO, comparándolo "
    "con la predicción para marcar ACIERTO o FALLÓ."
)


# ============================================================
# REFRESH
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
