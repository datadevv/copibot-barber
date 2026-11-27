from datetime import datetime
import os
import openpyxl

COLUMNAS_TURNOS = [
    "Fecha",
    "Hora",
    "Cliente",
    "Servicio",
    "Precio",
    "Estado",
]


def _abrir_excel_turnos(ruta_excel="turnos.xlsx"):
  if not os.path.exists(ruta_excel):
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Turnos"
    hoja.append(COLUMNAS_TURNOS)
    libro.save(ruta_excel)
    return libro, hoja

  libro = openpyxl.load_workbook(ruta_excel)
  hoja = libro.active
  if hoja.max_row < 1 or hoja.cell(1, 1).value is None:
    hoja.delete_rows(1, hoja.max_row + 1)
    hoja.append(COLUMNAS_TURNOS)
    libro.save(ruta_excel)
  return libro, hoja


def _normalizar_fecha_excel(valor_fecha) -> str:
  if isinstance(valor_fecha, datetime):
    return valor_fecha.strftime("%d-%m-%y")
  texto = str(valor_fecha or "").strip()
  for fmt in ("%d-%m-%y", "%d/%m/%y", "%d-%m-%Y", "%d/%m/%Y"):
    try:
      return datetime.strptime(texto, fmt).strftime("%d-%m-%y")
    except ValueError:
      continue
  return texto


def _normalizar_hora_excel(valor_hora) -> str:
  texto = str(valor_hora or "").strip()
  for fmt in ("%H:%M", "%H:%M:%S"):
    try:
      return datetime.strptime(texto, fmt).strftime("%H:%M")
    except ValueError:
      continue
  return texto


def agendar_turno(datos, ruta_excel="turnos.xlsx"):
  libro, hoja = _abrir_excel_turnos(ruta_excel)

  fecha = _normalizar_fecha_excel(
      datos.get("fecha") or datetime.now().strftime("%d-%m-%y")
  )
  hora = _normalizar_hora_excel(datos.get("hora"))
  cliente = str(datos.get("cliente") or "").strip().title()
  servicio = str(datos.get("servicio") or "corte").strip() or "corte"

  try:
    precio = int(float(datos.get("precio", 10000)))
  except (TypeError, ValueError):
    precio = 10000

  for fila in hoja.iter_rows(min_row=2, values_only=True):
    if not fila:
      continue
    f_fecha = _normalizar_fecha_excel(fila[0])
    f_hora = _normalizar_hora_excel(fila[1])
    f_estado = str(fila[5] or "").strip().lower()
    if f_fecha == fecha and f_hora == hora and f_estado == "agendado":
      return (
          f"⚠️ Ya hay un turno agendado el {fecha} a las {hora} ({fila[2]})."
      )

  hoja.append([fecha, hora, cliente, servicio, precio, "agendado"])
  libro.save(ruta_excel)

  return (
      f"✅ Turno agendado para {cliente}: {fecha} a las {hora} "
      f"({servicio}, ${precio})."
  )


def consultar_turnos(
    fecha=None, ruta_excel="turnos.xlsx", todos: bool = False
):
  if not os.path.exists(ruta_excel):
    return "📅 Todavía no hay turnos agendados."

  libro, hoja = _abrir_excel_turnos(ruta_excel)
  es_todos = todos or (
      str(fecha or "").strip().lower() in {"todos", "todo", "ver todos"}
  )
  turnos = []

  if es_todos:
    for fila in hoja.iter_rows(min_row=2, values_only=True):
      if fila and str(fila[5] or "").strip().lower() == "agendado":
        turnos.append((
            _normalizar_fecha_excel(fila[0]),
            _normalizar_hora_excel(fila[1]),
            str(fila[2] or "").strip(),
            str(fila[3] or "corte").strip(),
            fila[4] if fila[4] is not None else 10000,
        ))

    if not turnos:
      return "📅 No hay turnos agendados."

    turnos.sort(key=lambda item: (item[0], item[1]))
    lineas = ["📅 *Todos los turnos agendados:*"]
    for f_fecha, f_hora, f_cliente, f_servicio, f_precio in turnos:
      lineas.append(
          f"• {f_fecha} {f_hora} — {f_cliente} ({f_servicio}, ${f_precio})"
      )
    return "\n".join(lineas)

  fecha_objetivo = _normalizar_fecha_excel(
      fecha or datetime.now().strftime("%d-%m-%y")
  )
  for fila in hoja.iter_rows(min_row=2, values_only=True):
    if (
        fila
        and _normalizar_fecha_excel(fila[0]) == fecha_objetivo
        and str(fila[5] or "").strip().lower() == "agendado"
    ):
      turnos.append((
          _normalizar_hora_excel(fila[1]),
          str(fila[2] or "").strip(),
          str(fila[3] or "corte").strip(),
          fila[4] if fila[4] is not None else 10000,
      ))

  if not turnos:
    return f"📅 No hay turnos agendados para el {fecha_objetivo}."

  turnos.sort(key=lambda item: item[0])
  lineas = [f"📅 *Turnos del {fecha_objetivo}:*"]
  for f_hora, f_cliente, f_servicio, f_precio in turnos:
    lineas.append(f"• {f_hora} — {f_cliente} ({f_servicio}, ${f_precio})")

  return "\n".join(lineas)


def cancelar_turno(datos, ruta_excel="turnos.xlsx"):
  if not os.path.exists(ruta_excel):
    return "📅 No hay turnos agendados para cancelar."

  libro, hoja = _abrir_excel_turnos(ruta_excel)
  cliente = str(datos.get("cliente") or "").strip().lower()
  fecha = (
      _normalizar_fecha_excel(datos.get("fecha")) if datos.get("fecha") else ""
  )
  hora = _normalizar_hora_excel(datos.get("hora")) if datos.get("hora") else ""

  coincidencias = []
  for numero_fila in range(2, hoja.max_row + 1):
    fila = [hoja.cell(numero_fila, col).value for col in range(1, 7)]
    if not fila or str(fila[5] or "").strip().lower() != "agendado":
      continue
    if cliente and cliente not in str(fila[2] or "").strip().lower():
      continue
    if fecha and fecha != _normalizar_fecha_excel(fila[0]):
      continue
    if hora and hora != _normalizar_hora_excel(fila[1]):
      continue
    coincidencias.append((numero_fila, fila))

  if not coincidencias:
    return "❓ No encontré un turno agendado coincidente para cancelar."

  if len(coincidencias) > 1 and not (cliente and fecha and hora):
    return (
        "❓ Hay más de un turno coincidente. Indicame el nombre, fecha y/o hora"
        " para cancelar."
    )

  numero_fila, fila = coincidencias[0]
  hoja.cell(numero_fila, 6).value = "cancelado"
  libro.save(ruta_excel)

  return (
      f"🗑️ Turno cancelado para {fila[2]} "
      f"({_normalizar_fecha_excel(fila[0])} {_normalizar_hora_excel(fila[1])})."
  )


  coincidencias = []
  for numero_fila in range(2, hoja.max_row + 1):
    fila = [hoja.cell(numero_fila, col).value for col in range(1, 7)]
    if not fila or str(fila[5] or "").strip().lower() != "agendado":
      continue
    if cliente and cliente not in str(fila[2] or "").strip().lower():
      continue
    if hora and hora != _normalizar_hora_excel(fila[1]):
      continue
    if fecha and fecha != _normalizar_fecha_excel(fila[0]):
      continue
    coincidencias.append((numero_fila, fila))

  # Si no hubo coincidencias con fecha, reintentar ignorando la fecha
  # (el parser rellena "hoy" cuando el usuario no dio fecha)
  if not coincidencias and cliente:
    for numero_fila in range(2, hoja.max_row + 1):
      fila = [hoja.cell(numero_fila, col).value for col in range(1, 7)]
      if not fila or str(fila[5] or "").strip().lower() != "agendado":
        continue
      if cliente not in str(fila[2] or "").strip().lower():
        continue
      if hora and hora != _normalizar_hora_excel(fila[1]):
        continue
      coincidencias.append((numero_fila, fila))

  libro, hoja = _abrir_excel_turnos(ruta_excel)
  cliente = str(datos.get("cliente") or "").strip().lower()
  fecha = (
      _normalizar_fecha_excel(datos.get("fecha")) if datos.get("fecha") else ""
  )
  hora = _normalizar_hora_excel(datos.get("hora")) if datos.get("hora") else ""

  coincidencias = []
  for numero_fila in range(2, hoja.max_row + 1):
    fila = [hoja.cell(numero_fila, col).value for col in range(1, 7)]
    if not fila or str(fila[5] or "").strip().lower() != "agendado":
      continue
    if cliente and cliente not in str(fila[2] or "").strip().lower():
      continue
    if hora and hora != _normalizar_hora_excel(fila[1]):
      continue
    if fecha and cliente and fecha != _normalizar_fecha_excel(fila[0]):
      continue
    coincidencias.append((numero_fila, fila))

  if not coincidencias and not cliente and not hora:
    for numero_fila in range(hoja.max_row, 1, -1):
      fila = [hoja.cell(numero_fila, col).value for col in range(1, 7)]
      if fila and str(fila[5] or "").strip().lower() == "agendado":
        coincidencias.append((numero_fila, fila))
        break

  if not coincidencias:
    return (
        "❓ No encontré un turno agendado coincidente para marcar como"
        " realizado."
    )

  if len(coincidencias) > 1 and not (cliente and hora):
    return (
        "❓ Hay más de un turno coincidente. Indicame el nombre y/o la hora del"
        " corte."
    )

  numero_fila, fila = coincidencias[-1]
  precio_override = datos.get("precio")
  precio_final = (
      precio_override
      if precio_override not in (None, "", 0)
      else (fila[4] if fila[4] is not None else 10000)
  )

  hoja.cell(numero_fila, 5).value = precio_final
  hoja.cell(numero_fila, 6).value = "realizado"
  libro.save(ruta_excel)

  return (
      f"✂️ Corte de {fila[2]} ({_normalizar_fecha_excel(fila[0])}"
      f" {_normalizar_hora_excel(fila[1])}) marcado como realizado por"
      f" ${precio_final}."
  )
def consultar_balance(fecha=None, ruta_excel="turnos.xlsx"):
  if not os.path.exists(ruta_excel):
    return "💰 Todavía no tenés cortes realizados ni turnos registrados."

  libro, hoja = _abrir_excel_turnos(ruta_excel)
  fecha_dia = _normalizar_fecha_excel(
      fecha or datetime.now().strftime("%d-%m-%y")
  )

  realizado_dia = 0.0
  cant_realizado_dia = 0
  pendiente_dia = 0.0
  cant_pendiente_dia = 0

  realizado_total = 0.0
  cant_realizado_total = 0
  pendiente_total = 0.0
  cant_pendiente_total = 0

  for fila in hoja.iter_rows(min_row=2, values_only=True):
    if not fila or fila[2] is None:
      continue
    estado = str(fila[5] or "").strip().lower()
    try:
      monto = float(fila[4] if fila[4] is not None else 0)
    except (TypeError, ValueError):
      monto = 0.0

    es_del_dia = _normalizar_fecha_excel(fila[0]) == fecha_dia

    if estado == "realizado":
      realizado_total += monto
      cant_realizado_total += 1
      if es_del_dia:
        realizado_dia += monto
        cant_realizado_dia += 1
    elif estado == "agendado":
      pendiente_total += monto
      cant_pendiente_total += 1
      if es_del_dia:
        pendiente_dia += monto
        cant_pendiente_dia += 1

  def _fmt(num: float):
    return int(num) if num.is_integer() else round(num, 2)

  return (
      f"💰 *Balance del día ({fecha_dia}):*\n"
      f"• Cortes realizados: {cant_realizado_dia} (${_fmt(realizado_dia)})\n"
      f"• Turnos pendientes: {cant_pendiente_dia} (${_fmt(pendiente_dia)})\n\n"
      "📊 *Balance total acumulado:*\n"
      f"• Cortes realizados: {cant_realizado_total} (${_fmt(realizado_total)})\n"
      f"• Turnos pendientes: {cant_pendiente_total} (${_fmt(pendiente_total)})"
  )
def abrir_dia(fecha=None, ruta_excel="turnos.xlsx"):
  fecha_objetivo = _normalizar_fecha_excel(
      fecha or datetime.now().strftime("%d-%m-%y")
  )
  agenda = consultar_turnos(fecha=fecha_objetivo, ruta_excel=ruta_excel)
  return f"🌅 *Apertura del día ({fecha_objetivo}):*\n\n{agenda}"

def _resolver_ruta_excel(ruta_excel=None) -> str:
  if isinstance(ruta_excel, (str, bytes, os.PathLike)):
    ruta_str = os.fspath(ruta_excel)
    if isinstance(ruta_str, bytes):
      ruta_str = ruta_str.decode("utf-8", errors="ignore")
    if str(ruta_str).strip():
      return str(ruta_str).strip()
  return "turnos.xlsx"
def cerrar_dia(fecha=None, ruta_excel="turnos.xlsx"):
  fecha_objetivo = _normalizar_fecha_excel(
      fecha or datetime.now().strftime("%d-%m-%y")
  )

  if not os.path.exists(ruta_excel):
    return (
        f"🌙 *Cierre del día ({fecha_objetivo}):*\n"
        "• Cortes realizados: 0 ($0)\n"
        "• Turnos pendientes: 0 ($0)\n"
        "• Turnos cancelados: 0"
    )

  _, hoja = _abrir_excel_turnos(ruta_excel)

  realizados = []
  pendientes = []
  cancelados = 0
  total_dia = 0.0

  for fila in hoja.iter_rows(min_row=2, values_only=True):
    if not fila or fila[2] is None:
      continue
    if _normalizar_fecha_excel(fila[0]) != fecha_objetivo:
      continue

    hora_f = _normalizar_hora_excel(fila[1])
    cliente_f = str(fila[2] or "").strip()
    estado_f = str(fila[5] or "").strip().lower()
    try:
      monto_f = float(fila[4] if fila[4] is not None else 10000)
    except (TypeError, ValueError):
      monto_f = 10000.0

    if estado_f == "realizado":
      realizados.append((hora_f, cliente_f, monto_f))
      total_dia += monto_f
    elif estado_f == "agendado":
      pendientes.append((hora_f, cliente_f, monto_f))
    elif estado_f == "cancelado":
      cancelados += 1

  realizados.sort(key=lambda item: item[0])
  pendientes.sort(key=lambda item: item[0])

  total_fmt = (
      int(total_dia) if total_dia.is_integer() else round(total_dia, 2)
  )

  lineas = [
      f"🌙 *Cierre del día ({fecha_objetivo}):*",
      f"• Cortes realizados: {len(realizados)} (${total_fmt})",
      f"• Turnos pendientes: {len(pendientes)}",
      f"• Turnos cancelados: {cancelados}",
  ]

  if pendientes:
    lineas.append("\n⚠️ *Quedaron sin marcar como realizados:*")
    for h, c, _ in pendientes:
      lineas.append(f"  - {h} — {c}")

  return "\n".join(lineas)
