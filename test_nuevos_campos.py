from access_reader import AccessReader
from marc_converter import MarcConverter

mdb = r"C:\Users\ikerg\Downloads\Prometeo V-20260918T200642Z-1-001\Prometeo V\PROMETEO.mdb"
r = AccessReader(mdb)

# Probar con una ficha que tenga ejemplares (ficha 4 tiene 3)
fichas = r.leer_fichas(limite=5)

converter = MarcConverter(
    item_type_bib='LIBR0',
    item_type_item='LIBR0',
    homebranch='ITT',
    holdingbranch='ITT',
)

for ficha in fichas[:3]:
    id_ficha = ficha['Ficha_No']
    ejemplares = r.leer_ejemplares_por_ficha([id_ficha]).get(id_ficha, [])
    record = converter.ficha_a_record(ficha, ejemplares)
    marcxml = converter.record_a_marcxml(record)
    print(f"=== Ficha {id_ficha}: {ficha['Titulo'][:40]} ===")
    print(marcxml[:1500])
    print("\n" + "="*60 + "\n")

r.close()
print("Prueba completada.")
