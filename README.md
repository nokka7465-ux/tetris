# pokemoncard-AI

カード画像から **メルカリ出品タイトル＆概要欄** を自動生成するツール群。

## 機能

- TCGdex APIから日本語の全ポケモンカードを取り込み（SQLite）
- カード画像をOCRで識別し `card_id` を特定
- 5層構造の出品文を生成（タイトル40字 / 概要欄500字以内）
- 週1回ポケカトレンドを公式・メルカリから収集 → GPT-4o miniで100字要約
- 複数画像のフォルダ一括処理 → CSV出力

## ディレクトリ

```text
config/user_settings.json     ユーザー設定（喫煙/ペット/発送/挨拶/OCR/OpenAIキー）
data/cards_master.db          SQLite本体
data/weekly_trends.json       週次トレンド要約
mercari/templates.json        5層テンプレート（ヘッダー/レアリティ別本文/状態/発送/フッター）
tools/migrate_db.py           DBマイグレーション（冪等）
tools/fetch_tcgdex.py         TCGdex全件取り込み
tools/setup_user_config.py    設定対話CLI
tools/identify_card.py        画像→card_id 特定（OCR）
tools/generate_listing.py     card_id→タイトル＆概要欄生成
tools/fetch_weekly_trends.py  週次トレンド収集（タスクスケジューラ用）
tools/batch_listing.py        複数画像→CSV一括処理
```

## セットアップ

```bash
pip install pillow pytesseract openai
python tools/migrate_db.py
python tools/setup_user_config.py
python tools/fetch_tcgdex.py --fast        # 高速版（HP/技なし）
# python tools/fetch_tcgdex.py             # 詳細版（時間かかる）
```

Tesseract OCR本体: <https://github.com/UB-Mannheim/tesseract/wiki>

## 使い方

### 単発の出品文生成（手動でcard_id指定）

```bash
python tools/generate_listing.py --card-id SV4a-056 --condition near_mint
```

### 画像から識別 → 出品文

```bash
python tools/identify_card.py --image path/to/card.jpg
python tools/generate_listing.py --card-id <出力されたcard_id> --condition mint
```

### 一括処理

```text
data/inbox/
  mint/        <- 美品の画像をここに
  near_mint/
  excellent/
  played/
```

```bash
python tools/batch_listing.py --input data/inbox --output data/listings_batch.csv
```

### 週次トレンド（タスクスケジューラ）

```cmd
schtasks /Create /TN "PokemonTrendFetch" ^
  /TR "python C:\Users\nkmrkit\Documents\pokemoncard-AI\tools\fetch_weekly_trends.py" ^
  /SC WEEKLY /D SUN /ST 00:00
```

## DBスキーマ

- `cards_master`: カード情報（HP/タイプ/技/特性/画像URL等）
  - 主キー: `(card_id, variant_type)` ← 同じカードの通常版/マスボミラー/モンボミラーを別レコードで保持
  - `rarity_estimated`: `low`（コモン〜RR枠） / `high`（SR/AR/SAR等の特殊枠）。番号と公式総数から推定
  - `variant_type`: `standard` / `masterball_mirror` / `pokeball_mirror`
- `collection`: 所持カード（状態・購入価格・購入日）
- `listings`: 出品履歴（タイトル/概要/価格/利益）

## レアリティ自動フィルタ

`batch_listing.py` は既定で **「standard」かつ「rarity_estimated=low」のカード（コモン枠）はスキップ** します。
特殊variant（マスターボール/モンスターボールミラー）は常に処理対象。

低レアリティも含めたい場合: `--include-low-rarity` を付与。

## マスターボール/モンスターボールミラーの判定

OpenAI Vision (`gpt-4o-mini`) でカード画像の背景ホロパターンを判定し、
特殊variantが見つかれば `cards_master` に新variantレコードを作成（ベースカードからコピー）。
判定にはOpenAI APIキーが必要（`config/user_settings.json` に保存）。
