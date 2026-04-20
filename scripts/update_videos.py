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
CHANNEL_VIDEOS_URL = "https://www.youtube.com/@fxyosuga/videos?hl=ja&gl=JP"
VIDEOS_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "videos.js")
DISCORD_URLS_PATH = os.path.join(os.path.dirname(__file__), "discord_urls.json")

# 除外する動画のタイトルパターン（ユーザー指定）
EXCLUDE_TITLE_PATTERNS = [
    re.compile(r"今日のシナリオ構築"),
    re.compile(r"ゼロプロ.*期.*添削"),
]

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


def scrape_channel_videos_tab() -> list[tuple[str, str]]:
    """
    チャンネルの「動画」タブをHTMLから直接パースし、
    [(video_id, title), ...] を返す。

    この関数は YouTube Data API の playlistItems では返ってこない
    メンバー限定動画も拾える（チャンネルページ自体は公開されているため）。
    """
    try:
        r = requests.get(CHANNEL_VIDEOS_URL, headers=REQUEST_HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"  WARNING: チャンネルページ取得失敗: {e}", file=sys.stderr)
        return []

    html = r.text
    idx = html.find("var ytInitialData = ")
    if idx < 0:
        idx = html.find("ytInitialData = ")
    if idx < 0:
        print("  WARNING: ytInitialData が見つかりません", file=sys.stderr)
        return []

    # Parse JSON with balanced braces
    start = html.find("{", idx)
    depth = 0
    in_str = False
    esc = False
    end = -1
    for i, ch in enumerate(html[start:], start=start):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return []

    try:
        data = json.loads(html[start:end])
    except Exception as e:
        print(f"  WARNING: ytInitialData JSONパース失敗: {e}", file=sys.stderr)
        return []

    out: list[tuple[str, str]] = []
    try:
        tabs = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
        # タイトルに依存せず、richGridRenderer + videoRenderer を含むタブを探す。
        # これで言語設定（動画 / Videos）やタブ位置の違いに耐える。
        best_tab_items: list[dict] = []
        for t in tabs:
            tr = t.get("tabRenderer", {})
            content = tr.get("content", {}) or {}
            items = content.get("richGridRenderer", {}).get("contents", []) or []
            # 最初の長尺動画 videoRenderer を見つけたらこのタブが動画タブ
            if any(
                it.get("richItemRenderer", {}).get("content", {}).get("videoRenderer")
                for it in items
            ):
                best_tab_items = items
                title_label = tr.get("title", "?")
                print(f"  スクレイピング: '{title_label}' タブから {len(items)}件", file=sys.stderr)
                break

        for it in best_tab_items:
            vr = it.get("richItemRenderer", {}).get("content", {}).get("videoRenderer")
            if not vr or not vr.get("videoId"):
                continue
            vid = vr["videoId"]
            title_runs = vr.get("title", {}).get("runs", [])
            title = title_runs[0].get("text", "") if title_runs else ""
            out.append((vid, title))
    except (KeyError, TypeError) as e:
        print(f"  WARNING: ytInitialData 構造が想定と違います: {e}", file=sys.stderr)

    return out


def should_exclude_title(title: str) -> bool:
    """除外パターンに該当するか"""
    for p in EXCLUDE_TITLE_PATTERNS:
        if p.search(title):
            return True
    return False


def load_discord_urls() -> dict[str, str]:
    """fetch_discord_urls.py が生成したマッピングを読み込む"""
    if not os.path.exists(DISCORD_URLS_PATH):
        return {}
    try:
        with open(DISCORD_URLS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  WARNING: discord_urls.json 読み込み失敗: {e}", file=sys.stderr)
        return {}


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
            published_at = snippet.get("publishedAt", "")[:10]
            result[vid] = {
                "duration_sec": duration_sec,
                "is_live_broadcast": live_broadcast_content in ("live", "upcoming") or has_live_details,
                "published": published_at,
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
    # ただしメンバーシップ限定公開の場合は Discord URL になっているため除外
    is_discord = "discord.com/channels/" in entry["url"]
    if not is_discord:
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

    # Load Discord URL mapping (may be empty on first run)
    discord_urls = load_discord_urls()
    print(f"Discord URL mapping: {len(discord_urls)}件")

    # Fetch from YouTube
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    playlist_id = get_uploads_playlist_id(youtube)
    print(f"Uploads playlist: {playlist_id}")

    # 1. YouTube Data API: 公開・限定公開の動画（メンバー限定は返ってこない）
    latest_items = fetch_latest_videos(youtube, playlist_id, max_results=50)
    api_ids = {item["snippet"]["resourceId"]["videoId"] for item in latest_items}
    print(f"API items: {len(latest_items)}")

    # 2. チャンネルページスクレイピング: メンバー限定含む全動画
    scraped = scrape_channel_videos_tab()
    print(f"Scraped items (動画タブ): {len(scraped)}")

    # 3. マージして処理対象を組み立てる
    # (vid_id, title, published_date_or_None, is_member_only)
    new_items: list[tuple[str, str, str | None, bool]] = []
    seen = set()

    # API から来た動画（公開・限定公開）
    for item in latest_items:
        snippet = item["snippet"]
        vid_id = snippet["resourceId"]["videoId"]
        if vid_id in existing_ids or vid_id in seen:
            continue
        title = snippet["title"]
        if should_exclude_title(title):
            print(f"  SKIP (除外): {title}")
            continue
        seen.add(vid_id)
        new_items.append((vid_id, title, snippet["publishedAt"][:10], False))

    # スクレイプから来た動画のうち、API に無いものはメンバー限定扱い
    for vid_id, title in scraped:
        if vid_id in existing_ids or vid_id in seen:
            continue
        if should_exclude_title(title):
            print(f"  SKIP (除外): {title}")
            continue
        is_member_only = vid_id not in api_ids
        seen.add(vid_id)
        # スクレイプ由来は published 不明 → fetch_video_details で埋める
        new_items.append((vid_id, title, None, is_member_only))

    # 新規動画がなくても、既存のメンバー限定動画のURL更新は実行したいので
    # return せずに続ける
    print(f"New videos to process: {len(new_items)}")

    # Batch-fetch duration + live status + publishedAt for all new videos
    new_ids = [vid for vid, _, _, _ in new_items]
    details_map = fetch_video_details(youtube, new_ids) if new_ids else {}

    # Build entries
    new_videos: list[dict] = []
    for vid_id, title, published_hint, is_member_only in new_items:
        print(f"New video: {title} ({vid_id}) member_only={is_member_only}")

        details = details_map.get(vid_id)
        if not details:
            raise RuntimeError(
                f"videos.list returned no details for {vid_id}. "
                "Cannot safely classify — aborting."
            )

        duration_sec = details["duration_sec"]
        is_live_broadcast = details["is_live_broadcast"]
        published = published_hint or details.get("published", "")

        # Shorts detection: HEAD request to /shorts/{vid_id}
        # Skip Shorts check for live broadcasts (lives are never shorts)
        if is_live_broadcast:
            is_short = False
        else:
            is_short = is_youtube_short(vid_id)

        # URL / method 決定
        # - メンバー限定動画 かつ Discord URL が見つかれば → Discord URL に差し替え
        # - それ以外は従来通り YouTube URL
        method = "メンバーシップ限定公開" if is_member_only else "一般公開"
        discord_url = discord_urls.get(vid_id)

        if is_member_only and discord_url:
            url = discord_url
        elif is_short:
            url = f"https://www.youtube.com/shorts/{vid_id}"
        else:
            url = f"https://www.youtube.com/watch?v={vid_id}"

        # サムネイルは常に YouTube を使う（Discordに無いため）
        if is_short:
            thumb = f"https://i.ytimg.com/vi/{vid_id}/hq2.jpg"
        else:
            thumb = f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"

        print(
            f"  duration={duration_sec}s, is_short={is_short}, "
            f"is_live={is_live_broadcast}, method={method}, "
            f"url={'discord' if is_member_only and discord_url else 'youtube'}"
        )

        # Get transcript (only meaningful for non-shorts, 公開動画のみ）
        transcript = None
        if not is_short and not is_member_only:
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
            "method": method,
            "summary": metadata.get("summary", ""),
            "vid_id": vid_id,
            "date": published,
            "is_short": bool(is_short),
            "duration": int(duration_sec),
        }
        validate_entry(entry)
        new_videos.append(entry)

    # 既存のメンバー限定動画について、Discord URL が新たに判明した場合は上書き
    refreshed_count = 0
    for v in existing_videos:
        if v.get("method") != "メンバーシップ限定公開":
            continue
        vid = v.get("vid_id")
        if not vid:
            continue
        discord_url = discord_urls.get(vid)
        if discord_url and v.get("url") != discord_url:
            print(f"  URL更新: {v.get('title')} → Discord")
            v["url"] = discord_url
            refreshed_count += 1
    if refreshed_count:
        print(f"既存動画のURLを{refreshed_count}件更新しました")

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
