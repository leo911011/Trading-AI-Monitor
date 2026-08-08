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

# La predicción se hace durante los últimos 2 minutos
PREDICCION_SEGUNDOS = 120


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

        # Guardamos copia local también
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

        # Backup local
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

    # --------------------------------------------------------
    # PRIMERO guardamos localmente.
    # Esto evita que GitHub impida que aparezca
    # inmediatamente la predicción.
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
    # Después sincronizamos con GitHub.
    # --------------------------------------------------------

    try:

        guardar_historial_github(historial)

        return True

    except Exception as error:

        # No detenemos la aplicación
        st.session_state.github_error = str(error)

        return False


# ============================================================
# CREDENCIALES KALSHI
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

    return base64.b64encode(firma).decode("utf-8")


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
            str(valor).replace("Z", "+00:00")
        )

    except Exception:

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

    return data.get("markets", [])


# ============================================================
# CONTRATO INDIVIDUAL
# ============================================================

def obtener_contrato(ticker):

    data = kalshi_request(
        "GET",
        "/trade-api/v2/markets/" + ticker
    )

    return data.get("market", {})


# ============================================================
# FECHA CIERRE
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
# CONTRATO ACTUAL
# ============================================================

def buscar_contrato_actual():

    mercados = obtener_mercados_btc(
        status="open",
        limit=100
    )

    ahora = datetime.now(timezone.utc)

    candidatos = []

    for mercado in mercados:

        cierre = cierre_de_mercado(mercado)

        if cierre is None:
            continue

        if cierre > ahora:

            mercado["_close"] = cierre

            candidatos.append(mercado)

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
    ticker_actual
):

    if cierre_actual is None:
        return None

    try:

        mercados = obtener_mercados_btc(
            status="open",
            limit=100
        )

    except Exception:

        return None

    candidatos = []

    for mercado in mercados:

        ticker = mercado.get("ticker")

        if not ticker:
            continue

        if ticker == ticker_actual:
            continue

        cierre = cierre_de_mercado(mercado)

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
# BUSCAR TARGET
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

            clave_lower = str(clave).lower()

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
                buscar_targets_recursivo(valor)
            )

    elif isinstance(objeto, list):

        for elemento in objeto:

            encontrados.extend(
                buscar_targets_recursivo(elemento)
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
                    resultado.replace(",", "")
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

            detalle = obtener_contrato(ticker)

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
# COINBASE
# ============================================================

def obtener_btc_coinbase():

    response = requests.get(
        "https://api.exchange.coinbase.com/"
        "products/BTC-USD/candles",
        params={
            "granularity": 60
        },
        headers={
            "User-Agent": "BTC-Kalshi-Predictor/2.0"
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

    df = df.sort_values("time")

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

        return precio, "Coinbase"

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

    return precio, "Binance.US"


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

    df = df.sort_values("time")

    df = df.tail(120).copy()

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
        .ewm(span=9, adjust=False)
        .mean()
    )

    df["EMA21"] = (
        df["Close"]
        .ewm(span=21, adjust=False)
        .mean()
    )

    df["EMA50"] = (
        df["Close"]
        .ewm(span=50, adjust=False)
        .mean()
    )

    ema12 = (
        df["Close"]
        .ewm(span=12, adjust=False)
        .mean()
    )

    ema26 = (
        df["Close"]
        .ewm(span=26, adjust=False)
        .mean()
    )

    df["MACD"] = ema12 - ema26

    df["MACD_SIGNAL"] = (
        df["MACD"]
        .ewm(span=9, adjust=False)
        .mean()
    )

    cambio = df["Close"].diff()

    ganancias = cambio.clip(lower=0)

    perdidas = -cambio.clip(upper=0)

    avg_gain = ganancias.rolling(14).mean()
    avg_loss = perdidas.rolling(14).mean()

    rs = (
        avg_gain /
        avg_loss.replace(0, pd.NA)
    )

    df["RSI"] = (
        100 -
        (100 / (1 + rs))
    )

    df["Momentum1"] = (
        df["Close"].pct_change(1) * 100
    )

    df["Momentum3"] = (
        df["Close"].pct_change(3) * 100
    )

    df["Momentum5"] = (
        df["Close"].pct_change(5) * 100
    )

    df["Momentum10"] = (
        df["Close"].pct_change(10) * 100
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
#
# IMPORTANTE:
#
# Esta predicción NO usa el Target del contrato anterior
# para decidir el contrato que estamos prediciendo.
#
# Analiza el comportamiento de BTC durante el contrato
# anterior y decide ARRIBA / ABAJO para el SIGUIENTE.
# ============================================================

def generar_prediccion(df):

    ultimo = df.iloc[-1]

    score = 0
    razones = []

    precio = float(ultimo["Close"])

    ema9 = float(ultimo["EMA9"])
    ema21 = float(ultimo["EMA21"])
    ema50 = float(ultimo["EMA50"])

    macd = float(ultimo["MACD"])
    macd_signal = float(ultimo["MACD_SIGNAL"])

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
                f"Momentum {nombre} positivo "
                f"({valor:+.3f}%)."
            )

        elif valor < 0:

            score -= peso

            razones.append(
                f"Momentum {nombre} negativo "
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
                f"RSI {rsi:.1f}: presión alcista."
            )

        else:

            score -= 5

            razones.append(
                f"RSI {rsi:.1f}: presión bajista."
            )

    # --------------------------------------------------------
    # VOLATILIDAD
    # --------------------------------------------------------

    if pd.notna(volatilidad):

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

        fuerza = min(abs(score), 60)

        confianza = int(
            round(
                50 + fuerza * 0.65
            )
        )

        confianza = max(
            50,
            min(91, confianza)
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
# BUSCAR REGISTRO POR CONTRATO PREDICHO
# ============================================================

def buscar_registro_por_predicho(ticker):

    if not ticker:
        return None

    for registro in st.session_state.historial:

        if registro.get(
            "Contrato predicho"
        ) == ticker:

            return registro

    return None


# ============================================================
# BUSCAR PREDICCIÓN PENDIENTE DE TICKER
# ============================================================

def buscar_prediccion_sin_ticker():

    registros = st.session_state.historial

    for registro in reversed(registros):

        if (
            registro.get("Contrato predicho")
            in (None, "", "PENDIENTE")
        ):

            if registro.get(
                "Predicción"
            ):

                if registro.get(
                    "Resultado"
                ) == "⏳ PENDIENTE":

                    return registro

    return None


# ============================================================
# CREAR PREDICCIÓN PARA EL SIGUIENTE
# ============================================================

def crear_prediccion_siguiente(
    contrato_actual,
    df
):

    ticker_actual = contrato_actual.get(
        "ticker"
    )

    cierre_actual = cierre_de_mercado(
        contrato_actual
    )

    if not ticker_actual or not cierre_actual:
        return None

    # --------------------------------------------------------
    # Evitar duplicados.
    # Una predicción por cada contrato base.
    # --------------------------------------------------------

    for registro in st.session_state.historial:

        if registro.get(
            "Contrato base"
        ) == ticker_actual:

            return registro

    # --------------------------------------------------------
    # Generar predicción
    # --------------------------------------------------------

    (
        prediccion,
        confianza,
        razones,
        score,
        precio
    ) = generar_prediccion(df)

    # --------------------------------------------------------
    # Intentar identificar inmediatamente
    # el siguiente contrato.
    # --------------------------------------------------------

    siguiente = buscar_siguiente_contrato(
        cierre_actual,
        ticker_actual
    )

    ticker_siguiente = None
    target_siguiente = None

    if siguiente:

        ticker_siguiente = siguiente.get(
            "ticker"
        )

        target_siguiente = obtener_target(
            siguiente
        )

    # --------------------------------------------------------
    # Registro
    # --------------------------------------------------------

    registro = {

        "Contrato base":
            ticker_actual,

        "Contrato predicho":
            ticker_siguiente,

        "Target contrato predicho":
            (
                round(
                    float(target_siguiente),
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
            round(
                float(precio),
                2
            ),

        "Cierre contrato base":
            cierre_actual
            .astimezone(LOCAL_TZ)
            .strftime(
                "%Y-%m-%d %I:%M:%S %p"
            ),

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

        "Contrato siguiente identificado":
            bool(ticker_siguiente),

        "Estado predicción":
            (
                "CONTRATO IDENTIFICADO"
                if ticker_siguiente
                else "ESPERANDO TICKER SIGUIENTE"
            )
    }

    st.session_state.historial.append(
        registro
    )

    guardar_historial(
        st.session_state.historial
    )

    return registro


# ============================================================
# VINCULAR PREDICCIÓN AL SIGUIENTE CONTRATO
# ============================================================

def vincular_predicciones_pendientes():

    cambio = False

    for registro in st.session_state.historial:

        if registro.get(
            "Resultado"
        ) != "⏳ PENDIENTE":

            continue

        ticker_predicho = registro.get(
            "Contrato predicho"
        )

        if ticker_predicho:
            continue

        ticker_base = registro.get(
            "Contrato base"
        )

        cierre_texto = registro.get(
            "Cierre contrato base"
        )

        if not ticker_base or not cierre_texto:
            continue

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

            continue

        siguiente = buscar_siguiente_contrato(
            cierre_base,
            ticker_base
        )

        if not siguiente:
            continue

        ticker_siguiente = siguiente.get(
            "ticker"
        )

        if not ticker_siguiente:
            continue

        # ----------------------------------------------------
        # Evitar asignar el mismo contrato a dos predicciones
        # ----------------------------------------------------

        otro = buscar_registro_por_predicho(
            ticker_siguiente
        )

        if otro is not None and otro is not registro:
            continue

        registro[
            "Contrato predicho"
        ] = ticker_siguiente

        registro[
            "Contrato siguiente identificado"
        ] = True

        registro[
            "Estado predicción"
        ] = "CONTRATO IDENTIFICADO"

        try:

            target = obtener_target(
                siguiente
            )

            if target is not None:

                registro[
                    "Target contrato predicho"
                ] = round(
                    float(target),
                    2
                )

        except Exception:
            pass

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
# RESOLVER RESULTADOS
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

        # ----------------------------------------------------
        # Obtener contrato real
        # ----------------------------------------------------

        try:

            mercado = obtener_contrato(
                ticker
            )

        except Exception:

            continue

        # ----------------------------------------------------
        # Target REAL del contrato predicho
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

        # ----------------------------------------------------
        # Expiration Value REAL
        # ----------------------------------------------------

        expiration = mercado.get(
            "expiration_value"
        )

        if expiration in (
            None,
            "",
            "null"
        ):

            # El contrato todavía no terminó
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
        # Guardar valores reales
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
        # RESULTADO REAL KALSHI
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
        # COMPARAR CON LA PREDICCIÓN
        # ----------------------------------------------------

        prediccion = registro.get(
            "Predicción"
        )

        if (
            prediccion == "🟢 ARRIBA"
            and resultado_kalshi == "UP"
        ):

            resultado = "✅ ACIERTO"

        elif (
            prediccion == "🔴 ABAJO"
            and resultado_kalshi == "DOWN"
        ):

            resultado = "✅ ACIERTO"

        elif resultado_kalshi == "TIE":

            resultado = "⚪ EMPATE"

        elif prediccion == "⚪ NO APOSTAR":

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


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Predicción automática del siguiente "
    "contrato BTC 15M."
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
    f"☁️ Historial sincronizado con GitHub: "
    f"{GITHUB_USERNAME}/{GITHUB_REPO}"
)


# ============================================================
# SINCRONIZAR PREDICCIONES PENDIENTES
# ============================================================

try:

    vincular_predicciones_pendientes()

except Exception:
    pass


# ============================================================
# ACTUALIZAR RESULTADOS
# ============================================================

try:

    actualizar_resultados()

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
# BTC
# ============================================================

try:

    btc, precio, fuente = obtener_btc()

    btc = calcular_indicadores(btc)

except Exception as error:

    st.error(
        f"❌ Error obteniendo BTC: {error}"
    )

    time.sleep(REFRESH_SECONDS)

    st.rerun()


# ============================================================
# SI HAY CONTRATO
# ============================================================

if actual is not None:

    ticker_actual = actual.get(
        "ticker"
    )

    close_actual = cierre_de_mercado(
        actual
    )

    # --------------------------------------------------------
    # TARGET ACTUAL
    # --------------------------------------------------------

    target_actual = obtener_target(
        actual
    )

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

    minutos = segundos_restantes // 60
    segundos = segundos_restantes % 60

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
    # BTC
    # --------------------------------------------------------

    col1, col2 = st.columns(2)

    col1.metric(
        "₿ BTC actual",
        f"${precio:,.2f}"
    )

    col2.metric(
        "🎯 Target Kalshi",
        f"${target_actual:,.2f}"
    )

    st.caption(
        f"Fuente BTC: {fuente}"
    )

    # --------------------------------------------------------
    # DIFERENCIA TARGET
    # --------------------------------------------------------

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

    # ========================================================
    # GENERAR PREDICCIÓN DEL SIGUIENTE
    # ========================================================

    if (
        segundos_restantes <= PREDICCION_SEGUNDOS
        and
        segundos_restantes > 0
    ):

        registro_base = None

        for registro in st.session_state.historial:

            if registro.get(
                "Contrato base"
            ) == ticker_actual:

                registro_base = registro
                break

        if registro_base is None:

            try:

                registro_base = (
                    crear_prediccion_siguiente(
                        actual,
                        btc
                    )
                )

                if registro_base:

                    st.success(
                        "🚨 PREDICCIÓN GENERADA "
                        "Y GUARDADA AUTOMÁTICAMENTE"
                    )

            except Exception as error:

                st.error(
                    f"❌ Error generando predicción: "
                    f"{error}"
                )

    # ========================================================
    # MOSTRAR PREDICCIÓN
    # ========================================================

    registro_base = None

    for registro in reversed(
        st.session_state.historial
    ):

        if registro.get(
            "Contrato base"
        ) == ticker_actual:

            registro_base = registro
            break

    st.divider()

    st.subheader(
        "🔮 Predicción del SIGUIENTE contrato"
    )

    if registro_base:

        pred = registro_base.get(
            "Predicción"
        )

        confianza = registro_base.get(
            "Confianza"
        )

        st.success(
            "PREDICCIÓN AUTOMÁTICA"
        )

        st.write(
            f"# {pred}"
        )

        st.metric(
            "Confianza",
            confianza
        )

        st.write(
            f"**Basada en:** "
            f"`{ticker_actual}`"
        )

        st.write(
            f"**Precio BTC al analizar:** "
            f"${float(registro_base.get('Precio BTC predicción', 0)):,.2f}"
        )

        st.write(
            f"**Score:** "
            f"{registro_base.get('Score'):+d}"
        )

        contrato_predicho = registro_base.get(
            "Contrato predicho"
        )

        if contrato_predicho:

            st.success(
                f"🎯 Contrato predicho: "
                f"`{contrato_predicho}`"
            )

            target_pred = registro_base.get(
                "Target contrato predicho"
            )

            if target_pred is not None:

                st.write(
                    f"**Target del contrato predicho:** "
                    f"${float(target_pred):,.2f}"
                )

        else:

            st.warning(
                "⏳ Predicción guardada. "
                "Kalshi todavía no ha publicado "
                "el ticker del siguiente contrato. "
                "La app lo asociará automáticamente "
                "cuando aparezca."
            )

        st.subheader(
            "📊 Análisis utilizado"
        )

        for razon in registro_base.get(
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
            "La app generará automáticamente "
            "la predicción durante los últimos "
            "2 minutos del contrato actual."
        )

        if segundos_restantes <= PREDICCION_SEGUNDOS:

            st.warning(
                "⚠️ Está dentro de la ventana "
                "de predicción pero todavía "
                "no existe una predicción guardada."
            )


# ============================================================
# SI NO HAY CONTRATO ABIERTO
# ============================================================

else:

    st.warning(
        "⏳ Kalshi no muestra en este momento "
        "un contrato BTC 15M abierto."
    )

    # Intentar vincular predicciones guardadas
    try:
        vincular_predicciones_pendientes()
        actualizar_resultados()
    except Exception:
        pass


# ============================================================
# ÚLTIMA PREDICCIÓN
# ============================================================

if st.session_state.historial:

    ultima = st.session_state.historial[-1]

    st.divider()

    st.subheader(
        "🔔 Última predicción"
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
        f"**Contrato analizado:** "
        f"`{ultima.get('Contrato base')}`"
    )

    if ultima.get(
        "Contrato predicho"
    ):

        st.write(
            f"**Contrato predicho:** "
            f"`{ultima.get('Contrato predicho')}`"
        )

    else:

        st.write(
            "**Contrato predicho:** "
            "⏳ Esperando que Kalshi lo publique"
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

historial = st.session_state.historial

if historial:

    tabla = pd.DataFrame(historial)

    columnas = [
        "Contrato base",
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
        "Cierre contrato base",
        "Momento predicción",
        "Actualizado"
    ]

    existentes = [
        c for c in columnas
        if c in tabla.columns
    ]

    restantes = [
        c for c in tabla.columns
        if c not in existentes
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
        x.get("Resultado") == "✅ ACIERTO"
        for x in historial
    )

    fallos = sum(
        x.get("Resultado") == "❌ FALLÓ"
        for x in historial
    )

    pendientes = sum(
        x.get("Resultado") == "⏳ PENDIENTE"
        for x in historial
    )

    empates = sum(
        x.get("Resultado") == "⚪ EMPATE"
        for x in historial
    )

    no_apostar = sum(
        x.get("Resultado") == "⚪ NO APOSTAR"
        for x in historial
    )

    evaluados = aciertos + fallos

    precision = (
        (aciertos / evaluados) * 100
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
        "⚠️ La predicción está guardada localmente, "
        "pero GitHub no pudo sincronizarla todavía. "
        "La aplicación seguirá intentando sincronizar."
    )


# ============================================================
# EXPLICACIÓN
# ============================================================

st.divider()

st.caption(
    "FUNCIONAMIENTO: durante los últimos 2 minutos "
    "del contrato BTC 15M actual, la aplicación "
    "analiza el movimiento de BTC y los indicadores "
    "de los últimos minutos para generar automáticamente "
    "una predicción ARRIBA o ABAJO para el siguiente "
    "contrato. No requiere aceptar ni rechazar la "
    "predicción. La predicción se guarda automáticamente. "
    "Si el ticker del siguiente contrato todavía no "
    "está disponible, queda pendiente y se vincula "
    "automáticamente cuando Kalshi lo publique. "
    "Cuando el contrato predicho termina, la aplicación "
    "obtiene su Target y su Expiration Value reales. "
    "Si Expiration Value > Target = ARRIBA. "
    "Si Expiration Value < Target = ABAJO. "
    "Después compara ese resultado con la predicción "
    "y marca automáticamente ACIERTO o FALLÓ."
)


# ============================================================
# REFRESH
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
