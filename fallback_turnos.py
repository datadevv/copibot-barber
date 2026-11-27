import re
from datetime import datetime, timedelta


def interpretar_turno_basico(texto: str) -> list[dict]:
    texto_original = texto.strip()
    texto_bajo = texto_original.lower()
    hoy = datetime.now()

    # Determina la fecha. Revisamos "pasado mañana" primero.
    if "pasado mañana" in texto_bajo:
        fecha = hoy + timedelta(days=2)
    elif "mañana" in texto_bajo:
        fecha = hoy + timedelta(days=1)
    else:
        fecha = hoy

    # Determina la acción.
    if "cancelar" in texto_bajo or "cancela" in texto_bajo:
        accion = "cancelar"
    elif any(p in texto_bajo for p in ("consultar", "qué turnos", "que turnos", "mi agenda")):
        accion = "consultar"
    else:
        accion = "agendar"

    # Busca una hora como 15:30 o 15 hs.
    coincidencia_hora = re.search(
        r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\s*(?:hs?|horas?)?\b",
        texto_bajo,
    )
    hora = ""
    if coincidencia_hora:
        horas = int(coincidencia_hora.group(1))
        minutos = coincidencia_hora.group(2) or "00"
        hora = f"{horas:02d}:{minutos}"

    # Busca el nombre después de "para" o "con".
    coincidencia_cliente = re.search(
        r"\b(?:para|con)\s+([a-záéíóúñ]+(?:\s+[a-záéíóúñ]+){0,3})",
        texto_bajo,
    )
    cliente = coincidencia_cliente.group(1).title() if coincidencia_cliente else ""

    # Busca un precio indicado con $, "precio", "cobra" o "sale".
    coincidencia_precio = re.search(
        r"(?:precio|cobra|cobrar|sale)\s*(?:de|a)?\s*\$?\s*([\d.]+)|\$\s*([\d.]+)",
        texto_bajo,
    )
    precio = 10000
    if coincidencia_precio:
        valor = coincidencia_precio.group(1) or coincidencia_precio.group(2)
        precio = int(valor.replace(".", ""))

    if accion == "agendar" and (not cliente or not hora):
        accion = "desconocido"

    return [{
        "accion": accion,
        "cliente": cliente,
        "fecha": fecha.strftime("%d-%m-%y"),
        "hora": hora,
        "servicio": "corte",
        "precio": precio,
    }]