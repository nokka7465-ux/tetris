"""
既存のcards_masterデータに対して rarity_estimated をバックフィル。
card_number 形式 'NNN/TTT' から推定。

low: NNN <= official総数（C/U/R/RR）
high: NNN > official総数（SR/SAR/AR/UR/HR）
"""
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "cards_master.db"


def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT card_id, variant_type, card_number, set_code FROM cards_master "
        "WHERE rarity_estimated IS NULL"
    ).fetchall()

    set_official = {}
    for set_code, in conn.execute(
        "SELECT DISTINCT set_code FROM cards_master WHERE set_code IS NOT NULL"
    ).fetchall():
        max_total = conn.execute(
            "SELECT MAX(CAST(SUBSTR(card_number, INSTR(card_number,'/')+1) AS INTEGER)) "
            "FROM cards_master WHERE set_code = ?",
            (set_code,),
        ).fetchone()[0]
        set_official[set_code] = max_total

    updates = []
    for card_id, variant, num, set_code in rows:
        if not num or "/" not in num:
            continue
        m = re.match(r"(\d+)\s*/\s*(\d+)", num)
        if not m:
            continue
        n = int(m.group(1))
        total = int(m.group(2))
        official = set_official.get(set_code) or total
        est = "low" if n <= official else "high"
        updates.append((est, card_id, variant))

    conn.executemany(
        "UPDATE cards_master SET rarity_estimated = ? WHERE card_id = ? AND variant_type = ?",
        updates,
    )
    conn.commit()
    conn.close()
    print(f"Backfilled rarity_estimated on {len(updates)} rows")


if __name__ == "__main__":
    main()
