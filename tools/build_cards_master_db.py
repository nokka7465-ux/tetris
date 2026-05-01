import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DB = ROOT/"data/cards_master.db"
SEED = ROOT/"data/cards_master_seed.json"
rows = json.loads(SEED.read_text(encoding="utf-8"))
now = datetime.now(timezone.utc).isoformat()
for r in rows: r["updated_at"]=now
conn = sqlite3.connect(DB)
conn.execute("""CREATE TABLE IF NOT EXISTS cards_master(
card_id TEXT PRIMARY KEY,name TEXT,model_number TEXT,package_name TEXT,set_code TEXT,card_number TEXT,rarity TEXT,language TEXT,release_year INTEGER,updated_at TEXT)""")
conn.execute("DELETE FROM cards_master")
conn.executemany("""INSERT INTO cards_master(card_id,name,model_number,package_name,set_code,card_number,rarity,language,release_year,updated_at)
VALUES(:card_id,:name,:model_number,:package_name,:set_code,:card_number,:rarity,:language,:release_year,:updated_at)""", rows)
conn.commit(); conn.close()
print(f"Inserted {len(rows)} rows")
