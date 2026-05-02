"""
カード情報→メルカリ出品タイトル＆概要欄を生成。

タイトル: 40文字以内
概要欄: 500文字以内（超えたら優先度の低い項目から自動圧縮）
構造: ヘッダー → レアリティ別本文 → 状態説明 → 発送・梱包 → 週次トレンド → フッター

CLI:
  python tools/generate_listing.py --card-id SV4a-056 --condition near_mint
  python tools/generate_listing.py --card-id SV4a-056 --condition mint --output out.json
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "cards_master.db"
TEMPLATES = ROOT / "mercari" / "templates.json"
USER_CFG = ROOT / "config" / "user_settings.json"
TRENDS = ROOT / "data" / "weekly_trends.json"

TITLE_LIMIT = 40
DESC_LIMIT = 500


def load_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_card(card_id, variant_type="standard"):
    if not DB.exists():
        raise FileNotFoundError(f"DB not found: {DB}")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM cards_master WHERE card_id = ? AND variant_type = ?",
        (card_id, variant_type),
    ).fetchone()
    conn.close()
    if not row:
        raise LookupError(f"card_id+variant not found: {card_id} ({variant_type})")
    return dict(row)


def build_title(card, templates):
    variant = card.get("variant_type") or "standard"
    variant_tag = templates.get("variant_title_tag", {}).get(variant, "")
    rarity_disp = card.get("rarity") or variant_tag or ""
    fields = {
        "name": card.get("name") or "",
        "rarity": rarity_disp,
        "set_code": card.get("set_code") or "",
        "card_number": card.get("card_number") or "",
        "package_name": card.get("package_name") or "",
    }
    title = templates["title"].format(**fields)
    title = " ".join(title.split())
    if len(title) <= TITLE_LIMIT:
        return title

    fallback = templates["title_fallback"].format(**fields)
    fallback = " ".join(fallback.split())
    if variant_tag and variant_tag not in fallback:
        candidate = f"{fallback} {variant_tag}"
        if len(candidate) <= TITLE_LIMIT:
            return candidate
    if len(fallback) <= TITLE_LIMIT:
        return fallback

    return fallback[:TITLE_LIMIT]


def build_sections(card, condition, templates, user_cfg, weekly_trend):
    fields = {
        "name": card.get("name") or "",
        "rarity": card.get("rarity") or "ノーマル",
        "set_code": card.get("set_code") or "",
        "card_number": card.get("card_number") or "",
        "package_name": card.get("package_name") or "",
        "model_number": card.get("model_number") or "",
    }

    header = templates["header"].format(**fields)

    variant = card.get("variant_type") or "standard"
    variant_body = templates.get("variant_body", {}).get(variant, "")

    if variant_body:
        rarity_body = variant_body
    else:
        rarity_body_map = templates.get("rarity_body", {})
        rarity_body = rarity_body_map.get(card.get("rarity") or "", rarity_body_map.get("default", ""))

    cond_label = templates["condition_label_map"].get(condition, condition)
    condition_text = (
        f"■ 状態: {cond_label}\n"
        f"{user_cfg.get('condition_default_text', '')}"
    ).strip()

    shipping_text = (
        f"■ 発送: {user_cfg.get('shipping_method', '')} / "
        f"{user_cfg.get('shipping_days', '')}\n"
        f"{user_cfg.get('shipping_default_text', '')}"
    ).strip()

    trend_text = ""
    if weekly_trend:
        trend_text = templates.get("weekly_trend_prefix", "") + weekly_trend.strip()

    smoking = templates["smoking_text_map"].get(user_cfg.get("smoking", "no"), "")
    pets = templates["pets_text_map"].get(user_cfg.get("pets", "no"), "")
    instant = "即購入OK。" if user_cfg.get("instant_buy_ok") else ""
    footer_lines = [
        user_cfg.get("greeting", ""),
        instant,
        f"{smoking}{pets}".strip(),
        user_cfg.get("return_policy", ""),
    ]
    footer = "\n".join(s for s in footer_lines if s)

    return [
        ("header", header),
        ("rarity_body", rarity_body),
        ("condition", condition_text),
        ("shipping", shipping_text),
        ("trend", trend_text),
        ("footer", footer),
    ]


SHRINK_ORDER = ["trend", "rarity_body", "shipping", "condition", "header", "footer"]


def assemble(sections, limit):
    sections = [(k, v) for k, v in sections if v]
    text = "\n\n".join(v for _, v in sections)
    if len(text) <= limit:
        return text

    section_map = dict(sections)
    for drop_key in SHRINK_ORDER:
        if drop_key in section_map:
            del section_map[drop_key]
            text = "\n\n".join(
                v for k, v in sections if k in section_map and section_map.get(k)
            )
            if len(text) <= limit:
                return text

    return text[: limit - 1] + "…"


def generate(card_id, condition, variant_type="standard"):
    card = fetch_card(card_id, variant_type)
    templates = load_json(TEMPLATES)
    user_cfg = load_json(USER_CFG, {})
    trends = load_json(TRENDS, {})
    weekly_trend = trends.get("summary", "")

    title = build_title(card, templates)
    sections = build_sections(card, condition, templates, user_cfg, weekly_trend)
    description = assemble(sections, DESC_LIMIT)

    return {
        "card_id": card_id,
        "variant_type": variant_type,
        "rarity_estimated": card.get("rarity_estimated"),
        "title": title,
        "title_length": len(title),
        "description": description,
        "description_length": len(description),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--card-id", required=True)
    p.add_argument(
        "--condition",
        choices=["mint", "near_mint", "excellent", "played"],
        default="near_mint",
    )
    p.add_argument(
        "--variant",
        choices=["standard", "masterball_mirror", "pokeball_mirror"],
        default="standard",
    )
    p.add_argument("--output", help="JSON出力先（省略時は標準出力）")
    args = p.parse_args()

    try:
        result = generate(args.card_id, args.condition, args.variant)
    except LookupError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(out)


if __name__ == "__main__":
    main()
