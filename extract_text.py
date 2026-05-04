import json

with open("last_memorial_dump.json", "r", encoding="utf-8") as f:
    data = json.load(f)

text = data.get("texto_principal", "Nenhum texto encontrado.")

with open("last_memorial_text.md", "w", encoding="utf-8") as f:
    f.write(text)

print(f"Text extracted, length: {len(text)}")
