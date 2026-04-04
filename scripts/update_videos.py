"""
Fetch latest videos from @fxyosuga YouTube channel,
generate metadata via Claude API, and update videos.js.
"""

import json
import os
import re
import sys
from datetime import datetime

import anthropic
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CHANNEL_HANDLE = "@fxyosuga"
VIDEOS_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "videos.js")

EXISTING_CATEGORIES = [
    "手法", "基礎", "リアルトレード", "雑談", "メンタル", "実践",
    "資金管理", "プロップファーム", "シナリオ", "実績", "企画",
    "インタビュー", "トレード環境", "ゼロプロ(旧プレアストロ)", "過去検証",
    "YTT", "相場", "税金", "インジケーター", "ライン", "チャートパターン",
    "その他手法", "プライスアクション", "ナウキャスト", "あるある", "CFD",
    "損切", "大会", "コミュニティ", "SIRIUS",
]

LEVEL_OPTIONS = ["超初心者", "初心者", "中級", "上級"]

# ---------------------------------------------------------------------------
# videos.js I/O
# ---------------------------------------------------------------------------

def read_videos_js() -> tuple[list[dict], str]:
    """Read videos.js and return the VIDEOS array and the rest of the file."""
    with open(VIDEOS_JS_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    # Match VIDEOS array, stopping at "];" (non-greedy)
    match = re.search(r"const\s+VIDEOS\s*=\s*(\[.*?\n\]);", text, re.DOTALL)
    if not match:
        print("ERROR: Could not parse videos.js", file=sys.stderr)
        sys.exit(1)
    # Preserve everything after the VIDEOS array (e.g. ROADMAP)
    rest = text[match.end():]
    return json.loads(match.group(1)), rest


def write_videos_js(videos: list[dict], rest: str) -> None:
    """Write videos list back to videos.js, preserving ROADMAP etc."""
    json_str = json.dumps(videos, indent=2, ensure_ascii=False)
    with open(VIDEOS_JS_PATH, "w", encoding="utf-8") as f:
        f.write(f"const VIDEOS = {json_str};{rest}")


# ---------------------------------------------------------------------------
# YouTube API helpers
# ---------------------------------------------------------------------------

def get_uploads_playlist_id(youtube) -> str:
    """Get the uploads playlist ID for the channel."""
    resp = youtube.channels().list(
        part="contentDetails",
        forHandle=CHANNEL_HANDLE,
    ).execute()
    items = resp.get("items", [])
    if not items:
        print(f"ERROR: Channel {CHANNEL_HANDLE} not found", file=sys.stderr)
        sys.exit(1)
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def fetch_latest_videos(youtube, playlist_id: str, max_results: int = 50) -> list[dict]:
    """Fetch latest videos from the uploads playlist."""
    resp = youtube.playlistItems().list(
        part="snippet",
        playlistId=playlist_id,
        maxResults=max_results,
    ).execute()
    return resp.get("items", [])


# ---------------------------------------------------------------------------
# Transcript helper
# ---------------------------------------------------------------------------

def get_transcript(video_id: str) -> str | None:
    """Try to fetch Japanese transcript for a video."""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # Prefer manually created Japanese, then auto-generated Japanese
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


# ---------------------------------------------------------------------------
# Claude API helper
# ---------------------------------------------------------------------------

def generate_metadata(client: anthropic.Anthropic, title: str, transcript: str | None) -> dict:
    """Use Claude to generate summary, levels, and categories."""
    context = transcript if transcript else f"(字幕なし) タイトル: {title}"

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

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text.strip()
    # Strip markdown code fences if present
    response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
    response_text = re.sub(r"\s*```$", "", response_text)

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        print(f"WARNING: Could not parse Claude response for '{title}'", file=sys.stderr)
        print(f"Response: {response_text}", file=sys.stderr)
        return {
            "summary": title,
            "levels": ["初心者"],
            "categories": ["その他手法"],
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Read existing data
    existing_videos, rest_of_file = read_videos_js()
    existing_ids = {v["vid_id"] for v in existing_videos}
    print(f"Existing videos: {len(existing_videos)}")

    # Fetch from YouTube
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    playlist_id = get_uploads_playlist_id(youtube)
    print(f"Uploads playlist: {playlist_id}")

    latest_items = fetch_latest_videos(youtube, playlist_id, max_results=50)
    print(f"Fetched {len(latest_items)} items from YouTube")

    # Find new videos
    new_videos = []
    for item in latest_items:
        snippet = item["snippet"]
        vid_id = snippet["resourceId"]["videoId"]
        if vid_id in existing_ids:
            continue

        title = snippet["title"]
        published = snippet["publishedAt"][:10]  # YYYY-MM-DD
        print(f"New video: {title} ({vid_id})")

        # Get transcript
        transcript = get_transcript(vid_id)
        if transcript:
            print(f"  Transcript: {len(transcript)} chars")
        else:
            print("  No transcript available")

        # Generate metadata via Claude
        claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        metadata = generate_metadata(claude_client, title, transcript)

        video_entry = {
            "title": title,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
            "thumb": f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg",
            "levels": metadata.get("levels", ["初心者"]),
            "categories": metadata.get("categories", ["その他手法"]),
            "method": "一般公開",
            "summary": metadata.get("summary", title),
            "vid_id": vid_id,
            "date": published,
        }
        new_videos.append(video_entry)

    if not new_videos:
        print("No new videos found. Nothing to update.")
        return

    # Insert new videos at the beginning (newest first)
    # Sort new videos by date descending
    new_videos.sort(key=lambda v: v["date"], reverse=True)
    updated_videos = new_videos + existing_videos

    write_videos_js(updated_videos, rest_of_file)
    print(f"Added {len(new_videos)} new video(s). Total: {len(updated_videos)}")


if __name__ == "__main__":
    main()
