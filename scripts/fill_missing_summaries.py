"""
Fill missing summaries for existing videos using Gemini API.
One-time script: run locally or via GitHub Actions.
"""

import json
import os
import re
import sys
import time

import requests
from youtube_transcript_api import YouTubeTranscriptApi

VIDEOS_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "videos.js")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

EXISTING_CATEGORIES = [
    "手法", "基礎", "リアルトレード", "雑談", "メンタル", "実践",
    "資金管理", "プロップファーム", "シナリオ", "実績", "企画",
    "インタビュー", "トレード環境", "ゼロプロ(旧プレアストロ)", "過去検証",
    "YTT", "相場", "税金", "インジケーター", "ライン", "チャートパターン",
    "その他手法", "プライスアクション", "ナウキャスト", "あるある", "CFD",
    "損切", "大会", "コミュニティ", "SIRIUS",
]
LEVEL_OPTIONS = ["超初心者", "初心者", "中級", "上級"]


def read_videos_js():
    with open(VIDEOS_JS_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    match = re.search(r"const\s+VIDEOS\s*=\s*(\[.*?\n\]);", text, re.DOTALL)
    if not match:
        sys.exit("ERROR: Could not parse videos.js")
    rest = text[match.end():]
    return json.loads(match.group(1)), rest


def write_videos_js(videos, rest):
    json_str = json.dumps(videos, indent=2, ensure_ascii=False)
    with open(VIDEOS_JS_PATH, "w", encoding="utf-8") as f:
        f.write(f"const VIDEOS = {json_str};{rest}")


def get_transcript(video_id):
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        for method in ("find_transcript", "find_generated_transcript"):
            try:
                tr = getattr(transcript_list, method)(["ja"])
                parts = tr.fetch()
                return " ".join(entry["text"] for entry in parts)
            except Exception:
                continue
        return None
    except Exception:
        return None


def generate_metadata(title, transcript, need_full):
    """
    need_full=True: summary + levels + categories を生成
    need_full=False: summary のみ
    """
    context = transcript[:8000] if transcript else f"(字幕なし) タイトル: {title}"

    if need_full:
        prompt = f"""あなたはFXトレード教育チャンネル「@fxyosuga」の動画メタデータを生成するアシスタントです。

以下の動画情報を基に、JSON形式でメタデータを生成してください。

## 動画タイトル
{title}

## 動画の内容（字幕テキスト）
{context}

## 出力フォーマット（JSONのみ、他のテキストなし）
{{
  "summary": "動画の内容を1〜2文で要約（日本語）",
  "levels": ["該当するレベルを配列で"],
  "categories": ["該当するカテゴリを配列で"]
}}

## レベル選択肢（1つ以上選択）
{", ".join(LEVEL_OPTIONS)}

## 既存カテゴリ一覧（できるだけここから選択。該当なしの場合は新しいカテゴリを作成可）
{", ".join(EXISTING_CATEGORIES)}

## 注意
- summaryは「〜を解説している」「〜について紹介している」のような体言止めの文体
- levelsは対象視聴者のレベル（複数可）
- categoriesは動画の主題に合うもの（1〜3個）
- JSONのみ出力（マークダウンのコードブロックなし）"""
    else:
        prompt = f"""あなたはFXトレード教育チャンネル「@fxyosuga」の動画メタデータを生成するアシスタントです。

以下の動画情報を基に、動画の要約を1〜2文で生成してください。

## 動画タイトル
{title}

## 動画の内容（字幕テキスト）
{context}

## 注意
- 「〜を解説している」「〜について紹介している」のような体言止めの文体
- JSONのみ出力: {{"summary": "要約文"}}
- マークダウンのコードブロックなし"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512 if need_full else 256},
    }

    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 429 and attempt < max_retries:
                # レスポンスから retryDelay を取得
                delay_sec = 30  # デフォルト
                try:
                    err_data = resp.json()
                    for detail in err_data.get("error", {}).get("details", []):
                        if "retryDelay" in detail:
                            m = re.match(r"(\d+)", detail["retryDelay"])
                            if m:
                                delay_sec = int(m.group(1)) + 3
                                break
                except Exception:
                    pass
                print(f"  429: retry_delay={delay_sec}s 待機中... (attempt {attempt+1}/{max_retries})", file=sys.stderr)
                time.sleep(delay_sec)
                continue
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return json.loads(text)
        except Exception as e:
            if attempt == max_retries:
                print(f"  WARNING: Gemini error (最終): {e}", file=sys.stderr)
                return {}
            # 429以外の例外は短く待ってリトライ
            time.sleep(5)
    return {}


def main():
    if not GEMINI_API_KEY:
        sys.exit("ERROR: Set GEMINI_API_KEY environment variable")

    videos, rest = read_videos_js()
    # 対象: 要約が空 OR categories が ["未分類"]（update_videos.py のフォールバック値）
    def needs_fix(v):
        no_summary = not v.get("summary", "").strip()
        unclassified = v.get("categories") == ["未分類"]
        return no_summary or unclassified

    missing = [(i, v) for i, v in enumerate(videos) if needs_fix(v)]
    print(f"要約/カテゴリ補完対象: {len(missing)}件 / 全{len(videos)}件")

    if not missing:
        print("すべての動画に要約とカテゴリがあります。")
        return

    updated = 0
    for count, (idx, video) in enumerate(missing, 1):
        title = video["title"]
        vid_id = video.get("vid_id", "")
        # ["未分類"] の場合は levels/categories も再生成
        need_full = video.get("categories") == ["未分類"]
        print(f"[{count}/{len(missing)}] {title} (full={need_full})")

        try:
            transcript = get_transcript(vid_id) if vid_id else None
            if transcript:
                print(f"  字幕: {len(transcript)}文字")
            else:
                print("  字幕なし（タイトルから生成）")

            result = generate_metadata(title, transcript, need_full)
            changed = False
            if result.get("summary"):
                videos[idx]["summary"] = result["summary"]
                print(f"  要約: {result['summary']}")
                changed = True
            if need_full and result.get("categories"):
                videos[idx]["categories"] = result["categories"]
                print(f"  カテゴリ: {result['categories']}")
                changed = True
            if need_full and result.get("levels"):
                videos[idx]["levels"] = result["levels"]
                print(f"  レベル: {result['levels']}")
                changed = True
            if changed:
                updated += 1
            else:
                print("  生成失敗（スキップ）")
        except Exception as e:
            print(f"  エラー（スキップ）: {e}")

        # Gemini無料枠: 15RPM なので安全に5秒待つ
        time.sleep(5)

        # 10件ごとに中間保存
        if updated > 0 and updated % 10 == 0:
            write_videos_js(videos, rest)
            print(f"  (中間保存: {updated}件)")

    write_videos_js(videos, rest)
    print(f"\n完了: {updated}件の要約を追加しました")


if __name__ == "__main__":
    main()
