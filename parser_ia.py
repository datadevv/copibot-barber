from datetime import datetime
import json
import os
import re
import unicodedata

from fallback_turnos import interpretar_turno_basico
from google import genai
from google.genai import types

PRECIO_CORTE_DEFAULT = 10000
TZ = None

DIAS_SEMANA_ES = [
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
]

SCHEMA_TURNO = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "accion": types.Schema(
            type=types.Type.STRING,
            enum=[
                "agendar",
                "consultar",
                "cancelar",
                "realizado",
                "balance",
                "desconocido",
            ],
            description="Acción solicitada.",
        ),
        "cliente": types.Schema(
            type=types.Type.STRING,
            description="Nombre del cliente.",
        ),
        "fecha": types.Schema(
            type=types.Type.STRING,
            description="Fecha del turno en formato DD-MM-YY o 'todos'.",
        ),
        "hora": types.Schema(
            type=types.Type.STRING,
            description="Hora del turno en formato HH:MM.",
        ),
        "servicio": types.Schema(
            type=types.Type.STRING,
            enum=["corte"],
            description="Servicio solicitado.",
        ),
        "precio": types.Schema(
            type=types.Type.NUMBER,
            description="Precio del turno; 10000 si no se indicó otro.",
        ),
    },
    required=["accion", "cliente", "fecha", "hora", "servicio", "precio"],
)

SCHEMA_RESPUESTA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "operaciones": types.Schema(
            type=types.Type.ARRAY,
            items=SCHEMA_TURNO,
            description="Operaciones distintas encontradas en el mensaje.",
        ),
    },
    required=["operaciones"],
)


INSTRUCCIONES_SISTEMA = """
Sos el secretario privado de una barbería. El usuario habla con vos
como el barbero. Nunca contestes a nombre de un cliente.
Interpretá el mensaje y devolvé SOLO un JSON válido.

Acciones:
- agendar: crear un turno.
- consultar: consultar turnos de una fecha o todos ("todos", "ver todos").
- cancelar: cancelar un turno.
- realizado: marcar un corte/turno como ya realizado.
- balance: consultar el balance o total recaudado de los cortes realizados.
- desconocido: no pudo interpretarse.

Reconvertí todas las fechas relativas usando la fecha y día de la semana actuales del servidor.
Reglas de fechas:
- "hoy" -> fecha actual.
- "mañana" -> fecha actual + 1 día.
- "pasado mañana" -> fecha actual + 2 días.
- Si mencionan un día de la semana (lunes, martes, miércoles, jueves, viernes, sábado, domingo) o "el domingo" / "este domingo" / "el lunes que viene": calculá la fecha exacta de la PRÓXIMA fecha futura correspondiente a ese día de la semana a partir de hoy (nunca devuelvas una fecha pasada ni la de hoy si ya pasó ese día). Por ejemplo, si hoy es sábado 28-11-2026, el domingo es 29-11-26.
- Si el mensaje contiene el nombre de una persona, una fecha y una hora,
  interpretalo como una solicitud para agendar, aunque no diga "agendar"
  ni "turno".
- Aceptá fechas numéricas como 28/11, 28-11, 28/11/26 y 28-11-26.
  Interpretalas como día/mes/año y devolvelas en formato DD-MM-YY.
- Si la fecha no incluye año, usá el año actual; si ya pasó, usá el próximo año.
- Las horas deben tener formato HH:MM (ej. "13" -> "13:00", "18" -> "18:00").
- El cliente es una sola persona por operación.
- El servicio siempre es "corte".
- Si no se indica precio, usá 10000.
- Si se indica un precio con palabras como "precio", "$", "cobra" o
  "sale", convertilo a número entero sin puntos ni comas.
"""


def normalizar_texto(texto: str) -> str:
  texto = unicodedata.normalize("NFD", (texto or "").lower().strip())
  texto = "".join(
      caracter for caracter in texto if unicodedata.category(caracter) != "Mn"
  )
  return re.sub(r"\s+", " ", texto).strip()


def es_saludo_o_menu(texto: str) -> bool:
  normalizado = normalizar_texto(texto)

  saludos = {
      "hola",
      "buenas",
      "buen dia",
      "buenos dias",
      "buenas tardes",
      "buenas noches",
      "menu",
      "inicio",
      "ayuda",
  }

  saludo_alargado = re.fullmatch(r"ho+l+a*s*", normalizado)
  return normalizado in saludos or saludo_alargado is not None


def interpretar_mensaje(texto: str) -> list[dict]:
  """Interpreta el mensaje con Gemini y usa el parser local como respaldo."""
  texto = (texto or "").strip()
  if not texto:
    return []

  if es_saludo_o_menu(texto):
    return [{"accion": "menu"}]

  normalizado = normalizar_texto(texto)

  opciones = {
      "1": "opcion_agendar",
      "2": "opcion_consultar",
      "3": "opcion_cancelar",
  }
  if normalizado in opciones:
    return [{"accion": opciones[normalizado]}]

  api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
  modelo = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

  try:
    if api_key:
      cliente = genai.Client(api_key=api_key)
      ahora = datetime.now()
      fecha_actual = ahora.strftime("%d-%m-%Y")
      dia_semana = DIAS_SEMANA_ES[ahora.weekday()]

      respuesta = cliente.models.generate_content(
          model=modelo,
          contents=texto,
          config=types.GenerateContentConfig(
              system_instruction=(
                  INSTRUCCIONES_SISTEMA
                  + f"\nHoy es {dia_semana} {fecha_actual}."
              ),
              response_mime_type="application/json",
              response_schema=SCHEMA_RESPUESTA,
          ),
      )

      contenido = getattr(respuesta, "text", None)
      if not contenido:
        raise ValueError("Gemini no devolvió texto")

      datos = json.loads(contenido)
      operaciones = datos.get("operaciones", [])

      if isinstance(operaciones, list) and operaciones:
        if all(op.get("accion") == "desconocido" for op in operaciones):
          rescate = interpretar_turno_basico(texto)
          if rescate and rescate[0].get("accion") in {
              "realizado",
              "balance",
              "consultar",
          }:
            return rescate
        return operaciones
  except Exception as error:
    print(f"⚠️ Error Gemini ({modelo}): {error!r}", flush=True)

  try:
    resultado = interpretar_turno_basico(texto)
  except Exception:
    return []

  if isinstance(resultado, list):
    return resultado

  if isinstance(resultado, dict):
    if "operaciones" in resultado:
      operaciones = resultado["operaciones"]
      return operaciones if isinstance(operaciones, list) else []

    return [resultado]

  return []
