"""
最新の「Deploy to Production」実行の結果を待って表示する（リポジトリは公開なので認証不要）。
  python scripts/wait_deploy.py [head_sha]
head_sha を渡すとそのコミットのデプロイ結果を待つ。省略時は最新の実行。
"""

import json
import sys
import time
import urllib.request

REPO = "fxspace-dev/video-navi"


def latest_run(sha=None):
    url = f"https://api.github.com/repos/{REPO}/actions/runs?per_page=10"
    data = json.loads(urllib.request.urlopen(url, timeout=30).read())
    for r in data.get("workflow_runs", []):
        if r.get("name") != "Deploy to Production":
            continue
        if sha and not r.get("head_sha", "").startswith(sha):
            continue
        return r
    return None


def main():
    sha = sys.argv[1] if len(sys.argv) > 1 else None
    for _ in range(60):  # 最大約10分
        run = latest_run(sha)
        if run and run.get("status") == "completed":
            print(f"{run['conclusion']} | {run['head_sha'][:7]} | {run['html_url']}")
            sys.exit(0 if run["conclusion"] == "success" else 1)
        time.sleep(10)
    print("タイムアウト: まだ完了していません")
    sys.exit(2)


if __name__ == "__main__":
    main()
