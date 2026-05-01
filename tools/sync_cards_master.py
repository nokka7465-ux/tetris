import argparse, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DB = ROOT/"data/cards_master.db"

def norm(c):
    s=c.get("set",{}) or {}
    return {
      "card_id": c.get("card_id") or c.get("id"),
      "name": c.get("name",""),
      "model_number": c.get("model_number") or f'{c.get("set_code") or s.get("id")}-{c.get("card_number") or c.get("number")}',
      "package_name": c.get("package_name") or s.get("name"),
      "set_code": c.get("set_code") or s.get("id"),
      "card_number": c.get("card_number") or c.get("number"),
      "rarity": c.get("rarity"),
      "language": c.get("language","ja"),
      "release_year": int(c.get("release_year",2024)),
      "updated_at": datetime.now(timezone.utc).isoformat()
    }

p=argparse.ArgumentParser()
p.add_argument("--mode", choices=["snapshot","import-json"], default="snapshot")
p.add_argument("--snapshot", default=str(ROOT/"data/cards_api_snapshot.json"))
p.add_argument("--import-json", dest="import_json", default=None)
args=p.parse_args()

path = Path(args.snapshot if args.mode=="snapshot" else args.import_json)
cards = json.loads(path.read_text(encoding="utf-8"))
rows=[norm(x) for x in cards]

conn=sqlite3.connect(DB)
conn.execute("""CREATE TABLE IF NOT EXISTS cards_master(
card_id TEXT PRIMARY KEY,name TEXT,model_number TEXT,package_name TEXT,set_code TEXT,card_number TEXT,rarity TEXT,language TEXT,release_year INTEGER,updated_at TEXT)""")
conn.executemany("""INSERT INTO cards_master(card_id,name,model_number,package_name,set_code,card_number,rarity,language,release_year,updated_at)
VALUES(:card_id,:name,:model_number,:package_name,:set_code,:card_number,:rarity,:language,:release_year,:updated_at)
ON CONFLICT(card_id) DO UPDATE SET
name=excluded.name,model_number=excluded.model_number,package_name=excluded.package_name,set_code=excluded.set_code,card_number=excluded.card_number,rarity=excluded.rarity,language=excluded.language,release_year=excluded.release_year,updated_at=excluded.updated_at""", rows)
conn.commit(); conn.close()
print(f"Synced {len(rows)} rows")
