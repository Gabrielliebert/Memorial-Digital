import sqlite3
import json
import os

db_path = os.path.join("data", "memorial.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT * FROM memoriais ORDER BY id DESC LIMIT 1").fetchone()
conn.close()

if row:
    data = dict(row)
    with open("last_memorial_dump.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Dumped memorial ID: {data['id']} para {data['nome']}")
else:
    print("Nenhum memorial encontrado.")
