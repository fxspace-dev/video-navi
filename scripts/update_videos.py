"""
Fetch latest videos from @fxyosuga YouTube channel,
generate metadata via Gemini API, and update videos.js.

重要: 新規動画には必ず is_short / duration / url / thumb をセットする。
Shorts判定は youtube.com/shorts/{vid_id} への HEAD リクエストで行う
(これが唯一確実な方法。YouTube Data API の uploads playlist からは
Shortsも通常動画も区別なく /watch?v= 形式で返ってくる)。
"""

import json
import os
import re
import sys
from datetime import datetime

import requests
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", YOUTUBE_API_KEY)
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

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
}

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


def fetch_video_details(youtube, video_ids: list[str]) -> dict[str, dict]:
    """
    Batch-fetch content details (duration) and snippet (liveBroadcastContent)
    for a list of video IDs. Returns {vid_id: {duration_sec, is_live}}.
    """
    if not video_ids:
        return {}

    result: dict[str, dict] = {}
    # videos.list supports up to 50 IDs per request
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(
            part="contentDetails,snippet,liveStreamingDetails",
            id=",".join(batch),
        ).execute()
        for item in resp.get("items", []):
            vid = item["id"]
            iso_duration = item.get("contentDetails", {}).get("duration", "PT0S")
            duration_sec = iso8601_duration_to_seconds(iso_duration)
            snippet = item.get("snippet", {})
            live_broadcast_content = snippet.get("liveBroadcastContent", "none")
            has_live_details = "liveStreamingDetails" in item
            result[vid] = {
                "duration_sec": duration_sec,
                "is_live_broadcast": live_broadcast_content in ("live", "upcoming") or has_live_details,
            }
    return result


def iso8601_duration_to_seconds(iso: str) -> int:
    """Parse ISO 8601 duration (e.g., PT1H2M3S) into total seconds."""
    match = re.match(
        r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$",
        iso or "PT0S",
    )
    if not match:
        return 0
    h, m, s = match.groups()
    return int(h or 0) * 3600 + int(m or 0) * 60 + int(s or 0)


def is_youtube_short(vid_id: str) -> bool:
    """
    Determine if a video is a YouTube Short by checking the /shorts/{vid_id} URL.

    - Status 200 → it's a Short
    - Status 303/302 (redirect to /watch) → it's a regular video

    This is the only 100% reliable method because YouTube Data API does not
    expose a "this is a short" flag, and duration alone is insufficient
    (Shorts can be up to 180 seconds, but regular videos can also be <180s).
    """
    url = f"https://www.youtube.com/shorts/{vid_id}"
    try:
        resp = requests.head(
            url,
            headers=REQUEST_HEADERS,
            allow_redirects=False,
            timeout=15,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (301, 302, 303, 307, 308):
            # If the redirect target keeps /shorts/ in the path, it's still a short.
            # Normally YouTube redirects non-shorts to /watch?v=...
            location = resp.headers.get("Location", "")
            if "/shorts/" in location:
                return True
            return False
        # Fallback for unexpected status: assume not short
        print(
            f"  WARNING: unexpected HEAD status {resp.status_code} for {url}",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        print(
            f"  WARNING: HEAD request failed for {url}: {e}. "
            "Falling back to GET request.",
            file=sys.stderr,
        )
        # HEAD sometimes fails; fall back to a lightweight GET.
        try:
            resp = requests.get(
                url,
                headers=REQUEST_HEADERS,
                allow_redirects=False,
                timeout=15,
            )
            if resp.status_code == 200:
                return True
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                return "/shorts/" in location
            return False
        except Exception as e2:
            print(
                f"  ERROR: GET fallback also failed: {e2}. "
                "Cannot determine Shorts status — aborting to prevent misclassification.",
                file=sys.stderr,
            )
            raise


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
# Gemini API helper
# ---------------------------------------------------------------------------

def generate_metadata(title: str, transcript: str | None) -> dict:
    """Use Gemini to generate summary, levels, and categories."""
    context = transcript[:8000] if transcript else f"(字幕なし) タイトル: {title}"

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

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512},
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        response_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        # Strip markdown code fences if present
        response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
        response_text = re.sub(r"\s*```$", "", response_text)
        return json.loads(response_text)
    except Exception as e:
        print(f"WARNING: Gemini API error for '{title}': {e}", file=sys.stderr)
        return {
            "summary": "",
            "levels": ["初心者"],
            "categories": ["未分類"],
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = ("title", "url", "thumb", "vid_id", "date", "is_short", "duration")


def validate_entry(entry: dict) -> None:
    """
    Ensure every new video entry has all required fields.
    Abort the whole script if any field is missing — we would rather fail loudly
    than silently emit misclassified data.
    """
    missing = [f for f in REQUIRED_FIELDS if f not in entry or entry[f] is None]
    if missing:
        raise ValueError(
            f"Video entry is missing required fields {missing}: "
            f"{json.dumps(entry, ensure_ascii=False)}"
        )
    if not isinstance(entry["is_short"], bool):
        raise ValueError(
            f"is_short must be bool, got {type(entry['is_short']).__name__}: "
            f"{json.dumps(entry, ensure_ascii=False)}"
        )
    if not isinstance(entry["duration"], int) or entry["duration"] < 0:
        raise ValueError(
            f"duration must be a non-negative int, got {entry['duration']!r}: "
            f"{json.dumps(entry, ensure_ascii=False)}"
        )
    # Consistency check: URLs must match is_short
    if entry["is_short"] and "/shorts/" not in entry["url"]:
        raise ValueError(
            f"is_short=True but url does not contain /shorts/: "
            f"{json.dumps(entry, ensure_ascii=False)}"
        )
    if not entry["is_short"] and "/shorts/" in entry["url"]:
        raise ValueError(
            f"is_short=False but url contains /shorts/: "
            f"{json.dumps(entry, ensure_ascii=False)}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Read existing data
    existing_videos, rest_of_file = read_videos_js()
    existing_ids = {v["vid_id"] for v in existing_videos if v.get("vid_id")}
    print(f"Existing videos: {len(existing_videos)}")

    # Fetch from YouTube
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    playlist_id = get_uploads_playlist_id(youtube)
    print(f"Uploads playlist: {playlist_id}")

    latest_items = fetch_latest_videos(youtube, playlist_id, max_results=50)
    print(f"Fetched {len(latest_items)} items from YouTube")

    # Identify brand-new video IDs
    new_items = []
    for item in latest_items:
        snippet = item["snippet"]
        vid_id = snippet["resourceId"]["videoId"]
        if vid_id in existing_ids:
            continue
        new_items.append((vid_id, snippet))

    if not new_items:
        print("No new videos found. Nothing to update.")
        return

    print(f"New videos to process: {len(new_items)}")

    # Batch-fetch duration + live status for all new videos
    new_ids = [vid for vid, _ in new_items]
    details_map = fetch_video_details(youtube, new_ids)

    # Build entries
    new_videos: list[dict] = []
    for vid_id, snippet in new_items:
        title = snippet["title"]
        published = snippet["publishedAt"][:10]  # YYYY-MM-DD
        print(f"New video: {title} ({vid_id})")

        details = details_map.get(vid_id)
        if not details:
            raise RuntimeError(
                f"videos.list returned no details for {vid_id}. "
                "Cannot safely classify — aborting."
            )

        duration_sec = details["duration_sec"]
        is_live_broadcast = details["is_live_broadcast"]

        # Shorts detection: HEAD request to /shorts/{vid_id}
        # Skip Shorts check for live broadcasts (lives are never shorts)
        if is_live_broadcast:
            is_short = False
        else:
            is_short = is_youtube_short(vid_id)

        if is_short:
            url = f"https://www.youtube.com/shorts/{vid_id}"
            thumb = f"https://i.ytimg.com/vi/{vid_id}/hq2.jpg"
        else:
            url = f"https://www.youtube.com/watch?v={vid_id}"
            thumb = f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"

        print(
            f"  duration={duration_sec}s, is_short={is_short}, "
            f"is_live={is_live_broadcast}"
        )

        # Get transcript (only meaningful for non-shorts)
        transcript = None
        if not is_short:
            transcript = get_transcript(vid_id)
            if transcript:
                print(f"  Transcript: {len(transcript)} chars")
            else:
                print("  No transcript available")

        # Generate metadata via Gemini
        metadata = generate_metadata(title, transcript)

        entry = {
            "title": title,
            "url": url,
            "thumb": thumb,
            "levels": metadata.get("levels", ["初心者"]),
            "categories": metadata.get("categories", ["未分類"]),
            "method": "一般公開",
            "summary": metadata.get("summary", ""),
            "vid_id": vid_id,
            "date": published,
            "is_short": bool(is_short),
            "duration": int(duration_sec),
        }
        validate_entry(entry)
        new_videos.append(entry)

    # Insert new videos at the beginning (newest first)
    new_videos.sort(key=lambda v: v["date"], reverse=True)
    updated_videos = new_videos + existing_videos

    # Dedupe by title - keep first occurrence (which is the newest after sort)
    seen_titles = set()
    deduped = []
    removed_count = 0
    for v in updated_videos:
        title = (v.get("title") or "").strip()
        if title and title in seen_titles:
            removed_count += 1
            continue
        seen_titles.add(title)
        deduped.append(v)
    if removed_count:
        print(f"Removed {removed_count} duplicate(s) by title.")

    write_videos_js(deduped, rest_of_file)
    print(f"Added {len(new_videos)} new video(s). Total: {len(deduped)}")


if __name__ == "__main__":
    main()
