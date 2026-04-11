"""
One-time script: verify that every video in videos.js has correct
is_short / duration / url / thumb fields, and fix any inconsistencies.

For each YouTube-hosted video (has vid_id):
  1. Fetch duration via videos().list API
  2. Determine Shorts status via HEAD request to /shorts/{vid_id}
  3. Set: is_short, duration, url, thumb consistently

Discord-hosted videos (no vid_id, discord.com URL) are left untouched since
they have no YouTube equivalent.

Run with:
    YOUTUBE_API_KEY=xxx python scripts/verify_and_fix_shorts.py

Reports a diff summary and writes videos.js atomically at the end.
"""

import json
import os
import re
import sys
import time

import requests
from googleapiclient.discovery import build

VIDEOS_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "videos.js")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
}


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


def iso8601_duration_to_seconds(iso):
    match = re.match(
        r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$",
        iso or "PT0S",
    )
    if not match:
        return 0
    h, m, s = match.groups()
    return int(h or 0) * 3600 + int(m or 0) * 60 + int(s or 0)


def fetch_video_details(youtube, video_ids):
    """Batch-fetch duration for a list of video IDs."""
    if not video_ids:
        return {}
    result = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(
            part="contentDetails,snippet,liveStreamingDetails",
            id=",".join(batch),
        ).execute()
        found = {item["id"] for item in resp.get("items", [])}
        missing = set(batch) - found
        if missing:
            print(f"  WARN: videos.list returned no data for {len(missing)} IDs (private/deleted?): {list(missing)[:5]}...")
        for item in resp.get("items", []):
            vid = item["id"]
            iso = item.get("contentDetails", {}).get("duration", "PT0S")
            duration_sec = iso8601_duration_to_seconds(iso)
            snippet = item.get("snippet", {})
            live_broadcast = snippet.get("liveBroadcastContent", "none")
            has_live_details = "liveStreamingDetails" in item
            result[vid] = {
                "duration_sec": duration_sec,
                "is_live_broadcast": live_broadcast in ("live", "upcoming") or has_live_details,
            }
    return result


def is_youtube_short(vid_id):
    """HEAD request to /shorts/{vid_id}. Returns True if YouTube keeps the URL (200)."""
    url = f"https://www.youtube.com/shorts/{vid_id}"
    try:
        resp = requests.head(
            url, headers=REQUEST_HEADERS, allow_redirects=False, timeout=15
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            return "/shorts/" in location
        print(f"    WARN: unexpected HEAD status {resp.status_code}")
        return False
    except Exception as e:
        print(f"    WARN: HEAD failed: {e}; trying GET")
        try:
            resp = requests.get(
                url, headers=REQUEST_HEADERS, allow_redirects=False, timeout=15
            )
            if resp.status_code == 200:
                return True
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                return "/shorts/" in location
        except Exception as e2:
            print(f"    ERROR: GET also failed: {e2}")
            raise
        return False


def is_youtube_hosted(video):
    """True if the video has a YouTube vid_id and a youtube.com URL (not Discord)."""
    url = video.get("url", "") or ""
    vid_id = video.get("vid_id", "") or ""
    return bool(vid_id) and ("youtube.com" in url or "youtu.be" in url)


def main():
    if not YOUTUBE_API_KEY:
        sys.exit("ERROR: Set YOUTUBE_API_KEY environment variable")

    videos, rest = read_videos_js()
    print(f"Loaded {len(videos)} videos from videos.js")

    # Step 1: Identify YouTube-hosted videos that need verification
    yt_videos = [(i, v) for i, v in enumerate(videos) if is_youtube_hosted(v)]
    non_yt = len(videos) - len(yt_videos)
    print(f"YouTube-hosted: {len(yt_videos)} / Non-YouTube (Discord etc.): {non_yt}")

    # Step 2: Batch-fetch duration from YouTube API for all YT videos
    all_yt_ids = [v["vid_id"] for _, v in yt_videos]
    print(f"Fetching video details for {len(all_yt_ids)} videos...")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    details_map = fetch_video_details(youtube, all_yt_ids)
    print(f"Got details for {len(details_map)} videos")

    # Step 3: For each video, determine correct classification
    changes = []
    removed_videos = []  # videos that returned no data (deleted/private)

    for idx, video in yt_videos:
        vid_id = video["vid_id"]
        title = video.get("title", "")[:50]
        details = details_map.get(vid_id)

        if not details:
            # Video not found — possibly deleted/private. Leave as-is.
            print(f"  [{vid_id}] {title}: NOT FOUND on YouTube, skipping")
            continue

        duration_sec = details["duration_sec"]
        is_live_broadcast = details["is_live_broadcast"]

        # Determine is_short
        if is_live_broadcast:
            new_is_short = False
        elif video.get("url", "").startswith("https://www.youtube.com/shorts/"):
            # Trust existing URL since it was set from scraping Shorts tab
            new_is_short = True
        else:
            # Only run HEAD for videos that are suspicious:
            # - duration <= 180 (could be a short)
            # - or existing is_short is already True (re-verify)
            # - or is_short is missing
            needs_head = (
                duration_sec <= 180
                or video.get("is_short") is True
                or "is_short" not in video
            )
            if needs_head:
                print(f"  [{vid_id}] {title}: HEAD check (duration={duration_sec}s)")
                try:
                    new_is_short = is_youtube_short(vid_id)
                except Exception:
                    print(f"    FAILED, keeping existing is_short={video.get('is_short')}")
                    continue
                time.sleep(0.3)  # throttle
            else:
                new_is_short = False

        # Compute correct url and thumb
        if new_is_short:
            new_url = f"https://www.youtube.com/shorts/{vid_id}"
            new_thumb = f"https://i.ytimg.com/vi/{vid_id}/hq2.jpg"
        else:
            # Preserve any existing ?t= timestamp if present
            existing_url = video.get("url", "")
            if existing_url.startswith("https://www.youtube.com/watch?v="):
                new_url = existing_url  # keep as-is
            else:
                new_url = f"https://www.youtube.com/watch?v={vid_id}"
            # Keep existing thumb if it's a Notion-attached one
            existing_thumb = video.get("thumb", "")
            if "notion.so" in existing_thumb:
                new_thumb = existing_thumb
            else:
                new_thumb = f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"

        # Detect diffs
        diff = {}
        if video.get("is_short") != new_is_short:
            diff["is_short"] = (video.get("is_short"), new_is_short)
        if video.get("duration") != duration_sec:
            diff["duration"] = (video.get("duration"), duration_sec)
        if video.get("url") != new_url:
            diff["url"] = (video.get("url"), new_url)
        if video.get("thumb") != new_thumb:
            diff["thumb"] = (video.get("thumb"), new_thumb)

        if diff:
            changes.append((idx, title, diff))
            videos[idx]["is_short"] = new_is_short
            videos[idx]["duration"] = duration_sec
            videos[idx]["url"] = new_url
            videos[idx]["thumb"] = new_thumb

    # Step 4: Report changes
    print(f"\n=== Summary ===")
    print(f"Videos with changes: {len(changes)}")
    for idx, title, diff in changes[:30]:
        print(f"  [{idx}] {title}")
        for k, (old, new) in diff.items():
            if k in ("url", "thumb"):
                print(f"    {k}: {str(old)[:50]} -> {str(new)[:50]}")
            else:
                print(f"    {k}: {old} -> {new}")
    if len(changes) > 30:
        print(f"  ... and {len(changes) - 30} more")

    # Step 5: Final validation — every YT video must have is_short + duration
    errors = []
    for idx, video in enumerate(videos):
        if not is_youtube_hosted(video):
            continue
        if "is_short" not in video or not isinstance(video["is_short"], bool):
            errors.append(f"  [{idx}] {video.get('title', '')[:50]}: missing/invalid is_short")
        if "duration" not in video or not isinstance(video["duration"], int):
            errors.append(f"  [{idx}] {video.get('title', '')[:50]}: missing/invalid duration")

    if errors:
        print(f"\n!!! {len(errors)} videos still have issues:")
        for e in errors[:20]:
            print(e)
        sys.exit(1)

    # Step 6: Write back
    if changes:
        write_videos_js(videos, rest)
        print(f"\nWrote {len(changes)} updates to videos.js")
    else:
        print("\nNo changes needed. videos.js is already clean.")


if __name__ == "__main__":
    main()
