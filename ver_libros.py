from viejos.repartidores import REPARTIDORES  # pyright: ignore[reportMissingImports]
import openpyxl

for numero, r in REPARTIDORES.items():
    ruta = r["ruta_excel"]
    print("=" * 50)
    print(r["nombre"], numero)
    print(ruta)
    if not ruta.exists():
        print("   (todavía no existe)")
        continue
    ws = openpyxl.load_workbook(ruta).active
    print("   Títulos:", [c.value for c in ws[1]])
    for fila in list(ws.iter_rows(min_row=2, values_only=True))[-3:]:
        print("   ", fila)