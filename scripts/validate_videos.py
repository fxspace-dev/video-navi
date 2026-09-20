"""
videos.js の内容を公開前に検証するガードレール。

CI（deploy.yml）で FTP アップロードの前に実行し、データが壊れていたら
デプロイを止める。ネットワーク不要の純粋チェックのみ（CIで安全に動く）。

追加チェック（Discord接続が必要・ローカル専用）:
  python scripts/validate_videos.py --discord
  → メンバー限定動画の vid_id が実際に限定チャンネルに投稿されているか照合する
    （説明文リンク由来の誤マッピング等を検出。.env の DISCORD_BOT_TOKEN が必要）

終了コード: 問題なし=0 / 問題あり=1
"""

import json
import os
import re
import sys

# Windowsコンソール(cp932)でも日本語を出せるように標準出力をUTF-8化
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VIDEOS_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "videos.js")
INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "index.html")

# fill_missing_summaries.EXISTING_CATEGORIES と同期させること（CIでは重い依存を入れないため複製）
EXISTING_CATEGORIES = {
    "手法", "基礎", "リアルトレード", "雑談", "メンタル", "実践",
    "資金管理", "プロップファーム", "シナリオ", "実績", "企画",
    "インタビュー", "トレード環境", "ゼロプロ(旧プレアストロ)", "過去検証",
    "YTT", "相場", "税金", "インジケーター", "ライン", "チャートパターン",
    "その他手法", "プライスアクション", "ナウキャスト", "あるある", "CFD",
    "損切", "大会", "コミュニティ", "SIRIUS",
}
LEVEL_OPTIONS = {"超初心者", "初心者", "中級", "上級"}
REQUIRED_FIELDS = ("title", "url", "thumb", "vid_id", "date", "method",
                   "is_short", "is_live", "categories", "levels")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def read_videos():
    with open(VIDEOS_JS_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"const\s+VIDEOS\s*=\s*(\[.*?\n\]);", text, re.DOTALL)
    if not m:
        raise ValueError("videos.js から VIDEOS 配列を取り出せませんでした")
    return json.loads(m.group(1))


def validate(videos):
    problems = []

    def bad(v, msg):
        problems.append(f"{msg} | {v.get('vid_id', '?')} {(v.get('title') or '')[:40]}")

    seen_vid = {}
    seen_title = {}
    for v in videos:
        for f in REQUIRED_FIELDS:
            if f not in v or v[f] is None:
                bad(v, f"必須項目が無い: {f}")

        vid = v.get("vid_id")
        if vid:
            if vid in seen_vid:
                bad(v, f"vid_id が重複")
            seen_vid[vid] = True

        title = (v.get("title") or "").strip()
        if title:
            if title in seen_title:
                bad(v, "タイトルが重複（同一動画の二重登録の疑い）")
            seen_title[title] = True

        cats = v.get("categories") or []
        if not cats:
            bad(v, "categories が空")
        for c in cats:
            if c == "未分類":
                bad(v, "categories に「未分類」が残っている")
            elif c not in EXISTING_CATEGORIES:
                bad(v, f"許可外のカテゴリ: {c}")

        levels = v.get("levels") or []
        if not levels:
            bad(v, "levels が空")
        for l in levels:
            if l not in LEVEL_OPTIONS:
                bad(v, f"許可外のレベル: {l}")

        date = v.get("date") or ""
        if not DATE_RE.match(date):
            bad(v, f"date の形式が不正: {date!r}")

        for f in ("is_short", "is_live"):
            if f in v and not isinstance(v[f], bool):
                bad(v, f"{f} は true/false であるべき: {v[f]!r}")

        method = v.get("method")
        url = v.get("url") or ""
        if method == "メンバーシップ限定公開":
            if "discord.com/channels/" not in url:
                bad(v, "メンバー限定なのに url が Discord リンクでない")
        elif method == "一般公開":
            if "youtu" not in url:
                bad(v, "一般公開なのに url が YouTube リンクでない")
        else:
            bad(v, f"method が不正: {method!r}")

        thumb = v.get("thumb") or ""
        if vid and vid not in thumb:
            bad(v, "thumb が vid_id と一致していない")

    return problems


def validate_discord(videos):
    """メンバー限定動画の vid_id が限定チャンネルの投稿本文に存在するか照合（要 .env トークン）。"""
    import urllib.request

    env = {}
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            if "=" in line and not line.strip().startswith("#"):
                k, _, val = line.strip().partition("=")
                env[k] = val
    token = env.get("DISCORD_BOT_TOKEN", "").strip()
    channel = "1528174536175128767"  # 限定動画チャンネル
    if not token:
        print("  (--discord スキップ: DISCORD_BOT_TOKEN が無い)")
        return []

    yt = [re.compile(p) for p in (
        r"youtu\.be/([A-Za-z0-9_-]{11})", r"youtube\.com/watch\?v=([A-Za-z0-9_-]{11})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})", r"youtube\.com/live/([A-Za-z0-9_-]{11})")]
    posted = set()
    before = None
    while True:
        u = f"https://discord.com/api/v10/channels/{channel}/messages?limit=100"
        if before:
            u += f"&before={before}"
        req = urllib.request.Request(u, headers={"Authorization": f"Bot {token}",
                                                 "User-Agent": "fx-space-video-navi"})
        try:
            batch = json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception as e:
            print(f"  (--discord スキップ: 取得失敗 {e})")
            return []
        if not batch:
            break
        for msg in batch:
            for p in yt:
                for mm in p.finditer(msg.get("content", "") or ""):
                    posted.add(mm.group(1))
        before = batch[-1]["id"]
        if len(batch) < 100:
            break

    problems = []
    for v in videos:
        if v.get("method") == "メンバーシップ限定公開" and v.get("vid_id") not in posted:
            problems.append(f"限定チャンネルに投稿が無い vid_id | {v['vid_id']} {(v.get('title') or '')[:40]}")
    return problems


def main():
    videos = read_videos()
    print(f"videos.js: {len(videos)} 本を検証")
    problems = validate(videos)
    if "--discord" in sys.argv:
        problems += validate_discord(videos)

    if problems:
        print(f"\nNG: {len(problems)} 件の問題:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("OK: 問題なし")


if __name__ == "__main__":
    main()
