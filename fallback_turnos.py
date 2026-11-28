from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")

DIAS_SEMANA = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}

PALABRAS_NO_NOMBRE = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "uno",
    "hoy",
    "mañana",
    "manana",
    "pasado",
    "ayer",
    "turno",
    "turnos",
    "a",
    "de",
    "del",
    "al",
    "hs",
    "hora",
    "horas",
    "corte",
    "realizado",
    "todos",
    "cancelar",
    "cancela",
    "cancelo",
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
}


def _resolver_fecha(texto_bajo: str, hoy: datetime) -> tuple[str, str]:
  m_fecha = re.search(
      r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", texto_bajo
  )
  if m_fecha:
    dia = int(m_fecha.group(1))
    mes = int(m_fecha.group(2))
    anio_raw = m_fecha.group(3)
    if anio_raw:
      anio = int(anio_raw)
      if anio < 100:
        anio += 2000
    else:
      anio = hoy.year
      try:
        candidata = datetime(anio, mes, dia)
        if candidata.date() < hoy.date():
          anio += 1
      except ValueError:
        pass
    try:
      fecha_formateada = datetime(anio, mes, dia).strftime("%d-%m-%y")
      texto_limpio = (
          texto_bajo[: m_fecha.start()] + " " + texto_bajo[m_fecha.end() :]
      )
      return fecha_formateada, texto_limpio
    except ValueError:
      pass

  m_dia = re.search(r"\bel\s+(\d{1,2})\b(?!\s*[:/-]|\s*hs)", texto_bajo)
  if m_dia:
    dia = int(m_dia.group(1))
    try:
      candidata = datetime(hoy.year, hoy.month, dia)
      if candidata.date() < hoy.date():
        mes = hoy.month % 12 + 1
        anio = hoy.year + (1 if hoy.month == 12 else 0)
        candidata = datetime(anio, mes, dia)
      texto_limpio = texto_bajo[: m_dia.start()] + " " + texto_bajo[m_dia.end():]
      return candidata.strftime("%d-%m-%y"), texto_limpio
    except ValueError:
      pass
  if "pasado mañana" in texto_bajo or "pasado manana" in texto_bajo:
    return (hoy + timedelta(days=2)).strftime("%d-%m-%y"), texto_bajo
  if "mañana" in texto_bajo or "manana" in texto_bajo:
    return (hoy + timedelta(days=1)).strftime("%d-%m-%y"), texto_bajo

  m_semana = re.search(
      r"\b(?:el\s+)?(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b",
      texto_bajo,
  )
  if m_semana:
    objetivo = DIAS_SEMANA[m_semana.group(1)]
    dias = (objetivo - hoy.weekday()) % 7 or 7
    texto_limpio = (
        texto_bajo[: m_semana.start()] + " " + texto_bajo[m_semana.end() :]
    )
    return (hoy + timedelta(days=dias)).strftime("%d-%m-%y"), texto_limpio

  return hoy.strftime("%d-%m-%y"), texto_bajo


def _extraer_hora(texto_sin_fecha: str) -> str:
  m_ampm = re.search(
      r"\b(1[0-2]|0?[1-9])(?:\s*:\s*([0-5]\d))?\s*(am|pm)\b",
      texto_sin_fecha,
  )
  if m_ampm:
    hora = int(m_ampm.group(1)) % 12
    if m_ampm.group(3) == "pm":
      hora += 12
    return f"{hora:02d}:{m_ampm.group(2) or '00'}"

  m_exp = re.search(
      r"(?:\ba\s+las\s+)?\b([01]?\d|2[0-3])\s*:\s*([0-5]\d)(?:\s*(?:hs?|horas?))?\b",
      texto_sin_fecha,
  )
  if m_exp:
    return f"{int(m_exp.group(1)):02d}:{m_exp.group(2)}"

  m_hs = re.search(
      r"(?:\ba\s+las\s+)\b([01]?\d|2[0-3])(?:\s*(?:hs?|horas?))?\b",
      texto_sin_fecha,
  )
  if m_hs:
    return f"{int(m_hs.group(1)):02d}:00"

  m_hs_suelta = re.search(
      r"\b([01]?\d|2[0-3])\s*(?:hs?|horas?)\b",
      texto_sin_fecha,
  )
  if m_hs_suelta:
    return f"{int(m_hs_suelta.group(1)):02d}:00"

  m_4dig = re.search(r"\b([01]\d|2[0-3])([0-5]\d)\b", texto_sin_fecha)
  if m_4dig:
    return f"{int(m_4dig.group(1)):02d}:{m_4dig.group(2)}"

  return ""


def _limpiar_nombre(candidato: str) -> str:
  partes = [
      p
      for p in re.findall(r"[a-záéíóúñ]+", candidato.lower())
      if p not in PALABRAS_NO_NOMBRE
  ]
  if not partes:
    return ""
  return " ".join(partes[:2]).title()


def _sin_tildes(texto: str) -> str:
  import unicodedata

  return "".join(
      c
      for c in unicodedata.normalize("NFD", texto)
      if unicodedata.category(c) != "Mn"
  )


def interpretar_turno_basico(texto: str) -> list[dict]:
  texto_original = (texto or "").strip()
  texto_bajo = re.sub(r"\s+", " ", _sin_tildes(texto_original.lower())).strip()
  hoy = datetime.now(TZ_AR)

  if texto_bajo in {
      "listo",
      "gracias",
      "ok",
      "okey",
      "dale",
      "joya",
      "genial",
      "perfecto",
      "chau",
      "adios",
      "nada mas",
  }:
    return [{"accion": "cierre"}]

  if re.search(
      r"\b(balance|caja|recaudado|cuanto\s+llevo|cuanto\s+voy)\b", texto_bajo
  ):
    return [{
        "accion": "balance",
        "cliente": "",
        "fecha": "",
        "hora": "",
        "servicio": "corte",
        "precio": 10000,
    }]

  fecha_str, texto_sin_fecha = _resolver_fecha(texto_bajo, hoy)
  texto_sin_fecha = re.sub(r"\s+", " ", texto_sin_fecha).strip()

  if re.search(
      r"\b(abrir\s+el?\s*dia|abro\s+el?\s*dia|arrancar\s+el?\s*dia|empezar\s+el?\s*dia)\b",
      texto_bajo,
  ):
    return [{
        "accion": "abrir_dia",
        "cliente": "",
        "fecha": fecha_str,
        "hora": "",
        "servicio": "corte",
        "precio": 10000,
    }]

  if re.search(
      r"\b(cerrar\s+el?\s*dia|cierro\s+el?\s*dia|cerrar\s+caja|terminar\s+el?\s*dia)\b",
      texto_bajo,
  ):
    return [{
        "accion": "cerrar_dia",
        "cliente": "",
        "fecha": fecha_str,
        "hora": "",
        "servicio": "corte",
        "precio": 10000,
    }]

  if re.search(
      r"\b(realic[eé]\s+(?:el\s+)?corte|reakic[eé]\s+(?:el\s+)?corte|corte\s+realizado|ya\s+cort[eé]|termin[eé]\s+(?:el\s+)?corte|listo\s+el\s+corte|hice\s+(?:el\s+)?corte)\b",
      texto_bajo,
  ):
    accion = "realizado"
  elif "cancelar" in texto_bajo or "cancela" in texto_bajo:
    accion = "cancelar"
  elif any(
      p in texto_bajo
      for p in (
          "consultar",
          "que turnos",
          "mi agenda",
          "todos",
          "ver todos",
      )
  ):
    accion = "consultar"
  else:
    accion = "agendar"

  if accion == "consultar" and any(
      p in texto_bajo for p in ("todos", "ver todos")
  ):
    fecha_str = "todos"

  hora = _extraer_hora(texto_sin_fecha)

  cliente = ""
  coincidencia_cliente = re.search(
      r"\b(?:para|con|de)\s+([a-z]+(?:\s+[a-z]+){0,2}?)(?=\s+(?:el\b|la\b|hoy\b|manana\b|pasado\b|a\s+las\b|\d)|$)",
      texto_sin_fecha,
  )
  if coincidencia_cliente:
    cliente = _limpiar_nombre(coincidencia_cliente.group(1))

  if not cliente and accion == "realizado":
    m_realizado = re.search(
        r"\b(?:corte\s+realizado|realic[eé]\s+(?:el\s+)?corte|reakic[eé]\s+(?:el\s+)?corte|ya\s+cort[eé]|hice\s+(?:el\s+)?corte|termin[eé]\s+(?:el\s+)?corte)\s+(?:a\s+|de\s+|del\s+|para\s+|con\s+)?([a-z]+(?:\s+[a-z]+)?)",
        texto_sin_fecha,
    )
    if m_realizado:
      cliente = _limpiar_nombre(m_realizado.group(1))

  if not cliente and accion in {"agendar", "cancelar"}:
    m_inicio = re.match(
        r"^([a-z]+(?:\s+[a-z]+)?)\s+(?:el\b|hoy\b|manana\b|pasado\b|a\s+las\b|\d)",
        texto_sin_fecha,
    )
    if m_inicio:
      cliente = _limpiar_nombre(m_inicio.group(1))

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
      "fecha": fecha_str,
      "hora": hora,
      "servicio": "corte",
      "precio": precio,
  }]
  if any(
      frase in texto_bajo
      for frase in (
          "realice el corte",
          "realicé el corte",
          "realice corte",
          "realicé corte",
          "reakice corte",
          "corte realizado",
          "ya corte",
          "ya corté",
          "termine el corte",
          "terminé el corte",
          "termine corte",
          "terminé corte",
          "listo el corte",
          "hice el corte",
          "hice corte",
      )
  ):
    accion = "realizado"
  elif "cancelar" in texto_bajo or "cancela" in texto_bajo:
    accion = "cancelar"
  elif any(
      p in texto_bajo
      for p in (
          "consultar",
          "qué turnos",
          "que turnos",
          "mi agenda",
          "todos",
          "ver todos",
      )
  ):
    accion = "consultar"
  else:
    accion = "agendar"

  if accion == "consultar" and any(
      p in texto_bajo for p in ("todos", "ver todos")
  ):
    fecha_str = "todos"

  hora = _extraer_hora(texto_sin_fecha)

  cliente = ""
  coincidencia_cliente = re.search(
      r"\b(?:para|con|de)\s+([a-záéíóúñ]+(?:\s+[a-záéíóúñ]+){0,2}?)(?=\s+(?:el\b|la\b|hoy\b|mañana\b|manana\b|pasado\b|a\s+las\b|\d)|$)",
      texto_sin_fecha,
  )
  if coincidencia_cliente:
    cliente = _limpiar_nombre(coincidencia_cliente.group(1))

  if not cliente and accion == "realizado":
    m_realizado = re.search(
        r"\b(?:corte\s+realizado|realic[eé]\s+(?:el\s+)?corte|reakice\s+(?:el\s+)?corte|ya\s+cort[eé]|hice\s+(?:el\s+)?corte|termin[eé]\s+(?:el\s+)?corte)\s+(?:a\s+|de\s+|del\s+|para\s+|con\s+)?([a-záéíóúñ]+(?:\s+[a-záéíóúñ]+)?)",
        texto_sin_fecha,
    )
    if m_realizado:
      cliente = _limpiar_nombre(m_realizado.group(1))

  if not cliente and accion in {"agendar", "cancelar"}:
    m_inicio = re.match(
        r"^([a-záéíóúñ]+(?:\s+[a-záéíóúñ]+)?)\s+(?:el\b|hoy\b|mañana\b|manana\b|pasado\b|a\s+las\b|\d)",
        texto_sin_fecha,
    )
    if m_inicio:
      cliente = _limpiar_nombre(m_inicio.group(1))

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
      "fecha": fecha_str,
      "hora": hora,
      "servicio": "corte",
      "precio": precio,
  }]
