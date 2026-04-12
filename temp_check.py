import sqlite3
db = sqlite3.connect('amparo.db')
db.row_factory = sqlite3.Row
rows = db.execute("SELECT clave, valor FROM configuracion WHERE clave LIKE '%mail%'").fetchall()
for r in rows:
    print(r['clave'], '=', r['valor'])
