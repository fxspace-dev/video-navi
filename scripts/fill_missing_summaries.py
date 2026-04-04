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


def generate_summary(title, transcript):
    context = transcript[:8000] if transcript else f"(字幕なし) タイトル: {title}"

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

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 256},
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
        return result.get("summary", "")
    except Exception as e:
        print(f"  WARNING: Gemini error: {e}", file=sys.stderr)
        return ""


def main():
    if not GEMINI_API_KEY:
        sys.exit("ERROR: Set GEMINI_API_KEY environment variable")

    videos, rest = read_videos_js()
    missing = [(i, v) for i, v in enumerate(videos) if not v.get("summary", "").strip()]
    print(f"要約なし: {len(missing)}件 / 全{len(videos)}件")

    if not missing:
        print("すべての動画に要約があります。")
        return

    updated = 0
    for count, (idx, video) in enumerate(missing, 1):
        title = video["title"]
        vid_id = video.get("vid_id", "")
        print(f"[{count}/{len(missing)}] {title}")

        try:
            transcript = get_transcript(vid_id) if vid_id else None
            if transcript:
                print(f"  字幕: {len(transcript)}文字")
            else:
                print("  字幕なし（タイトルから要約生成）")

            summary = generate_summary(title, transcript)
            if summary:
                videos[idx]["summary"] = summary
                print(f"  要約: {summary}")
                updated += 1
            else:
                print("  要約生成失敗（スキップ）")
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
