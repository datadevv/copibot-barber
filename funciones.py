from datetime import datetime
import json
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


# ---------------------------------------------------------------------------
# ALMACENAMIENTO
# Si existen las variables GOOGLE_SHEET_ID y GOOGLE_CREDENTIALS_JSON se usa
# Google Sheets (una pestaña por número). Si no, se usa un Excel local.
# Las dos opciones ofrecen lo mismo: filas(), agregar() y actualizar().
# ---------------------------------------------------------------------------


class _AlmacenExcel:

  def __init__(self, ruta):
    self.ruta = ruta

  def _abrir(self):
    if not os.path.exists(self.ruta):
      libro = openpyxl.Workbook()
      hoja = libro.active
      hoja.title = "Turnos"
      hoja.append(COLUMNAS_TURNOS)
      libro.save(self.ruta)
      return libro, hoja

    libro = openpyxl.load_workbook(self.ruta)
    hoja = libro.active
    if hoja.max_row < 1 or hoja.cell(1, 1).value is None:
      hoja.delete_rows(1, hoja.max_row + 1)
      hoja.append(COLUMNAS_TURNOS)
      libro.save(self.ruta)
    return libro, hoja

  def filas(self):
    """Devuelve [(numero_de_fila, [6 valores])] sin el encabezado."""
    _, hoja = self._abrir()
    resultado = []
    for numero in range(2, hoja.max_row + 1):
      fila = [hoja.cell(numero, col).value for col in range(1, 7)]
      if all(valor is None for valor in fila):
        continue
      resultado.append((numero, fila))
    return resultado

  def agregar(self, fila):
    libro, hoja = self._abrir()
    hoja.append(fila)
    libro.save(self.ruta)

  def actualizar(self, numero_fila, cambios):
    """cambios = {numero_de_columna: nuevo_valor}"""
    libro, hoja = self._abrir()
    for columna, valor in cambios.items():
      hoja.cell(numero_fila, columna).value = valor
    libro.save(self.ruta)


class _AlmacenSheets:
  _planilla_cache = None
  _hojas_cache = {}

  def __init__(self, ruta):
    base = os.path.basename(ruta)
    self.titulo = os.path.splitext(base)[0] or "turnos"

  @classmethod
  def _planilla(cls):
    if cls._planilla_cache is None:
      import gspread

      credenciales = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
      cliente = gspread.service_account_from_dict(credenciales)
      cls._planilla_cache = cliente.open_by_key(os.environ["GOOGLE_SHEET_ID"])
    return cls._planilla_cache

  def _hoja(self):
    if self.titulo in self._hojas_cache:
      return self._hojas_cache[self.titulo]

    import gspread

    planilla = self._planilla()
    try:
      hoja = planilla.worksheet(self.titulo)
    except gspread.WorksheetNotFound:
      hoja = planilla.add_worksheet(title=self.titulo, rows=500, cols=6)
      hoja.append_row(COLUMNAS_TURNOS, value_input_option="RAW")

    self._hojas_cache[self.titulo] = hoja
    return hoja

  def filas(self):
    hoja = self._hoja()
    valores = hoja.get_all_values()
    if not valores:
      hoja.append_row(COLUMNAS_TURNOS, value_input_option="RAW")
      return []

    resultado = []
    for numero, fila in enumerate(valores[1:], start=2):
      fila = (list(fila) + [""] * 6)[:6]
      if not any(str(valor).strip() for valor in fila):
        continue
      fila = [valor if valor != "" else None for valor in fila]
      try:
        if fila[4] is not None:
          fila[4] = int(float(fila[4]))
      except (TypeError, ValueError):
        pass
      resultado.append((numero, fila))
    return resultado

  def agregar(self, fila):
    self._hoja().append_row(fila, value_input_option="RAW")

  def actualizar(self, numero_fila, cambios):
    hoja = self._hoja()
    datos = []
    for columna, valor in cambios.items():
      celda = openpyxl.utils.get_column_letter(columna) + str(numero_fila)
      datos.append({"range": celda, "values": [[valor]]})
    hoja.batch_update(datos, value_input_option="RAW")


def _resolver_ruta_excel(ruta_excel=None) -> str:
  if isinstance(ruta_excel, (str, bytes, os.PathLike)):
    ruta_str = os.fspath(ruta_excel)
    if isinstance(ruta_str, bytes):
      ruta_str = ruta_str.decode("utf-8", errors="ignore")
    if str(ruta_str).strip():
      return str(ruta_str).strip()
  return "turnos.xlsx"


def _almacen(ruta_excel=None):
  ruta = _resolver_ruta_excel(ruta_excel)
  if os.getenv("GOOGLE_SHEET_ID") and os.getenv("GOOGLE_CREDENTIALS_JSON"):
    return _AlmacenSheets(ruta)
  return _AlmacenExcel(ruta)


# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------


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


def _estado(fila) -> str:
  return str(fila[5] or "").strip().lower()


# ---------------------------------------------------------------------------
# OPERACIONES
# ---------------------------------------------------------------------------


def agendar_turno(datos, ruta_excel="turnos.xlsx"):
  almacen = _almacen(ruta_excel)

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

  for _, fila in almacen.filas():
    if (
        _normalizar_fecha_excel(fila[0]) == fecha
        and _normalizar_hora_excel(fila[1]) == hora
        and _estado(fila) == "agendado"
    ):
      return (
          f"⚠️ Ya hay un turno agendado el {fecha} a las {hora} ({fila[2]})."
      )

  almacen.agregar([fecha, hora, cliente, servicio, precio, "agendado"])

  return (
      f"✅ Turno agendado para {cliente}: {fecha} a las {hora} "
      f"({servicio}, ${precio})."
  )


def consultar_turnos(
    fecha=None, ruta_excel="turnos.xlsx", todos: bool = False
):
  almacen = _almacen(ruta_excel)
  filas = [fila for _, fila in almacen.filas() if _estado(fila) == "agendado"]

  es_todos = todos or (
      str(fecha or "").strip().lower() in {"todos", "todo", "ver todos"}
  )

  if es_todos:
    turnos = [
        (
            _normalizar_fecha_excel(fila[0]),
            _normalizar_hora_excel(fila[1]),
            str(fila[2] or "").strip(),
            str(fila[3] or "corte").strip(),
            fila[4] if fila[4] is not None else 10000,
        )
        for fila in filas
    ]

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
  turnos = [
      (
          _normalizar_hora_excel(fila[1]),
          str(fila[2] or "").strip(),
          str(fila[3] or "corte").strip(),
          fila[4] if fila[4] is not None else 10000,
      )
      for fila in filas
      if _normalizar_fecha_excel(fila[0]) == fecha_objetivo
  ]

  if not turnos:
    return f"📅 No hay turnos agendados para el {fecha_objetivo}."

  turnos.sort(key=lambda item: item[0])
  lineas = [f"📅 *Turnos del {fecha_objetivo}:*"]
  for f_hora, f_cliente, f_servicio, f_precio in turnos:
    lineas.append(f"• {f_hora} — {f_cliente} ({f_servicio}, ${f_precio})")

  return "\n".join(lineas)


def cancelar_turno(datos, ruta_excel="turnos.xlsx"):
  almacen = _almacen(ruta_excel)
  cliente = str(datos.get("cliente") or "").strip().lower()
  fecha = (
      _normalizar_fecha_excel(datos.get("fecha")) if datos.get("fecha") else ""
  )
  hora = _normalizar_hora_excel(datos.get("hora")) if datos.get("hora") else ""

  coincidencias = []
  for numero_fila, fila in almacen.filas():
    if _estado(fila) != "agendado":
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
  almacen.actualizar(numero_fila, {6: "cancelado"})

  return (
      f"🗑️ Turno cancelado para {fila[2]} "
      f"({_normalizar_fecha_excel(fila[0])} {_normalizar_hora_excel(fila[1])})."
  )


def marcar_corte_realizado(datos, ruta_excel="turnos.xlsx"):
  almacen = _almacen(ruta_excel)
  cliente = str(datos.get("cliente") or "").strip().lower()
  fecha = (
      _normalizar_fecha_excel(datos.get("fecha")) if datos.get("fecha") else ""
  )
  hora = _normalizar_hora_excel(datos.get("hora")) if datos.get("hora") else ""

  agendados = [(n, f) for n, f in almacen.filas() if _estado(f) == "agendado"]

  def buscar(usar_fecha):
    encontrados = []
    for numero_fila, fila in agendados:
      if cliente and cliente not in str(fila[2] or "").strip().lower():
        continue
      if hora and hora != _normalizar_hora_excel(fila[1]):
        continue
      if usar_fecha and fecha and fecha != _normalizar_fecha_excel(fila[0]):
        continue
      encontrados.append((numero_fila, fila))
    return encontrados

  coincidencias = buscar(usar_fecha=True)

  # Si con la fecha no hay nada, reintentar sin fecha (el parser pone "hoy"
  # cuando el usuario no dijo ninguna).
  if not coincidencias and cliente:
    coincidencias = buscar(usar_fecha=False)

  if not coincidencias and not cliente and not hora and agendados:
    coincidencias = [agendados[-1]]

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

  almacen.actualizar(numero_fila, {5: precio_final, 6: "realizado"})

  return (
      f"✂️ Corte de {fila[2]} ({_normalizar_fecha_excel(fila[0])}"
      f" {_normalizar_hora_excel(fila[1])}) marcado como realizado por"
      f" ${precio_final}."
  )


def consultar_balance(fecha=None, ruta_excel="turnos.xlsx"):
  almacen = _almacen(ruta_excel)
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

  for _, fila in almacen.filas():
    if fila[2] is None:
      continue
    estado = _estado(fila)
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


def cerrar_dia(fecha=None, ruta_excel="turnos.xlsx"):
  almacen = _almacen(ruta_excel)
  fecha_objetivo = _normalizar_fecha_excel(
      fecha or datetime.now().strftime("%d-%m-%y")
  )

  realizados = []
  pendientes = []
  cancelados = 0
  total_dia = 0.0

  for _, fila in almacen.filas():
    if fila[2] is None:
      continue
    if _normalizar_fecha_excel(fila[0]) != fecha_objetivo:
      continue

    hora_f = _normalizar_hora_excel(fila[1])
    cliente_f = str(fila[2] or "").strip()
    estado_f = _estado(fila)
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

  total_fmt = int(total_dia) if total_dia.is_integer() else round(total_dia, 2)

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
