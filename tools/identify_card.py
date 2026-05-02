"""
カード画像→card_id特定モジュール。
OCRで右下の型番（例: "056/190" + パック略号）を読み取り、cards_master を検索。

依存（pytesseract方式）:
  pip install pillow pytesseract
  Tesseract OCR本体: https://github.com/UB-Mannheim/tesseract/wiki

使い方:
  python tools/identify_card.py --image path/to/card.jpg
  → {"card_id": "SV4a-056", "confidence": "high", "matched_by": "ocr_number+set"}
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "cards_master.db"
USER_CFG = ROOT / "config" / "user_settings.json"

NUMBER_PATTERN = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})")
SET_CODE_PATTERN = re.compile(r"\b([A-Za-z]{1,4}\d{1,2}[a-z]?)\b")

VARIANT_LABELS = {
    "standard": "通常版",
    "masterball_mirror": "マスターボールミラー",
    "pokeball_mirror": "モンスターボールミラー",
}


def load_cfg():
    if USER_CFG.exists():
        return json.loads(USER_CFG.read_text(encoding="utf-8"))
    return {}


def ocr_image(image_path, cfg):
    method = cfg.get("ocr_method", "pytesseract")

    if method == "pytesseract":
        return ocr_pytesseract(image_path, cfg)
    if method == "openai_vision":
        return ocr_openai_vision(image_path, cfg)
    raise RuntimeError(f"OCR method '{method}' is disabled or unknown.")


def ocr_pytesseract(image_path, cfg):
    try:
        from PIL import Image
        import pytesseract
    except ImportError as e:
        raise RuntimeError(
            "pillow / pytesseract がインストールされていません。"
            "pip install pillow pytesseract"
        ) from e

    tess_path = cfg.get("tesseract_path")
    if tess_path and Path(tess_path).exists():
        pytesseract.pytesseract.tesseract_cmd = tess_path

    img = Image.open(image_path)
    w, h = img.size
    bottom_right = img.crop((int(w * 0.55), int(h * 0.85), w, h))
    text_full = pytesseract.image_to_string(img, lang="eng+jpn")
    text_corner = pytesseract.image_to_string(bottom_right, lang="eng")
    return text_full + "\n" + text_corner


def ocr_openai_vision(image_path, cfg):
    api_key = cfg.get("openai_api_key", "").strip()
    if not api_key:
        raise RuntimeError("openai_api_key が未設定です（user_settings.json）")
    try:
        import base64
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai パッケージが必要です: pip install openai") from e

    client = OpenAI(api_key=api_key)
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    resp = client.chat.completions.create(
        model=cfg.get("openai_model", "gpt-4o-mini"),
        messages=[{
            "role": "user",
            "content": [
                {"type": "text",
                 "text": "このポケモンカード画像から右下の型番（例: 056/190）と"
                         "パック略号（例: SV4a）を抽出し、'NUMBER: xxx/yyy SET: ZZZ' "
                         "形式で1行だけ返してください。"},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        max_tokens=80,
    )
    return resp.choices[0].message.content


def detect_variant_via_vision(image_path, cfg):
    """
    画像から特殊variantを判定: standard / masterball_mirror / pokeball_mirror
    背景全体のホロパターンを判定材料にする。
    """
    api_key = cfg.get("openai_api_key", "").strip()
    if not api_key:
        return "standard"
    try:
        import base64
        from openai import OpenAI
    except ImportError:
        return "standard"

    client = OpenAI(api_key=api_key)
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    prompt = (
        "このポケモンカードの背景ホロパターンを判定してください。\n"
        "次のいずれか1つだけ返答（他の語は付けない）:\n"
        "- masterball_mirror : 背景全体に紫色のマスターボール柄（M字マーク）のホロが入っている\n"
        "- pokeball_mirror   : 背景全体に赤白のモンスターボール柄のホロが入っている\n"
        "- standard          : 上記いずれでもない通常背景\n"
    )
    try:
        resp = client.chat.completions.create(
            model=cfg.get("openai_model", "gpt-4o-mini"),
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=20,
            temperature=0,
        )
        out = (resp.choices[0].message.content or "").strip().lower()
        for token in ("masterball_mirror", "pokeball_mirror", "standard"):
            if token in out:
                return token
        return "standard"
    except Exception as e:
        print(f"  ! variant detection failed: {e}", file=sys.stderr)
        return "standard"


def parse_ocr(text):
    number_match = NUMBER_PATTERN.search(text)
    card_number = None
    if number_match:
        card_number = f"{number_match.group(1).zfill(3)}/{number_match.group(2)}"

    set_codes = SET_CODE_PATTERN.findall(text)
    set_code = None
    for code in set_codes:
        if code.lower().startswith(("sv", "sm", "xy", "bw", "s", "sa", "pm")) and any(c.isdigit() for c in code):
            set_code = code
            break
    if not set_code and set_codes:
        set_code = set_codes[0]

    return {"card_number": card_number, "set_code": set_code}


def lookup(card_number, set_code):
    if not DB.exists():
        raise FileNotFoundError(f"DB not found: {DB}")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    if card_number and set_code:
        rows = conn.execute(
            "SELECT * FROM cards_master WHERE card_number = ? AND set_code = ? "
            "AND variant_type = 'standard' COLLATE NOCASE",
            (card_number, set_code),
        ).fetchall()
        if len(rows) == 1:
            conn.close()
            return dict(rows[0]), "high", "ocr_number+set"
        if len(rows) > 1:
            conn.close()
            return dict(rows[0]), "medium", "ocr_number+set (multi)"

    if card_number:
        rows = conn.execute(
            "SELECT * FROM cards_master WHERE card_number = ? AND variant_type = 'standard'",
            (card_number,),
        ).fetchall()
        if len(rows) == 1:
            conn.close()
            return dict(rows[0]), "medium", "ocr_number_only"

    conn.close()
    return None, "low", "no_match"


def ensure_variant_row(base_card, variant_type):
    """variant_type のレコードが無ければ、baseをコピーして作成。"""
    if variant_type == "standard" or not base_card:
        return base_card
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    existing = conn.execute(
        "SELECT * FROM cards_master WHERE card_id = ? AND variant_type = ?",
        (base_card["card_id"], variant_type),
    ).fetchone()
    if existing:
        conn.close()
        return dict(existing)

    new = dict(base_card)
    new["variant_type"] = variant_type
    new["rarity_estimated"] = "high"
    new["rarity"] = base_card.get("rarity") or VARIANT_LABELS.get(variant_type)

    cols = list(new.keys())
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO cards_master ({', '.join(cols)}) VALUES ({placeholders})",
        [new[c] for c in cols],
    )
    conn.commit()
    conn.close()
    return new


def identify(image_path, detect_variant=True):
    cfg = load_cfg()
    raw = ocr_image(image_path, cfg)
    parsed = parse_ocr(raw)
    card, conf, how = lookup(parsed["card_number"], parsed["set_code"])

    variant = "standard"
    if detect_variant and card and cfg.get("ocr_method") != "none":
        variant = detect_variant_via_vision(image_path, cfg)
        if variant != "standard":
            card = ensure_variant_row(card, variant)

    return {
        "card_id": card.get("card_id") if card else None,
        "variant_type": variant,
        "variant_label": VARIANT_LABELS.get(variant, variant),
        "name": card.get("name") if card else None,
        "set_code": card.get("set_code") if card else parsed["set_code"],
        "card_number": card.get("card_number") if card else parsed["card_number"],
        "rarity_estimated": card.get("rarity_estimated") if card else None,
        "confidence": conf,
        "matched_by": how,
        "ocr_excerpt": raw[:200],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True)
    args = p.parse_args()
    if not Path(args.image).exists():
        print(f"image not found: {args.image}", file=sys.stderr)
        sys.exit(2)
    result = identify(args.image)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
