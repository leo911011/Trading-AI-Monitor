import streamlit as st
import requests
import pandas as pd
import json
import os
import time
import base64

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
            "No existe KALSHI_PRIVATE_KEY."
        )

    key = PRIVATE_KEY.strip()

    try:

        return serialization.load_pem_private_key(
            key.encode("utf-8"),
            password=None
        )

    except Exception as e:

        raise Exception(
            "La KALSHI_PRIVATE_KEY no tiene "
            "un formato PEM válido. "
            "Debe comenzar con BEGIN RSA PRIVATE KEY "
            "o BEGIN PRIVATE KEY y terminar con END correspondiente."
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
            f"Kalshi HTTP {response.status_code}: "
            f"{response.text[:400]}"
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
            texto.replace(
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

        if valor not in (
            None,
            ""
        ):

            try:

                return float(valor)

            except Exception:

                pass

    raise Exception(
        "No pude encontrar el Target del contrato."
    )


# ============================================================
# PRECIO BTC - COINBASE
# ============================================================

def obtener_coinbase():

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

    datos = response.json()

    if not isinstance(
        datos,
        list
    ):

        raise Exception(
            "Coinbase no devolvió datos válidos."
        )

    filas = []

    for vela in datos:

        if len(vela) < 5:
            continue

        filas.append({

            "time": vela[0],
            "Low": vela[1],
            "High": vela[2],
            "Open": vela[3],
            "Close": vela[4]

        })

    df = pd.DataFrame(filas)

    if df.empty:
        raise Exception(
            "Coinbase devolvió datos vacíos."
        )

    df = df.sort_values(
        "time"
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

    df = df.dropna()

    return df


# ============================================================
# PRECIO BTC - RESPALDO
# ============================================================

def obtener_coincap():

    url = (
        "https://api.coincap.io/v2/assets/bitcoin/history"
    )

    response = requests.get(

        url,

        params={
            "interval": "m1"
        },

        headers={
            "User-Agent":
                "BTC-Kalshi-Predictor/1.0"
        },

        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    registros = data.get(
        "data",
        []
    )

    if not registros:
        raise Exception(
            "CoinCap no devolvió datos."
        )

    filas = []

    for item in registros[-120:]:

        precio = float(
            item["priceUsd"]
        )

        filas.append({

            "time":
                item["time"],

            "Open":
                precio,

            "High":
                precio,

            "Low":
                precio,

            "Close":
                precio

        })

    return pd.DataFrame(filas)


# ============================================================
# OBTENER BTC CON RESPALDO
# ============================================================

def obtener_btc():

    errores = []

    try:

        return obtener_coinbase()

    except Exception as e:

        errores.append(
            "Coinbase: " + str(e)
        )

    try:

        return obtener_coincap()

    except Exception as e:

        errores.append(
            "CoinCap: " + str(e)
        )

    raise Exception(
        "No pude obtener el precio de BTC.\n"
        +
        "\n".join(errores)
    )


# ============================================================
# INDICADORES
# ============================================================

def indicadores(df):

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

    df["Momentum"] = (
        df["Close"]
        .pct_change(3)
        * 100
    )

    return df


# ============================================================
# PREDICCIÓN HACIA EL TARGET
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

    distancia = (
        precio - target
    )

    distancia_pct = (
        distancia /
        target
    ) * 100


    # ========================================================
    # POSICIÓN RESPECTO AL TARGET
    # ========================================================

    if distancia > 0:

        subir += 20

        razones.append(
            f"BTC está "
            f"${distancia:,.2f} "
            f"({distancia_pct:+.3f}%) "
            "sobre el Target."
        )

    elif distancia < 0:

        bajar += 20

        razones.append(
            f"BTC está "
            f"${abs(distancia):,.2f} "
            f"({distancia_pct:+.3f}%) "
            "debajo del Target."
        )

    else:

        razones.append(
            "BTC está exactamente en el Target."
        )


    # ========================================================
    # EMA
    # ========================================================

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


    # ========================================================
    # MACD
    # ========================================================

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


    # ========================================================
    # RSI
    # ========================================================

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


    # ========================================================
    # MOMENTUM
    # ========================================================

    if pd.notna(momentum):

        momentum = float(
            momentum
        )

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


    # ========================================================
    # RESULTADO
    # ========================================================

    total = (
        subir +
        bajar
    )

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

        pass

    return []


def guardar_historial(
    historial
):

    with open(
        HISTORIAL_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            historial,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# ESTADO
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

st.write(
    "Predicción: ¿BTC terminará "
    "**ARRIBA o ABAJO del Target de Kalshi?**"
)


# ============================================================
# CREDENCIALES
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ Faltan las credenciales de Kalshi."
    )

    st.info(
        "Ve a Streamlit → Settings → Secrets."
    )

    st.stop()


# ============================================================
# EJECUCIÓN
# ============================================================

try:

    # ========================================================
    # KALSHI
    # ========================================================

    mercado = buscar_mercado_actual()

    ticker = mercado.get(
        "ticker"
    )

    target = obtener_target(
        mercado
    )

    close_time = mercado["_close"]


    # ========================================================
    # BTC
    # ========================================================

    btc = obtener_btc()

    btc = indicadores(
        btc
    )

    precio = float(
        btc["Close"].iloc[-1]
    )


    # ========================================================
    # NUEVO CONTRATO
    # ========================================================

    if (
        st.session_state.ticker
        != ticker
    ):

        # ----------------------------------------------------
        # INTENTAR RESOLVER EL CONTRATO ANTERIOR
        # ----------------------------------------------------

        if (
            st.session_state.ticker
            and
            st.session_state.prediccion
        ):

            try:

                anterior = kalshi_request(

                    "GET",

                    "/trade-api/v2/markets/"
                    +
                    st.session_state.ticker
                )

                mercado_anterior = (
                    anterior.get(
                        "market",
                        {}
                    )
                )

                resultado_kalshi = (
                    mercado_anterior.get(
                        "result"
                    )
                )

                expiration_value = (
                    mercado_anterior.get(
                        "expiration_value"
                    )
                )

                resultado_real = "UNKNOWN"


                if resultado_kalshi:

                    resultado_real = (
                        str(
                            resultado_kalshi
                        ).upper()
                    )

                elif (
                    expiration_value
                    not in
                    (None, "")
                ):

                    try:

                        exp = float(
                            expiration_value
                        )

                        if (
                            exp >
                            st.session_state.target
                        ):

                            resultado_real = "UP"

                        elif (
                            exp <
                            st.session_state.target
                        ):

                            resultado_real = "DOWN"

                        else:

                            resultado_real = "TIE"

                    except Exception:

                        resultado_real = "UNKNOWN"


                pred = (
                    st.session_state.prediccion
                )

                if (
                    pred == "🟢 ARRIBA"
                    and
                    resultado_real == "UP"
                ):

                    resultado = "✅ ACIERTO"

                elif (
                    pred == "🔴 ABAJO"
                    and
                    resultado_real == "DOWN"
                ):

                    resultado = "✅ ACIERTO"

                elif (
                    pred == "⚪ NO APOSTAR"
                ):

                    resultado = "⚪ NO APOSTAR"

                elif (
                    resultado_real == "UNKNOWN"
                ):

                    resultado = "⏳ SIN RESOLVER"

                else:

                    resultado = "❌ FALLÓ"


                registro = {

                    "Ticker":
                        st.session_state.ticker,

                    "Target":
                        round(
                            st.session_state.target,
                            2
                        ),

                    "Predicción":
                        pred,

                    "Confianza":
                        f"{st.session_state.confianza}%",

                    "Precio entrada":
                        round(
                            st.session_state.precio_inicio,
                            2
                        ),

                    "Resultado Kalshi":
                        resultado_real,

                    "Expiration Value":
                        expiration_value,

                    "Resultado":
                        resultado,

                    "Hora":
                        datetime.now(
                            LOCAL_TZ
                        ).strftime(
                            "%Y-%m-%d %I:%M:%S %p"
                        )
                }


                existentes = [

                    x.get("Ticker")

                    for x
                    in st.session_state.historial

                ]


                if (
                    st.session_state.ticker
                    not in existentes
                ):

                    st.session_state.historial.append(
                        registro
                    )

                    guardar_historial(
                        st.session_state.historial
                    )


            except Exception as e:

                st.warning(
                    "⚠️ El contrato anterior "
                    "todavía no pudo verificarse: "
                    +
                    str(e)
                )


        # ----------------------------------------------------
        # NUEVA PREDICCIÓN
        # ----------------------------------------------------

        prediccion, confianza, razones = (
            generar_prediccion(
                btc,
                target
            )
        )

        st.session_state.ticker = ticker

        st.session_state.prediccion = (
            prediccion
        )

        st.session_state.confianza = (
            confianza
        )

        st.session_state.precio_inicio = (
            precio
        )

        st.session_state.target = (
            target
        )

        st.session_state.close_time = (
            close_time.isoformat()
        )

        st.session_state.razones = (
            razones
        )


    # ========================================================
    # TIEMPO REAL
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

    if titulo:

        st.write(
            f"**{titulo}**"
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


    if diferencia > 0:

        st.success(
            f"BTC está "
            f"${diferencia:,.2f} "
            "POR ENCIMA del Target."
        )

    elif diferencia < 0:

        st.error(
            f"BTC está "
            f"${abs(diferencia):,.2f} "
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
    # TIEMPO
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


    hora_cierre = (
        close_time
        .astimezone(
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
    # ANÁLISIS
    # ========================================================

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

        evaluados = (
            aciertos +
            fallos
        )

        if evaluados:

            precision = (
                aciertos /
                evaluados
            ) * 100

        else:

            precision = 0


        a, b, c = st.columns(3)

        a.metric(
            "✅ Aciertos",
            aciertos
        )

        b.metric(
            "❌ Fallos",
            fallos
        )

        c.metric(
            "🎯 Precisión",
            f"{precision:.1f}%"
        )

    else:

        st.info(
            "El historial aparecerá "
            "cuando termine el primer contrato."
        )


    # ========================================================
    # INFORMACIÓN
    # ========================================================

    st.divider()

    st.caption(
        "La aplicación analiza los contratos "
        "BTC 15M de Kalshi y registra las "
        "predicciones y resultados. "
        "NO coloca apuestas automáticamente."
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

time.sleep(5)

st.rerun()
