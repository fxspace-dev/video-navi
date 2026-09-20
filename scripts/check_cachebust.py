"""
アセット(videos.js / app.js / style.css)を変更したのに index.html の ?v=
（キャッシュ更新）を上げ忘れていないかを検査するガードレール。

CI（deploy.yml）で push の前後コミットを比較して実行する:
  python scripts/check_cachebust.py <before_sha> <after_sha>

before が空 or 全ゼロ（初回push等）や引数なしのときはスキップ（=合格）。
終了コード: 問題なし=0 / 上げ忘れあり=1
"""

import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ASSETS = ["videos.js", "app.js", "style.css"]


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def vparam(html, asset):
    m = re.search(re.escape(asset) + r"\?v=(\d+)", html)
    return m.group(1) if m else None


def main():
    if len(sys.argv) < 3:
        print("スキップ: before/after が指定されていません（合格扱い）")
        return
    before, after = sys.argv[1], sys.argv[2]
    if not before or set(before) == {"0"}:
        print("スキップ: 初回push等（合格扱い）")
        return

    changed = set(git("diff", "--name-only", before, after).split())
    before_html = git("show", f"{before}:index.html")
    after_html = git("show", f"{after}:index.html")

    problems = []
    for asset in ASSETS:
        if asset in changed:
            if vparam(before_html, asset) == vparam(after_html, asset):
                problems.append(asset)

    if problems:
        print("NG: 変更したのに index.html の ?v= を上げていないファイル:")
        for a in problems:
            print(f"  - {a}（index.html の {a}?v=... を新しい番号に更新してください）")
        sys.exit(1)
    print("OK: キャッシュ更新（?v=）は問題なし")


if __name__ == "__main__":
    main()
