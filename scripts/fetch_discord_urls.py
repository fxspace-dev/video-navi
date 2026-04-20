"""
Discord REST API を使って、指定チャンネル群からYouTube動画リンクを含む
メッセージを抽出し、{vid_id: discord_message_url} のマッピングを生成する。

環境変数:
- DISCORD_BOT_TOKEN: Bot Token
- DISCORD_SERVER_ID: サーバー(ギルド)ID
- DISCORD_CHANNEL_IDS: カンマ区切りのチャンネルID群

出力: scripts/discord_urls.json
"""

import json
import os
import re
import sys
import time

import requests

DISCORD_API = "https://discord.com/api/v10"
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
SERVER_ID = os.environ.get("DISCORD_SERVER_ID", "")
CHANNEL_IDS = [c.strip() for c in os.environ.get("DISCORD_CHANNEL_IDS", "").split(",") if c.strip()]

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "discord_urls.json")

# YouTube video ID を抽出する正規表現
YT_PATTERNS = [
    re.compile(r"youtube\.com/watch\?v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/live/([A-Za-z0-9_-]{11})"),
]


def headers():
    return {
        "Authorization": f"Bot {BOT_TOKEN}",
        "User-Agent": "fx-space-video-navi (https://fx-space.com/videonavi)",
    }


def fetch_messages(channel_id: str, limit_total: int = 1000) -> list[dict]:
    """
    指定チャンネルのメッセージ履歴を遡って取得する。
    新しい順に取得し、limit_total 件まで。
    """
    messages: list[dict] = []
    before = None
    while len(messages) < limit_total:
        params = {"limit": 100}
        if before:
            params["before"] = before
        url = f"{DISCORD_API}/channels/{channel_id}/messages"
        r = requests.get(url, headers=headers(), params=params, timeout=30)
        if r.status_code == 403:
            print(
                f"  WARNING: 403 Forbidden on channel {channel_id}. "
                "Bot がこのチャンネルの閲覧権限を持っていない可能性があります。",
                file=sys.stderr,
            )
            return messages
        if r.status_code == 404:
            print(
                f"  WARNING: 404 Not Found on channel {channel_id}. "
                "チャンネルIDが間違っているか、Botが未参加です。",
                file=sys.stderr,
            )
            return messages
        if r.status_code == 429:
            retry = r.json().get("retry_after", 5)
            print(f"  Rate limited, sleeping {retry}s", file=sys.stderr)
            time.sleep(retry)
            continue
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        messages.extend(batch)
        before = batch[-1]["id"]
        if len(batch) < 100:
            break
        # Discord rate limit: conservative sleep
        time.sleep(0.3)
    return messages


def extract_vid_ids(msg: dict) -> list[str]:
    """メッセージ(content+embeds)からYouTube動画IDをすべて抽出"""
    ids: list[str] = []
    text_sources = [msg.get("content", "")]
    for emb in msg.get("embeds", []):
        text_sources.append(emb.get("url", "") or "")
        text_sources.append(emb.get("title", "") or "")
        text_sources.append(emb.get("description", "") or "")
    for src in text_sources:
        for pat in YT_PATTERNS:
            for m in pat.finditer(src):
                vid = m.group(1)
                if vid not in ids:
                    ids.append(vid)
    return ids


def build_message_url(server_id: str, channel_id: str, message_id: str) -> str:
    return f"https://discord.com/channels/{server_id}/{channel_id}/{message_id}"


def main():
    if not BOT_TOKEN or not SERVER_ID or not CHANNEL_IDS:
        sys.exit(
            "ERROR: DISCORD_BOT_TOKEN / DISCORD_SERVER_ID / DISCORD_CHANNEL_IDS "
            "がすべて設定されている必要があります。"
        )

    print(f"Server: {SERVER_ID}")
    print(f"Channels: {len(CHANNEL_IDS)}件")

    mapping: dict[str, str] = {}  # vid_id -> discord_message_url

    for ch_id in CHANNEL_IDS:
        print(f"\n--- Channel {ch_id} ---")
        msgs = fetch_messages(ch_id)
        print(f"  取得メッセージ数: {len(msgs)}")
        hits = 0
        for msg in msgs:
            vids = extract_vid_ids(msg)
            if not vids:
                continue
            msg_url = build_message_url(SERVER_ID, ch_id, msg["id"])
            for vid in vids:
                # 同じ動画が複数メッセージに貼られている場合、
                # より新しいメッセージ（先に来る）を優先。
                # 既に登録済みなら上書きしない。
                if vid not in mapping:
                    mapping[vid] = msg_url
                    hits += 1
        print(f"  マッピング追加: {hits}件")

    print(f"\n合計マッピング: {len(mapping)}件")
    # デバッグ: 全マッピングの vid_id 一覧を出力
    print("\n--- 全マッピング vid_id ---")
    for vid in sorted(mapping.keys()):
        print(f"  {vid}")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"\n保存先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
