"""
全動画の再生回数(viewCount)を YouTube Data API で取得し、videos.js の各エントリに
`views` として保存する。カード上で常時「再生数」を表示するためのデータ。

- クライアント側で毎回APIを叩くとクォータを圧迫するため、日次でここに保存しておく。
- 取得できなかった動画（非公開化など）は既存の views を維持する。
- スクレイピング不要・API のみ。失敗しても pipeline を止めない想定。
"""

import os
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))
import update_videos as uv  # read/write helpers と APIキーを再利用


def main() -> None:
    videos, rest = uv.read_videos_js()
    ids = [v["vid_id"] for v in videos if v.get("vid_id")]
    uniq = list(dict.fromkeys(ids))
    counts: dict[str, int] = {}
    for i in range(0, len(uniq), 50):
        chunk = uniq[i : i + 50]
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/videos"
                f"?part=statistics&id={','.join(chunk)}&key={uv.YOUTUBE_API_KEY}",
                timeout=30,
            ).json()
        except Exception as e:
            print(f"  WARNING: viewCount取得失敗: {e}", file=sys.stderr)
            continue
        for it in r.get("items", []):
            vc = it.get("statistics", {}).get("viewCount")
            if vc is not None:
                counts[it["id"]] = int(vc)

    updated = 0
    for v in videos:
        vid = v.get("vid_id")
        if vid and vid in counts and v.get("views") != counts[vid]:
            v["views"] = counts[vid]
            updated += 1

    if updated:
        uv.write_videos_js(videos, rest)
        print(f"{updated}本の再生数を更新しました（取得 {len(counts)}件）")
    else:
        print(f"再生数の更新なし（取得 {len(counts)}件）")


if __name__ == "__main__":
    main()
