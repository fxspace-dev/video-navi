"""
診断用スクリプト: サーバー内の全チャンネルを走査して、特定のYouTube動画IDが
どのチャンネル/メッセージに貼られているかを報告する。

環境変数:
- DISCORD_BOT_TOKEN
- DISCORD_SERVER_ID
"""

import os
import sys
import time

import requests

DISCORD_API = "https://discord.com/api/v10"
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
SERVER_ID = os.environ.get("DISCORD_SERVER_ID", "")

# 探す対象の動画ID
TARGET_VID_IDS = ["xAQLqpI73DY", "GJGx8xPoztI", "z_1f4US6wbk"]


def headers():
    return {"Authorization": f"Bot {BOT_TOKEN}"}


def main():
    if not BOT_TOKEN or not SERVER_ID:
        sys.exit("ERROR: DISCORD_BOT_TOKEN / DISCORD_SERVER_ID が必要です")

    # 1. 全チャンネルを取得
    r = requests.get(f"{DISCORD_API}/guilds/{SERVER_ID}/channels", headers=headers(), timeout=30)
    r.raise_for_status()
    channels = r.json()
    print(f"サーバー内チャンネル数: {len(channels)}")

    found: dict[str, list[str]] = {vid: [] for vid in TARGET_VID_IDS}

    for ch in channels:
        ch_id = ch["id"]
        ch_name = ch.get("name", "?")
        ch_type = ch.get("type")
        # 0=text, 5=announcement, 15=forum, 16=media
        if ch_type not in (0, 5, 15, 16):
            continue

        # メッセージ取得（最新100件のみで十分 — 最近投稿のメンバー限定動画を探すため）
        try:
            mr = requests.get(
                f"{DISCORD_API}/channels/{ch_id}/messages",
                headers=headers(),
                params={"limit": 100},
                timeout=30,
            )
            if mr.status_code != 200:
                continue
            msgs = mr.json()
        except Exception as e:
            continue

        for msg in msgs:
            text = msg.get("content", "") or ""
            for emb in msg.get("embeds", []):
                text += " " + (emb.get("url") or "")
                text += " " + (emb.get("title") or "")
                text += " " + (emb.get("description") or "")
            for vid in TARGET_VID_IDS:
                if vid in text:
                    msg_url = f"https://discord.com/channels/{SERVER_ID}/{ch_id}/{msg['id']}"
                    found[vid].append(f"{ch_name} ({ch_id}) → {msg_url}")

        time.sleep(0.3)

    print("\n=== 検索結果 ===")
    for vid, locations in found.items():
        print(f"\n{vid}:")
        if not locations:
            print("  ❌ どのチャンネルにも見つかりませんでした")
        else:
            for loc in locations:
                print(f"  ✅ {loc}")


if __name__ == "__main__":
    main()
