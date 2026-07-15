"""
既存動画のテーマ(categories)を付け直して精度を上げる。

- 字幕は取得しない（タイトル＋既存の要約から判定 → 高速・IPブロックなし）。
- Gemini で内容テーマ＋形式カテゴリを再判定し、
  さらにタイトルベースの高信頼ルールで形式カテゴリ（インタビュー等）を補強する。
- cat_v2 フラグで再実行時は処理済みをスキップ（レジューム可能）。
- 429(日次クォータ)で止まっても、それまでの結果は保存される。

環境変数:
  RECAT_BATCH: 1回で処理する最大件数（既定 400）
  RECAT_FORCE: 1 で cat_v2 を無視して全件やり直し
"""

import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from fill_missing_summaries import (
    EXISTING_CATEGORIES,
    CATEGORY_GUIDE,
    LEVEL_OPTIONS,
    read_videos_js,
    write_videos_js,
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BATCH = int(os.environ.get("RECAT_BATCH", "400"))
FORCE = os.environ.get("RECAT_FORCE", "0").lower() in ("1", "true")


# タイトル/要約からの高信頼ルール（Geminiの取りこぼしを補強する。追加のみ・削除しない）
def rule_based_categories(title: str, summary: str) -> set:
    t = title or ""
    s = summary or ""
    both = t + " " + s
    cats = set()

    def has(*keys, src=t):
        return any(k in src for k in keys)

    # 形式（主にタイトルで判定＝高精度）
    # インタビュー: 本人登場の対話回のみ。暴露・対決・解説回への誤付与を避ける。
    # 強い合図(インタビュー/対談/ゲスト/密着)は常に採用。弱い合図(〜に聞く等)は
    # 暴露・対決・「〜の真実」等の解説マーカーが無いときだけ採用する。
    if has("インタビュー", "対談", "ゲスト", "密着") or (
        has("に聞く", "に全部聞く", "聞いてみた", "会ったら", "会ってきた", "対話")
        and not has("暴露", "対決", "追及", "の真実", "事例")
    ):
        cats.add("インタビュー")
    if has("リアルトレード", "お手本トレード", "今週の全", "今週のトレード", "実況"):
        cats.add("リアルトレード")
    if has("あるある"):
        cats.add("あるある")
    if has("大会", "コンテスト", "トーナメント"):
        cats.add("大会")
    if re.search(r"[\+＋]\d|\d+\s*%|\d+万円|\d+pips", t) or has("成績", "結果報告", "達成", "実績"):
        cats.add("実績")

    # 内容テーマ（タイトル＋要約で判定）
    if has("Fintokei", "Fundora", "FTO", "プロップ", "MyForex", "プロップファーム", src=both):
        cats.add("プロップファーム")
    if has("税金", "確定申告", "税理士", src=both):
        cats.add("税金")
    if has("YTT", src=both):
        cats.add("YTT")
    if has("損切", src=both):
        cats.add("損切")
    if has("ナウキャスト", "ダウ理論", "ダウ手法", src=both):
        cats.add("ナウキャスト")
    if has("ライン", "水平線", "トレンドライン", src=both):
        cats.add("ライン")
    if has("メンタル", "心理", "マインド", "メンタリティ", src=both):
        cats.add("メンタル")
    if has("資金管理", "ロット", "リスクリワード", "資金", src=both):
        cats.add("資金管理")
    if has("過去検証", "過去相場", src=both):
        cats.add("過去検証")
    if has("CFD", src=both):
        cats.add("CFD")
    if has("プライスアクション", src=both):
        cats.add("プライスアクション")
    if has("チャートパターン", "三尊", "逆三尊", "ダブルトップ", "ダブルボトム", src=both):
        cats.add("チャートパターン")

    # 既存カテゴリに存在するものだけ採用
    return {c for c in cats if c in EXISTING_CATEGORIES}


def gemini_categories(title: str, summary: str):
    """タイトル＋要約から categories と levels を再判定。失敗時 None、日次枯渇時 'QUOTA'。"""
    prompt = f"""あなたはFXトレード教育チャンネル「@fxyosuga」の動画メタデータを付け直すアシスタントです。
タイトルと要約から、テーマ(categories)と対象レベル(levels)を判定してください。

## 動画タイトル
{title}

## 要約
{summary or "(要約なし)"}

## 既存カテゴリ一覧（原則ここから選ぶ）
{", ".join(EXISTING_CATEGORIES)}

## レベル選択肢
{", ".join(LEVEL_OPTIONS)}

{CATEGORY_GUIDE}

## 出力（JSONのみ、マークダウン禁止）
{{"categories": ["内容テーマと形式の両面から該当を全て(通常2〜4個)"], "levels": ["対象レベル(1つ以上)"]}}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}],
               "generationConfig": {"temperature": 0.1, "maxOutputTokens": 256}}
    for attempt in range(6):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 429:
                delay = 30
                daily = False
                try:
                    for d in resp.json().get("error", {}).get("details", []):
                        m = re.match(r"(\d+)", str(d.get("retryDelay", "")))
                        if m:
                            delay = int(m.group(1)) + 3
                        if d.get("reason") == "RATE_LIMIT_EXCEEDED" and delay > 300:
                            daily = True
                except Exception:
                    pass
                if daily:
                    return "QUOTA"
                if attempt < 5:
                    time.sleep(delay)
                    continue
                return None
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return json.loads(text)
        except Exception:
            if attempt >= 5:
                return None
            time.sleep(4)
    return None


def main():
    if not GEMINI_API_KEY:
        sys.exit("ERROR: Set GEMINI_API_KEY")
    videos, rest = read_videos_js()

    targets = [
        (i, v) for i, v in enumerate(videos)
        if not v.get("is_short", False) and (FORCE or not v.get("cat_v2"))
    ]
    total = len(targets)
    targets = targets[:BATCH]
    print(f"再カテゴライズ対象: 残り{total}件中 今回{len(targets)}件")

    changed = 0
    processed = 0
    for i, v in targets:
        title = v.get("title", "")
        summary = v.get("summary", "")
        g = gemini_categories(title, summary)
        if g == "QUOTA":
            print("日次クォータ枯渇。ここまでを保存して終了します。", file=sys.stderr)
            break

        old = set(v.get("categories") or [])
        new = set()
        if isinstance(g, dict) and g.get("categories"):
            # 既存カテゴリのみ採用（新カテゴリの氾濫を防ぐ）
            new = {c for c in g["categories"] if c in EXISTING_CATEGORIES}
            if g.get("levels"):
                lv = [l for l in g["levels"] if l in LEVEL_OPTIONS]
                if lv:
                    v["levels"] = lv
        else:
            new = set(old)  # Gemini失敗時は既存維持

        # ルールベースの形式カテゴリで補強
        new |= rule_based_categories(title, summary)
        new = {c for c in new if c} or old or {"未分類"}

        if new != old:
            v["categories"] = sorted(new, key=lambda c: (c not in old, c))
            changed += 1
            print(f"  {sorted(old)} -> {sorted(new)} | {title[:34]}")
        v["cat_v2"] = True
        processed += 1
        # 途中経過をこまめに保存（クォータ切れ・中断に備える）
        if processed % 20 == 0:
            write_videos_js(videos, rest)

    write_videos_js(videos, rest)
    print(f"{processed}件処理、{changed}件のカテゴリを更新（残り{total - processed}件）")


if __name__ == "__main__":
    main()
