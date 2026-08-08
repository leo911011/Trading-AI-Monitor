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
SERIES = "KXBTC15M"

LOCAL_TZ = ZoneInfo("America/Chicago")

HISTORIAL_FILE = "historial_kalshi.json"

REFRESH_SECONDS = 5

# La predicción del SIGUIENTE contrato se hace
# durante el último minuto del contrato actual.
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
# CONTRATO POR TICKER
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
# ENCONTRAR CONTRATO ACTUAL
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

        return None

    candidatos.sort(
        key=lambda x: x["_close"]
    )

    return candidatos[0]


# ============================================================
# CONVERTIR PRECIO
# ============================================================

def convertir_numero_precio(valor):

    if valor is None:
        return None

    try:

        texto = str(valor)

        texto = (
            texto
            .replace(",", "")
            .replace("$", "")
            .strip()
        )

        numero = float(texto)

        if numero > 1000:

            return numero

    except Exception:

        return None

    return None


# ============================================================
# BUSCADOR RECURSIVO TARGET
# ============================================================

def buscar_targets_recursivo(objeto):

    encontrados = []

    if isinstance(objeto, dict):

        for clave, valor in objeto.items():

            clave_lower = str(
                clave
            ).lower()

            campos = (

                "functional_strike",
                "target_price",
                "target",
                "strike_price",
                "strike",
                "floor_strike",
                "cap_strike"
            )

            if clave_lower in campos:

                numero = convertir_numero_precio(
                    valor
                )

                if numero is not None:

                    prioridad = 100

                    if clave_lower in (
                        "floor_strike",
                        "cap_strike"
                    ):

                        prioridad = 80

                    encontrados.append(
                        (
                            prioridad,
                            numero,
                            clave_lower
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

    raise Exception(
        "No pude encontrar el Target del contrato "
        f"{ticker if ticker else ''}."
    )


# ============================================================
# BTC - COINBASE
# ============================================================

def obtener_btc():

    url = (
        "https://api.exchange.coinbase.com/"
        "products/BTC-USD/candles"
    )

    response = requests.get(

        url,

        params={

            "granularity":
                60
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
            "Coinbase no devolvió datos válidos."
        )

    # Coinbase:
    # [time, low, high, open, close, volume]

    df = pd.DataFrame(

        data,

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

    df = df.sort_values(
        "time"
    )

    df = df.dropna(
        subset=["Close"]
    )

    # Coinbase puede devolver hasta
    # aproximadamente 300 velas.

    df = df.tail(120)

    return df.reset_index(
        drop=True
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
# ============================================================

def generar_prediccion(
    df,
    target_actual
):

    ultimo = df.iloc[-1]

    precio = float(
        ultimo["Close"]
    )

    target = float(
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
    # TARGET DEL CONTRATO ACTUAL
    # ========================================================

    diferencia = (
        precio -
        target
    )

    diferencia_pct = (
        diferencia /
        target
    ) * 100

    # Para predecir el siguiente contrato,
    # el Target actual es la referencia principal.

    # Se pondera según distancia.

    if diferencia_pct > 0.08:

        score += 30

        razones.append(
            f"BTC está ${diferencia:,.2f} "
            f"({diferencia_pct:+.3f}%) por encima "
            "del Target actual."
        )

    elif diferencia_pct > 0.025:

        score += 22

        razones.append(
            f"BTC está ${diferencia:,.2f} "
            f"({diferencia_pct:+.3f}%) por encima "
            "del Target actual."
        )

    elif diferencia_pct > 0:

        score += 14

        razones.append(
            f"BTC está ${diferencia:,.2f} "
            f"({diferencia_pct:+.3f}%) por encima "
            "del Target actual."
        )

    elif diferencia_pct < -0.08:

        score -= 30

        razones.append(
            f"BTC está ${abs(diferencia):,.2f} "
            f"({diferencia_pct:+.3f}%) por debajo "
            "del Target actual."
        )

    elif diferencia_pct < -0.025:

        score -= 22

        razones.append(
            f"BTC está ${abs(diferencia):,.2f} "
            f"({diferencia_pct:+.3f}%) por debajo "
            "del Target actual."
        )

    elif diferencia_pct < 0:

        score -= 14

        razones.append(
            f"BTC está ${abs(diferencia):,.2f} "
            f"({diferencia_pct:+.3f}%) por debajo "
            "del Target actual."
        )

    else:

        razones.append(
            "BTC está exactamente en el Target."
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
    # MACD / SEÑAL
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

        pass

    return []


def guardar_historial(
    historial
):

    temporal = (
        HISTORIAL_FILE +
        ".tmp"
    )

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


# ============================================================
# GUARDAR PREDICCIÓN DEL SIGUIENTE
# ============================================================

def guardar_prediccion_siguiente(

    ticker_actual,

    ticker_siguiente,

    target_actual,

    prediccion,

    confianza,

    precio,

    cierre_siguiente,

    score

):

    historial = (
        st.session_state.historial
    )

    # El identificador real del siguiente contrato
    # puede no existir todavía.
    #
    # Por eso usamos el cierre esperado como
    # identificador provisional.

    identificador = (
        f"NEXT-{cierre_siguiente.isoformat()}"
    )

    for registro in historial:

        if registro.get(
            "ID_PREDICCION"
        ) == identificador:

            return

    registro = {

        "ID_PREDICCION":
            identificador,

        "Contrato usado para analizar":
            ticker_actual,

        "Ticker siguiente":
            ticker_siguiente,

        "Target usado":
            round(
                float(target_actual),
                2
            ),

        "Predicción":
            prediccion,

        "Confianza":
            f"{confianza}%",

        "Score":
            score,

        "Precio BTC predicción":
            round(
                float(precio),
                2
            ),

        "Cierre esperado":
            cierre_siguiente.astimezone(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S %p"
            ),

        "Ticker confirmado":
            False,

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
# BUSCAR EL SIGUIENTE CONTRATO DESPUÉS DE QUE APAREZCA
# ============================================================

def encontrar_contrato_por_cierre(
    cierre_esperado
):

    try:

        mercados = obtener_mercados_btc()

    except Exception:

        return None

    mejor = None
    mejor_diferencia = None

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

        diferencia = abs(
            (
                cierre -
                cierre_esperado
            ).total_seconds()
        )

        # Tolerancia de 90 segundos.

        if diferencia <= 90:

            if (
                mejor is None
                or diferencia < mejor_diferencia
            ):

                mercado["_close"] = cierre

                mejor = mercado

                mejor_diferencia = diferencia

    return mejor


# ============================================================
# VINCULAR PREDICCIONES CON EL SIGUIENTE CONTRATO
# ============================================================

def vincular_siguientes():

    historial = (
        st.session_state.historial
    )

    cambio = False

    for registro in historial:

        if registro.get(
            "Ticker confirmado"
        ):

            continue

        cierre_texto = registro.get(
            "Cierre esperado"
        )

        if not cierre_texto:

            continue

        try:

            cierre_esperado = datetime.strptime(
                cierre_texto,
                "%Y-%m-%d %I:%M:%S %p"
            ).replace(
                tzinfo=LOCAL_TZ
            ).astimezone(
                timezone.utc
            )

        except Exception:

            continue

        contrato = (
            encontrar_contrato_por_cierre(
                cierre_esperado
            )
        )

        if contrato is None:

            continue

        ticker = contrato.get(
            "ticker"
        )

        if not ticker:

            continue

        registro[
            "Ticker siguiente"
        ] = ticker

        registro[
            "Ticker confirmado"
        ] = True

        cambio = True

    if cambio:

        guardar_historial(
            historial
        )


# ============================================================
# RESULTADO OFICIAL KALSHI
# ============================================================

def obtener_resultado_kalshi(
    ticker,
    target
):

    if not ticker:

        return None, None

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

def actualizar_resultados():

    historial = (
        st.session_state.historial
    )

    cambio = False

    # Primero intentar vincular
    # las predicciones con el contrato real.

    try:

        vincular_siguientes()

    except Exception:

        pass

    for registro in historial:

        if registro.get(
            "Resultado"
        ) != "⏳ PENDIENTE":

            continue

        ticker = registro.get(
            "Ticker siguiente"
        )

        target = registro.get(
            "Target usado"
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


if "prediccion_actual_ciclo" not in st.session_state:

    st.session_state.prediccion_actual_ciclo = None


if "prediccion_hecha" not in st.session_state:

    st.session_state.prediccion_hecha = False


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


if "cierre_siguiente" not in st.session_state:

    st.session_state.cierre_siguiente = None


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Predice el SIGUIENTE contrato antes de que comience, "
    "utilizando el contrato actual + comportamiento del mercado."
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
# RESULTADOS ANTERIORES
# ============================================================

try:

    actualizar_resultados()

except Exception as error:

    st.warning(
        f"No se pudieron actualizar algunos resultados: {error}"
    )


# ============================================================
# CONTRATO ACTUAL
# ============================================================

try:

    actual = buscar_mercado_actual()

except Exception as error:

    st.error(
        f"❌ Error consultando Kalshi: {error}"
    )

    actual = None


# ============================================================
# SI KALSHI NO DEVUELVE CONTRATO
# ============================================================

if actual is None:

    st.warning(
        "⏳ Kalshi no está mostrando temporalmente "
        "un contrato BTC 15M abierto."
    )

    st.info(
        "La aplicación NO borra el historial ni las "
        "predicciones pendientes. Seguirá intentando."
    )

    st.subheader(
        "📜 Historial de predicciones"
    )

    if st.session_state.historial:

        st.dataframe(
            pd.DataFrame(
                st.session_state.historial
            ),
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
# DATOS DEL CONTRATO
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

# ============================================================
# CAMBIO DE CONTRATO
#
# IMPORTANTE:
# NO borramos el historial.
# Solamente reiniciamos el estado visual
# para el nuevo ciclo.
# ============================================================

if (
    st.session_state.ticker_actual
    != ticker_actual
):

    st.session_state.ticker_actual = (
        ticker_actual
    )

    st.session_state.prediccion_hecha = False

    st.session_state.prediccion = None

    st.session_state.confianza = 0

    st.session_state.target_usado = None

    st.session_state.precio_prediccion = None

    st.session_state.razones = []

    st.session_state.score = 0

    st.session_state.cierre_siguiente = None


# ============================================================
# TARGET DEL CONTRATO ACTUAL
# ============================================================

try:

    target_actual = obtener_target(
        actual
    )

    target_error = None

except Exception as error:

    target_actual = None

    target_error = str(
        error
    )


# ============================================================
# BTC
# ============================================================

try:

    btc = obtener_btc()

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

if close_actual is None:

    segundos_restantes = 0

else:

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
# GENERAR PREDICCIÓN DEL SIGUIENTE
#
# AQUÍ ESTÁ EL CAMBIO PRINCIPAL.
#
# NO buscamos el siguiente contrato.
# NO necesitamos su Target.
#
# Usamos el Target del contrato actual
# para anticipar el comportamiento del
# siguiente contrato.
# ============================================================

if (

    segundos_restantes <= PREDICCION_SEGUNDOS

    and

    segundos_restantes > 0

    and

    not st.session_state.prediccion_hecha

    and

    target_actual is not None

):

    (
        prediccion,
        confianza,
        razones,
        score
    ) = generar_prediccion(

        btc,

        target_actual
    )

    # El siguiente contrato debería comenzar
    # cuando termine el actual y durar 15 minutos.

    cierre_siguiente = (
        close_actual +
        timedelta(
            minutes=15
        )
    )

    guardar_prediccion_siguiente(

        ticker_actual=ticker_actual,

        ticker_siguiente=None,

        target_actual=target_actual,

        prediccion=prediccion,

        confianza=confianza,

        precio=precio,

        cierre_siguiente=cierre_siguiente,

        score=score
    )

    st.session_state.prediccion_hecha = True

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

    st.session_state.cierre_siguiente = (
        cierre_siguiente
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
# BTC / TARGET
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


# ============================================================
# DIFERENCIA TARGET
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
        "⚠️ No se pudo obtener el Target de Kalshi."
    )


st.caption(
    "Fuente BTC: Coinbase"
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


# ============================================================
# PREDICCIÓN DEL SIGUIENTE
# ============================================================

st.divider()

st.subheader(
    "🔮 Predicción del SIGUIENTE contrato"
)

if st.session_state.prediccion is not None:

    st.success(
        "✅ PREDICCIÓN GENERADA ANTES DEL NUEVO CONTRATO"
    )

    st.write(
        f"# {st.session_state.prediccion}"
    )

    st.metric(
        "Confianza",
        f"{st.session_state.confianza}%"
    )

    st.write(
        f"**Contrato analizado:** "
        f"`{ticker_actual}`"
    )

    st.write(
        f"**🎯 Target utilizado:** "
        f"${st.session_state.target_usado:,.2f}"
    )

    st.write(
        f"**BTC al realizar predicción:** "
        f"${st.session_state.precio_prediccion:,.2f}"
    )

    if st.session_state.cierre_siguiente:

        st.write(
            "**Predicción corresponde al contrato "
            "que comienza después del actual.**"
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

    if target_actual is None:

        st.warning(
            "Esperando el Target de Kalshi."
        )

    elif segundos_restantes > 60:

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
            "La predicción del SIGUIENTE contrato "
            "se generará durante el último minuto "
            "del contrato actual. "
            f"Faltan aproximadamente {mm:02d}:{ss:02d}."
        )

    else:

        st.warning(
            "⚠️ Dentro del último minuto. "
            "Generando predicción del siguiente contrato..."
        )


# ============================================================
# ESTADO DEL SIGUIENTE CONTRATO
# ============================================================

st.divider()

st.subheader(
    "🔄 Próximo contrato"
)

if st.session_state.prediccion is not None:

    st.info(
        "La predicción ya fue realizada. "
        "No es necesario conocer el Target del siguiente "
        "contrato para generar esta predicción."
    )

    if st.session_state.cierre_siguiente:

        hora_siguiente = (
            st.session_state.cierre_siguiente
            .astimezone(
                LOCAL_TZ
            )
        )

        st.write(
            "El contrato siguiente debería cerrar aproximadamente:",
            hora_siguiente.strftime(
                "%I:%M:%S %p"
            )
        )

else:

    st.write(
        "El siguiente contrato todavía no es necesario "
        "para realizar la predicción."
    )


# ============================================================
# GRÁFICO BTC
# ============================================================

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


# ============================================================
# ACTUALIZAR RESULTADOS
# ============================================================

try:

    actualizar_resultados()

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


# ============================================================
# EXPLICACIÓN
# ============================================================

st.divider()

st.caption(
    "El sistema NO necesita conocer el Target del siguiente "
    "contrato para predecirlo. Durante el último minuto "
    "del contrato actual utiliza el Target actual como "
    "referencia junto con EMA, MACD, RSI, momentum y "
    "volatilidad de BTC. La predicción queda guardada "
    "ANTES de que comience el siguiente contrato. "
    "Cuando Kalshi publica el siguiente contrato, la "
    "aplicación lo vincula automáticamente y después "
    "consulta su resultado oficial para determinar "
    "ACIerto o FALLÓ."
)


# ============================================================
# REFRESCO
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
