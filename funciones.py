import re
from datetime import datetime
import openpyxl


def _ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------
# CIERRE DEL DÍA
# ---------------------------------------------------------------
def obtener_resumen_cierre(ruta_excel, stock_actual: dict | None = None) -> str:
    """Resumen del día: lo vendido, lo cobrado y lo que deben los clientes."""
    hoy = datetime.now().strftime("%Y-%m-%d")

    total_efectivo = 0
    total_transferencia = 0
    total_grandes = 0
    total_chicos = 0
    total_sifones = 0
    total_envases_devueltos = 0
    total_envases_prestados = 0
    fiado_hoy = 0          # lo que quedó debiendo en las entregas de hoy
    saldos = {}            # saldo acumulado de cada cliente (todo el historial)

    try:
        libro = openpyxl.load_workbook(ruta_excel, data_only=True)
        hoja = libro.active

        for fila in hoja.iter_rows(min_row=2, values_only=True):
            if not fila or fila[0] is None:
                continue

            cobrado = fila[9] or 0
            # Filas viejas sin "Total Pedido": se consideran pagadas completas
            pedido = fila[10] if len(fila) > 10 and fila[10] is not None else cobrado
            saldo_fila = pedido - cobrado

            # Deuda acumulada por cliente (cuenta todos los días)
            cliente = str(fila[1] or "").strip().title()
            if cliente:
                saldos[cliente] = saldos.get(cliente, 0) + saldo_fila

            # Del resto solo cuenta lo de hoy
            if not str(fila[0]).startswith(hoy):
                continue

            total_grandes += fila[2] or 0
            total_chicos += fila[3] or 0
            total_sifones += fila[4] or 0
            total_envases_devueltos += fila[5] or 0
            total_envases_prestados += fila[6] or 0

            texto_pago = (str(fila[7] or "") + " " + str(fila[8] or "")).lower()
            if "efectivo" in texto_pago:
                total_efectivo += cobrado
            elif "transfer" in texto_pago or "mp" in texto_pago.split():
                total_transferencia += cobrado

            if saldo_fila > 0:
                fiado_hoy += saldo_fila
    except Exception as e:
        return f"⚠️ No pude leer el cierre de hoy: {e}"

    recaudacion_total = total_efectivo + total_transferencia

    texto = (
        f"📊 *RESUMEN DEL CIERRE DE HOY ({hoy})*\n"
        f"🔹 Grandes entregados: {total_grandes}\n"
        f"🔹 Chicos entregados: {total_chicos}\n"
        f"🔹 Sifones entregados: {total_sifones}\n"
        f"🔹 Envases devueltos: {total_envases_devueltos}\n"
        f"🔹 Envases prestados: {total_envases_prestados}\n"
        f"───────────────\n"
        f"💵 Efectivo: ${total_efectivo}\n"
        f"💳 Transferencia/MP: ${total_transferencia}\n"
        f"💰 Recaudación total: ${recaudacion_total}\n"
        f"🧾 Quedó debiendo hoy: ${fiado_hoy}"
    )

    # Quiénes deben plata (de mayor a menor)
    deudores = sorted(
        ((nombre, s) for nombre, s in saldos.items() if s > 0),
        key=lambda x: -x[1],
    )
    texto += "\n───────────────\n"
    if deudores:
        deuda_total = sum(s for _, s in deudores)
        texto += f"📒 *Deuda total de clientes: ${deuda_total}*"
        for nombre, s in deudores[:10]:
            texto += f"\n• {nombre}: ${s}"
        if len(deudores) > 10:
            texto += f"\n…y {len(deudores) - 10} más."
    else:
        texto += "📒 Nadie debe plata 🎉"

    if isinstance(stock_actual, dict):
        texto += (
            f"\n───────────────\n"
            f"📦 Stock actual: {stock_actual.get('grandes', 0)} grandes, "
            f"{stock_actual.get('chicos', 0)} chicos, {stock_actual.get('sifones', 0)} sifones."
        )

    return texto
# ---------------------------------------------------------------
# ENTREGAS Y COBROS
# Columnas del Excel:
#  1 Fecha  2 Cliente  3 Grandes  4 Chicos  5 Sifones  6 Devueltos
#  7 Prestados  8 Estado Pago  9 Detalle Pago  10 Total Cobrado
#  11 Total Pedido  12 Saldo Pendiente
# ---------------------------------------------------------------
def registrar_entrega(datos, stock_camioneta, ruta_excel="libro_diario.xlsx"):
    grandes = int(datos.get("grandes_vendidos") or 0)
    chicos = int(datos.get("chicos_vendidos") or 0)
    sifones = int(datos.get("sifones_vendidos") or 0)
    devueltos = int(datos.get("envases_devueltos") or 0)
    prestados = int(datos.get("envases_prestados") or 0)
    cliente = str(datos.get("cliente") or "").strip().title()

    if not cliente or (grandes + chicos + sifones + devueltos + prestados) == 0:
        return "❓ No pude registrar la entrega: falta el cliente o los productos."

    total_cobrado = datos.get("total_cobrado") or 0
    total_pedido = datos.get("total_pedido") or 0
    sin_total = False
    if total_pedido == 0:
        # Si no dijo el total, asumimos que pagó todo lo que mencionó
        total_pedido = total_cobrado
        sin_total = (total_cobrado == 0)

    saldo = total_pedido - total_cobrado

    if (stock_camioneta["grandes"] >= grandes
        and stock_camioneta["chicos"] >= chicos
        and stock_camioneta["sifones"] >= sifones):
        stock_camioneta["grandes"] -= grandes
        stock_camioneta["chicos"] -= chicos
        stock_camioneta["sifones"] -= sifones

        libro = openpyxl.load_workbook(ruta_excel)
        hoja = libro.active
        hoja.append([
            _ahora(),
            cliente,
            grandes, chicos, sifones,
            devueltos,
            prestados,
            datos.get("estado_pago", ""),
            datos.get("detalle_pago", ""),
            total_cobrado,
            total_pedido,
            saldo,
        ])
        libro.save(ruta_excel)

        mensaje = f"✅ Entrega de {cliente} registrada con éxito."
        if saldo > 0:
            mensaje += f"\n🧾 Quedó debiendo ${saldo}."
        if sin_total:
            mensaje += (
                "\n⚠️ No me dijiste el total, así que no anoté deuda. "
                "Si debe plata, mandá por ejemplo: dejé 3 grandes a Perez total 9000 pagó 5000"
            )
        return mensaje

    return "❌ ¡ALERTA! Stock insuficiente en la camioneta."


def registrar_cobro(datos, ruta_excel="libro_diario.xlsx"):
    cliente = str(datos.get("cliente") or "").strip().title()
    monto = datos.get("total_cobrado") or 0

    if not cliente or monto <= 0:
        return "❓ No pude registrar el cobro: falta el cliente o el monto."

    libro = openpyxl.load_workbook(ruta_excel)
    hoja = libro.active
    hoja.append([
        _ahora(), cliente, 0, 0, 0, 0, 0,
        datos.get("estado_pago", ""),
        datos.get("detalle_pago", ""),
        monto,
        0,
        -monto,   # un cobro baja lo que el cliente debía
    ])
    libro.save(ruta_excel)
    return f"✅ Cobro de ${monto} a {cliente} registrado."


# ---------------------------------------------------------------
# DESHACER LA ÚLTIMA CARGA
# ---------------------------------------------------------------
def deshacer_ultimo(ruta_excel, stock_actual):
    """Borra la última fila cargada y devuelve la mercadería al stock."""
    libro = openpyxl.load_workbook(ruta_excel)
    hoja = libro.active

    ultima = None
    for n in range(hoja.max_row, 1, -1):
        if hoja.cell(row=n, column=1).value is not None:
            ultima = n
            break

    if ultima is None:
        return "↩️ No hay nada para deshacer."

    valores = [hoja.cell(row=ultima, column=c).value for c in range(1, 11)]
    hoja.delete_rows(ultima)
    libro.save(ruta_excel)

    cliente = valores[1] or "sin nombre"
    grandes = int(valores[2] or 0)
    chicos = int(valores[3] or 0)
    sifones = int(valores[4] or 0)
    monto = valores[9] or 0

    stock_actual["grandes"] += grandes
    stock_actual["chicos"] += chicos
    stock_actual["sifones"] += sifones

    partes = []
    if grandes:
        partes.append(f"{grandes} grandes")
    if chicos:
        partes.append(f"{chicos} chicos")
    if sifones:
        partes.append(f"{sifones} sifones")
    detalle = ", ".join(partes) if partes else "cobro"

    return (
        f"↩️ Deshice la última carga: {cliente} ({detalle}, ${monto}).\n"
        f"📦 Stock actual: {stock_actual['grandes']} grandes, "
        f"{stock_actual['chicos']} chicos, {stock_actual['sifones']} sifones."
    )


# ---------------------------------------------------------------
# SALDO DE UN CLIENTE
# ---------------------------------------------------------------
def obtener_saldo_cliente(ruta_excel, nombre):
    """Cuánta plata debe un cliente y cuántos envases tiene sin devolver."""
    buscado = nombre.strip().lower()
    if not buscado:
        return "❓ Decime el cliente. Ejemplo: debe Perez"

    libro = openpyxl.load_workbook(ruta_excel, data_only=True)
    hoja = libro.active

    pedido_total = 0
    cobrado_total = 0
    prestados = 0
    devueltos = 0
    encontrado = False

    for fila in hoja.iter_rows(min_row=2, values_only=True):
        if not fila or fila[1] is None:
            continue
        if str(fila[1]).strip().lower() != buscado:
            continue

        encontrado = True
        cobrado = fila[9] or 0
        # Filas viejas sin "Total Pedido": se consideran pagadas completas
        pedido = fila[10] if len(fila) > 10 and fila[10] is not None else cobrado

        pedido_total += pedido
        cobrado_total += cobrado
        prestados += fila[6] or 0
        devueltos += fila[5] or 0

    nombre_lindo = nombre.strip().title()
    if not encontrado:
        return f"❓ No encontré movimientos de {nombre_lindo}."

    deuda = pedido_total - cobrado_total
    envases = max(prestados - devueltos, 0)

    if deuda > 0:
        linea_plata = f"💰 Debe: ${deuda}"
    elif deuda < 0:
        linea_plata = f"💰 Tiene ${-deuda} a favor"
    else:
        linea_plata = "💰 Está al día"

    return (
        f"📒 Saldo de {nombre_lindo}:\n"
        f"{linea_plata}\n"
        f"📦 Envases prestados sin devolver: {envases}"
    )


# ---------------------------------------------------------------
# STOCK
# ---------------------------------------------------------------
def interpretar_stock(texto):
    """
    Devuelve None si no es un mensaje de stock.
    Si lo es, devuelve un dict con:
      - "modo": "consultar" | "sumar" | "fijar"
      - "valores": {"grandes": int, "chicos": int, "sifones": int} (vacío si es consultar)
    """
    t = " ".join(texto.lower().strip().split())

    if t.startswith("fijar stock"):
        resto = t[len("fijar stock"):].strip()
        modo = "fijar"
    elif t.startswith("stock"):
        resto = t[len("stock"):].strip()
        modo = "sumar"
    else:
        return None

    if not resto:
        return {"modo": "consultar", "valores": {}}

    def buscar(nombre):
        m = re.search(rf"(\d+)\s*(?:bidones?\s+)?{nombre}", resto)
        return int(m.group(1)) if m else 0

    valores = {
        "grandes": buscar(r"grandes?"),
        "chicos": buscar(r"chicos?"),
        "sifones": buscar(r"sifones?"),
    }

    if all(v == 0 for v in valores.values()):
        return {"modo": "consultar", "valores": {}}

    return {"modo": modo, "valores": valores}