import os
import threading
import time
import unicodedata
from urllib.parse import quote

from flask import Flask, jsonify, request
from funciones import (
    abrir_dia,
    agendar_turno,
    cancelar_turno,
    cerrar_dia,
    consultar_balance,
    consultar_turnos,
    marcar_corte_realizado,
)
from parser_ia import interpretar_mensaje
import requests

app = Flask(__name__)
LOCK = threading.Lock()

EVOLUTION_URL = os.getenv("EVOLUTION_URL", "").rstrip("/")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")
EVOLUTION_APIKEY = os.getenv("EVOLUTION_APIKEY", "")

# Segundos máximos de antigüedad de un mensaje para procesarlo. Sirve para
# atender los mensajes que llegaron mientras Render estaba despertando.
MAX_ANTIGUEDAD_SEG = 300


def _leer_autorizados() -> set:
  """Lee los números permitidos de la variable REMITENTES_AUTORIZADOS.

  En Render: REMITENTES_AUTORIZADOS = 5491100000000,5491100000001
  (solo números, separados por coma).
  """
  crudo = os.getenv("REMITENTES_AUTORIZADOS", "")
  autorizados = set()
  for parte in crudo.split(","):
    numero = "".join(c for c in parte if c.isdigit())
    if numero:
      autorizados.add(f"{numero}@s.whatsapp.net")
  return autorizados


REMITENTES_AUTORIZADOS = _leer_autorizados()

mensajes_vistos = set()
filtros_por_numero = {}


def ruta_agenda(remitente: str) -> str:
  """Devuelve la agenda propia de cada número (una pestaña / un Excel)."""
  numero = "".join(c for c in remitente.split("@")[0] if c.isdigit())
  if not numero:
    return "turnos.xlsx"
  return f"turnos_{numero}.xlsx"


def filtro_de(remitente: str) -> dict:
  """Último filtro de consulta de cada número (cada uno tiene el suyo)."""
  return filtros_por_numero.setdefault(remitente, {"todos": False, "fecha": ""})


def sin_tildes(texto: str) -> str:
  return "".join(
      c
      for c in unicodedata.normalize("NFD", texto)
      if unicodedata.category(c) != "Mn"
  )


def es_chat_valido(remitente: str) -> bool:
  if not remitente:
    return False
  if remitente.endswith("@g.us"):
    return False
  return True


def enviar_whatsapp(remitente: str, texto: str) -> None:
  if not EVOLUTION_APIKEY or not texto:
    print(
        "⚠️ Falta configurar EVOLUTION_APIKEY; "
        "no se envió respuesta por WhatsApp.",
        flush=True,
    )
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
    respuesta = requests.post(url, json=payload, headers=headers, timeout=10)
    if respuesta.status_code >= 400:
      print(
          f"⚠️ Error Evolution API ({respuesta.status_code}): {respuesta.text}",
          flush=True,
      )
    else:
      print(f"📤 Confirmación enviada a {numero}", flush=True)
  except Exception as error:
    print(
        "⚠️ No se pudo enviar confirmación por WhatsApp:",
        repr(error),
        flush=True,
    )


def extraer_mensajes_nuevos(payload: dict) -> list[tuple[str, str, str]]:
  event = payload.get("event")
  if event and event != "messages.upsert":
    return []

  raw_data = payload.get("data", payload)
  items = raw_data if isinstance(raw_data, list) else [raw_data]

  ahora = int(time.time())
  mensajes_validos = []

  def extraer_texto(mensaje: dict) -> str:
    while isinstance(mensaje, dict):
      texto = (
          mensaje.get("conversation")
          or (mensaje.get("extendedTextMessage") or {}).get("text")
          or (mensaje.get("imageMessage") or {}).get("caption")
          or (mensaje.get("videoMessage") or {}).get("caption")
          or (mensaje.get("documentMessage") or {}).get("caption")
      )

      if texto:
        return str(texto).strip()

      envoltorio = (
          mensaje.get("ephemeralMessage")
          or mensaje.get("viewOnceMessage")
          or mensaje.get("viewOnceMessageV2")
          or mensaje.get("documentWithCaptionMessage")
      )
      if not isinstance(envoltorio, dict):
        return ""

      mensaje = envoltorio.get("message") or {}

    return ""

  for item in items:
    if not isinstance(item, dict):
      continue

    key = item.get("key") or {}
    if key.get("fromMe"):
      continue

    remitente = key.get("remoteJid") or ""
    # WhatsApp a veces manda un ID interno (@lid) en vez del número real.
    # El número real viene en remoteJidAlt.
    if remitente.endswith("@lid"):
      remitente = key.get("remoteJidAlt") or remitente
    if not es_chat_valido(remitente):
      continue

    msg_id = key.get("id") or ""
    if msg_id and msg_id in mensajes_vistos:
      continue

    ts = item.get("messageTimestamp")
    if isinstance(ts, (int, float)) and (ahora - ts) > MAX_ANTIGUEDAD_SEG:
      continue

    mensaje = item.get("message") or {}
    texto = extraer_texto(mensaje)

    if not texto:
      continue

    mensajes_validos.append((msg_id, texto, remitente))

  return mensajes_validos


def responder(remitente: str, respuesta: str) -> None:
  print(respuesta, flush=True)
  enviar_whatsapp(remitente, respuesta)


def menu_principal() -> str:
  return (
      "👋 ¡Hola! Soy el asistente de turnos de la barbería.\n\n"
      "¿Qué necesitás?\n"
      "1️⃣ Agendar un turno\n"
      "2️⃣ Consultar mis turnos\n"
      "3️⃣ Cancelar un turno"
  )


def menu_continuar() -> str:
  return (
      "¿Qué más querés hacer?\n"
      "1️⃣ Agendar un turno\n"
      "2️⃣ Consultar mis turnos\n"
      "3️⃣ Cancelar un turno"
  )


def procesar_mensajes(mensajes):
  for msg_id, texto, remitente in mensajes:
    if remitente.strip().lower() not in REMITENTES_AUTORIZADOS:
      print("🚫 Remitente no autorizado", flush=True)
      continue

    if msg_id:
      if msg_id in mensajes_vistos:
        print("♻️ Mensaje duplicado ignorado", flush=True)
        continue
      mensajes_vistos.add(msg_id)
      if len(mensajes_vistos) > 2000:
        mensajes_vistos.clear()

    try:
      print(f"💬 Mensaje nuevo de {remitente}: {texto}", flush=True)
      operaciones = interpretar_mensaje(texto)
      print("🤖 El parser entendió:", operaciones, flush=True)

      if not operaciones:
        responder(
            remitente,
            "No pude interpretar el mensaje. "
            "Indicá si querés agendar, consultar o cancelar un turno.",
        )
        continue

      ruta = ruta_agenda(remitente)
      ultimo_filtro_turnos = filtro_de(remitente)
      resultados = []
      for datos in operaciones:
        accion = datos.get("accion")

        if accion == "abrir_dia":
          fecha_dia = datos.get("fecha") or ""
          ultimo_filtro_turnos["todos"] = False
          ultimo_filtro_turnos["fecha"] = fecha_dia
          resultados.append(
              f"{abrir_dia(fecha_dia or None, ruta_excel=ruta)}\n\n{menu_continuar()}"
          )
        elif accion == "cerrar_dia":
          fecha_dia = datos.get("fecha") or None
          resultados.append(f"{cerrar_dia(fecha_dia, ruta_excel=ruta)}\n\n{menu_continuar()}")
        elif accion == "menu":
          resultados.append(menu_principal())
        elif accion == "cierre":
          resultados.append(
              "¡Bárbaro! Cuando necesites agendar, consultar o cancelar un"
              " turno, avisame."
          )
        elif accion == "opcion_agendar":
          resultados.append(
              "Para agendar, mandame el nombre del cliente, el día y la"
              " hora.\nEjemplo: Juan mañana a las 15:00"
          )
        elif accion == "opcion_consultar":
          resultados.append(
              "¿De qué fecha querés consultar los turnos?\n"
              "Ejemplo: consultar turnos de mañana o escribí *todos*"
          )
        elif accion == "opcion_cancelar":
          resultados.append(
              "Pasame el nombre del cliente y la fecha y hora del"
              " turno.\nEjemplo: cancelar turno de Juan mañana a las 15:00"
          )
        elif accion == "agendar":
          resultados.append(f"{agendar_turno(datos, ruta_excel=ruta)}\n\n{menu_continuar()}")
        elif accion == "consultar":
          pedir_todos = (
              str(datos.get("fecha") or "").strip().lower()
              in {"todos", "todo", "ver todos"}
              or "todos" in sin_tildes(texto).lower()
          )
          ultimo_filtro_turnos["todos"] = pedir_todos
          ultimo_filtro_turnos["fecha"] = (
              "" if pedir_todos else (datos.get("fecha") or "")
          )
          resultados.append(
              f"{consultar_turnos(datos.get('fecha'), ruta_excel=ruta, todos=pedir_todos)}\n\n{menu_continuar()}"
          )
        elif accion == "cancelar":
          resultados.append(f"{cancelar_turno(datos, ruta_excel=ruta)}\n\n{menu_continuar()}")
        elif accion == "realizado":
          msg_realizado = marcar_corte_realizado(datos, ruta_excel=ruta)
          if ultimo_filtro_turnos["todos"]:
            lista_restante = consultar_turnos(ruta_excel=ruta, todos=True)
          else:
            fecha_lista = ultimo_filtro_turnos["fecha"] or datos.get("fecha")
            lista_restante = consultar_turnos(fecha_lista, ruta_excel=ruta, todos=False)
          resultados.append(
              f"{msg_realizado}\n\n{lista_restante}\n\n{menu_continuar()}"
          )
        elif accion == "balance":
          fecha_bal = datos.get("fecha") or (
              None
              if ultimo_filtro_turnos["todos"]
              else (ultimo_filtro_turnos["fecha"] or None)
          )
          resultados.append(
              f"{consultar_balance(fecha_bal, ruta_excel=ruta)}\n\n{menu_continuar()}"
          )
        else:
          resultados.append(
              "No entendí la operación. Probá indicar si querés agendar,"
              " consultar o cancelar un turno."
          )

      if resultados:
        responder(remitente, "\n\n".join(map(str, resultados)))

    except Exception as error:
      print("⚠️ Algo falló:", repr(error), flush=True)
      enviar_whatsapp(
          remitente,
          "⚠️ No pude procesar el mensaje. Probá de nuevo en un rato.",
      )

  return jsonify({"status": "ok"}), 200


@app.route("/webhook", methods=["POST"])
def recibir_mensaje_whatsapp():
  datos_recibidos = request.get_json(silent=True) or {}

  data = datos_recibidos.get("data")
  clave = data.get("key", {}) if isinstance(data, dict) else {}
  remitente = clave.get("remoteJid", "")
  if remitente.endswith("@lid"):
    remitente = clave.get("remoteJidAlt") or remitente

  if (
      datos_recibidos.get("event") == "messages.upsert"
      and remitente in REMITENTES_AUTORIZADOS
      and not clave.get("fromMe")
  ):
    print(
        "🔎",
        datos_recibidos.get("event"),
        remitente,
        "fromMe:",
        clave.get("fromMe"),
        flush=True,
    )

  mensajes = extraer_mensajes_nuevos(datos_recibidos)
  if not mensajes:
    return jsonify({"status": "ignored"}), 200

  with LOCK:
    return procesar_mensajes(mensajes)


if __name__ == "__main__":
  if not REMITENTES_AUTORIZADOS:
    print(
        "⚠️ No hay números autorizados. Cargá la variable de entorno "
        "REMITENTES_AUTORIZADOS (números separados por coma).",
        flush=True,
    )
  print(
      "🚀 Servidor de turnos escuchando mensajes de Evolution API...",
      flush=True,
  )
  app.run(host="0.0.0.0", port=5000, debug=False)
