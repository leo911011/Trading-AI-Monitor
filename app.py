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

KALSHI_URL = "https://external-api.kalshi.com"
SERIES = "KXBTC15M"

LOCAL_TZ = ZoneInfo("America/Chicago")

HISTORIAL_FILE = "historial_kalshi.json"

REFRESH_SECONDS = 5

# A partir de aquí comienza la prepredicción del siguiente
SEGUNDOS_PREVISION = 60


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
            "No existe KALSHI_PRIVATE_KEY en Streamlit Secrets."
        )

    key_text = PRIVATE_KEY.strip()

    try:

        return serialization.load_pem_private_key(
            key_text.encode("utf-8"),
            password=None
        )

    except Exception as e:

        raise Exception(
            "La KALSHI_PRIVATE_KEY no tiene un formato PEM válido."
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
            "Falta KALSHI_API_KEY_ID en Streamlit Secrets."
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
# MERCADOS BTC
# ============================================================

def obtener_mercados_btc():

    data = kalshi_request(

        "GET",

        "/trade-api/v2/markets",

        params={
            "series_ticker": SERIES,
            "status": "open",
            "limit": 100
        }
    )

    return data.get(
        "markets",
        []
    )


# ============================================================
# FECHAS
# ============================================================

def convertir_fecha(texto):

    if not texto:
        return None

    try:

        return datetime.fromisoformat(
            str(texto).replace(
                "Z",
                "+00:00"
            )
        )

    except Exception:

        return None


# ============================================================
# MERCADOS ABIERTOS ORDENADOS
# ============================================================

def obtener_mercados_ordenados():

    mercados = obtener_mercados_btc()

    ahora = datetime.now(
        timezone.utc
    )

    candidatos = []

    for mercado in mercados:

        cierre = convertir_fecha(
            mercado.get("close_time")
        )

        if cierre is None:

            cierre = convertir_fecha(
                mercado.get("expiration_time")
            )

        if cierre is None:
            continue

        if cierre > ahora:

            mercado["_close"] = cierre

            candidatos.append(
                mercado
            )

    candidatos.sort(
        key=lambda x: x["_close"]
    )

    return candidatos


# ============================================================
# CONTRATO ACTUAL
# ============================================================

def buscar_mercado_actual():

    candidatos = obtener_mercados_ordenados()

    if not candidatos:

        raise Exception(
            "No encontré un contrato BTC 15M abierto."
        )

    return candidatos[0]


# ============================================================
# SIGUIENTE CONTRATO
# ============================================================

def buscar_siguiente_mercado(ticker_actual):

    candidatos = obtener_mercados_ordenados()

    for mercado in candidatos:

        ticker = mercado.get(
            "ticker"
        )

        if ticker != ticker_actual:

            return mercado

    return None


# ============================================================
# TARGET
# ============================================================

def obtener_target(mercado):

    campos = [

        "functional_strike",
        "floor_strike",
        "cap_strike"
    ]

    for campo in campos:

        valor = mercado.get(
            campo
        )

        if valor not in (
            None,
            ""
        ):

            try:

                numero = float(
                    valor
                )

                if numero > 1000:

                    return numero

            except Exception:

                pass


    texto = " ".join([

        str(
            mercado.get(
                "title",
                ""
            )
        ),

        str(
            mercado.get(
                "subtitle",
                ""
            )
        ),

        str(
            mercado.get(
                "yes_sub_title",
                ""
            )
        ),

        str(
            mercado.get(
                "no_sub_title",
                ""
            )
        )
    ])


    numeros = re.findall(
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
        texto
    )


    candidatos = []

    for numero in numeros:

        try:

            valor = float(
                numero.replace(
                    ",",
                    ""
                )
            )

            if valor > 1000:

                candidatos.append(
                    valor
                )

        except Exception:

            pass


    if candidatos:

        return candidatos[0]


    raise Exception(
        "No pude encontrar el Target del contrato."
    )


# ============================================================
# PRECIO BTC EN TIEMPO REAL
# ============================================================

def obtener_precio_btc_tiempo_real():

    urls = [

        "https://api.binance.us/api/v3/ticker/price",

        "https://api.binance.com/api/v3/ticker/price"

    ]

    errores = []

    for url in urls:

        try:

            response = requests.get(

                url,

                params={
                    "symbol": "BTCUSDT"
                },

                timeout=5
            )

            response.raise_for_status()

            data = response.json()

            precio = float(
                data["price"]
            )

            if precio > 0:

                return precio

        except Exception as e:

            errores.append(
                str(e)
            )

    raise Exception(
        "No pude obtener BTC en tiempo real. "
        + " | ".join(errores)
    )


# ============================================================
# VELAS BTC
# ============================================================

def obtener_btc_binance():

    urls = [

        "https://api.binance.us/api/v3/klines",

        "https://api.binance.com/api/v3/klines"

    ]

    errores = []

    for url in urls:

        try:

            response = requests.get(

                url,

                params={
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "limit": 120
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
                    "Respuesta inválida."
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
                "Close"

            ]:

                df[columna] = pd.to_numeric(
                    df[columna],
                    errors="coerce"
                )

            df = df.dropna(
                subset=["Close"]
            )

            return df[
                [
                    "time",
                    "Open",
                    "High",
                    "Low",
                    "Close"
                ]
            ]

        except Exception as e:

            errores.append(
                str(e)
            )

    raise Exception(
        "No pude obtener las velas BTC. "
        + " | ".join(errores)
    )


# ============================================================
# INDICADORES
# ============================================================

def indicadores(df):

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
        ema12 - ema26
    )

    # Momentum 3 minutos
    df["Momentum3"] = (
        df["Close"]
        .pct_change(3)
        * 100
    )

    # Momentum 5 minutos
    df["Momentum5"] = (
        df["Close"]
        .pct_change(5)
        * 100
    )

    # Momentum 10 minutos
    df["Momentum10"] = (
        df["Close"]
        .pct_change(10)
        * 100
    )

    return df


# ============================================================
# PREDICCIÓN NORMAL
# ============================================================

def generar_prediccion(
    df,
    target,
    precio_real=None
):

    ultimo = df.iloc[-1]

    if precio_real is None:

        precio = float(
            ultimo["Close"]
        )

    else:

        precio = float(
            precio_real
        )

    ema9 = float(
        ultimo["EMA9"]
    )

    ema21 = float(
        ultimo["EMA21"]
    )

    macd = float(
        ultimo["MACD"]
    )

    rsi = ultimo["RSI"]

    momentum3 = ultimo["Momentum3"]

    momentum5 = ultimo["Momentum5"]

    momentum10 = ultimo["Momentum10"]


    subir = 0.0
    bajar = 0.0

    razones = []


    # --------------------------------------------------------
    # DISTANCIA AL TARGET
    # --------------------------------------------------------

    distancia = (
        precio -
        target
    )

    porcentaje = (
        distancia /
        target
    ) * 100


    # La distancia al target es importante,
    # pero NO determina por sí sola el resultado.

    if distancia > 0:

        subir += 12

        razones.append(
            f"BTC está ${distancia:,.2f} "
            f"({porcentaje:+.3f}%) sobre el Target."
        )

    elif distancia < 0:

        bajar += 12

        razones.append(
            f"BTC está ${abs(distancia):,.2f} "
            f"({porcentaje:+.3f}%) debajo del Target."
        )

    else:

        razones.append(
            "BTC está exactamente en el Target."
        )


    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if ema9 > ema21:

        subir += 22

        razones.append(
            "EMA9 > EMA21: tendencia alcista."
        )

    else:

        bajar += 22

        razones.append(
            "EMA9 < EMA21: tendencia bajista."
        )


    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if macd > 0:

        subir += 18

        razones.append(
            "MACD positivo."
        )

    else:

        bajar += 18

        razones.append(
            "MACD negativo."
        )


    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if pd.notna(rsi):

        rsi = float(rsi)

        if rsi < 30:

            # Sobreventa: posible rebote,
            # pero no damos una señal exagerada.

            subir += 12

            razones.append(
                f"RSI {rsi:.1f}: zona de sobreventa, "
                "posible rebote."
            )

        elif rsi > 70:

            bajar += 12

            razones.append(
                f"RSI {rsi:.1f}: zona de sobrecompra."
            )

        else:

            razones.append(
                f"RSI {rsi:.1f}: zona neutral."
            )


    # --------------------------------------------------------
    # MOMENTUM 3
    # --------------------------------------------------------

    if pd.notna(momentum3):

        momentum3 = float(
            momentum3
        )

        if momentum3 > 0:

            subir += 14

            razones.append(
                f"Momentum 3m +{momentum3:.3f}%."
            )

        elif momentum3 < 0:

            bajar += 14

            razones.append(
                f"Momentum 3m {momentum3:.3f}%."
            )


    # --------------------------------------------------------
    # MOMENTUM 5
    # --------------------------------------------------------

    if pd.notna(momentum5):

        momentum5 = float(
            momentum5
        )

        if momentum5 > 0:

            subir += 8

        elif momentum5 < 0:

            bajar += 8


    # --------------------------------------------------------
    # MOMENTUM 10
    # --------------------------------------------------------

    if pd.notna(momentum10):

        momentum10 = float(
            momentum10
        )

        if momentum10 > 0:

            subir += 6

        elif momentum10 < 0:

            bajar += 6


    total = subir + bajar


    if total <= 0:

        return (
            "⚪ NO APOSTAR",
            50,
            razones
        )


    diferencia_puntos = abs(
        subir - bajar
    )

    confianza = (
        50 +
        (
            diferencia_puntos /
            total
        ) * 50
    )

    confianza = min(
        90,
        max(
            50,
            confianza
        )
    )


    if subir > bajar:

        prediccion = "🟢 ARRIBA"

    elif bajar > subir:

        prediccion = "🔴 ABAJO"

    else:

        prediccion = "⚪ NO APOSTAR"


    return (
        prediccion,
        round(confianza),
        razones
    )


# ============================================================
# PREDICCIÓN DEL SIGUIENTE CONTRATO
# ============================================================

def generar_preprediccion_siguiente(
    df,
    precio,
    target_siguiente=None
):

    ultimo = df.iloc[-1]

    ema9 = float(
        ultimo["EMA9"]
    )

    ema21 = float(
        ultimo["EMA21"]
    )

    macd = float(
        ultimo["MACD"]
    )

    rsi = ultimo["RSI"]

    momentum3 = ultimo["Momentum3"]

    momentum5 = ultimo["Momentum5"]

    momentum10 = ultimo["Momentum10"]


    subir = 0.0
    bajar = 0.0

    razones = []


    # ========================================================
    # TARGET DEL SIGUIENTE
    # ========================================================

    if target_siguiente is not None:

        diferencia = (
            precio -
            target_siguiente
        )

        porcentaje = (
            diferencia /
            target_siguiente
        ) * 100


        # Tiene peso, pero no domina la predicción.

        if diferencia > 0:

            subir += 18

            razones.append(
                f"BTC está ${diferencia:,.2f} "
                f"({porcentaje:+.3f}%) sobre el Target "
                "del siguiente contrato."
            )

        elif diferencia < 0:

            bajar += 18

            razones.append(
                f"BTC está ${abs(diferencia):,.2f} "
                f"({porcentaje:+.3f}%) debajo del Target "
                "del siguiente contrato."
            )

        else:

            razones.append(
                "BTC está exactamente en el Target "
                "del siguiente contrato."
            )


    # ========================================================
    # TENDENCIA
    # ========================================================

    if ema9 > ema21:

        subir += 20

        razones.append(
            "EMA9 > EMA21: tendencia actual alcista."
        )

    else:

        bajar += 20

        razones.append(
            "EMA9 < EMA21: tendencia actual bajista."
        )


    # ========================================================
    # MACD
    # ========================================================

    if macd > 0:

        subir += 16

        razones.append(
            "MACD positivo."
        )

    else:

        bajar += 16

        razones.append(
            "MACD negativo."
        )


    # ========================================================
    # MOMENTUM 3
    # ========================================================

    if pd.notna(momentum3):

        momentum3 = float(
            momentum3
        )

        if momentum3 > 0:

            subir += 18

            razones.append(
                f"Momentum 3m positivo "
                f"(+{momentum3:.3f}%)."
            )

        elif momentum3 < 0:

            bajar += 18

            razones.append(
                f"Momentum 3m negativo "
                f"({momentum3:.3f}%)."
            )


    # ========================================================
    # MOMENTUM 5
    # ========================================================

    if pd.notna(momentum5):

        momentum5 = float(
            momentum5
        )

        if momentum5 > 0:

            subir += 10

        elif momentum5 < 0:

            bajar += 10


    # ========================================================
    # MOMENTUM 10
    # ========================================================

    if pd.notna(momentum10):

        momentum10 = float(
            momentum10
        )

        if momentum10 > 0:

            subir += 8

        elif momentum10 < 0:

            bajar += 8


    # ========================================================
    # RSI
    # ========================================================

    if pd.notna(rsi):

        rsi = float(
            rsi
        )

        if rsi < 30:

            subir += 6

            razones.append(
                f"RSI {rsi:.1f}: sobreventa; "
                "posible rebote."
            )

        elif rsi > 70:

            bajar += 6

            razones.append(
                f"RSI {rsi:.1f}: sobrecompra."
            )


    total = subir + bajar


    if total <= 0:

        return (
            "⚪ NO APOSTAR",
            50,
            razones
        )


    diferencia = abs(
        subir - bajar
    )

    confianza = (
        50 +
        (
            diferencia /
            total
        ) * 50
    )

    confianza = min(
        85,
        max(
            50,
            confianza
        )
    )


    if subir > bajar:

        prediccion = "🟢 ARRIBA"

    elif bajar > subir:

        prediccion = "🔴 ABAJO"

    else:

        prediccion = "⚪ NO APOSTAR"


    return (
        prediccion,
        round(confianza),
        razones
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
        ) as f:

            data = json.load(f)

            if isinstance(
                data,
                list
            ):

                return data

    except Exception:

        pass

    return []


def guardar_historial(historial):

    temp_file = HISTORIAL_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            historial,
            f,
            indent=2,
            ensure_ascii=False
        )

    os.replace(
        temp_file,
        HISTORIAL_FILE
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
# RESULTADO KALSHI
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

    expiration_value = mercado.get(
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

            return "UP", expiration_value


        if resultado in (
            "DOWN",
            "NO"
        ):

            return "DOWN", expiration_value


    if expiration_value not in (
        None,
        ""
    ):

        try:

            exp = float(
                expiration_value
            )

            target = float(
                target
            )

            if exp > target:

                return "UP", exp

            elif exp < target:

                return "DOWN", exp

            else:

                return "TIE", exp

        except Exception:

            pass


    return None, expiration_value


# ============================================================
# GUARDAR NUEVO CONTRATO
# ============================================================

def guardar_nuevo_contrato(
    ticker,
    target,
    prediccion,
    confianza,
    precio,
    close_time
):

    historial = st.session_state.historial

    existentes = [

        x.get("Ticker")

        for x in historial
    ]

    if ticker in existentes:

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

        "Precio entrada":
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

        "Tipo":
            "Predicción normal",

        "Actualizado":
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
# GUARDAR PREPREDICCIÓN DEL SIGUIENTE
# ============================================================

def guardar_preprediccion_siguiente(
    mercado_siguiente,
    prediccion,
    confianza,
    precio
):

    if mercado_siguiente is None:

        return


    ticker = mercado_siguiente.get(
        "ticker"
    )

    if not ticker:

        return


    historial = st.session_state.historial


    # --------------------------------------------------------
    # Si ya existe la prepredicción, actualizarla
    # --------------------------------------------------------

    encontrado = None

    for registro in historial:

        if (
            registro.get("Ticker")
            == ticker
            and
            registro.get("Tipo")
            == "Prepredicción siguiente"
        ):

            encontrado = registro

            break


    target = obtener_target(
        mercado_siguiente
    )

    close_time = mercado_siguiente.get(
        "_close"
    )


    if encontrado is not None:

        encontrado["Predicción"] = prediccion

        encontrado["Confianza"] = (
            f"{confianza}%"
        )

        encontrado["Precio prepredicción"] = round(
            float(precio),
            2
        )

        encontrado["Actualizado"] = (
            datetime.now(
                LOCAL_TZ
            ).strftime(
                "%Y-%m-%d %I:%M:%S"
            )
        )

    else:

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

            "Precio entrada":
                None,

            "Precio prepredicción":
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

            "Tipo":
                "Prepredicción siguiente",

            "Actualizado":
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
# PROMOVER PREPREDICCIÓN A PREDICCIÓN NORMAL
# ============================================================

def obtener_preprediccion_guardada(
    ticker
):

    for registro in st.session_state.historial:

        if (
            registro.get("Ticker")
            == ticker
            and
            registro.get("Tipo")
            == "Prepredicción siguiente"
        ):

            return registro

    return None


# ============================================================
# ACTUALIZAR RESULTADOS
# ============================================================

def actualizar_pendientes():

    historial = st.session_state.historial

    cambio = False


    for registro in historial:

        if registro.get(
            "Resultado"
        ) not in (
            "⏳ PENDIENTE",
            "⏳ SIN RESOLVER"
        ):

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
# STREAMLIT STATE
# ============================================================

if "historial" not in st.session_state:

    st.session_state.historial = (
        cargar_historial()
    )


if "ticker" not in st.session_state:

    st.session_state.ticker = None


if "prediccion" not in st.session_state:

    st.session_state.prediccion = None


if "confianza" not in st.session_state:

    st.session_state.confianza = 0


if "precio_inicio" not in st.session_state:

    st.session_state.precio_inicio = 0


if "target" not in st.session_state:

    st.session_state.target = 0


if "close_time" not in st.session_state:

    st.session_state.close_time = None


if "razones" not in st.session_state:

    st.session_state.razones = []


if "next_prediction" not in st.session_state:

    st.session_state.next_prediction = None


if "next_confianza" not in st.session_state:

    st.session_state.next_confianza = 0


if "next_ticker" not in st.session_state:

    st.session_state.next_ticker = None


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15 Min"
)

st.caption(
    "Predicción del cierre + prepredicción del siguiente contrato"
)


# ============================================================
# CREDENCIALES
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ No se encontraron las credenciales de Kalshi."
    )

    st.info(
        "Ve a Streamlit → Settings → Secrets "
        "y revisa KALSHI_API_KEY_ID y KALSHI_PRIVATE_KEY."
    )

    st.stop()


# ============================================================
# ACTUALIZAR HISTORIAL
# ============================================================

try:

    actualizar_pendientes()

except Exception as e:

    st.warning(
        "No se pudieron actualizar algunos contratos: "
        f"{e}"
    )


# ============================================================
# EJECUCIÓN PRINCIPAL
# ============================================================

try:

    # ========================================================
    # CONTRATOS
    # ========================================================

    mercados = obtener_mercados_ordenados()

    if not mercados:

        raise Exception(
            "No encontré contratos BTC 15M abiertos."
        )


    mercado = mercados[0]

    ticker = mercado.get(
        "ticker"
    )

    target = obtener_target(
        mercado
    )

    close_time = mercado["_close"]


    # ========================================================
    # SIGUIENTE
    # ========================================================

    mercado_siguiente = None

    if len(mercados) >= 2:

        mercado_siguiente = mercados[1]


    # ========================================================
    # BTC
    # ========================================================

    # Precio REAL actualizado
    precio = obtener_precio_btc_tiempo_real()

    # Velas para indicadores
    btc = obtener_btc_binance()

    # IMPORTANTE:
    # Reemplazamos la última vela con el precio actual.
    # Así EMA/RSI/MACD trabajan con el precio más reciente.

    if len(btc) > 0:

        btc.loc[
            btc.index[-1],
            "Close"
        ] = precio

    btc = indicadores(
        btc
    )


    # ========================================================
    # NUEVO CONTRATO ACTUAL
    # ========================================================

    if (
        st.session_state.ticker
        != ticker
    ):

        # ----------------------------------------------------
        # Primero intentamos utilizar la prepredicción
        # del siguiente contrato.
        # ----------------------------------------------------

        pre = obtener_preprediccion_guardada(
            ticker
        )


        if pre is not None:

            prediccion = pre.get(
                "Predicción",
                "⚪ NO APOSTAR"
            )

            confianza_texto = str(
                pre.get(
                    "Confianza",
                    "50%"
                )
            ).replace(
                "%",
                ""
            )

            try:

                confianza = int(
                    confianza_texto
                )

            except Exception:

                confianza = 50

            razones = [
                "Esta predicción comenzó como "
                "prepredicción del contrato anterior."
            ]

        else:

            prediccion, confianza, razones = (
                generar_prediccion(
                    btc,
                    target,
                    precio
                )
            )


        guardar_nuevo_contrato(

            ticker=ticker,

            target=target,

            prediccion=prediccion,

            confianza=confianza,

            precio=precio,

            close_time=close_time
        )


        st.session_state.ticker = ticker

        st.session_state.prediccion = prediccion

        st.session_state.confianza = confianza

        st.session_state.precio_inicio = precio

        st.session_state.target = target

        st.session_state.close_time = (
            close_time.isoformat()
        )

        st.session_state.razones = razones

        # Limpiamos la prepredicción visual anterior

        st.session_state.next_prediction = None

        st.session_state.next_confianza = 0

        st.session_state.next_ticker = None


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
                close_time -
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
        "🎯 Contrato actual de Kalshi"
    )

    st.write(
        f"**Ticker:** `{ticker}`"
    )


    titulo = mercado.get(
        "title",
        ""
    )

    subtitulo = mercado.get(
        "subtitle",
        ""
    )


    if titulo:

        st.write(
            f"**{titulo}**"
        )


    if subtitulo:

        st.caption(
            subtitulo
        )


    # ========================================================
    # BTC / TARGET
    # ========================================================

    col1, col2 = st.columns(2)


    col1.metric(
        "₿ BTC actual",
        f"${precio:,.2f}"
    )


    col2.metric(
        "🎯 Target",
        f"${target:,.2f}"
    )


    diferencia = (
        precio -
        target
    )

    porcentaje = (
        diferencia /
        target
    ) * 100


    if diferencia > 0:

        st.success(
            f"BTC está ${diferencia:,.2f} "
            f"({porcentaje:+.3f}%) "
            "POR ENCIMA del Target."
        )

    elif diferencia < 0:

        st.error(
            f"BTC está ${abs(diferencia):,.2f} "
            f"({porcentaje:+.3f}%) "
            "POR DEBAJO del Target."
        )

    else:

        st.warning(
            "BTC está exactamente en el Target."
        )


    # ========================================================
    # PREDICCIÓN ACTUAL
    # ========================================================

    st.subheader(
        "🔮 Predicción para el cierre actual"
    )


    st.write(
        f"# {st.session_state.prediccion}"
    )


    st.metric(
        "Confianza",
        f"{st.session_state.confianza}%"
    )


    st.write(
        f"Precio de entrada: "
        f"${st.session_state.precio_inicio:,.2f}"
    )


    # ========================================================
    # TEMPORIZADOR
    # ========================================================

    if segundos_restantes <= SEGUNDOS_PREVISION:

        st.warning(
            f"⚠️ PREPARANDO SIGUIENTE CONTRATO — "
            f"{minutos:02d}:{segundos:02d}"
        )


    st.subheader(
        f"⏳ Tiempo restante: "
        f"{minutos:02d}:{segundos:02d}"
    )


    hora_cierre = close_time.astimezone(
        LOCAL_TZ
    )


    st.write(
        "Cierre:",
        hora_cierre.strftime(
            "%I:%M:%S %p"
        )
    )


    # ========================================================
    # PREPREDICCIÓN DEL SIGUIENTE
    # ========================================================

    if (
        segundos_restantes
        <= SEGUNDOS_PREVISION
    ):

        st.divider()

        st.subheader(
            "🔮 PREPREDICCIÓN DEL SIGUIENTE CONTRATO"
        )


        if mercado_siguiente is not None:

            next_ticker = mercado_siguiente.get(
                "ticker"
            )

            try:

                next_target = obtener_target(
                    mercado_siguiente
                )

            except Exception:

                next_target = None


            next_prediction, next_confianza, next_reasons = (
                generar_preprediccion_siguiente(

                    btc,

                    precio,

                    next_target
                )
            )


            # Guardar / actualizar
            guardar_preprediccion_siguiente(

                mercado_siguiente,

                next_prediction,

                next_confianza,

                precio
            )


            st.session_state.next_prediction = (
                next_prediction
            )

            st.session_state.next_confianza = (
                next_confianza
            )

            st.session_state.next_ticker = (
                next_ticker
            )


            st.write(
                f"**Ticker siguiente:** `{next_ticker}`"
            )


            if next_target is not None:

                st.write(
                    f"**Target siguiente:** "
                    f"${next_target:,.2f}"
                )

            else:

                st.write(
                    "**Target siguiente:** "
                    "todavía no disponible"
                )


            st.write(
                "## "
                +
                next_prediction
            )


            st.metric(
                "Confianza preliminar",
                f"{next_confianza}%"
            )


            st.caption(
                "Esta predicción se genera aproximadamente "
                "1 minuto antes del cierre del contrato actual "
                "utilizando el comportamiento acumulado de BTC."
            )


            with st.expander(
                "Ver análisis del siguiente"
            ):

                for razon in next_reasons:

                    st.write(
                        "•",
                        razon
                    )


        else:

            st.info(
                "Kalshi todavía no muestra el siguiente "
                "contrato abierto. La aplicación esperará "
                "hasta que aparezca."
            )


    # ========================================================
    # ANÁLISIS ACTUAL
    # ========================================================

    st.subheader(
        "📊 Análisis del contrato actual"
    )


    for razon in st.session_state.razones:

        st.write(
            "•",
            razon
        )


    # ========================================================
    # GRÁFICO
    # ========================================================

    st.subheader(
        "📈 BTC — últimos 120 minutos"
    )


    st.line_chart(
        btc["Close"]
    )


    # ========================================================
    # HISTORIAL
    # ========================================================

    st.subheader(
        "📜 Historial de predicciones"
    )


    try:

        actualizar_pendientes()

    except Exception:

        pass


    if st.session_state.historial:

        tabla = pd.DataFrame(
            st.session_state.historial
        )


        st.dataframe(
            tabla,
            use_container_width=True,
            hide_index=True
        )


        aciertos = len(
            tabla[
                tabla["Resultado"]
                ==
                "✅ ACIERTO"
            ]
        )


        fallos = len(
            tabla[
                tabla["Resultado"]
                ==
                "❌ FALLÓ"
            ]
        )


        pendientes = len(
            tabla[
                tabla["Resultado"]
                .isin([
                    "⏳ PENDIENTE",
                    "⏳ SIN RESOLVER"
                ])
            ]
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


    else:

        st.info(
            "Todavía no hay contratos registrados."
        )


    # ========================================================
    # INFORMACIÓN
    # ========================================================

    st.divider()


    st.caption(
        "BTC se actualiza cada 5 segundos. "
        "La prepredicción del siguiente contrato "
        "se activa durante el último minuto del contrato actual. "
        "La aplicación no coloca operaciones automáticamente."
    )


except Exception as error:

    st.error(
        "❌ Error"
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
