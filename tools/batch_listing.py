"""
フォルダ内の複数カード画像を一括処理して、出品タイトル＆概要欄をCSVで出力。

入力フォルダの構成例:
  inbox/
    mint/         <- 状態ごとにサブフォルダ（mint/near_mint/excellent/played）
      card_a.jpg
      card_b.jpg
    near_mint/
      card_c.jpg

サブフォルダ名が状態として認識される。直下のファイルは --default-condition で扱う。

使い方:
  python tools/batch_listing.py --input data/inbox --output data/listings_batch.csv
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import identify_card  # noqa: E402
import generate_listing  # noqa: E402

VALID_CONDITIONS = {"mint", "near_mint", "excellent", "played"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def collect_images(root, default_condition):
    items = []
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(root)

    for sub in root.iterdir():
        if sub.is_dir() and sub.name.lower() in VALID_CONDITIONS:
            cond = sub.name.lower()
            for f in sub.rglob("*"):
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                    items.append((f, cond))
        elif sub.is_file() and sub.suffix.lower() in IMAGE_EXTS:
            items.append((sub, default_condition))
    return items


def empty_row(image_path, condition, status, card_id="", variant=""):
    return {
        "image": str(image_path),
        "condition": condition,
        "card_id": card_id,
        "variant_type": variant,
        "title": "",
        "title_length": 0,
        "description": "",
        "description_length": 0,
        "status": status,
    }


def process_one(image_path, condition, skip_low_rarity=True):
    try:
        ident = identify_card.identify(str(image_path))
    except Exception as e:
        return empty_row(image_path, condition, f"identify_error: {e}")

    card_id = ident.get("card_id")
    if not card_id:
        return empty_row(
            image_path, condition,
            f"no_match (ocr={ident.get('ocr_excerpt','')[:60]})",
        )

    variant = ident.get("variant_type", "standard")

    if skip_low_rarity and variant == "standard" and ident.get("rarity_estimated") == "low":
        return empty_row(
            image_path, condition,
            f"skipped_low_rarity ({card_id})", card_id, variant,
        )

    try:
        listing = generate_listing.generate(card_id, condition, variant)
    except Exception as e:
        return empty_row(image_path, condition, f"generate_error: {e}", card_id, variant)

    return {
        "image": str(image_path),
        "condition": condition,
        "card_id": card_id,
        "variant_type": variant,
        "title": listing["title"],
        "title_length": listing["title_length"],
        "description": listing["description"],
        "description_length": listing["description_length"],
        "status": f"ok ({ident.get('confidence')}, {ident.get('variant_label','通常版')})",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="画像フォルダ")
    p.add_argument("--output", required=True, help="出力CSVパス")
    p.add_argument(
        "--default-condition",
        default="near_mint",
        choices=sorted(VALID_CONDITIONS),
        help="サブフォルダで分類されていない画像に適用する状態",
    )
    p.add_argument(
        "--include-low-rarity",
        action="store_true",
        help="コモン等の低レアリティも出品候補に含める（既定では除外、ただし特殊variantは常に処理）",
    )
    args = p.parse_args()

    items = collect_images(args.input, args.default_condition)
    if not items:
        print("no images found", file=sys.stderr)
        sys.exit(2)
    print(f"{len(items)} image(s) found")

    rows = []
    skip_low = not args.include_low_rarity
    for i, (img, cond) in enumerate(items, 1):
        print(f"[{i}/{len(items)}] {img.name} ({cond}) ...", end=" ")
        row = process_one(img, cond, skip_low_rarity=skip_low)
        rows.append(row)
        print(row["status"])

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "image", "condition", "card_id", "variant_type", "title",
                "title_length", "description", "description_length", "status",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    ok = sum(1 for r in rows if r["status"].startswith("ok"))
    print(f"Wrote {out} ({ok}/{len(rows)} succeeded)")


if __name__ == "__main__":
    main()
