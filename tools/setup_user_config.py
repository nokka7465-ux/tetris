"""
ユーザー設定の対話CLI。
config/user_settings.json に保存。再実行で既存値が初期値として表示される。

使い方:
  python tools/setup_user_config.py          # 全項目を順に確認
  python tools/setup_user_config.py --show   # 現在の設定を表示するだけ
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "user_settings.json"

DEFAULTS = {
    "smoking": "no",
    "pets": "no",
    "shipping_method": "らくらくメルカリ便（ネコポス）",
    "shipping_days": "1〜2日で発送",
    "instant_buy_ok": True,
    "greeting": "ご覧いただきありがとうございます。",
    "return_policy": "ノークレーム・ノーリターンでお願いいたします。",
    "condition_default_text": "開封後すぐスリーブに入れて保管しています。初期傷等はご了承ください。",
    "shipping_default_text": "スリーブ＋折れ対策＋防水で発送いたします。",
    "ocr_method": "pytesseract",
    "tesseract_path": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
}

PROMPTS = [
    ("smoking", "喫煙環境ですか？ (yes/no)", ["yes", "no"]),
    ("pets", "ペットはいますか？ (yes/no)", ["yes", "no"]),
    ("shipping_method", "発送方法", None),
    ("shipping_days", "発送日数の表記", None),
    ("instant_buy_ok", "即購入OK？ (yes/no)", ["yes", "no"]),
    ("greeting", "挨拶文", None),
    ("return_policy", "返品ポリシー文", None),
    ("condition_default_text", "状態説明の定型文", None),
    ("shipping_default_text", "発送・梱包の定型文", None),
    ("ocr_method", "OCR方式 (pytesseract / openai_vision / none)",
     ["pytesseract", "openai_vision", "none"]),
    ("tesseract_path", "Tesseractの実行パス（pytesseract使用時のみ）", None),
    ("openai_api_key", "OpenAI APIキー（週次トレンド要約・openai_vision用）", None),
    ("openai_model", "OpenAIモデル", None),
]


def load_existing():
    if CONFIG_FILE.exists():
        try:
            return {**DEFAULTS, **json.loads(CONFIG_FILE.read_text(encoding="utf-8"))}
        except Exception:
            pass
    return dict(DEFAULTS)


def to_bool(s):
    return str(s).strip().lower() in ("yes", "y", "true", "1", "ok")


def ask(prompt, current, choices):
    shown = "yes" if current is True else ("no" if current is False else current)
    suffix = f" [現在: {shown}]" if shown != "" else " [未設定]"
    while True:
        ans = input(f"{prompt}{suffix}\n> ").strip()
        if ans == "":
            return current
        if choices and ans not in choices:
            print(f"  {choices} のいずれかで入力してください")
            continue
        return ans


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--show", action="store_true", help="現在の設定を表示するだけ")
    args = p.parse_args()

    cfg = load_existing()

    if args.show:
        masked = dict(cfg)
        if masked.get("openai_api_key"):
            k = masked["openai_api_key"]
            masked["openai_api_key"] = k[:6] + "..." + k[-4:] if len(k) > 12 else "***"
        print(json.dumps(masked, ensure_ascii=False, indent=2))
        return

    print("=== ユーザー設定（Enterで現在値を維持） ===\n")
    for key, prompt, choices in PROMPTS:
        new_val = ask(prompt, cfg.get(key, ""), choices)
        if key in ("instant_buy_ok",):
            cfg[key] = to_bool(new_val) if not isinstance(new_val, bool) else new_val
        else:
            cfg[key] = new_val
        print()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"保存しました: {CONFIG_FILE}")


if __name__ == "__main__":
    main()
