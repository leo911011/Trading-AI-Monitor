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
# KALSHI - CLAVE PRIVADA
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
            "La KALSHI_PRIVATE_KEY no tiene un formato PEM válido. "
            "Debe comenzar con -----BEGIN RSA PRIVATE KEY----- "
            "o -----BEGIN PRIVATE KEY----- y terminar con el "
            "bloque END correspondiente."
        ) from e


# ============================================================
# FIRMA
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

    if not candidatos:

        raise Exception(
            "No encontré un contrato BTC 15M abierto actualmente."
        )

    candidatos.sort(
        key=lambda x: x["_close"]
    )

    return candidatos[0]


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

        valor = mercado.get(campo)

        if valor not in (None, ""):

            try:

                numero = float(valor)

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

                candidatos.append(valor)

        except Exception:
            pass


    if candidatos:

        return candidatos[0]


    raise Exception(
        "No pude encontrar el Target del contrato."
    )


# ============================================================
# PRECIO BTC
# ============================================================

def obtener_btc_binance():

    url = (
        "https://api.binance.us/api/v3/klines"
    )

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

    if not isinstance(data, list):
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


def obtener_btc():

    errores = []

    fuentes = [

        obtener_btc_binance,

    ]

    for fuente in fuentes:

        try:

            df = fuente()

            if len(df) >= 30:
                return df

        except Exception as e:

            errores.append(
                str(e)
            )


    raise Exception(
        "No pude obtener el precio de BTC. "
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


    # Momentum

    df["Momentum"] = (
        df["Close"]
        .pct_change(3)
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

    momentum = ultimo["Momentum"]


    subir = 0
    bajar = 0

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


    if distancia > 0:

        subir += 20

        razones.append(
            f"BTC está ${distancia:,.2f} "
            f"({porcentaje:+.3f}%) sobre el Target."
        )

    elif distancia < 0:

        # IMPORTANTE:
        # Estar debajo del target NO significa automáticamente
        # que vaya a terminar debajo.
        # Solo damos una pequeña señal de contexto.

        bajar += 10

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

        subir += 25

        razones.append(
            "EMA9 > EMA21: tendencia alcista."
        )

    else:

        bajar += 25

        razones.append(
            "EMA9 < EMA21: tendencia bajista."
        )


    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if macd > 0:

        subir += 20

        razones.append(
            "MACD positivo."
        )

    else:

        bajar += 20

        razones.append(
            "MACD negativo."
        )


    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if pd.notna(rsi):

        rsi = float(rsi)

        if rsi < 35:

            subir += 15

            razones.append(
                f"RSI {rsi:.1f}: posible rebote."
            )

        elif rsi > 65:

            bajar += 15

            razones.append(
                f"RSI {rsi:.1f}: presión bajista."
            )

        else:

            razones.append(
                f"RSI {rsi:.1f}: zona neutral."
            )


    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if pd.notna(momentum):

        momentum = float(momentum)

        if momentum > 0:

            subir += 20

            razones.append(
                f"Momentum +{momentum:.3f}%."
            )

        elif momentum < 0:

            bajar += 20

            razones.append(
                f"Momentum {momentum:.3f}%."
            )


    total = subir + bajar


    if total == 0:

        return (
            "⚪ NO APOSTAR",
            50,
            razones
        )


    if subir > bajar:

        prediccion = "🟢 ARRIBA"

        confianza = (
            subir /
            total
        ) * 100

    elif bajar > subir:

        prediccion = "🔴 ABAJO"

        confianza = (
            bajar /
            total
        ) * 100

    else:

        prediccion = "⚪ NO APOSTAR"

        confianza = 50


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

        return []


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
# BUSCAR CONTRATO POR TICKER
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
# OBTENER RESULTADO REAL
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


    # --------------------------------------------------------
    # RESULTADO OFICIAL
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

            return "UP", expiration_value


        if resultado in (
            "DOWN",
            "NO"
        ):

            return "DOWN", expiration_value


    # --------------------------------------------------------
    # EXPIRATION VALUE
    # --------------------------------------------------------

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
# ACTUALIZAR CONTRATOS PENDIENTES
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
# ESTADO STREAMLIT
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


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15 Min"
)

st.caption(
    "Predicción: ¿BTC terminará ARRIBA o ABAJO del Target de Kalshi?"
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
# ACTUALIZAR HISTORIAL PENDIENTE
# ============================================================

try:

    actualizar_pendientes()

except Exception as e:

    st.warning(
        "No se pudieron actualizar algunos contratos "
        f"pendientes: {e}"
    )


# ============================================================
# EJECUCIÓN PRINCIPAL
# ============================================================

try:

    # --------------------------------------------------------
    # MERCADO ACTUAL
    # --------------------------------------------------------

    mercado = buscar_mercado_actual()

    ticker = mercado.get(
        "ticker"
    )

    target = obtener_target(
        mercado
    )

    close_time = mercado["_close"]


    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    btc = obtener_btc()

    btc = indicadores(
        btc
    )

    precio = float(
        btc["Close"].iloc[-1]
    )


    # --------------------------------------------------------
    # NUEVO CONTRATO
    # --------------------------------------------------------

    if (
        st.session_state.ticker
        != ticker
    ):

        prediccion, confianza, razones = (
            generar_prediccion(
                btc,
                target
            )
        )


        # Guardar inmediatamente.
        # NO esperamos a que termine para crear
        # el registro.

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
        f"${st.session_state.target:,.2f}"
    )


    diferencia = (
        precio -
        st.session_state.target
    )


    porcentaje = (
        diferencia /
        st.session_state.target
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
    # PREDICCIÓN
    # ========================================================

    st.subheader(
        "🔮 Predicción para el cierre"
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

    if segundos_restantes <= 60:

        st.warning(
            f"⚠️ ÚLTIMO MINUTO — "
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
    # ANÁLISIS
    # ========================================================

    st.subheader(
        "📊 Análisis"
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
        "📈 BTC"
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


    # Actualizar nuevamente antes de mostrarlo.

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
        "La aplicación analiza los contratos BTC 15M "
        "de Kalshi. No coloca apuestas automáticamente. "
        "El resultado se actualiza cuando Kalshi publica "
        "la resolución del contrato."
    )


except Exception as error:

    st.error(
        "❌ Error"
    )

    st.code(
        str(error)
    )


# ============================================================
# ACTUALIZACIÓN
# ============================================================

time.sleep(
    REFRESH_SECONDS
)

st.rerun()
