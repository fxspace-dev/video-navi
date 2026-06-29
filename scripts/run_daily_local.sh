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
DESKTOP_ALERT="/mnt/c/Users/airic/Desktop/【要確認】動画ナビ更新失敗.txt"
POWERSHELL="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
cd "$REPO_DIR"

# 失敗時: Windowsポップアップ + デスクトップに失敗レポートを作成
notify_failure() {
  local step="$1"
  {
    echo "動画ナビ（https://fx-space.com/videonavi/）の自動更新が失敗しました。"
    echo ""
    echo "失敗日時: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "失敗ステップ: $step"
    echo ""
    echo "直近のログ（詳細は video-navi/scripts/local_run.log）:"
    echo "----------------------------------------"
    tail -30 "$LOG_FILE" 2>/dev/null
    echo "----------------------------------------"
    echo ""
    echo "Claude Code に「動画ナビの更新が失敗したので調べて」と伝えれば調査できます。"
    echo "このファイルは次回更新が成功すると自動で消えます。"
  } > "$DESKTOP_ALERT"
  # ポップアップは表示したまま放置されてもいいようにバックグラウンドで出す
  "$POWERSHELL" -NoProfile -Command \
    "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('動画ナビの自動更新が失敗しました（ステップ: $step）。デスクトップの「【要確認】動画ナビ更新失敗.txt」を確認してください。','動画ナビ 更新失敗','OK','Warning')" \
    >/dev/null 2>&1 &
}

fail() {
  echo "ERROR: $1 failed" >> "$LOG_FILE"
  notify_failure "$1"
  echo "===== run_daily_local.sh ABORT: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"
  exit 1
}

{
  echo "===== run_daily_local.sh start: $(date '+%Y-%m-%d %H:%M:%S') ====="
} >> "$LOG_FILE"

set -a
source .env
set +a

git pull --rebase origin main >> "$LOG_FILE" 2>&1 || fail "git pull"
python3 scripts/fetch_discord_urls.py >> "$LOG_FILE" 2>&1 || fail "Discord URL取得 (fetch_discord_urls)"
python3 scripts/update_videos.py >> "$LOG_FILE" 2>&1 || fail "新着動画取り込み (update_videos)"

# 欠損補完（空カテゴリ・空レベル・空要約）
python3 scripts/fill_missing_summaries.py >> "$LOG_FILE" 2>&1 \
  || echo "WARNING: fill_missing_summaries failed (continuing)" >> "$LOG_FILE"

# 字幕ベース要約への移行が未完の動画を毎日少しずつ処理
# (transcript_ok が付いた動画はスキップされるので、完了後は実質no-op)
FORCE_ALL=1 python3 scripts/fill_missing_summaries.py >> "$LOG_FILE" 2>&1 \
  || echo "WARNING: FORCE_ALL pass failed (continuing)" >> "$LOG_FILE"

(
  if ! git diff --quiet videos.js; then
    # キャッシュバスティング: エックスサーバーはnginxが静的ファイルに7日間の
    # ブラウザキャッシュ(max-age=604800)を付け、.htaccessでは制御できない。
    # そこでvideos.jsが変わるたびにindex.html内の ?v= を更新し、URLを変えることで
    # 訪問者のブラウザに必ず最新を取り直させる。
    # 毎日変わるのは videos.js だけなので、その ?v= のみ更新する。
    # app.js / style.css は中身を変えたときに手動で ?v= を上げること
    # (毎日変えると未変更ファイルの無駄な再DLが発生するため)。
    VER=$(date +%Y%m%d%H%M)
    python3 -c "
import re
s=open('index.html',encoding='utf-8').read()
s=re.sub(r'videos\.js\?v=[^\"]*', 'videos.js?v=$VER', s)
open('index.html','w',encoding='utf-8').write(s)
"
    git add videos.js index.html
    git commit -m "Update videos.js with latest uploads & summaries (local run)"
    git push origin main || exit 9
    echo "videos.js updated & pushed (cache version: $VER)"
  else
    echo "No changes in videos.js"
  fi
) >> "$LOG_FILE" 2>&1 || fail "git push"

# 成功: 前回の失敗アラートが残っていたら消す
rm -f "$DESKTOP_ALERT"
echo "===== run_daily_local.sh end (success): $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"
