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
            "No existe KALSHI_PRIVATE_KEY en Secrets."
        )

    key = PRIVATE_KEY.strip()

    try:

        return serialization.load_pem_private_key(
            key.encode("utf-8"),
            password=None
        )

    except Exception as e:

        raise Exception(
            "La KALSHI_PRIVATE_KEY no tiene un "
            "formato PEM válido. Debe comenzar con "
            "-----BEGIN RSA PRIVATE KEY----- o "
            "-----BEGIN PRIVATE KEY----- y terminar "
            "con su correspondiente END."
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
            "Falta KALSHI_API_KEY_ID en Secrets."
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
# MERCADOS BTC 15M
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
# FECHA
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
        key=lambda x:
        x["_close"]
    )

    return candidatos[0]


# ============================================================
# OBTENER TARGET
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


    for numero in numeros:

        try:

            valor = float(
                numero.replace(
                    ",",
                    ""
                )
            )

            if valor > 1000:
                return valor

        except Exception:
            pass


    raise Exception(
        "No pude encontrar el Target "
        "del contrato."
    )


# ============================================================
# BTC DESDE BINANCE
# ============================================================

def obtener_btc():

    url = (
        "https://api.binance.com/api/v3/klines"
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

    filas = []

    for vela in data:

        filas.append({

            "time":
                datetime.fromtimestamp(
                    vela[0] / 1000,
                    tz=timezone.utc
                ),

            "Open":
                float(vela[1]),

            "High":
                float(vela[2]),

            "Low":
                float(vela[3]),

            "Close":
                float(vela[4]),

            "Volume":
                float(vela[5])
        })


    df = pd.DataFrame(filas)

    return df


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
        ema12 -
        ema26
    )


    # MOMENTUM

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
            f"BTC está "
            f"${distancia:,.2f} "
            f"(+{porcentaje:.3f}%) "
            "sobre el Target."
        )

    elif distancia < 0:

        bajar += 20

        razones.append(
            f"BTC está "
            f"${abs(distancia):,.2f} "
            f"({porcentaje:.3f}%) "
            "debajo del Target."
        )

    else:

        razones.append(
            "BTC está exactamente "
            "en el Target."
        )


    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if ema9 > ema21:

        subir += 25

        razones.append(
            "EMA9 > EMA21: "
            "tendencia alcista."
        )

    else:

        bajar += 25

        razones.append(
            "EMA9 < EMA21: "
            "tendencia bajista."
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
                f"RSI {rsi:.1f}: "
                "posible rebote."
            )

        elif rsi > 65:

            bajar += 15

            razones.append(
                f"RSI {rsi:.1f}: "
                "presión bajista."
            )

        else:

            razones.append(
                f"RSI {rsi:.1f}: "
                "zona neutral."
            )


    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if pd.notna(momentum):

        momentum = float(momentum)

        if momentum > 0:

            subir += 20

            razones.append(
                f"Momentum "
                f"+{momentum:.3f}%."
            )

        elif momentum < 0:

            bajar += 20

            razones.append(
                f"Momentum "
                f"{momentum:.3f}%."
            )


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

        prediccion = (
            "⚪ NO APOSTAR"
        )

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
# OBTENER RESULTADO REAL DE KALSHI
# ============================================================

def obtener_resultado_kalshi(
    ticker,
    target
):

    data = kalshi_request(

        "GET",

        "/trade-api/v2/markets/"
        + ticker
    )

    mercado = data.get(
        "market",
        {}
    )


    resultado = mercado.get(
        "result"
    )


    expiration_value = mercado.get(
        "expiration_value"
    )


    if resultado:

        resultado = str(
            resultado
        ).upper()

        if resultado in (
            "YES",
            "UP"
        ):

            return "UP", expiration_value

        if resultado in (
            "NO",
            "DOWN"
        ):

            return "DOWN", expiration_value


    if expiration_value not in (
        None,
        ""
    ):

        try:

            valor = float(
                expiration_value
            )

            if valor > float(target):

                return (
                    "UP",
                    expiration_value
                )

            elif valor < float(target):

                return (
                    "DOWN",
                    expiration_value
                )

        except Exception:
            pass


    return (
        "UNKNOWN",
        expiration_value
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

st.caption(
    "Predicción: ¿BTC terminará ARRIBA "
    "o ABAJO del Target de Kalshi?"
)


# ============================================================
# CREDENCIALES
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ Faltan las credenciales de Kalshi."
    )

    st.info(
        "Ve a Streamlit → Settings → Secrets "
        "y verifica KALSHI_API_KEY_ID y "
        "KALSHI_PRIVATE_KEY."
    )

    st.stop()


# ============================================================
# EJECUCIÓN
# ============================================================

try:

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
    # CONTRATO KALSHI
    # --------------------------------------------------------

    mercado = buscar_mercado_actual()


    # --------------------------------------------------------
    # SI NO HAY CONTRATO MOMENTÁNEAMENTE
    # --------------------------------------------------------

    if mercado is None:

        st.warning(
            "⏳ Kalshi está entre contratos. "
            "Esperando el próximo BTC 15M..."
        )

        st.write(
            f"₿ BTC actual: "
            f"${precio:,.2f}"
        )

        st.info(
            "La aplicación seguirá comprobando "
            "automáticamente."
        )

        time.sleep(3)
        st.rerun()


    ticker = mercado.get(
        "ticker"
    )

    target = obtener_target(
        mercado
    )

    close_time = mercado[
        "_close"
    ]


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


    # ========================================================
    # NUEVO CONTRATO
    # ========================================================

    if (
        st.session_state.ticker
        != ticker
    ):


        # ----------------------------------------------------
        # CERRAR CONTRATO ANTERIOR
        # ----------------------------------------------------

        if (
            st.session_state.ticker
            and
            st.session_state.prediccion
        ):

            anterior_ticker = (
                st.session_state.ticker
            )

            anterior_target = (
                st.session_state.target
            )

            anterior_prediccion = (
                st.session_state.prediccion
            )

            anterior_confianza = (
                st.session_state.confianza
            )

            anterior_precio = (
                st.session_state.precio_inicio
            )


            try:

                resultado_real, expiration_value = (
                    obtener_resultado_kalshi(

                        anterior_ticker,

                        anterior_target
                    )
                )


                if (
                    anterior_prediccion
                    == "🟢 ARRIBA"
                    and
                    resultado_real
                    == "UP"
                ):

                    resultado = (
                        "✅ ACIERTO"
                    )

                elif (
                    anterior_prediccion
                    == "🔴 ABAJO"
                    and
                    resultado_real
                    == "DOWN"
                ):

                    resultado = (
                        "✅ ACIERTO"
                    )

                elif (
                    anterior_prediccion
                    == "⚪ NO APOSTAR"
                ):

                    resultado = (
                        "⚪ NO APOSTAR"
                    )

                elif (
                    resultado_real
                    == "UNKNOWN"
                ):

                    resultado = (
                        "⏳ SIN RESOLVER"
                    )

                else:

                    resultado = (
                        "❌ FALLÓ"
                    )


                registro = {

                    "Hora":
                        datetime.now(
                            LOCAL_TZ
                        ).strftime(
                            "%Y-%m-%d %I:%M:%S %p"
                        ),

                    "Ticker":
                        anterior_ticker,

                    "Target":
                        round(
                            anterior_target,
                            2
                        ),

                    "Predicción":
                        anterior_prediccion,

                    "Confianza":
                        f"{anterior_confianza}%",

                    "Precio entrada":
                        round(
                            anterior_precio,
                            2
                        ),

                    "Expiration Value":
                        expiration_value,

                    "Resultado Kalshi":
                        resultado_real,

                    "Resultado":
                        resultado
                }


                tickers = [

                    x.get(
                        "Ticker"
                    )

                    for x
                    in st.session_state.historial
                ]


                if (
                    anterior_ticker
                    not in tickers
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
                    "terminó, pero Kalshi todavía "
                    "no ha publicado el resultado. "
                    "Se intentará nuevamente."
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


        st.session_state.ticker = (
            ticker
        )

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
            "BTC está exactamente "
            "en el Target."
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

    minutos = (
        segundos_restantes // 60
    )

    segundos = (
        segundos_restantes % 60
    )


    if segundos_restantes <= 60:

        st.warning(
            f"⚠️ ÚLTIMO MINUTO — "
            f"{minutos:02d}:{segundos:02d}"
        )


    st.subheader(
        f"⏳ Tiempo restante: "
        f"{minutos:02d}:{segundos:02d}"
    )


    hora_cierre_local = (
        close_time.astimezone(
            LOCAL_TZ
        )
    )


    st.write(
        "Cierre:",
        hora_cierre_local.strftime(
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
        "📈 BTC — últimos minutos"
    )


    grafico = btc[
        [
            "time",
            "Close"
        ]
    ].copy()


    grafico = grafico.set_index(
        "time"
    )


    st.line_chart(
        grafico
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


        if evaluados > 0:

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
            "cuando termine el primer "
            "contrato."
        )


    # ========================================================
    # INFORMACIÓN
    # ========================================================

    st.divider()


    st.caption(
        "La aplicación NO coloca apuestas. "
        "Solamente analiza los contratos BTC "
        "15M de Kalshi y registra la predicción "
        "y su resultado."
    )


except requests.exceptions.HTTPError as e:

    st.error(
        "❌ Error obteniendo el precio de BTC."
    )

    st.code(
        str(e)
    )

    st.info(
        "La aplicación ya no utiliza CoinGecko. "
        "Si Binance tiene un problema temporal, "
        "se reintentará automáticamente."
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
