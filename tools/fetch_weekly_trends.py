"""
週次トレンドフェッチャー。
- ポケモンカード公式サイトから新弾・お知らせを収集
- メルカリ「ポケカ」検索の売り切れ上位タイトルを収集
- OpenAI GPT-4o mini で100文字程度に要約
- data/weekly_trends.json に保存

タスクスケジューラ例:
  schtasks /Create /TN "PokemonTrendFetch" /TR "python C:\\path\\to\\tools\\fetch_weekly_trends.py" /SC WEEKLY /D SUN /ST 00:00

依存: openai （pip install openai）
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
USER_CFG = ROOT / "config" / "user_settings.json"
OUT = ROOT / "data" / "weekly_trends.json"

OFFICIAL_NEWS_URL = "https://www.pokemon-card.com/info.html"
MERCARI_SEARCH_URL = (
    "https://api.mercari.jp/v2/entities:search"
)
MERCARI_WEB_FALLBACK = (
    "https://jp.mercari.com/search?keyword=%E3%83%9D%E3%82%B1%E3%82%AB&status=sold_out&order=desc&sort=created_time"
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SUMMARY_TARGET_CHARS = 100
RETRY = 2


def http_get(url, timeout=15):
    last = None
    for i in range(RETRY):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
            with urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET failed: {url} ({last})")


def strip_html(html):
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_official_news():
    try:
        html = http_get(OFFICIAL_NEWS_URL)
    except Exception as e:
        print(f"  ! official news fetch failed: {e}", file=sys.stderr)
        return []
    items = re.findall(
        r'<li[^>]*class="[^"]*Article[^"]*"[\s\S]*?</li>', html, flags=re.I
    )
    if not items:
        body = strip_html(html)
        return [body[:600]] if body else []
    return [strip_html(it)[:300] for it in items[:8]]


def fetch_mercari_titles():
    try:
        html = http_get(MERCARI_WEB_FALLBACK)
    except Exception as e:
        print(f"  ! mercari fetch failed: {e}", file=sys.stderr)
        return []
    titles = re.findall(r'aria-label="([^"]+の画像)"', html)
    titles = [t.replace("の画像", "") for t in titles]
    if not titles:
        titles = re.findall(r'<title>([^<]+)</title>', html)
    return titles[:30]


def summarize_with_openai(official_items, mercari_titles, cfg):
    api_key = cfg.get("openai_api_key", "").strip()
    if not api_key:
        return rule_based_summary(official_items, mercari_titles)
    try:
        from openai import OpenAI
    except ImportError:
        print("  ! openai package not installed; using rule-based summary", file=sys.stderr)
        return rule_based_summary(official_items, mercari_titles)

    client = OpenAI(api_key=api_key)
    model = cfg.get("openai_model", "gpt-4o-mini")

    prompt = (
        "あなたはポケモンカードのトレンドをメルカリ出品文用にまとめるアシスタントです。\n"
        "以下の情報源から、今週注目すべきポケモンカード関連のトピックを"
        f"日本語で{SUMMARY_TARGET_CHARS}文字以内（最大でも120文字）にまとめてください。\n"
        "・購入意欲を高める言い回しで、ハッシュタグは付けない。\n"
        "・新弾・人気カード・需要のあるパックを優先。\n\n"
        f"[公式お知らせ]\n{chr(10).join('・'+x for x in official_items[:8])}\n\n"
        f"[メルカリ売れ筋タイトル]\n{chr(10).join('・'+x for x in mercari_titles[:20])}"
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
        )
        text = resp.choices[0].message.content.strip()
        if len(text) > 120:
            text = text[:119] + "…"
        return text
    except Exception as e:
        print(f"  ! OpenAI API failed: {e}", file=sys.stderr)
        return rule_based_summary(official_items, mercari_titles)


def rule_based_summary(official_items, mercari_titles):
    parts = []
    if official_items:
        first = official_items[0][:60]
        parts.append(f"公式: {first}")
    if mercari_titles:
        top = mercari_titles[0][:40]
        parts.append(f"人気: {top}")
    if not parts:
        return "今週も多彩なポケカが注目を集めています。コレクションにぜひ。"
    text = " / ".join(parts)
    return text[:120]


def main():
    cfg = json.loads(USER_CFG.read_text(encoding="utf-8")) if USER_CFG.exists() else {}

    print("Fetching official news...")
    official = fetch_official_news()
    print(f"  got {len(official)} items")

    print("Fetching mercari sold listings...")
    mercari = fetch_mercari_titles()
    print(f"  got {len(mercari)} titles")

    print("Summarizing...")
    summary = summarize_with_openai(official, mercari, cfg)
    print(f"  -> {summary}")

    payload = {
        "summary": summary,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "official_count": len(official),
            "mercari_count": len(mercari),
        },
        "raw": {
            "official": official[:8],
            "mercari": mercari[:20],
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
