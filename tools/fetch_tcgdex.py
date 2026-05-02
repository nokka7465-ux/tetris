"""
TCGdex API から日本語の全ポケモンカードを取り込み、cards_master にUPSERT。

使い方:
  python tools/fetch_tcgdex.py             # 全件取得
  python tools/fetch_tcgdex.py --set SV4a  # 特定セットのみ
  python tools/fetch_tcgdex.py --limit-sets 3  # 動作確認用に先頭3セットだけ
"""
import argparse
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "cards_master.db"
API_BASE = "https://api.tcgdex.net/v2/ja"
ASSET_QUALITY_SMALL = "low.webp"
ASSET_QUALITY_LARGE = "high.png"
MAX_WORKERS = 8
RETRY = 3
RETRY_WAIT = 2.0


def get_json(url):
    last = None
    for i in range(RETRY):
        try:
            req = Request(url, headers={"User-Agent": "pokemoncard-AI/1.0"})
            with urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as e:
            last = e
            time.sleep(RETRY_WAIT * (i + 1))
    raise RuntimeError(f"GET failed: {url} ({last})")


def estimate_rarity(local_id, official, total):
    """カード番号と公式総数から推定レア度。
    番号 ≤ official: 'low' （C/U/R/RR）
    official < 番号 ≤ total: 'high' （SR/SAR/AR/UR/HR）
    """
    try:
        n = int(str(local_id).lstrip("0") or "0")
    except ValueError:
        return None
    if not official:
        return None
    if n <= int(official):
        return "low"
    return "high"


def normalize_card(c, set_meta):
    image = c.get("image")
    image_small = f"{image}/{ASSET_QUALITY_SMALL}" if image else None
    image_large = f"{image}/{ASSET_QUALITY_LARGE}" if image else None

    set_id = set_meta["id"]
    local_id = c.get("localId") or ""
    cc = set_meta.get("cardCount") or {}
    official = cc.get("official")
    total = cc.get("total") or official
    card_number = f"{local_id}/{total}" if total else local_id
    model_number = f"{set_id}-{local_id}"

    release = set_meta.get("releaseDate") or ""
    release_year = int(release[:4]) if release[:4].isdigit() else None
    rarity_estimated = estimate_rarity(local_id, official, total)

    abilities = c.get("abilities")
    attacks = c.get("attacks")
    weaknesses = c.get("weaknesses")
    resistances = c.get("resistances")
    types = c.get("types")
    stage = c.get("stage")
    subtypes = [stage] if stage else None

    return {
        "card_id": c["id"],
        "name": c.get("name", ""),
        "name_en": None,
        "model_number": model_number,
        "package_name": set_meta.get("name"),
        "set_code": set_id,
        "card_number": card_number,
        "rarity": c.get("rarity"),
        "language": "ja",
        "release_year": release_year,
        "supertype": c.get("category"),
        "subtypes": json.dumps(subtypes, ensure_ascii=False) if subtypes else None,
        "hp": c.get("hp"),
        "types": json.dumps(types, ensure_ascii=False) if types else None,
        "abilities": json.dumps(abilities, ensure_ascii=False) if abilities else None,
        "attacks": json.dumps(attacks, ensure_ascii=False) if attacks else None,
        "weaknesses": json.dumps(weaknesses, ensure_ascii=False) if weaknesses else None,
        "resistances": json.dumps(resistances, ensure_ascii=False) if resistances else None,
        "retreat_cost": c.get("retreat"),
        "illustrator": c.get("illustrator"),
        "image_small_url": image_small,
        "image_large_url": image_large,
        "image_local_path": None,
        "rarity_estimated": rarity_estimated,
        "variant_type": "standard",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


UPSERT_SQL = """
INSERT INTO cards_master(
    card_id, name, name_en, model_number, package_name, set_code, card_number,
    rarity, language, release_year, supertype, subtypes, hp, types,
    abilities, attacks, weaknesses, resistances, retreat_cost, illustrator,
    image_small_url, image_large_url, image_local_path,
    rarity_estimated, variant_type, updated_at
) VALUES (
    :card_id, :name, :name_en, :model_number, :package_name, :set_code, :card_number,
    :rarity, :language, :release_year, :supertype, :subtypes, :hp, :types,
    :abilities, :attacks, :weaknesses, :resistances, :retreat_cost, :illustrator,
    :image_small_url, :image_large_url, :image_local_path,
    :rarity_estimated, :variant_type, :updated_at
)
ON CONFLICT(card_id, variant_type) DO UPDATE SET
    name=excluded.name, name_en=excluded.name_en, model_number=excluded.model_number,
    package_name=excluded.package_name, set_code=excluded.set_code,
    card_number=excluded.card_number, rarity=COALESCE(excluded.rarity, cards_master.rarity),
    language=excluded.language, release_year=excluded.release_year,
    supertype=excluded.supertype, subtypes=excluded.subtypes, hp=excluded.hp,
    types=excluded.types, abilities=excluded.abilities, attacks=excluded.attacks,
    weaknesses=excluded.weaknesses, resistances=excluded.resistances,
    retreat_cost=excluded.retreat_cost, illustrator=excluded.illustrator,
    image_small_url=excluded.image_small_url, image_large_url=excluded.image_large_url,
    rarity_estimated=excluded.rarity_estimated,
    updated_at=excluded.updated_at
"""


def fetch_set_with_cards(set_id):
    """
    200 OK を最優先で返す。404の時のみ大文字小文字を試す。
    cards 配列が空でも例外にしない（TCGdex側のデータ欠損として扱う）。
    """
    candidates = [set_id]
    if set_id != set_id.upper():
        candidates.append(set_id.upper())
    if set_id != set_id.lower():
        candidates.append(set_id.lower())

    last_err = None
    for sid in candidates:
        try:
            return get_json(f"{API_BASE}/sets/{sid}")
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(last_err)


def fetch_card_detail(card_id):
    return get_json(f"{API_BASE}/cards/{card_id}")


def import_set(conn, set_id, fast=False):
    set_data = fetch_set_with_cards(set_id)
    set_meta = {k: set_data[k] for k in ("id", "name", "releaseDate", "cardCount") if k in set_data}
    cards = set_data.get("cards", [])

    if fast:
        rows = [normalize_card(c, set_meta) for c in cards]
    else:
        rows = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(fetch_card_detail, c["id"]): c["id"] for c in cards}
            for f in as_completed(futures):
                cid = futures[f]
                try:
                    detail = f.result()
                    rows.append(normalize_card(detail, set_meta))
                except Exception as e:
                    print(f"  ! skip {cid}: {e}", file=sys.stderr)

    conn.executemany(UPSERT_SQL, rows)
    conn.commit()
    return len(rows), set_meta.get("name", set_id)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--set", help="特定セットIDのみ取り込み (例: SV4a)")
    p.add_argument("--limit-sets", type=int, default=None, help="先頭N個のセットだけ処理（テスト用）")
    p.add_argument("--fast", action="store_true",
                   help="セット概要のみ使用（HP/技/特性は取れない／高速）")
    args = p.parse_args()

    if not DB.exists():
        print(f"DB not found at {DB}. Run tools/migrate_db.py first.", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(DB)

    if args.set:
        set_ids = [args.set]
    else:
        sets = get_json(f"{API_BASE}/sets")
        seen = set()
        set_ids = []
        for s in sets:
            sid = s["id"]
            if sid.lower() in seen:
                continue
            seen.add(sid.lower())
            set_ids.append(sid)
        if args.limit_sets:
            set_ids = set_ids[: args.limit_sets]
        print(f"Deduped sets: {len(set_ids)} unique (raw list had {len(sets)})")

    print(f"Importing {len(set_ids)} set(s) (fast={args.fast})")
    total = 0
    empty_sets = []
    for i, sid in enumerate(set_ids, 1):
        try:
            n, name = import_set(conn, sid, fast=args.fast)
            total += n
            mark = "" if n > 0 else "  ⚠ no cards in TCGdex (data gap)"
            print(f"[{i}/{len(set_ids)}] {sid} {name}: {n} cards{mark}")
            if n == 0:
                empty_sets.append(sid)
        except Exception as e:
            print(f"[{i}/{len(set_ids)}] {sid}: FAILED ({e})", file=sys.stderr)
            empty_sets.append(sid)

    conn.close()
    print(f"\nDone. Total imported/updated: {total}")
    if empty_sets:
        print(f"⚠ {len(empty_sets)} sets had no card data in TCGdex:")
        print(" ", ", ".join(empty_sets))
        print("  → これらは公式サイトのスクレイピング等で別途補完が必要")


if __name__ == "__main__":
    main()
