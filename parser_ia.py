import json
import os
import re
from datetime import datetime, timedelta
from fallback_turnos import interpretar_turno_basico
from google import genai
from google.genai import types


PRECIO_CORTE_DEFAULT = 10000
TZ = None  # Usa la fecha del sistema del servidor



SCHEMA_TURNO = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "accion": types.Schema(
            type=types.Type.STRING,
            enum=["agendar", "consultar", "cancelar", "desconocido"],
            description="Acción solicitada por el barbero.",
        ),
        "cliente": types.Schema(
            type=types.Type.STRING,
            description="Nombre del cliente.",
        ),
        "fecha": types.Schema(
            type=types.Type.STRING,
            description="Fecha del turno en formato DD-MM-YY.",
        ),
        "hora": types.Schema(
            type=types.Type.STRING,
            description="Hora del turno en formato HH:MM.",
        ),
        "servicio": types.Schema(
            type=types.Type.STRING,
            enum=["corte", ""],
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

def interpretar_mensaje(texto: str) -> list[dict]:
    """Interpreta el mensaje con Gemini y usa el parser local como respaldo."""
    texto = (texto or "").strip()
    if not texto:
        return []

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

    try:
        if api_key:
            cliente = genai.Client(api_key=api_key)
            fecha_actual = datetime.now().strftime("%d-%m-%Y")
            respuesta = cliente.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
                contents=texto,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        INSTRUCCIONES_SISTEMA
                        if False
                        else INSTRUCCIONES_SISTEMA
                    )
                    + f"\nFecha actual del servidor: {fecha_actual}.",
                    response_mime_type="application/json",
                    response_schema=SCHEMA_RESPUESTA,
                ),
            )

            contenido = getattr(respuesta, "text", None)
            if not contenido:
                raise ValueError("Gemini no devolvió texto")

            datos = json.loads(contenido)
            operaciones = datos.get("operaciones", [])
            if isinstance(operaciones, list):
                return operaciones
    except (Exception,):
        # Cualquier fallo del proveedor deja el procesamiento disponible
        # mediante el parser básico local.
        pass

    try:
        resultado = interpretar_turno_basico(texto)
    except Exception:
        return []

    if isinstance(resultado, list):
        return resultado
    if isinstance(resultado, dict):
        if "operaciones" in resultado:
            operaciones = resultado.get("operaciones")
            return operaciones if isinstance(operaciones, list) else []
        return [resultado]
    return []


INSTRUCCIONES_SISTEMA = """
Sos el secretario privado de una barbería. El usuario habla con vos
como el barbero. Nunca contestes a nombre de un cliente.
Interpretá el mensaje y devolvé SOLO un JSON válido.

Acciones:
- agendar: crear un turno.
- consultar: consultar turnos de una fecha.
- cancelar: cancelar un turno.
- desconocido: no pudo interpretarse.

Reconvertí todas las fechas relativas usando la fecha actual del servidor.
Ejemplos:
- hoy -> fecha actual
- mañana -> fecha actual + 1 día
- pasado mañana -> fecha actual + 2 días

Reglas:
- El cliente es una sola persona por operación.
- El servicio siempre es "corte".
- Si no se indica precio, usá 10000.
- Si se indica un precio con palabras como "precio", "$", "cobra" o
  "sale", convertilo a número entero sin puntos ni comas.
- Las horas deben tener formato HH:MM.
- Las fechas deben tener formato DD-MM-YY.
"""
