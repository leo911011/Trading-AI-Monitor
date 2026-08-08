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

# Analizar durante los últimos 2 minutos
PREDICCION_SEGUNDOS = 120

# Últimos contratos cerrados que se usarán como señal
CONTRATOS_KALSHI_ANALISIS = 3


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
# URL DEL HISTORIAL
# ============================================================

def github_historial_url():

    return (
        f"{GITHUB_API}/repos/"
        f"{GITHUB_USERNAME}/"
        f"{GITHUB_REPO}/contents/"
        f"{HISTORIAL_FILE}"
    )


# ============================================================
# LEER ARCHIVO DE GITHUB
# ============================================================

def leer_archivo_github():

    if not GITHUB_USERNAME:
        raise Exception("Falta GITHUB_USERNAME.")

    response = requests.get(
        github_historial_url(),
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=15
    )

    if response.status_code == 404:
        return [], None, "NOT_FOUND"

    if response.status_code >= 400:
        raise Exception(
            f"GitHub HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    data = response.json()

    contenido = data.get("content")

    if not contenido:
        return [], data.get("sha"), "EMPTY"

    try:

        texto = base64.b64decode(
            contenido.replace("\n", "")
        ).decode("utf-8")

        historial = json.loads(texto)

        if not isinstance(historial, list):
            raise Exception(
                "El historial de GitHub no contiene una lista."
            )

        return (
            historial,
            data.get("sha"),
            "OK"
        )

    except Exception as error:

        raise Exception(
            f"Error leyendo historial de GitHub: {error}"
        )


# ============================================================
# GUARDAR COPIA LOCAL
# ============================================================

def guardar_copia_local(historial):

    try:

        temporal = HISTORIAL_FILE + ".tmp"

        with open(
            temporal,
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
            temporal,
            HISTORIAL_FILE
        )

        return True

    except Exception:

        return False


# ============================================================
# CARGAR COPIA LOCAL
# ============================================================

def cargar_copia_local():

    try:

        if not os.path.exists(
            HISTORIAL_FILE
        ):

            return []

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
# IDENTIFICADOR ÚNICO DEL REGISTRO
# ============================================================

def clave_registro(registro):

    contrato_base = registro.get(
        "Contrato base"
    )

    if contrato_base:
        return f"BASE::{contrato_base}"

    contrato_predicho = registro.get(
        "Contrato predicho"
    )

    if contrato_predicho:
        return f"PRED::{contrato_predicho}"

    momento = registro.get(
        "Momento predicción"
    )

    return f"OTRO::{momento}"


# ============================================================
# COMBINAR HISTORIALES
#
# GitHub es la memoria permanente.
# El historial local se utiliza para recuperar
# información que todavía no haya llegado a GitHub.
# ============================================================

def combinar_historiales(remoto, local):

    combinado = {}

    # Primero el remoto
    for registro in remoto:

        if not isinstance(registro, dict):
            continue

        combinado[
            clave_registro(registro)
        ] = registro.copy()

    # Después el local.
    # El registro local más actualizado puede contener
    # un resultado que todavía no estaba en remoto.
    for registro in local:

        if not isinstance(registro, dict):
            continue

        clave = clave_registro(registro)

        if clave not in combinado:

            combinado[clave] = registro.copy()

        else:

            existente = combinado[clave].copy()

            for campo, valor in registro.items():

                if valor not in (
                    None,
                    "",
                    "PENDIENTE"
                ):

                    existente[campo] = valor

            combinado[clave] = existente

    resultado = list(
        combinado.values()
    )

    # Orden cronológico
    resultado.sort(
        key=lambda x: str(
            x.get(
                "Momento predicción",
                ""
            )
        )
    )

    return resultado


# ============================================================
# GUARDAR EN GITHUB CON REINTENTOS
# ============================================================

def guardar_historial_github(
    historial,
    max_intentos=5
):

    if not GITHUB_USERNAME:
        raise Exception(
            "Falta GITHUB_USERNAME."
        )

    if not GITHUB_TOKEN:
        raise Exception(
            "Falta GITHUB_TOKEN."
        )

    ultimo_error = None

    for intento in range(
        1,
        max_intentos + 1
    ):

        try:

            # ----------------------------------------------
            # IMPORTANTE:
            # Antes de escribir volvemos a leer GitHub.
            # Esto evita usar un SHA viejo.
            # ----------------------------------------------

            remoto, sha, estado = (
                leer_archivo_github()
            )

            # ----------------------------------------------
            # Fusionar remoto + historial actual
            # ----------------------------------------------

            historial_final = combinar_historiales(
                remoto,
                historial
            )

            contenido = json.dumps(
                historial_final,
                indent=2,
                ensure_ascii=False
            )

            contenido_b64 = base64.b64encode(
                contenido.encode("utf-8")
            ).decode("utf-8")

            payload = {
                "message":
                    "Actualizar historial BTC Kalshi",
                "content":
                    contenido_b64,
                "branch":
                    GITHUB_BRANCH
            }

            if sha:
                payload["sha"] = sha

            response = requests.put(
                github_historial_url(),
                headers=github_headers(),
                json=payload,
                timeout=20
            )

            # ----------------------------------------------
            # ÉXITO
            # ----------------------------------------------

            if response.status_code in (
                200,
                201
            ):

                guardar_copia_local(
                    historial_final
                )

                st.session_state.github_error = None

                return (
                    True,
                    historial_final
                )

            # ----------------------------------------------
            # CONFLICTO
            # Volver a leer GitHub y reintentar.
            # ----------------------------------------------

            if response.status_code in (
                409,
                422
            ):

                ultimo_error = (
                    f"GitHub HTTP "
                    f"{response.status_code}: "
                    f"{response.text[:500]}"
                )

                time.sleep(
                    min(
                        1.5 * intento,
                        5
                    )
                )

                continue

            # ----------------------------------------------
            # ERROR DE AUTORIZACIÓN
            # ----------------------------------------------

            if response.status_code in (
                401,
                403
            ):

                raise Exception(
                    f"GitHub HTTP "
                    f"{response.status_code}: "
                    f"{response.text[:800]}"
                )

            # ----------------------------------------------
            # OTRO ERROR
            # ----------------------------------------------

            ultimo_error = (
                f"GitHub HTTP "
                f"{response.status_code}: "
                f"{response.text[:800]}"
            )

            time.sleep(1)

        except Exception as error:

            ultimo_error = str(error)

            if intento < max_intentos:

                time.sleep(
                    min(
                        1.5 * intento,
                        5
                    )
                )

    raise Exception(
        "No fue posible sincronizar con GitHub "
        f"después de {max_intentos} intentos. "
        f"Último error: {ultimo_error}"
    )


# ============================================================
# CARGAR HISTORIAL PERMANENTE
# ============================================================

def cargar_historial():

    local = cargar_copia_local()

    try:

        remoto, sha, estado = (
            leer_archivo_github()
        )

        # ----------------------------------------------
        # Si GitHub tiene información, la combinamos.
        # ----------------------------------------------

        historial = combinar_historiales(
            remoto,
            local
        )

        guardar_copia_local(
            historial
        )

        # ----------------------------------------------
        # Si el remoto estaba vacío pero el local
        # tenía información, intentamos recuperarla.
        # ----------------------------------------------

        if (
            len(remoto) == 0
            and len(local) > 0
        ):

            try:

                guardar_historial_github(
                    local
                )

            except Exception as error:

                st.session_state.github_error = (
                    str(error)
                )

        return historial

    except Exception as error:

        # ----------------------------------------------
        # MUY IMPORTANTE:
        # Si GitHub falla, NO reemplazamos el historial
        # por [].
        # ----------------------------------------------

        st.session_state.github_error = str(
            error
        )

        return local


# ============================================================
# GUARDAR HISTORIAL COMPLETO
# ============================================================

def guardar_historial(historial):

    # Primero guardamos localmente
    guardar_copia_local(
        historial
    )

    try:

        exito, historial_final = (
            guardar_historial_github(
                historial
            )
        )

        # Actualizamos el estado con la versión
        # realmente fusionada.
        st.session_state.historial = (
            historial_final
        )

        return True

    except Exception as error:

        st.session_state.github_error = (
            str(error)
        )

        # NO borramos la información local.
        return False


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
            "Falta KALSHI_PRIVATE_KEY."
        )

    try:

        return (
            serialization
            .load_pem_private_key(
                PRIVATE_KEY.strip().encode(
                    "utf-8"
                ),
                password=None
            )
        )

    except Exception as error:

        raise Exception(
            "KALSHI_PRIVATE_KEY inválida."
        ) from error


# ============================================================
# FIRMA KALSHI
# ============================================================

def crear_firma(
    timestamp,
    method,
    path
):

    private_key = (
        cargar_clave_privada()
    )

    path_sin_query = (
        path.split("?")[0]
    )

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
            salt_length=(
                padding.PSS.DIGEST_LENGTH
            )
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
            f"{response.text[:800]}"
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

        return fecha

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

def obtener_contrato(
    ticker
):

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
# FECHA CIERRE
# ============================================================

def cierre_de_mercado(
    mercado
):

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

            mercado["_close"] = (
                cierre
            )

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
    ticker_actual
):

    if not cierre_actual:
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

def convertir_numero_precio(
    valor
):

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

        for clave, valor in (
            objeto.items()
        ):

            clave_lower = (
                str(clave).lower()
            )

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

        r"target[^0-9]*"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",

        r"strike[^0-9]*"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)"
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
            "symbol":
                "BTCUSDT"
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

    df = df.tail(
        120
    ).copy()

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
# HISTORIAL DE LOS ÚLTIMOS CONTRATOS KALSHI
# ============================================================

def obtener_ultimos_contratos_kalshi():

    try:

        mercados = obtener_mercados_btc(
            status="closed",
            limit=20
        )

    except Exception:

        return []


    resultados = []

    for mercado in mercados:

        ticker = mercado.get(
            "ticker"
        )

        if not ticker:
            continue

        target = obtener_target(
            mercado
        )

        expiration = mercado.get(
            "expiration_value"
        )

        if (
            target is None
            or expiration in (
                None,
                "",
                "null"
            )
        ):
            continue

        try:

            target = float(target)
            expiration = float(
                expiration
            )

        except Exception:

            continue

        if expiration > target:

            direccion = "UP"

        elif expiration < target:

            direccion = "DOWN"

        else:

            direccion = "TIE"

        cierre = cierre_de_mercado(
            mercado
        )

        resultados.append({
            "ticker": ticker,
            "target": target,
            "expiration": expiration,
            "direccion": direccion,
            "cierre": cierre
        })

    resultados.sort(
        key=lambda x:
            x["cierre"]
            if x["cierre"]
            else datetime.min.replace(
                tzinfo=timezone.utc
            ),
        reverse=True
    )

    return resultados[
        :CONTRATOS_KALSHI_ANALISIS
    ]


# ============================================================
# PREDICCIÓN
# ============================================================

def generar_prediccion(
    df,
    contratos_kalshi=None
):

    ultimo = df.iloc[-1]

    score = 0
    razones = []

    # --------------------------------------------------------
    # VALORES
    # --------------------------------------------------------

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

    # ========================================================
    # EMA
    # ========================================================

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

    # ========================================================
    # MOMENTUM
    # ========================================================

    for nombre, valor, peso in [

        (
            "1m",
            momentum1,
            5
        ),

        (
            "3m",
            momentum3,
            7
        ),

        (
            "5m",
            momentum5,
            8
        ),

        (
            "10m",
            momentum10,
            10
        )
    ]:

        if pd.isna(valor):
            continue

        valor = float(
            valor
        )

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

    # ========================================================
    # RSI
    # ========================================================

    if pd.notna(rsi):

        rsi = float(
            rsi
        )

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

    # ========================================================
    # ÚLTIMOS 3 CONTRATOS KALSHI
    # ========================================================

    kalshi_up = 0
    kalshi_down = 0
    kalshi_tie = 0

    if contratos_kalshi:

        for contrato in (
            contratos_kalshi
        ):

            direccion = (
                contrato.get(
                    "direccion"
                )
            )

            if direccion == "UP":

                kalshi_up += 1

            elif direccion == "DOWN":

                kalshi_down += 1

            else:

                kalshi_tie += 1

        # ----------------------------------------------------
        # Los contratos anteriores aportan señal,
        # pero no dominan completamente al BTC actual.
        # ----------------------------------------------------

        if kalshi_up >= 2:

            score += 12

            razones.append(
                f"Últimos "
                f"{len(contratos_kalshi)} "
                "contratos de Kalshi: "
                f"{kalshi_up} ARRIBA."
            )

        elif kalshi_down >= 2:

            score -= 12

            razones.append(
                f"Últimos "
                f"{len(contratos_kalshi)} "
                "contratos de Kalshi: "
                f"{kalshi_down} ABAJO."
            )

        else:

            razones.append(
                f"Últimos "
                f"{len(contratos_kalshi)} "
                "contratos de Kalshi "
                "sin señal dominante."
            )

        # ----------------------------------------------------
        # Mostrar detalle
        # ----------------------------------------------------

        for contrato in (
            contratos_kalshi
        ):

            razones.append(
                f"Kalshi "
                f"{contrato.get('ticker')}: "
                f"{contrato.get('direccion')} "
                f"(Target "
                f"${contrato.get('target'):,.2f}, "
                f"Expiration "
                f"${contrato.get('expiration'):,.2f})."
            )

    else:

        razones.append(
            "No se pudieron obtener "
            "los últimos contratos de Kalshi."
        )

    # ========================================================
    # VOLATILIDAD
    # ========================================================

    if pd.notna(
        volatilidad
    ):

        razones.append(
            "Volatilidad: "
            f"{float(volatilidad):.4f}%."
        )

    # ========================================================
    # RESULTADO
    # ========================================================

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
            80
        )

        confianza = int(
            round(
                50 +
                fuerza * 0.55
            )
        )

        confianza = max(
            50,
            min(
                95,
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
# BUSCAR REGISTRO
# ============================================================

def buscar_registro_por_base(
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
# CREAR PREDICCIÓN PARA SIGUIENTE CONTRATO
# ============================================================

def crear_prediccion_siguiente(
    contrato_actual,
    df
):

    ticker_actual = (
        contrato_actual.get(
            "ticker"
        )
    )

    cierre_actual = (
        cierre_de_mercado(
            contrato_actual
        )
    )

    if (
        not ticker_actual
        or not cierre_actual
    ):

        return None

    # --------------------------------------------------------
    # EVITAR DUPLICADOS
    # --------------------------------------------------------

    existente = (
        buscar_registro_por_base(
            ticker_actual
        )
    )

    if existente:

        return existente

    # ========================================================
    # ÚLTIMOS 3 CONTRATOS KALSHI
    # ========================================================

    contratos_kalshi = (
        obtener_ultimos_contratos_kalshi()
    )

    # ========================================================
    # GENERAR PREDICCIÓN
    # ========================================================

    (
        prediccion,
        confianza,
        razones,
        score,
        precio
    ) = generar_prediccion(
        df,
        contratos_kalshi
    )

    # ========================================================
    # SIGUIENTE CONTRATO
    # ========================================================

    siguiente = (
        buscar_siguiente_contrato(
            cierre_actual,
            ticker_actual
        )
    )

    ticker_siguiente = None
    target_siguiente = None

    if siguiente:

        ticker_siguiente = (
            siguiente.get(
                "ticker"
            )
        )

        target_siguiente = (
            obtener_target(
                siguiente
            )
        )

    # ========================================================
    # REGISTRO
    # ========================================================

    registro = {

        "Contrato base":
            ticker_actual,

        "Contrato predicho":
            ticker_siguiente,

        "Target contrato predicho":
            (
                round(
                    float(
                        target_siguiente
                    ),
                    2
                )
                if target_siguiente
                is not None
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
            .astimezone(
                LOCAL_TZ
            )
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
            bool(
                ticker_siguiente
            ),

        "Estado predicción":
            (
                "CONTRATO IDENTIFICADO"
                if ticker_siguiente
                else
                "ESPERANDO TICKER SIGUIENTE"
            )
    }

    st.session_state.historial.append(
        registro
    )

    # ========================================================
    # GUARDAR INMEDIATAMENTE
    # ========================================================

    guardar_historial(
        st.session_state.historial
    )

    return registro


# ============================================================
# VINCULAR PREDICCIONES
# ============================================================

def vincular_predicciones_pendientes():

    cambio = False

    for registro in (
        st.session_state.historial
    ):

        if registro.get(
            "Resultado"
        ) != "⏳ PENDIENTE":

            continue

        ticker_predicho = (
            registro.get(
                "Contrato predicho"
            )
        )

        if ticker_predicho:
            continue

        ticker_base = (
            registro.get(
                "Contrato base"
            )
        )

        cierre_texto = (
            registro.get(
                "Cierre contrato base"
            )
        )

        if (
            not ticker_base
            or not cierre_texto
        ):

            continue

        try:

            cierre_base = (
                datetime.strptime(
                    cierre_texto,
                    "%Y-%m-%d %I:%M:%S %p"
                )
                .replace(
                    tzinfo=LOCAL_TZ
                )
                .astimezone(
                    timezone.utc
                )
            )

        except Exception:

            continue

        siguiente = (
            buscar_siguiente_contrato(
                cierre_base,
                ticker_base
            )
        )

        if not siguiente:
            continue

        ticker_siguiente = (
            siguiente.get(
                "ticker"
            )
        )

        if not ticker_siguiente:
            continue

        # ----------------------------------------------------
        # Evitar duplicados
        # ----------------------------------------------------

        otro = (
            buscar_registro_por_predicho(
                ticker_siguiente
            )
        )

        if (
            otro is not None
            and otro is not registro
        ):

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

            target = (
                obtener_target(
                    siguiente
                )
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

    for registro in (
        st.session_state.historial
    ):

        if registro.get(
            "Resultado"
        ) != "⏳ PENDIENTE":

            continue

        ticker = (
            registro.get(
                "Contrato predicho"
            )
        )

        if not ticker:
            continue

        try:

            mercado = (
                obtener_contrato(
                    ticker
                )
            )

        except Exception:

            continue

        # ====================================================
        # TARGET REAL
        # ====================================================

        target = (
            registro.get(
                "Target contrato predicho"
            )
        )

        if target is None:

            try:

                target = (
                    obtener_target(
                        mercado
                    )
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

        # ====================================================
        # EXPIRATION VALUE
        # ====================================================

        expiration = (
            mercado.get(
                "expiration_value"
            )
        )

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

        # ====================================================
        # GUARDAR VALORES
        # ====================================================

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

        # ====================================================
        # RESULTADO KALSHI
        # ====================================================

        if expiration > target:

            resultado_kalshi = "UP"

        elif expiration < target:

            resultado_kalshi = "DOWN"

        else:

            resultado_kalshi = "TIE"

        registro[
            "Resultado Kalshi"
        ] = resultado_kalshi

        # ====================================================
        # COMPARAR PREDICCIÓN
        # ====================================================

        prediccion = (
            registro.get(
                "Predicción"
            )
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

        elif (
            resultado_kalshi == "TIE"
        ):

            resultado = "⚪ EMPATE"

        elif (
            prediccion ==
            "⚪ NO APOSTAR"
        ):

            resultado = (
                "⚪ NO APOSTAR"
            )

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

    # ========================================================
    # GUARDAR RESULTADOS INMEDIATAMENTE
    # ========================================================

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
    "Predicción automática de cada "
    "contrato BTC 15 minutos."
)

st.caption(
    f"☁️ Memoria permanente: "
    f"{GITHUB_USERNAME}/"
    f"{GITHUB_REPO}/"
    f"{HISTORIAL_FILE}"
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


# ============================================================
# SINCRONIZACIÓN INICIAL
# ============================================================

try:

    # Volvemos a leer GitHub al iniciar cada ejecución.
    # Esto permite recuperar el historial después de reiniciar.
    historial_remoto, sha_remoto, estado_remoto = (
        leer_archivo_github()
    )

    historial_local = (
        cargar_copia_local()
    )

    historial_combinado = (
        combinar_historiales(
            historial_remoto,
            historial_local
        )
    )

    st.session_state.historial = (
        historial_combinado
    )

    guardar_copia_local(
        historial_combinado
    )

    # Si había datos locales que todavía no estaban
    # en GitHub, intentamos subirlos.
    if len(historial_combinado) > len(
        historial_remoto
    ):

        try:

            exito, historial_guardado = (
                guardar_historial_github(
                    historial_combinado
                )
            )

            if exito:

                st.session_state.historial = (
                    historial_guardado
                )

        except Exception as error:

            st.session_state.github_error = (
                str(error)
            )

except Exception as error:

    # JAMÁS reemplazar el historial por [].
    st.session_state.github_error = (
        str(error)
    )

    if not st.session_state.historial:

        st.session_state.historial = (
            cargar_copia_local()
        )


# ============================================================
# ACTUALIZAR RESULTADOS ANTERIORES
# ============================================================

try:

    vincular_predicciones_pendientes()

except Exception:
    pass


try:

    actualizar_resultados()

except Exception:
    pass


# ============================================================
# BUSCAR CONTRATO ACTUAL
# ============================================================

try:

    actual = (
        buscar_contrato_actual()
    )

except Exception as error:

    actual = None

    st.error(
        f"❌ Error consultando Kalshi: "
        f"{error}"
    )


# ============================================================
# BTC
# ============================================================

try:

    btc, precio, fuente = (
        obtener_btc()
    )

    btc = (
        calcular_indicadores(
            btc
        )
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
# CONTRATO ACTUAL
# ============================================================

if actual is not None:

    ticker_actual = (
        actual.get(
            "ticker"
        )
    )

    close_actual = (
        cierre_de_mercado(
            actual
        )
    )

    target_actual = (
        obtener_target(
            actual
        )
    )

    # ========================================================
    # TIEMPO
    # ========================================================

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

    # ========================================================
    # CONTRATO
    # ========================================================

    st.subheader(
        "🎯 Contrato actualmente vigente"
    )

    st.write(
        f"**Ticker:** "
        f"`{ticker_actual}`"
    )

    if actual.get(
        "title"
    ):

        st.write(
            actual.get(
                "title"
            )
        )

    if actual.get(
        "subtitle"
    ):

        st.caption(
            actual.get(
                "subtitle"
            )
        )

    # ========================================================
    # BTC
    # ========================================================

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

    else:

        col2.metric(
            "🎯 Target Kalshi",
            "No disponible"
        )

    st.caption(
        f"Fuente BTC: {fuente}"
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
            f"{minutos:02d}:"
            f"{segundos:02d}"
        )

    elif (
        segundos_restantes
        <= PREDICCION_SEGUNDOS
    ):

        st.warning(
            f"🟡 VENTANA DE PREDICCIÓN — "
            f"{minutos:02d}:"
            f"{segundos:02d}"
        )

    else:

        st.info(
            f"⏱️ "
            f"{minutos:02d}:"
            f"{segundos:02d}"
        )

    st.write(
        "Cierre:",
        close_actual
        .astimezone(
            LOCAL_TZ
        )
        .strftime(
            "%I:%M:%S %p"
        )
    )

    # ========================================================
    # PREDICCIÓN DEL SIGUIENTE CONTRATO
    # ========================================================

    registro_base = (
        buscar_registro_por_base(
            ticker_actual
        )
    )

    # --------------------------------------------------------
    # Durante los últimos 2 minutos se genera.
    # --------------------------------------------------------

    if (
        registro_base is None
        and
        segundos_restantes
        <= PREDICCION_SEGUNDOS
        and
        segundos_restantes > 0
    ):

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
                    "Y GUARDADA."
                )

        except Exception as error:

            st.error(
                "❌ Error generando "
                f"predicción: {error}"
            )

    # ========================================================
    # MOSTRAR PREDICCIÓN
    # ========================================================

    registro_base = (
        buscar_registro_por_base(
            ticker_actual
        )
    )

    st.divider()

    st.subheader(
        "🔮 Predicción para "
        "el SIGUIENTE contrato"
    )

    if registro_base:

        pred = (
            registro_base.get(
                "Predicción"
            )
        )

        confianza = (
            registro_base.get(
                "Confianza"
            )
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
            f"**Contrato base:** "
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

        contrato_predicho = (
            registro_base.get(
                "Contrato predicho"
            )
        )

        if contrato_predicho:

            st.success(
                f"🎯 Contrato predicho: "
                f"`{contrato_predicho}`"
            )

            target_pred = (
                registro_base.get(
                    "Target contrato predicho"
                )
            )

            if target_pred is not None:

                st.write(
                    f"**Target del contrato "
                    f"predicho:** "
                    f"${float(target_pred):,.2f}"
                )

        else:

            st.warning(
                "⏳ La predicción está guardada. "
                "Esperando que Kalshi publique "
                "el ticker del siguiente contrato."
            )

        st.write(
            f"**Estado:** "
            f"{registro_base.get('Resultado')}"
        )

        st.subheader(
            "📊 Análisis utilizado"
        )

        for razon in (
            registro_base.get(
                "Análisis",
                []
            )
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
            "La app generará automáticamente "
            "la predicción durante los últimos "
            "2 minutos del contrato actual."
        )

        st.caption(
            f"Tiempo aproximado hasta la ventana: "
            f"{mm:02d}:{ss:02d}"
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
        "🔔 Última predicción guardada"
    )

    st.write(
        f"**Contrato:** "
        f"`{ultima.get('Contrato base')}`"
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
        "Contrato predicho"
    ):

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
        "Close":
            "BTC"
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

historial = (
    st.session_state.historial
)

if historial:

    tabla = pd.DataFrame(
        historial
    )

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
            f"⚪ No apostar: "
            f"{no_apostar}"
        )

else:

    st.info(
        "Todavía no hay predicciones guardadas."
    )


# ============================================================
# ESTADO DE GITHUB
# ============================================================

if st.session_state.github_error:

    st.error(
        "⚠️ GitHub presenta un problema "
        "de sincronización."
    )

    st.caption(
        "La información se conserva en la "
        "copia local y la aplicación seguirá "
        "intentando sincronizar."
    )

    # Mostrar el error técnico para poder
    # identificar cualquier problema real.
    with st.expander(
        "Ver detalle de sincronización"
    ):

        st.code(
            str(
                st.session_state.github_error
            )
        )

else:

    st.success(
        "☁️ Historial sincronizado "
        "correctamente con GitHub."
    )


# ============================================================
# EXPLICACIÓN
# ============================================================

st.divider()

st.caption(
    "FUNCIONAMIENTO: la aplicación observa "
    "el contrato BTC 15M actual. Durante los "
    "últimos 2 minutos analiza el movimiento "
    "reciente de BTC, indicadores técnicos y "
    "los últimos 3 contratos cerrados de Kalshi. "
    "Con esa información genera una predicción "
    "para el siguiente contrato. La predicción "
    "se guarda inmediatamente. Cuando el siguiente "
    "contrato termina, la aplicación obtiene su "
    "Target y Expiration Value reales y determina "
    "si terminó ARRIBA o ABAJO. Después compara "
    "ese resultado con la predicción y guarda "
    "permanentemente ACIERTO, FALLÓ o EMPATE. "
    "El historial se sincroniza con GitHub y se "
    "recupera nuevamente al reiniciar la aplicación."
)


# ============================================================
# REFRESH
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
