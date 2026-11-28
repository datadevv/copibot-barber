from datetime import datetime
import json
import os
import threading

import gspread
from google.oauth2.service_account import Credentials

COLUMNAS_TURNOS = [
    "Fecha",
    "Hora",
    "Cliente",
    "Servicio",
    "Precio",
    "Estado",
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_SHEETS_LOCK = threading.Lock()
_GC_CLIENT = None
_SPREADSHEET = None


def _cargar_creds_dict(creds_raw: str) -> dict:
    if creds_raw.startswith("{"):
        return json.loads(creds_raw)
    if os.path.exists(creds_raw):
        with open(creds_raw, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(creds_raw)


def _obtener_planilla():
    global _GC_CLIENT, _SPREADSHEET

    sheet_id = (os.getenv("GOOGLE_SHEET_ID") or "").strip()
    creds_raw = (os.getenv("GOOGLE_CREDENTIALS_JSON") or "").strip()

    if not sheet_id:
        raise RuntimeError("Falta configurar la variable de entorno GOOGLE_SHEET_ID.")
    if not creds_raw:
        raise RuntimeError(
            "Falta configurar la variable de entorno GOOGLE_CREDENTIALS_JSON."
        )

    if _SPREADSHEET is None:
        creds_info = _cargar_creds_dict(creds_raw)
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        _GC_CLIENT = gspread.authorize(creds)
        try:
            _SPREADSHEET = _GC_CLIENT.open_by_key(sheet_id)
        except gspread.SpreadsheetNotFound:
            url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
            _SPREADSHEET = _GC_CLIENT.open_by_url(url)

    return _SPREADSHEET


def _nombre_pestana(ruta_excel: str | None) -> str:
    raw = str(ruta_excel or "turnos").strip()
    if raw.endswith(".xlsx"):
        raw = raw[:-5]
    raw = os.path.basename(raw).strip()
    for ch in [":", "\\", "/", "?", "*", "[", "]"]:
        raw = raw.replace(ch, "_")
    return (raw or "turnos")[:100]


def _abrir_hoja_turnos(ruta_excel="turnos", crear_si_no_existe=True):
    planilla = _obtener_planilla()
    titulo = _nombre_pestana(ruta_excel)

    try:
        ws = planilla.worksheet(titulo)
    except gspread.WorksheetNotFound:
        if not crear_si_no_existe:
            return None
        ws = planilla.add_worksheet(title=titulo, rows=200, cols=10)
        ws.append_row(COLUMNAS_TURNOS, value_input_option="USER_ENTERED")
        return ws

    valores = ws.get_all_values()
    if not valores or not any(str(c).strip() for c in valores[0]):
        ws.clear()
        ws.append_row(COLUMNAS_TURNOS, value_input_option="USER_ENTERED")

    return ws


def _leer_filas_turnos(ws):
    """Devuelve lista de tuplas (numero_fila_1_based, fila_6_cols)."""
    if ws is None:
        return []
    todas = ws.get_all_values()
    if len(todas) <= 1:
        return []

    filas = []
    for idx, fila in enumerate(todas[1:], start=2):
        padded = list(fila[:6]) + [""] * max(0, 6 - len(fila[:6]))
        if not any(str(c).strip() for c in padded):
            continue
        filas.append((idx, padded))
    return filas


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


def _fmt_precio(valor) -> int | float:
    try:
        num = float(valor)
        return int(num) if num.is_integer() else round(num, 2)
    except (TypeError, ValueError):
        return 10000


def agendar_turno(datos, ruta_excel="turnos"):
    with _SHEETS_LOCK:
        ws = _abrir_hoja_turnos(ruta_excel, crear_si_no_existe=True)

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

        for _, fila in _leer_filas_turnos(ws):
            f_fecha = _normalizar_fecha_excel(fila[0])
            f_hora = _normalizar_hora_excel(fila[1])
            f_estado = str(fila[5] or "").strip().lower()
            if f_fecha == fecha and f_hora == hora and f_estado == "agendado":
                return (
                    f"⚠️ Ya hay un turno agendado el {fecha} a las {hora} ({fila[2]})."
                )

        ws.append_row(
            [fecha, hora, cliente, servicio, precio, "agendado"],
            value_input_option="USER_ENTERED",
        )

        return (
            f"✅ Turno agendado para {cliente}: {fecha} a las {hora} "
            f"({servicio}, ${precio})."
        )


def consultar_turnos(fecha=None, ruta_excel="turnos", todos: bool = False):
    with _SHEETS_LOCK:
        ws = _abrir_hoja_turnos(ruta_excel, crear_si_no_existe=False)
        filas = _leer_filas_turnos(ws)
        if not filas:
            return "📅 Todavía no hay turnos agendados."

        es_todos = todos or (
            str(fecha or "").strip().lower() in {"todos", "todo", "ver todos"}
        )
        turnos = []

        if es_todos:
            for _, fila in filas:
                if str(fila[5] or "").strip().lower() == "agendado":
                    turnos.append((
                        _normalizar_fecha_excel(fila[0]),
                        _normalizar_hora_excel(fila[1]),
                        str(fila[2] or "").strip(),
                        str(fila[3] or "corte").strip(),
                        _fmt_precio(fila[4] if fila[4] != "" else 10000),
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
        for _, fila in filas:
            if (
                _normalizar_fecha_excel(fila[0]) == fecha_objetivo
                and str(fila[5] or "").strip().lower() == "agendado"
            ):
                turnos.append((
                    _normalizar_hora_excel(fila[1]),
                    str(fila[2] or "").strip(),
                    str(fila[3] or "corte").strip(),
                    _fmt_precio(fila[4] if fila[4] != "" else 10000),
                ))

        if not turnos:
            return f"📅 No hay turnos agendados para el {fecha_objetivo}."

        turnos.sort(key=lambda item: item[0])
        lineas = [f"📅 *Turnos del {fecha_objetivo}:*"]
        for f_hora, f_cliente, f_servicio, f_precio in turnos:
            lineas.append(f"• {f_hora} — {f_cliente} ({f_servicio}, ${f_precio})")

        return "\n".join(lineas)


def cancelar_turno(datos, ruta_excel="turnos"):
    with _SHEETS_LOCK:
        ws = _abrir_hoja_turnos(ruta_excel, crear_si_no_existe=False)
        filas = _leer_filas_turnos(ws)
        if not filas:
            return "📅 No hay turnos agendados para cancelar."

        cliente = str(datos.get("cliente") or "").strip().lower()
        fecha = (
            _normalizar_fecha_excel(datos.get("fecha"))
            if datos.get("fecha")
            else ""
        )
        hora = (
            _normalizar_hora_excel(datos.get("hora")) if datos.get("hora") else ""
        )

        coincidencias = []
        for numero_fila, fila in filas:
            if str(fila[5] or "").strip().lower() != "agendado":
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
                "❓ Hay más de un turno coincidente. Indicame el nombre, fecha y/o"
                " hora para cancelar."
            )

        numero_fila, fila = coincidencias[0]
        ws.update_cell(numero_fila, 6, "cancelado")

        return (
            f"🗑️ Turno cancelado para {fila[2]} "
            f"({_normalizar_fecha_excel(fila[0])} {_normalizar_hora_excel(fila[1])})."
        )


def marcar_corte_realizado(datos, ruta_excel="turnos"):
    with _SHEETS_LOCK:
        ws = _abrir_hoja_turnos(ruta_excel, crear_si_no_existe=False)
        filas = _leer_filas_turnos(ws)
        if not filas:
            return "📅 No hay turnos agendados para marcar como realizados."

        cliente = str(datos.get("cliente") or "").strip().lower()
        fecha = (
            _normalizar_fecha_excel(datos.get("fecha"))
            if datos.get("fecha")
            else ""
        )
        hora = (
            _normalizar_hora_excel(datos.get("hora")) if datos.get("hora") else ""
        )

        def buscar(usar_fecha):
            encontrados = []
            for numero_fila, fila in filas:
                if str(fila[5] or "").strip().lower() != "agendado":
                    continue
                if cliente and cliente not in str(fila[2] or "").strip().lower():
                    continue
                if hora and hora != _normalizar_hora_excel(fila[1]):
                    continue
                if usar_fecha and fecha and fecha != _normalizar_fecha_excel(fila[0]):
                    continue
                encontrados.append((numero_fila, fila))
            return encontrados

        coincidencias = buscar(usar_fecha=True)

        if not coincidencias and cliente:
            coincidencias = buscar(usar_fecha=False)

        if not coincidencias and not cliente and not hora:
            for numero_fila, fila in reversed(filas):
                if str(fila[5] or "").strip().lower() == "agendado":
                    coincidencias.append((numero_fila, fila))
                    break

        if not coincidencias:
            return (
                "❓ No encontré un turno agendado coincidente para marcar como"
                " realizado."
            )

        if len(coincidencias) > 1 and not (cliente and hora):
            return (
                "❓ Hay más de un turno coincidente. Indicame el nombre y/o la hora"
                " del corte."
            )

        numero_fila, fila = coincidencias[-1]
        precio_override = datos.get("precio")
        precio_final = (
            precio_override
            if precio_override not in (None, "", 0)
            else (fila[4] if fila[4] != "" else 10000)
        )
        precio_final_fmt = _fmt_precio(precio_final)

        ws.update_cell(numero_fila, 5, precio_final_fmt)
        ws.update_cell(numero_fila, 6, "realizado")

        return (
            f"✂️ Corte de {fila[2]} ({_normalizar_fecha_excel(fila[0])}"
            f" {_normalizar_hora_excel(fila[1])}) marcado como realizado por"
            f" ${precio_final_fmt}."
        )


def consultar_balance(fecha=None, ruta_excel="turnos"):
    with _SHEETS_LOCK:
        ws = _abrir_hoja_turnos(ruta_excel, crear_si_no_existe=False)
        filas = _leer_filas_turnos(ws)
        if not filas:
            return "💰 Todavía no tenés cortes realizados ni turnos registrados."

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

        for _, fila in filas:
            if not str(fila[2] or "").strip():
                continue
            estado = str(fila[5] or "").strip().lower()
            try:
                monto = float(fila[4] if fila[4] != "" else 0)
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
            f"• Turnos pendientes: {cant_pendiente_dia}"
            f" (${_fmt(pendiente_dia)})\n\n"
            "📊 *Balance total acumulado:*\n"
            f"• Cortes realizados: {cant_realizado_total}"
            f" (${_fmt(realizado_total)})\n"
            f"• Turnos pendientes: {cant_pendiente_total}"
            f" (${_fmt(pendiente_total)})"
        )


def abrir_dia(fecha=None, ruta_excel="turnos"):
    fecha_objetivo = _normalizar_fecha_excel(
        fecha or datetime.now().strftime("%d-%m-%y")
    )
    agenda = consultar_turnos(fecha=fecha_objetivo, ruta_excel=ruta_excel)
    return f"🌅 *Apertura del día ({fecha_objetivo}):*\n\n{agenda}"


def cerrar_dia(fecha=None, ruta_excel="turnos"):
    fecha_objetivo = _normalizar_fecha_excel(
        fecha or datetime.now().strftime("%d-%m-%y")
    )

    with _SHEETS_LOCK:
        ws = _abrir_hoja_turnos(ruta_excel, crear_si_no_existe=False)
        filas = _leer_filas_turnos(ws)

        if not filas:
            return (
                f"🌙 *Cierre del día ({fecha_objetivo}):*\n"
                "• Cortes realizados: 0 ($0)\n"
                "• Turnos pendientes: 0 ($0)\n"
                "• Turnos cancelados: 0"
            )

        realizados = []
        pendientes = []
        cancelados = 0
        total_dia = 0.0

        for _, fila in filas:
            if not str(fila[2] or "").strip():
                continue
            if _normalizar_fecha_excel(fila[0]) != fecha_objetivo:
                continue

            hora_f = _normalizar_hora_excel(fila[1])
            cliente_f = str(fila[2] or "").strip()
            estado_f = str(fila[5] or "").strip().lower()
            try:
                monto_f = float(fila[4] if fila[4] != "" else 10000)
            except (TypeError,
