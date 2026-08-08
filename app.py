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

# Comenzar a buscar el siguiente contrato
PREPARAR_SEGUNDOS = 180

# Predicción definitiva cuando falte 1 minuto
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

def obtener_mercados_btc():

    data = kalshi_request(

        "GET",

        "/trade-api/v2/markets",

        params={

            "series_ticker":
                SERIES,

            "status":
                "open",

            "limit":
                100
        }
    )

    return data.get(
        "markets",
        []
    )


# ============================================================
# OBTENER CONTRATO POR TICKER
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

    mercados = obtener_mercados_btc()

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

        raise Exception(
            "No encontré un contrato BTC 15M abierto."
        )

    candidatos.sort(
        key=lambda x: x["_close"]
    )

    return candidatos[0]


# ============================================================
# CONVERTIR POSIBLE PRECIO
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

        # Evitar números absurdamente pequeños
        # o identificadores.

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

    # --------------------------------------------------------
    # DICCIONARIO
    # --------------------------------------------------------

    if isinstance(objeto, dict):

        for clave, valor in objeto.items():

            clave_lower = str(
                clave
            ).lower()

            # Campos que tienen alta probabilidad
            # de contener el strike/target.

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

            # Continuar buscando dentro
            # de estructuras anidadas.

            encontrados.extend(
                buscar_targets_recursivo(
                    valor
                )
            )

    # --------------------------------------------------------
    # LISTA
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Patrones específicos
    # --------------------------------------------------------

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

        # Preferir valores cercanos
        # al precio actual de BTC.

        return candidatos[0]


    return None


# ============================================================
# OBTENER TARGET ROBUSTO
# ============================================================

def obtener_target(mercado):

    # --------------------------------------------------------
    # 1. Buscar directamente en el objeto
    # --------------------------------------------------------

    encontrados = buscar_targets_recursivo(
        mercado
    )


    if encontrados:

        # Ordenar por prioridad.

        encontrados.sort(
            key=lambda x: x[0],
            reverse=True
        )

        return float(
            encontrados[0][1]
        )


    # --------------------------------------------------------
    # 2. Buscar en textos
    # --------------------------------------------------------

    target_texto = buscar_target_en_texto(
        mercado
    )


    if target_texto is not None:

        return float(
            target_texto
        )


    # --------------------------------------------------------
    # 3. Último intento:
    # consultar ticker individual
    # --------------------------------------------------------

    ticker = mercado.get(
        "ticker"
    )


    if ticker:

        try:

            mercado_detallado = (
                obtener_contrato(
                    ticker
                )
            )

            encontrados = (
                buscar_targets_recursivo(
                    mercado_detallado
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
                    mercado_detallado
                )
            )


            if target_texto is not None:

                return float(
                    target_texto
                )

        except Exception:

            pass


    # --------------------------------------------------------
    # No encontrado
    # --------------------------------------------------------

    raise Exception(
        "No pude encontrar el Target del contrato "
        f"{ticker if ticker else ''}."
    )


# ============================================================
# BTC BINANCE
# ============================================================

def obtener_btc():

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


    df = df.dropna(
        subset=["Close"]
    )


    return df


# ============================================================
# INDICADORES
# ============================================================

def calcular_indicadores(df):

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


    # EMA 50

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


    # Señal MACD

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
    # DISTANCIA AL TARGET
    # ========================================================

    diferencia = (
        precio -
        target
    )


    diferencia_pct = (

        diferencia /
        target
    ) * 100


    # Esta es una de las señales principales.

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
    # EMA 9 / EMA 21
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
    # EMA 21 / EMA 50
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

                f"RSI {rsi:.1f}: "
                "sobreventa, posible rebote."
            )


        elif rsi > 70:

            score -= 5

            razones.append(

                f"RSI {rsi:.1f}: "
                "sobrecompra, posible corrección."
            )


        elif rsi >= 50:

            score += 3

            razones.append(

                f"RSI {rsi:.1f}: "
                "ligeramente alcista."
            )


        else:

            score -= 3

            razones.append(

                f"RSI {rsi:.1f}: "
                "ligeramente bajista."
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

            return


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


# ============================================================
# BUSCAR SIGUIENTE CONTRATO
# ============================================================

def buscar_siguiente_contrato(
    contrato_actual
):

    mercados = obtener_mercados_btc()


    cierre_actual = (
        contrato_actual.get(
            "_close"
        )
    )


    if cierre_actual is None:

        cierre_actual = convertir_fecha(
            contrato_actual.get(
                "close_time"
            )
        )


    candidatos = []


    for mercado in mercados:

        ticker = mercado.get(
            "ticker"
        )


        if ticker == contrato_actual.get(
            "ticker"
        ):

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


        if cierre_actual is not None:

            if cierre <= cierre_actual:

                continue


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
# OBTENER RESULTADO KALSHI
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
    # Resultado oficial
    # --------------------------------------------------------

    if resultado not in (
        None,
        "",
        "null"
    ):

        resultado = str(
            resultado
        ).upper()


        if resultado in (
            "UP",
            "YES"
        ):

            return "UP", expiration


        if resultado in (
            "DOWN",
            "NO"
        ):

            return "DOWN", expiration


    # --------------------------------------------------------
    # Expiration Value
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
# ACTUALIZAR RESULTADOS
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


if "siguiente_contrato" not in st.session_state:

    st.session_state.siguiente_contrato = None


if "prediccion_hecha" not in st.session_state:

    st.session_state.prediccion_hecha = False


if "prediccion" not in st.session_state:

    st.session_state.prediccion = None


if "confianza" not in st.session_state:

    st.session_state.confianza = 0


if "target_siguiente" not in st.session_state:

    st.session_state.target_siguiente = None


if "precio_prediccion" not in st.session_state:

    st.session_state.precio_prediccion = None


if "razones" not in st.session_state:

    st.session_state.razones = []


if "score" not in st.session_state:

    st.session_state.score = 0


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Predicción del siguiente contrato usando "
    "Target de Kalshi + comportamiento del mercado."
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

except Exception as error:

    st.warning(
        f"No se pudieron actualizar algunos "
        f"resultados: {error}"
    )


# ============================================================
# EJECUCIÓN
# ============================================================

try:

    # ========================================================
    # CONTRATO ACTUAL
    # ========================================================

    actual = buscar_mercado_actual()


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


    # --------------------------------------------------------
    # TARGET ACTUAL
    # --------------------------------------------------------

    try:

        target_actual = obtener_target(
            actual
        )

        target_actual_error = None

    except Exception as error:

        target_actual = None

        target_actual_error = str(
            error
        )


    # ========================================================
    # DETECTAR CAMBIO DE CONTRATO
    # ========================================================

    if (

        st.session_state.ticker_actual
        != ticker_actual

    ):

        st.session_state.ticker_actual = (
            ticker_actual
        )

        st.session_state.siguiente_contrato = None

        st.session_state.prediccion_hecha = False

        st.session_state.prediccion = None

        st.session_state.confianza = 0

        st.session_state.target_siguiente = None

        st.session_state.precio_prediccion = None

        st.session_state.razones = []

        st.session_state.score = 0


    # ========================================================
    # BTC
    # ========================================================

    btc = obtener_btc()

    btc = calcular_indicadores(
        btc
    )


    precio = float(
        btc["Close"].iloc[-1]
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
    # BUSCAR SIGUIENTE CONTRATO
    # ========================================================

    if (

        segundos_restantes
        <= PREPARAR_SEGUNDOS

        and

        st.session_state.siguiente_contrato
        is None

    ):

        try:

            siguiente = (
                buscar_siguiente_contrato(
                    actual
                )
            )


            if siguiente is not None:

                target_siguiente = (
                    obtener_target(
                        siguiente
                    )
                )


                st.session_state.siguiente_contrato = {

                    "ticker":
                        siguiente.get(
                            "ticker"
                        ),

                    "target":
                        target_siguiente,

                    "close":
                        siguiente.get(
                            "_close"
                        )
                }


        except Exception as error:

            st.session_state.siguiente_error = str(
                error
            )


    # ========================================================
    # GENERAR PREDICCIÓN
    # ========================================================

    if (

        segundos_restantes
        <= PREDICCION_SEGUNDOS

        and

        segundos_restantes > 0

        and

        not st.session_state.prediccion_hecha

    ):


        siguiente_info = (
            st.session_state.siguiente_contrato
        )


        if siguiente_info is not None:

            ticker_siguiente = (
                siguiente_info["ticker"]
            )


            target_siguiente = (
                siguiente_info["target"]
            )


            close_siguiente = (
                siguiente_info["close"]
            )


            if close_siguiente is None:

                close_siguiente = (
                    datetime.now(
                        timezone.utc
                    )
                )


            (

                prediccion,

                confianza,

                razones,

                score

            ) = generar_prediccion(

                btc,

                target_siguiente
            )


            guardar_prediccion(

                ticker=ticker_siguiente,

                target=target_siguiente,

                prediccion=prediccion,

                confianza=confianza,

                precio=precio,

                close_time=close_siguiente,

                score=score
            )


            st.session_state.prediccion_hecha = True

            st.session_state.prediccion = (
                prediccion
            )

            st.session_state.confianza = (
                confianza
            )

            st.session_state.target_siguiente = (
                target_siguiente
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


    # ========================================================
    # CONTRATO ACTUAL
    # ========================================================

    st.subheader(
        "🎯 Contrato actual"
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
            "🎯 Target actual",
            f"${target_actual:,.2f}"
        )

    else:

        col2.metric(
            "🎯 Target actual",
            "No disponible"
        )


    # ========================================================
    # DIFERENCIA TARGET ACTUAL
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
            "⚠️ Kalshi no entregó el Target actual "
            "en el formato esperado."
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

            f"🟡 PREPARANDO SIGUIENTE CONTRATO — "
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


    # ========================================================
    # SIGUIENTE CONTRATO
    # ========================================================

    st.divider()


    st.subheader(
        "🔮 Siguiente contrato"
    )


    siguiente_info = (
        st.session_state.siguiente_contrato
    )


    if siguiente_info is not None:

        st.success(

            "✅ Siguiente contrato encontrado"
        )


        st.write(

            f"**Ticker:** "
            f"`{siguiente_info['ticker']}`"
        )


        st.write(

            f"**🎯 Target siguiente:** "
            f"${siguiente_info['target']:,.2f}"
        )


        diferencia_siguiente = (

            precio -
            float(
                siguiente_info["target"]
            )
        )


        porcentaje_siguiente = (

            diferencia_siguiente /
            float(
                siguiente_info["target"]
            )
        ) * 100


        if diferencia_siguiente > 0:

            st.success(

                f"BTC está ${diferencia_siguiente:,.2f} "
                f"({porcentaje_siguiente:+.3f}%) "
                "POR ENCIMA del Target siguiente."
            )


        elif diferencia_siguiente < 0:

            st.error(

                f"BTC está ${abs(diferencia_siguiente):,.2f} "
                f"({porcentaje_siguiente:+.3f}%) "
                "POR DEBAJO del Target siguiente."
            )


        else:

            st.warning(
                "BTC está exactamente en el Target siguiente."
            )


    else:

        if segundos_restantes <= 180:

            st.warning(

                "🔎 Buscando el siguiente contrato "
                "y su Target en Kalshi..."
            )

        else:

            st.info(

                "La aplicación comenzará a buscar "
                "el siguiente contrato cuando falten "
                "3 minutos."
            )


    # ========================================================
    # PREDICCIÓN
    # ========================================================

    st.divider()


    st.subheader(
        "🔮 Predicción del SIGUIENTE contrato"
    )


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
            f"`{siguiente_info['ticker']}`"
        )


        st.write(

            f"**Target:** "
            f"${st.session_state.target_siguiente:,.2f}"
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

        if segundos_restantes > 60:

            faltan = (
                segundos_restantes -
                60
            )


            mm = (
                faltan // 60
            )


            ss = (
                faltan % 60
            )


            st.info(

                "⏱️ La predicción se generará "
                "cuando falte 1 minuto. "

                f"Faltan aproximadamente "
                f"{mm:02d}:{ss:02d}."
            )


        else:

            st.warning(

                "⚠️ Estamos dentro del último minuto. "
                "La aplicación está intentando generar "
                "la predicción."
            )


    # ========================================================
    # GRÁFICO
    # ========================================================

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

        "El sistema observa el contrato actual, "
        "localiza el siguiente contrato de Kalshi "
        "y utiliza su Target junto con EMA, MACD, RSI, "
        "momentum y volatilidad de BTC. "
        "La predicción definitiva se genera durante "
        "el último minuto del contrato actual."
    )


except Exception as error:

    st.error(
        "❌ Error de ejecución"
    )

    st.code(
        str(error)
    )


# ============================================================
# ACTUALIZACIÓN AUTOMÁTICA
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
