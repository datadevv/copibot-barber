import os
import threading
import time
import unicodedata
from urllib.parse import quote

from flask import Flask, jsonify, request
import requests

from funciones import (
    deshacer_ultimo,
    interpretar_stock,
    obtener_resumen_cierre,
    obtener_saldo_cliente,
    registrar_cobro,
    registrar_entrega,
)
from parser_ia import interpretar_mensaje

# Cargar el módulo local sin depender de que el editor reconozca su ruta de importación.
import importlib

_repartidores = importlib.import_module(".repartidores", __package__) if __package__ else importlib.import_module("repartidores")
cambiar_estado_jornada = _repartidores.cambiar_estado_jornada
guardar_stock = _repartidores.guardar_stock
obtener_estado_jornada = _repartidores.obtener_estado_jornada
obtener_repartidor = _repartidores.obtener_repartidor

app = Flask(__name__)
LOCK = threading.Lock()

# Configuración de Evolution API (las claves van en variables de entorno)
EVOLUTION_URL = os.getenv("EVOLUTION_URL", "http://localhost:8080").rstrip("/")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "Benicio Sturla")
EVOLUTION_APIKEY = os.getenv("EVOLUTION_APIKEY", "")

# Guarda IDs de mensajes ya procesados para no llamar a la IA duplicado
mensajes_vistos = set()


def sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def es_chat_valido(remitente: str) -> bool:
    """Filtra grupos (@g.us) y chats vacíos."""
    if not remitente:
        return False
    if remitente.endswith("@g.us"):
        return False
    return True


def enviar_whatsapp(remitente: str, texto: str) -> None:
    """Envía el mensaje de confirmación por Evolution API al remitente."""
    if not EVOLUTION_APIKEY or not texto:
        print("⚠️ Falta configurar EVOLUTION_APIKEY; no se envió respuesta por WhatsApp.", flush=True)
        return

    numero = remitente.split("@")[0]
    url = f"{EVOLUTION_URL}/message/sendText/{quote(EVOLUTION_INSTANCE)}"
    headers = {
        "apikey": EVOLUTION_APIKEY,
        "Content-Type": "application/json",
    }
    payload = {
        "number": numero,
        "text": str(texto),
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code >= 400:
            print(f"⚠️ Error Evolution API ({resp.status_code}): {resp.text}", flush=True)
        else:
            print(f"📤 Confirmación enviada a {numero}", flush=True)
    except Exception as e:
        print("⚠️ No se pudo enviar confirmación por WhatsApp:", repr(e), flush=True)


def extraer_mensajes_nuevos(payload: dict) -> list[tuple[str, str, str]]:
    """Devuelve [(msg_id, texto, remitente), ...] solo de mensajes entrantes recientes con texto."""
    event = payload.get("event")
    if event and event != "messages.upsert":
        return []

    raw_data = payload.get("data", payload)
    items = raw_data if isinstance(raw_data, list) else [raw_data]

    ahora = int(time.time())
    mensajes_validos = []

    for item in items:
        if not isinstance(item, dict):
            continue

        key = item.get("key") or {}
        if key.get("fromMe"):
            continue

        remitente = key.get("remoteJid") or ""
        if not es_chat_valido(remitente):
            continue

        msg_id = key.get("id") or ""
        if msg_id and msg_id in mensajes_vistos:
            continue

        # Ignora mensajes históricos (más de 120 segundos de antigüedad)
        ts = item.get("messageTimestamp")
        if isinstance(ts, (int, float)) and (ahora - ts) > 120:
            continue

        msg = item.get("message") or {}

        texto = (
            msg.get("conversation")
            or (msg.get("extendedTextMessage") or {}).get("text")
            or ""
        ).strip()

        if texto:
            mensajes_validos.append((msg_id, texto, remitente))

    return mensajes_validos


def responder(remitente: str, respuesta: str) -> None:
    print(respuesta, flush=True)
    enviar_whatsapp(remitente, respuesta)


def procesar_mensajes(mensajes):
    for msg_id, texto, remitente in mensajes:
        if msg_id:
            mensajes_vistos.add(msg_id)
            if len(mensajes_vistos) > 2000:
                mensajes_vistos.clear()

        repartidor = obtener_repartidor(remitente)
        if not repartidor:
            print(f"⛔ Mensaje ignorado: {remitente} no está registrado como repartidor.", flush=True)
            continue

        stock_actual = repartidor["stock"]
        ruta_excel = repartidor["ruta_excel"]

        try:
            print(f"💬 Mensaje nuevo de {remitente} ({repartidor['nombre']}): {texto}", flush=True)

            # Comando en minúsculas y sin tildes: "Resumen del día" -> "resumen del dia"
            cmd = " ".join(sin_tildes(texto).lower().split())

            # ---------- STOCK ----------
            info_stock = interpretar_stock(texto)
            if info_stock is not None:
                modo = info_stock["modo"]
                valores = info_stock["valores"]

                if modo == "sumar":
                    for k, v in valores.items():
                        stock_actual[k] = stock_actual.get(k, 0) + v
                    prefijo = "📦 Stock sumado:"
                    guardar_stock(repartidor)
                elif modo == "fijar":
                    for k, v in valores.items():
                        stock_actual[k] = v
                    prefijo = "📦 Stock fijado:"
                    guardar_stock(repartidor)
                else:
                    prefijo = "📦 Tu stock actual:"

                respuesta = (
                    f"{prefijo} {stock_actual['grandes']} grandes, "
                    f"{stock_actual['chicos']} chicos, {stock_actual['sifones']} sifones."
                )
                if modo == "consultar":
                    respuesta += (
                        "\nPara sumar carga: stock 24 grandes 10 chicos 36 sifones"
                        "\nPara corregir/reemplazar: fijar stock 24 grandes 10 chicos 36 sifones"
                    )
                responder(remitente, respuesta)
                continue

            # ---------- RESUMEN DEL DÍA ----------
            if cmd in ("resumen", "resumen del dia", "cierre"):
                responder(remitente, obtener_resumen_cierre(ruta_excel, stock_actual))
                continue

            # ---------- SALDO DE UN CLIENTE ----------
            if cmd.startswith(("debe ", "saldo ")):
                nombre = texto.strip().split(" ", 1)[1]
                responder(remitente, obtener_saldo_cliente(ruta_excel, nombre))
                continue

            # ---------- ABRIR DÍA ----------
            if cmd in ("abrir dia", "activar dia", "abrir jornada", "iniciar dia"):
                jornada = cambiar_estado_jornada(repartidor, "abierta")
                respuesta = (
                    f"🟢 Jornada {jornada['fecha']} activada.\n"
                    f"📦 Stock actual: {stock_actual['grandes']} grandes, "
                    f"{stock_actual['chicos']} chicos, {stock_actual['sifones']} sifones."
                )
                responder(remitente, respuesta)
                continue

            # ---------- CERRAR DÍA ----------
            if cmd in ("cerrar dia", "cerrar jornada"):
                jornada = cambiar_estado_jornada(repartidor, "cerrada")
                resumen_txt = obtener_resumen_cierre(ruta_excel, stock_actual)
                responder(remitente, f"🔒 Jornada {jornada['fecha']} cerrada.\n\n{resumen_txt}")
                continue

            # ---------- SI EL DÍA ESTÁ CERRADO, NO SE CARGA NADA ----------
            if obtener_estado_jornada(repartidor)["estado"] == "cerrada":
                responder(
                    remitente,
                    "🔒 El día está cerrado. Mandá 'abrir dia' si necesitás registrar más movimientos.",
                )
                continue

            # ---------- DESHACER ----------
            if cmd.startswith(("deshacer", "borrar ultimo")):
                respuesta = deshacer_ultimo(ruta_excel, stock_actual)
                guardar_stock(repartidor)
                responder(remitente, respuesta)
                continue

            # ---------- ENTREGAS Y COBROS (con IA) ----------
            print("⏳ Llamando a Gemini...", flush=True)
            operaciones = interpretar_mensaje(texto)
            print("🤖 La IA entendió:", operaciones, flush=True)

            resultados = []
            for datos in operaciones:
                if datos.get("accion") == "entrega":
                    resultados.append(registrar_entrega(datos, stock_actual, ruta_excel))
                    repartidor["stock"] = stock_actual
                    guardar_stock(repartidor)
                elif datos.get("accion") == "cobro":
                    resultados.append(registrar_cobro(datos, ruta_excel))
                else:
                    resultados.append("🤖 No entendí si es una entrega o un cobro.")

            responder(remitente, "\n\n".join(resultados))

        except Exception as e:
            print("⚠️ Algo falló:", repr(e), flush=True)
            enviar_whatsapp(remitente, "⚠️ No pude registrar tu mensaje. Probá de nuevo en un rato.")

    return jsonify({"status": "ok"}), 200


@app.route("/webhook", methods=["POST"])
def recibir_mensaje_whatsapp():
    datos_recibidos = request.get_json(silent=True) or {}
    data = datos_recibidos.get("data")
    clave = data.get("key", {}) if isinstance(data, dict) else {}
    print("🔎", datos_recibidos.get("event"), clave.get("remoteJid", ""), "fromMe:", clave.get("fromMe"), flush=True)

    mensajes = extraer_mensajes_nuevos(datos_recibidos)
    if not mensajes:
        return jsonify({"status": "ignored"}), 200

    with LOCK:
        return procesar_mensajes(mensajes)


if __name__ == "__main__":
    print("🚀 Servidor de CopiBot escuchando mensajes de Evolution API...", flush=True)
    app.run(host="0.0.0.0", port=5000, debug=False)