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
