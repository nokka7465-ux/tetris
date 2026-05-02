"""
DBマイグレーション: cards_master拡張 + collection/listings 追加
冪等。何度実行しても安全。
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "cards_master.db"

CARDS_MASTER_NEW_COLUMNS = [
    ("name_en", "TEXT"),
    ("supertype", "TEXT"),
    ("subtypes", "TEXT"),
    ("hp", "INTEGER"),
    ("types", "TEXT"),
    ("abilities", "TEXT"),
    ("attacks", "TEXT"),
    ("weaknesses", "TEXT"),
    ("resistances", "TEXT"),
    ("retreat_cost", "INTEGER"),
    ("illustrator", "TEXT"),
    ("image_small_url", "TEXT"),
    ("image_large_url", "TEXT"),
    ("image_local_path", "TEXT"),
    ("rarity_estimated", "TEXT"),
    ("variant_type", "TEXT NOT NULL DEFAULT 'standard'"),
]

CREATE_COLLECTION = """
CREATE TABLE IF NOT EXISTS collection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL,
    condition TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    purchase_price INTEGER,
    purchase_date TEXT,
    note TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(card_id) REFERENCES cards_master(card_id)
)
"""

CREATE_LISTINGS = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL,
    collection_id INTEGER,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    list_price INTEGER,
    sold_price INTEGER,
    fee INTEGER,
    shipping_cost INTEGER,
    profit INTEGER,
    status TEXT NOT NULL DEFAULT 'draft',
    listed_at TEXT,
    sold_at TEXT,
    mercari_item_id TEXT,
    image_paths TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(card_id) REFERENCES cards_master(card_id),
    FOREIGN KEY(collection_id) REFERENCES collection(id)
)
"""

CREATE_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_cards_set ON cards_master(set_code)",
    "CREATE INDEX IF NOT EXISTS idx_cards_name ON cards_master(name)",
    "CREATE INDEX IF NOT EXISTS idx_collection_card ON collection(card_id)",
    "CREATE INDEX IF NOT EXISTS idx_listings_card ON listings(card_id)",
    "CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)",
]


def existing_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def primary_key_columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall() if row[5] > 0]


def rebuild_cards_master_with_composite_pk(conn):
    """Recreate cards_master with PRIMARY KEY (card_id, variant_type)."""
    cols = [row for row in conn.execute("PRAGMA table_info(cards_master)").fetchall()]
    col_defs = []
    col_names = []
    for cid, name, typ, notnull, dflt, pk in cols:
        col_names.append(name)
        d = f"{name} {typ}"
        if notnull and name != "card_id":
            d += " NOT NULL"
        if dflt is not None:
            d += f" DEFAULT {dflt}"
        col_defs.append(d)
    col_defs.append("PRIMARY KEY (card_id, variant_type)")
    new_sql = f"CREATE TABLE cards_master_new (\n  " + ",\n  ".join(col_defs) + "\n)"
    conn.execute(new_sql)
    conn.execute(
        f"INSERT INTO cards_master_new ({', '.join(col_names)}) "
        f"SELECT {', '.join(col_names)} FROM cards_master"
    )
    conn.execute("DROP TABLE cards_master")
    conn.execute("ALTER TABLE cards_master_new RENAME TO cards_master")


def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)

    conn.execute("""CREATE TABLE IF NOT EXISTS cards_master(
        card_id TEXT PRIMARY KEY, name TEXT, model_number TEXT, package_name TEXT,
        set_code TEXT, card_number TEXT, rarity TEXT, language TEXT,
        release_year INTEGER, updated_at TEXT)""")

    cols = existing_columns(conn, "cards_master")
    added = []
    for name, typ in CARDS_MASTER_NEW_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE cards_master ADD COLUMN {name} {typ}")
            added.append(name)

    pk_cols = primary_key_columns(conn, "cards_master")
    rebuilt = False
    if pk_cols != ["card_id", "variant_type"]:
        rebuild_cards_master_with_composite_pk(conn)
        rebuilt = True

    conn.execute(CREATE_COLLECTION)
    conn.execute(CREATE_LISTINGS)
    for sql in CREATE_INDICES:
        conn.execute(sql)

    conn.commit()
    conn.close()

    print(f"Migration done. Added columns to cards_master: {added or 'none'}")
    if rebuilt:
        print("Rebuilt cards_master with PRIMARY KEY (card_id, variant_type)")
    print("Tables ensured: cards_master, collection, listings")


if __name__ == "__main__":
    main()
