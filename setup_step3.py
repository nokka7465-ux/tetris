import json, sqlite3, os
from pathlib import Path
root = Path(".")

# folders
for p in ["tools","data","data/inbox","mercari"]:
    (root / p).mkdir(parents=True, exist_ok=True)

# README
(root/"README.md").write_text("""# tetris / pokeca tools

- tools/build_cards_master_db.py
- tools/sync_cards_master.py
- tools/mercari_automation.py
- data/cards_master_seed.json
- mercari/templates.json
""", encoding="utf-8")

# sample seed
seed = [
 {"card_id":"jp-sv4a-056","name":"ピカチュウ","model_number":"sv4a-056/190","package_name":"シャイニートレジャーex","set_code":"sv4a","card_number":"056/190","rarity":"AR","language":"ja","release_year":2024},
 {"card_id":"jp-sv2a-172","name":"ミュウex","model_number":"sv2a-172/165","package_name":"ポケモンカード151","set_code":"sv2a","card_number":"172/165","rarity":"SR","language":"ja","release_year":2023}
]
(root/"data/cards_master_seed.json").write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
(root/"data/cards_api_snapshot.json").write_text(json.dumps([{
 "id":"jp-sv4a-056","name":"ピカチュウ","number":"056/190","rarity":"AR","language":"ja","set":{"id":"sv4a","name":"シャイニートレジャーex","releaseDate":"2023/12/01"}
}], ensure_ascii=False, indent=2), encoding="utf-8")

# template
(root/"mercari/templates.json").write_text(json.dumps({
 "default":{"title":"{card_name} {set_code} {card_number} {rarity}",
 "description":"【商品名】\\n{card_name}\\n\\n【型番】\\n{model_number}\\n\\n【収録パック】\\n{package_name}\\n\\n【レアリティ】\\n{rarity}"}
}, ensure_ascii=False, indent=2), encoding="utf-8")

# mercari sample in/out
(root/"data/mercari_input_sample.json").write_text(json.dumps({
 "name":"ピカチュウ","set_code":"sv4a","card_number":"056/190","rarity":"AR",
 "model_number":"sv4a-056/190","package_name":"シャイニートレジャーex"
}, ensure_ascii=False, indent=2), encoding="utf-8")

# build_cards_master_db.py
(root/"tools/build_cards_master_db.py").write_text(r'''
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
'''.strip()+"\n", encoding="utf-8")

# sync_cards_master.py
(root/"tools/sync_cards_master.py").write_text(r'''
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
'''.strip()+"\n", encoding="utf-8")

# mercari_automation.py
(root/"tools/mercari_automation.py").write_text(r'''
import argparse, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument("--input", required=True)
p.add_argument("--output", required=True)
args=p.parse_args()
t = json.loads((ROOT/"mercari/templates.json").read_text(encoding="utf-8"))["default"]
c = json.loads(Path(args.input).read_text(encoding="utf-8"))
m = {"card_name":c.get("name",""),"set_code":c.get("set_code",""),"card_number":c.get("card_number",""),"rarity":c.get("rarity",""),"model_number":c.get("model_number",""),"package_name":c.get("package_name","")}
out={"title":t["title"].format(**m),"description":t["description"].format(**m)}
Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("Wrote", args.output)
'''.strip()+"\n", encoding="utf-8")

print("Scaffold done")
