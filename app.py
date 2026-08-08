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

PREPARAR_SEGUNDOS = 180

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

@st.cache_resource
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

    except Exception as error:

        raise Exception(
            "KALSHI_PRIVATE_KEY no tiene un formato PEM válido."
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

    try:

        return response.json()

    except Exception as error:

        raise Exception(
            "Kalshi no devolvió JSON válido."
        ) from error


# ============================================================
# FECHAS
# ============================================================

def convertir_fecha(valor):

    if not valor:
        return None

    try:

        texto = str(valor)

        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"

        fecha = datetime.fromisoformat(texto)

        if fecha.tzinfo is None:
            fecha = fecha.replace(
                tzinfo=timezone.utc
            )

        return fecha

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

    mercados = data.get(
        "markets",
        []
    )

    return mercados


# ============================================================
# CONTRATO INDIVIDUAL
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
# OBTENER CONTRATO ACTUAL
# ============================================================

def obtener_cierre(mercado):

    cierre = convertir_fecha(
        mercado.get("close_time")
    )

    if cierre is None:

        cierre = convertir_fecha(
            mercado.get("expiration_time")
        )

    return cierre


def buscar_mercado_actual():

    mercados = obtener_mercados_btc()

    ahora = datetime.now(
        timezone.utc
    )

    candidatos = []

    for mercado in mercados:

        cierre = obtener_cierre(
            mercado
        )

        if cierre is None:
            continue

        if cierre > ahora:

            copia = dict(mercado)

            copia["_close"] = cierre

            candidatos.append(
                copia
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
# CONVERSIÓN DE PRECIOS
# ============================================================

def convertir_numero_precio(valor):

    if valor is None:
        return None

    try:

        if isinstance(valor, bool):
            return None

        if isinstance(valor, (int, float)):

            numero = float(valor)

        else:

            texto = str(valor)

            texto = (
                texto
                .replace(",", "")
                .replace("$", "")
                .replace("USD", "")
                .strip()
            )

            numero = float(texto)

        if not math.isfinite(numero):
            return None

        # BTC en este programa debe ser claramente
        # superior a 1,000 USD.

        if numero >= 1000:
            return numero

    except Exception:
        return None

    return None


# ============================================================
# BUSCAR TARGET
# ============================================================

def buscar_targets_recursivo(
    objeto,
    resultados=None,
    ruta=""
):

    if resultados is None:
        resultados = []

    # --------------------------------------------------------
    # DICCIONARIO
    # --------------------------------------------------------

    if isinstance(objeto, dict):

        for clave, valor in objeto.items():

            clave_lower = str(
                clave
            ).lower()

            nueva_ruta = (
                f"{ruta}.{clave}"
                if ruta
                else str(clave)
            )

            # ------------------------------------------------
            # CAMPOS MÁS IMPORTANTES
            # ------------------------------------------------

            if clave_lower in (
                "functional_strike",
                "target_price",
                "strike_price",
                "strike"
            ):

                numero = convertir_numero_precio(
                    valor
                )

                if numero is not None:

                    resultados.append({

                        "valor": numero,

                        "prioridad": 100,

                        "campo":
                            clave,

                        "ruta":
                            nueva_ruta
                    })

            # ------------------------------------------------
            # FLOOR STRIKE
            # ------------------------------------------------

            elif clave_lower == "floor_strike":

                numero = convertir_numero_precio(
                    valor
                )

                if numero is not None:

                    resultados.append({

                        "valor": numero,

                        "prioridad": 95,

                        "campo":
                            clave,

                        "ruta":
                            nueva_ruta
                    })

            # ------------------------------------------------
            # CAMPOS SECUNDARIOS
            # ------------------------------------------------

            elif clave_lower in (
                "cap_strike",
                "lower_strike",
                "upper_strike"
            ):

                numero = convertir_numero_precio(
                    valor
                )

                if numero is not None:

                    resultados.append({

                        "valor": numero,

                        "prioridad": 70,

                        "campo":
                            clave,

                        "ruta":
                            nueva_ruta
                    })

            # ------------------------------------------------
            # RECURSIÓN
            # ------------------------------------------------

            buscar_targets_recursivo(
                valor,
                resultados,
                nueva_ruta
            )

    # --------------------------------------------------------
    # LISTAS
    # --------------------------------------------------------

    elif isinstance(objeto, list):

        for indice, elemento in enumerate(objeto):

            nueva_ruta = (
                f"{ruta}[{indice}]"
            )

            buscar_targets_recursivo(
                elemento,
                resultados,
                nueva_ruta
            )

    return resultados


# ============================================================
# EXTRAER NÚMEROS DE TEXTO
# ============================================================

def extraer_precios_de_texto(texto):

    resultados = []

    if not texto:
        return resultados

    patrones = [

        # $64,887.18
        r"\$([0-9][0-9,]*(?:\.[0-9]+)?)",

        # 64887.18 USD
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:USD|USDT)",

        # target 64887.18
        r"target[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)",

        # strike 64887.18
        r"strike[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)"
    ]

    for patron in patrones:

        encontrados = re.findall(
            patron,
            texto,
            flags=re.IGNORECASE
        )

        for encontrado in encontrados:

            try:

                numero = float(
                    encontrado.replace(
                        ",",
                        ""
                    )
                )

                if numero >= 1000:

                    resultados.append(
                        numero
                    )

            except Exception:
                pass

    return resultados


# ============================================================
# TARGET DESDE TEXTO
# ============================================================

def buscar_target_en_texto(mercado):

    campos_prioritarios = [

        "subtitle",
        "yes_sub_title",
        "no_sub_title",
        "title",
        "event_title",
        "ticker",
        "event_ticker"
    ]

    candidatos = []

    for campo in campos_prioritarios:

        valor = mercado.get(
            campo
        )

        if not valor:
            continue

        precios = extraer_precios_de_texto(
            str(valor)
        )

        for precio in precios:

            prioridad = 10

            if campo in (
                "subtitle",
                "yes_sub_title",
                "no_sub_title"
            ):
                prioridad = 30

            if campo == "title":
                prioridad = 20

            candidatos.append(
                (
                    prioridad,
                    precio,
                    campo
                )
            )

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda x: x[0],
        reverse=True
    )

    return float(
        candidatos[0][1]
    )


# ============================================================
# TARGET ROBUSTO
# ============================================================

def obtener_target(mercado):

    # --------------------------------------------------------
    # 1. TARGET DIRECTO
    # --------------------------------------------------------

    encontrados = buscar_targets_recursivo(
        mercado
    )

    if encontrados:

        # Prioridad primero.

        encontrados.sort(

            key=lambda x: (
                x["prioridad"],
                x["valor"]
            ),

            reverse=True
        )

        return float(
            encontrados[0]["valor"]
        )


    # --------------------------------------------------------
    # 2. TEXTO
    # --------------------------------------------------------

    target_texto = buscar_target_en_texto(
        mercado
    )

    if target_texto is not None:

        return float(
            target_texto
        )


    # --------------------------------------------------------
    # 3. CONSULTAR CONTRATO COMPLETO
    # --------------------------------------------------------

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

                    key=lambda x: (
                        x["prioridad"],
                        x["valor"]
                    ),

                    reverse=True
                )

                return float(
                    encontrados[0]["valor"]
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
        f"{ticker or ''}."
    )


# ============================================================
# BTC BINANCE
# ============================================================

def obtener_btc():

    urls = [

        "https://api.binance.us/api/v3/klines",

        "https://api.binance.com/api/v3/klines"
    ]

    ultimo_error = None

    for url in urls:

        try:

            response = requests.get(

                url,

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
                    "Respuesta inválida."
                )

            if len(data) < 30:
                raise Exception(
                    "No hay suficientes velas."
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

            if len(df) < 30:
                raise Exception(
                    "Datos BTC insuficientes."
                )

            return df

        except Exception as error:

            ultimo_error = error

    raise Exception(
        f"No se pudo obtener BTC: {ultimo_error}"
    )


# ============================================================
# INDICADORES
# ============================================================

def calcular_indicadores(df):

    df = df.copy()

    close = df["Close"]

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    df["EMA9"] = (
        close
        .ewm(
            span=9,
            adjust=False
        )
        .mean()
    )

    df["EMA21"] = (
        close
        .ewm(
            span=21,
            adjust=False
        )
        .mean()
    )

    df["EMA50"] = (
        close
        .ewm(
            span=50,
            adjust=False
        )
        .mean()
    )

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    ema12 = (
        close
        .ewm(
            span=12,
            adjust=False
        )
        .mean()
    )

    ema26 = (
        close
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

    df["MACD_HIST"] = (
        df["MACD"] -
        df["MACD_SIGNAL"]
    )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    cambio = close.diff()

    ganancias = cambio.clip(
        lower=0
    )

    perdidas = -cambio.clip(
        upper=0
    )

    avg_gain = (
        ganancias
        .rolling(
            14,
            min_periods=14
        )
        .mean()
    )

    avg_loss = (
        perdidas
        .rolling(
            14,
            min_periods=14
        )
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

    # --------------------------------------------------------
    # Momentum
    # --------------------------------------------------------

    df["Momentum1"] = (
        close
        .pct_change(1)
        * 100
    )

    df["Momentum3"] = (
        close
        .pct_change(3)
        * 100
    )

    df["Momentum5"] = (
        close
        .pct_change(5)
        * 100
    )

    df["Momentum10"] = (
        close
        .pct_change(10)
        * 100
    )

    df["Momentum15"] = (
        close
        .pct_change(15)
        * 100
    )

    # --------------------------------------------------------
    # Volatilidad
    # --------------------------------------------------------

    retornos = (
        close
        .pct_change()
    )

    df["Volatilidad"] = (
        retornos
        .rolling(15)
        .std()
        * 100
    )

    # --------------------------------------------------------
    # Máximo / mínimo recientes
    # --------------------------------------------------------

    df["High15"] = (
        df["High"]
        .rolling(15)
        .max()
    )

    df["Low15"] = (
        df["Low"]
        .rolling(15)
        .min()
    )

    return df


# ============================================================
# UTILIDAD PARA SEÑALES
# ============================================================

def numero_seguro(valor):

    try:

        numero = float(valor)

        if math.isfinite(numero):
            return numero

    except Exception:
        pass

    return None


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

    # ========================================================
    # VALORES
    # ========================================================

    ema9 = numero_seguro(
        ultimo["EMA9"]
    )

    ema21 = numero_seguro(
        ultimo["EMA21"]
    )

    ema50 = numero_seguro(
        ultimo["EMA50"]
    )

    macd = numero_seguro(
        ultimo["MACD"]
    )

    macd_signal = numero_seguro(
        ultimo["MACD_SIGNAL"]
    )

    macd_hist = numero_seguro(
        ultimo["MACD_HIST"]
    )

    rsi = numero_seguro(
        ultimo["RSI"]
    )

    momentum1 = numero_seguro(
        ultimo["Momentum1"]
    )

    momentum3 = numero_seguro(
        ultimo["Momentum3"]
    )

    momentum5 = numero_seguro(
        ultimo["Momentum5"]
    )

    momentum10 = numero_seguro(
        ultimo["Momentum10"]
    )

    momentum15 = numero_seguro(
        ultimo["Momentum15"]
    )

    volatilidad = numero_seguro(
        ultimo["Volatilidad"]
    )

    # ========================================================
    # SCORE
    # ========================================================

    score = 0

    razones = []

    señales = []


    # ========================================================
    # 1. TARGET
    # ========================================================

    diferencia = (
        precio -
        target
    )

    diferencia_pct = (
        diferencia /
        target
    ) * 100

    razones.append(
        f"BTC ${precio:,.2f} vs Target "
        f"${target:,.2f}: "
        f"{diferencia:+,.2f} "
        f"({diferencia_pct:+.4f}%)."
    )

    # --------------------------------------------------------
    # Distancia fuerte
    # --------------------------------------------------------

    # Para un contrato de 15 minutos no queremos darle
    # demasiado peso a una diferencia mínima.

    abs_pct = abs(
        diferencia_pct
    )

    if abs_pct >= 0.08:

        puntos_target = 28

    elif abs_pct >= 0.05:

        puntos_target = 24

    elif abs_pct >= 0.03:

        puntos_target = 20

    elif abs_pct >= 0.015:

        puntos_target = 12

    elif abs_pct >= 0.005:

        puntos_target = 6

    else:

        puntos_target = 0

    if diferencia > 0:

        score += puntos_target

        if puntos_target > 0:

            señales.append(
                "Target: ARRIBA"
            )

    elif diferencia < 0:

        score -= puntos_target

        if puntos_target > 0:

            señales.append(
                "Target: ABAJO"
            )


    # ========================================================
    # 2. MOMENTUM 1M
    # ========================================================

    if momentum1 is not None:

        if momentum1 > 0.015:

            score += 5

            razones.append(
                f"Momentum 1m alcista: "
                f"+{momentum1:.3f}%."
            )

        elif momentum1 < -0.015:

            score -= 5

            razones.append(
                f"Momentum 1m bajista: "
                f"{momentum1:.3f}%."
            )


    # ========================================================
    # 3. MOMENTUM 3M
    # ========================================================

    if momentum3 is not None:

        if momentum3 > 0.025:

            score += 8

            razones.append(
                f"Momentum 3m alcista: "
                f"+{momentum3:.3f}%."
            )

        elif momentum3 < -0.025:

            score -= 8

            razones.append(
                f"Momentum 3m bajista: "
                f"{momentum3:.3f}%."
            )


    # ========================================================
    # 4. MOMENTUM 5M
    # ========================================================

    if momentum5 is not None:

        if momentum5 > 0.035:

            score += 9

            razones.append(
                f"Momentum 5m alcista: "
                f"+{momentum5:.3f}%."
            )

        elif momentum5 < -0.035:

            score -= 9

            razones.append(
                f"Momentum 5m bajista: "
                f"{momentum5:.3f}%."
            )


    # ========================================================
    # 5. MOMENTUM 10M
    # ========================================================

    if momentum10 is not None:

        if momentum10 > 0.05:

            score += 7

            razones.append(
                f"Momentum 10m alcista: "
                f"+{momentum10:.3f}%."
            )

        elif momentum10 < -0.05:

            score -= 7

            razones.append(
                f"Momentum 10m bajista: "
                f"{momentum10:.3f}%."
            )


    # ========================================================
    # 6. MOMENTUM 15M
    # ========================================================

    if momentum15 is not None:

        if momentum15 > 0.07:

            score += 7

            razones.append(
                f"Momentum 15m alcista: "
                f"+{momentum15:.3f}%."
            )

        elif momentum15 < -0.07:

            score -= 7

            razones.append(
                f"Momentum 15m bajista: "
                f"{momentum15:.3f}%."
            )


    # ========================================================
    # 7. EMA 9 / 21
    # ========================================================

    if ema9 is not None and ema21 is not None:

        if ema9 > ema21:

            score += 10

            razones.append(
                "EMA9 > EMA21: tendencia "
                "corta alcista."
            )

        elif ema9 < ema21:

            score -= 10

            razones.append(
                "EMA9 < EMA21: tendencia "
                "corta bajista."
            )


    # ========================================================
    # 8. EMA 21 / 50
    # ========================================================

    if ema21 is not None and ema50 is not None:

        if ema21 > ema50:

            score += 7

            razones.append(
                "EMA21 > EMA50: estructura "
                "alcista."
            )

        elif ema21 < ema50:

            score -= 7

            razones.append(
                "EMA21 < EMA50: estructura "
                "bajista."
            )


    # ========================================================
    # 9. PRECIO VS EMA9
    # ========================================================

    if ema9 is not None:

        if precio > ema9:

            score += 4

        elif precio < ema9:

            score -= 4


    # ========================================================
    # 10. MACD
    # ========================================================

    if (
        macd is not None
        and
        macd_signal is not None
    ):

        if macd > macd_signal:

            score += 8

            razones.append(
                "MACD por encima de su señal."
            )

        elif macd < macd_signal:

            score -= 8

            razones.append(
                "MACD por debajo de su señal."
            )


    # ========================================================
    # 11. MACD HISTOGRAMA
    # ========================================================

    if macd_hist is not None:

        if macd_hist > 0:

            score += 4

        elif macd_hist < 0:

            score -= 4


    # ========================================================
    # 12. RSI
    # ========================================================

    if rsi is not None:

        if 50 <= rsi <= 65:

            score += 5

            razones.append(
                f"RSI {rsi:.1f}: "
                "zona favorable para continuidad alcista."
            )

        elif 35 <= rsi < 50:

            score -= 4

            razones.append(
                f"RSI {rsi:.1f}: "
                "momentum ligeramente bajista."
            )

        elif rsi < 30:

            score += 3

            razones.append(
                f"RSI {rsi:.1f}: "
                "sobreventa; posible rebote."
            )

        elif rsi > 70:

            score -= 3

            razones.append(
                f"RSI {rsi:.1f}: "
                "sobrecompra; riesgo de corrección."
            )


    # ========================================================
    # 13. VOLATILIDAD
    # ========================================================

    if volatilidad is not None:

        razones.append(
            f"Volatilidad 15m: "
            f"{volatilidad:.4f}%."
        )


    # ========================================================
    # 14. CONSISTENCIA TARGET + MOMENTUM
    # ========================================================

    # Esta es una parte importante.
    #
    # Si BTC está por encima del Target Y el mercado
    # también está subiendo, reforzamos.
    #
    # Si BTC está por encima pero el momentum está
    # cayendo, reducimos la confianza.

    momentum_referencia = 0

    for valor, peso in [

        (momentum3, 1.0),

        (momentum5, 1.2),

        (momentum10, 0.8)

    ]:

        if valor is not None:

            momentum_referencia += (
                valor * peso
            )

    if diferencia > 0:

        if momentum_referencia > 0:

            score += 8

            razones.append(
                "Target + momentum están alineados "
                "al alza."
            )

        elif momentum_referencia < 0:

            score -= 6

            razones.append(
                "BTC está sobre el Target, pero "
                "el momentum está debilitándose."
            )

    elif diferencia < 0:

        if momentum_referencia < 0:

            score -= 8

            razones.append(
                "Target + momentum están alineados "
                "a la baja."
            )

        elif momentum_referencia > 0:

            score += 6

            razones.append(
                "BTC está bajo el Target, pero "
                "el momentum está recuperándose."
            )


    # ========================================================
    # DECISIÓN
    # ========================================================

    if score >= 25:

        prediccion = "🟢 ARRIBA"

    elif score <= -25:

        prediccion = "🔴 ABAJO"

    else:

        prediccion = "⚪ NO APOSTAR"


    # ========================================================
    # CONFIANZA
    # ========================================================

    if prediccion == "⚪ NO APOSTAR":

        confianza = 50

    else:

        fuerza = abs(score)

        # Escala conservadora.
        #
        # No queremos que una sola señal produzca
        # artificialmente 90% de confianza.

        if fuerza < 30:

            confianza = 56

        elif fuerza < 40:

            confianza = 63

        elif fuerza < 50:

            confianza = 70

        elif fuerza < 60:

            confianza = 77

        elif fuerza < 70:

            confianza = 83

        else:

            confianza = 88

        confianza = min(
            confianza,
            88
        )


    # ========================================================
    # RESUMEN
    # ========================================================

    razones.append(
        f"Score final: {score:+d}."
    )

    razones.append(
        f"Señal principal del Target: "
        f"{'ARRIBA' if diferencia > 0 else 'ABAJO' if diferencia < 0 else 'NEUTRAL'}."
    )

    return (

        prediccion,

        confianza,

        razones,

        score,

        {
            "precio": precio,
            "target": target,
            "diferencia": diferencia,
            "diferencia_pct": diferencia_pct,
            "momentum1": momentum1,
            "momentum3": momentum3,
            "momentum5": momentum5,
            "momentum10": momentum10,
            "momentum15": momentum15,
            "ema9": ema9,
            "ema21": ema21,
            "ema50": ema50,
            "macd": macd,
            "macd_signal": macd_signal,
            "rsi": rsi,
            "volatilidad": volatilidad
        }
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

    score,

    detalles

):

    historial = (
        st.session_state.historial
    )

    # --------------------------------------------------------
    # EVITAR DUPLICADOS
    # --------------------------------------------------------

    for registro in historial:

        if registro.get(
            "Ticker"
        ) == ticker:

            return


    cierre_texto = ""

    if close_time is not None:

        cierre_texto = (
            close_time
            .astimezone(LOCAL_TZ)
            .strftime(
                "%Y-%m-%d %I:%M:%S %p"
            )
        )


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
            int(score),

        "Precio predicción":
            round(
                float(precio),
                2
            ),

        "Distancia Target":
            round(
                float(
                    detalles["diferencia"]
                ),
                2
            ),

        "Distancia Target %":
            round(
                float(
                    detalles["diferencia_pct"]
                ),
                5
            ),

        "Momentum 1m":
            detalles["momentum1"],

        "Momentum 3m":
            detalles["momentum3"],

        "Momentum 5m":
            detalles["momentum5"],

        "Momentum 10m":
            detalles["momentum10"],

        "Momentum 15m":
            detalles["momentum15"],

        "RSI":
            detalles["rsi"],

        "Cierre":
            cierre_texto,

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

    cierre_actual = contrato_actual.get(
        "_close"
    )

    if cierre_actual is None:

        cierre_actual = obtener_cierre(
            contrato_actual
        )

    candidatos = []

    ticker_actual = contrato_actual.get(
        "ticker"
    )

    for mercado in mercados:

        ticker = mercado.get(
            "ticker"
        )

        if ticker == ticker_actual:
            continue

        cierre = obtener_cierre(
            mercado
        )

        if cierre is None:
            continue

        if (
            cierre_actual is not None
            and
            cierre <= cierre_actual
        ):
            continue

        copia = dict(mercado)

        copia["_close"] = cierre

        candidatos.append(
            copia
        )

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda x: x["_close"]
    )

    return candidatos[0]


# ============================================================
# RESULTADO OFICIAL DE KALSHI
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
    # RESULTADO OFICIAL
    # --------------------------------------------------------

    if resultado not in (
        None,
        "",
        "null"
    ):

        resultado_texto = str(
            resultado
        ).upper()

        if resultado_texto in (
            "UP",
            "YES"
        ):

            return (
                "UP",
                expiration
            )

        if resultado_texto in (
            "DOWN",
            "NO"
        ):

            return (
                "DOWN",
                expiration
            )


    # --------------------------------------------------------
    # EXPIRATION VALUE
    # --------------------------------------------------------

    if expiration not in (
        None,
        ""
    ):

        try:

            exp = float(
                expiration
            )

            target_float = float(
                target
            )

            if exp > target_float:

                return (
                    "UP",
                    exp
                )

            if exp < target_float:

                return (
                    "DOWN",
                    exp
                )

            return (
                "TIE",
                exp
            )

        except Exception:
            pass


    return (
        None,
        expiration
    )


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


        # ----------------------------------------------------
        # ACIERTO
        # ----------------------------------------------------

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


        # ----------------------------------------------------
        # NO APOSTAR
        # ----------------------------------------------------

        elif (

            prediccion == "⚪ NO APOSTAR"

        ):

            resultado = "⚪ NO APOSTAR"


        # ----------------------------------------------------
        # EMPATE
        # ----------------------------------------------------

        elif resultado_real == "TIE":

            resultado = "⚪ EMPATE"


        # ----------------------------------------------------
        # FALLO
        # ----------------------------------------------------

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


if "detalles_prediccion" not in st.session_state:

    st.session_state.detalles_prediccion = {}


if "siguiente_error" not in st.session_state:

    st.session_state.siguiente_error = None


# ============================================================
# INTERFAZ
# ============================================================

st.title(
    "₿ Bitcoin Predictor — Kalshi 15M"
)

st.caption(
    "Target de Kalshi + tendencia + momentum + "
    "EMA + MACD + RSI + volatilidad."
)


# ============================================================
# CREDENCIALES
# ============================================================

if not API_KEY_ID or not PRIVATE_KEY:

    st.error(
        "❌ No se encontraron las credenciales de Kalshi."
    )

    st.info(
        "Revisa en Streamlit Secrets:"
    )

    st.code(
        "KALSHI_API_KEY_ID\n"
        "KALSHI_PRIVATE_KEY"
    )

    st.stop()


# ============================================================
# ACTUALIZAR RESULTADOS
# ============================================================

try:

    actualizar_pendientes()

except Exception as error:

    st.warning(
        "No se pudieron actualizar algunos "
        f"resultados: {error}"
    )


# ============================================================
# EJECUCIÓN PRINCIPAL
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

        close_actual = obtener_cierre(
            actual
        )


    # ========================================================
    # TARGET ACTUAL
    # ========================================================

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
    # CAMBIO DE CONTRATO
    # ========================================================

    if (

        st.session_state.ticker_actual
        != ticker_actual

    ):

        st.session_state.ticker_actual = (
            ticker_actual
        )

        st.session_state.siguiente_contrato = None

        st.session_state.siguiente_error = None

        st.session_state.prediccion_hecha = False

        st.session_state.prediccion = None

        st.session_state.confianza = 0

        st.session_state.target_siguiente = None

        st.session_state.precio_prediccion = None

        st.session_state.razones = []

        st.session_state.score = 0

        st.session_state.detalles_prediccion = {}


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

    if close_actual is None:

        raise Exception(
            "No pude determinar el cierre del contrato."
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
                        float(
                            target_siguiente
                        ),

                    "close":
                        siguiente.get(
                            "_close"
                        )
                }

                st.session_state.siguiente_error = None

            else:

                st.session_state.siguiente_error = (
                    "Kalshi no entregó el siguiente "
                    "contrato abierto."
                )

        except Exception as error:

            st.session_state.siguiente_error = str(
                error
            )


    # ========================================================
    # PREDICCIÓN
    # ========================================================

    if (

        segundos_restantes
        <= PREDICCION_SEGUNDOS

        and

        segundos_restantes >= 0

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

            target_siguiente = float(
                siguiente_info["target"]
            )

            close_siguiente = (
                siguiente_info["close"]
            )

            if close_siguiente is None:

                close_siguiente = (
                    close_actual
                )

            (

                prediccion,

                confianza,

                razones,

                score,

                detalles

            ) = generar_prediccion(

                btc,

                target_siguiente
            )


            # ------------------------------------------------
            # GUARDAR HISTORIAL
            # ------------------------------------------------

            guardar_prediccion(

                ticker=ticker_siguiente,

                target=target_siguiente,

                prediccion=prediccion,

                confianza=confianza,

                precio=precio,

                close_time=close_siguiente,

                score=score,

                detalles=detalles
            )


            # ------------------------------------------------
            # SESSION STATE
            # ------------------------------------------------

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

            st.session_state.detalles_prediccion = (
                detalles
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
        st.write(titulo)

    if subtitulo:
        st.caption(subtitulo)


    # ========================================================
    # BTC / TARGET
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
    # DISTANCIA TARGET ACTUAL
    # ========================================================

    if target_actual is not None:

        diferencia_actual = (
            precio -
            target_actual
        )

        porcentaje_actual = (

            diferencia_actual /
            target_actual
        ) * 100


        if diferencia_actual > 0:

            st.success(

                f"BTC está ${diferencia_actual:,.2f} "
                f"({porcentaje_actual:+.4f}%) "
                "POR ENCIMA del Target."
            )

        elif diferencia_actual < 0:

            st.error(

                f"BTC está ${abs(diferencia_actual):,.2f} "
                f"({porcentaje_actual:+.4f}%) "
                "POR DEBAJO del Target."
            )

        else:

            st.warning(
                "BTC está exactamente en el Target."
            )

    else:

        st.warning(
            "⚠️ No se pudo obtener el Target actual."
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
        close_actual
        .astimezone(LOCAL_TZ)
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
                f"({porcentaje_siguiente:+.4f}%) "
                "POR ENCIMA del Target siguiente."
            )

        elif diferencia_siguiente < 0:

            st.error(

                f"BTC está ${abs(diferencia_siguiente):,.2f} "
                f"({porcentaje_siguiente:+.4f}%) "
                "POR DEBAJO del Target siguiente."
            )

        else:

            st.warning(
                "BTC está exactamente en el Target siguiente."
            )


    else:

        if st.session_state.siguiente_error:

            st.warning(
                "🔎 Todavía no se pudo obtener "
                "el siguiente contrato."
            )

            st.caption(
                st.session_state.siguiente_error
            )

        elif segundos_restantes <= 180:

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

        if siguiente_info is not None:

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


        # ====================================================
        # DETALLES
        # ====================================================

        detalles = (
            st.session_state.detalles_prediccion
        )

        if detalles:

            st.subheader(
                "📊 Señales utilizadas"
            )

            col1, col2 = st.columns(2)

            col1.metric(
                "Distancia Target",
                f"${detalles['diferencia']:+,.2f}"
            )

            col2.metric(
                "Distancia %",
                f"{detalles['diferencia_pct']:+.4f}%"
            )

            col1, col2 = st.columns(2)

            if detalles["momentum5"] is not None:

                col1.metric(
                    "Momentum 5m",
                    f"{detalles['momentum5']:+.3f}%"
                )

            if detalles["momentum15"] is not None:

                col2.metric(
                    "Momentum 15m",
                    f"{detalles['momentum15']:+.3f}%"
                )


            col1, col2 = st.columns(2)

            if detalles["rsi"] is not None:

                col1.metric(
                    "RSI",
                    f"{detalles['rsi']:.1f}"
                )

            if detalles["volatilidad"] is not None:

                col2.metric(
                    "Volatilidad",
                    f"{detalles['volatilidad']:.4f}%"
                )


        st.subheader(
            "🧠 Análisis"
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

            if siguiente_info is None:

                st.warning(
                    "⚠️ Estamos en el último minuto, "
                    "pero todavía no se encontró "
                    "el siguiente contrato."
                )

            else:

                st.warning(
                    "⚠️ Generando la predicción..."
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

        # Mostrar primero los registros más recientes.

        tabla = tabla.iloc[::-1]

        st.dataframe(

            tabla,

            use_container_width=True,

            hide_index=True
        )


        # ====================================================
        # ESTADÍSTICAS
        # ====================================================

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


        empates = sum(

            1

            for x in historial

            if x.get(
                "Resultado"
            )
            == "⚪ EMPATE"
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


        if empates > 0:

            st.caption(
                f"⚪ Empates: {empates}"
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

        "El modelo utiliza el Target del siguiente "
        "contrato de Kalshi como señal principal y "
        "lo combina con la dirección y fuerza del "
        "movimiento reciente de BTC, EMA9/21/50, "
        "MACD, RSI, momentum de 1/3/5/10/15 minutos "
        "y volatilidad. La predicción se genera "
        "durante el último minuto del contrato actual. "
        "La aplicación no coloca apuestas automáticamente."
    )


# ============================================================
# ERRORES GENERALES
# ============================================================

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
