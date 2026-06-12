#!/usr/bin/env bash
# 動画ナビ デイリー更新（ローカル実行版）
#
# GitHub Actions のランナーは YouTube に字幕取得をブロックされる
# (youtube-transcript-api → RequestBlocked) ため、字幕ベースの要約生成は
# 自宅IPで動くこのスクリプトで行う。
# Windows タスクスケジューラから毎日 JST 21:00 に wsl.exe 経由で起動される。
# サイトへのFTPデプロイは push を受けた GitHub Actions (deploy.yml) が行う。
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$REPO_DIR/scripts/local_run.log"
cd "$REPO_DIR"

{
  echo "===== run_daily_local.sh start: $(date '+%Y-%m-%d %H:%M:%S') ====="

  set -a
  source .env
  set +a

  git pull --rebase origin main || { echo "ERROR: git pull failed"; exit 1; }

  python3 scripts/fetch_discord_urls.py || { echo "ERROR: fetch_discord_urls failed"; exit 1; }
  python3 scripts/update_videos.py || { echo "ERROR: update_videos failed"; exit 1; }

  # 欠損補完（空カテゴリ・空レベル・空要約）
  python3 scripts/fill_missing_summaries.py || echo "WARNING: fill_missing_summaries failed (continuing)"

  # 字幕ベース要約への移行が未完の動画を毎日少しずつ処理
  # (transcript_ok が付いた動画はスキップされるので、完了後は実質no-op)
  FORCE_ALL=1 python3 scripts/fill_missing_summaries.py || echo "WARNING: FORCE_ALL pass failed (continuing)"

  if ! git diff --quiet videos.js; then
    git add videos.js
    git commit -m "Update videos.js with latest uploads & summaries (local run)"
    git push origin main || { echo "ERROR: git push failed"; exit 1; }
    echo "videos.js updated & pushed"
  else
    echo "No changes in videos.js"
  fi

  echo "===== run_daily_local.sh end: $(date '+%Y-%m-%d %H:%M:%S') ====="
} >> "$LOG_FILE" 2>&1
