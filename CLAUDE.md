# video-navi — エージェント向け案内

よすがのYouTube動画一覧サイト（学習ナビ）。データ駆動の静的サイト。
本番: https://fx-space.com/videonavi/ ／ 公開: main に push → GitHub Actions が FTP で xserver へ。

## データ = videos.js
`videos.js` の `const VIDEOS = [...]` が全動画データ。編集は Python で読み書きする
（`fill_missing_summaries.py` の read/write と同じく、正規表現で配列を取り出し
`json.dumps(indent=2, ensure_ascii=False)` で書き戻す）と整形が崩れない。

## 公開前に必ず通すチェック（CIゲート・ローカルでも実行可）
- `python scripts/validate_videos.py` — 壊れ・必須項目・許可外カテゴリ・未分類・重複・
  method↔url整合・thumb↔vid_id整合を検査。**通らないと本番デプロイは止まる**。
  `--discord` を付けると限定動画のリンク実在も照合（要 .env トークン・ローカル専用）。
- アセット（videos.js / app.js / style.css）を変えたら **index.html の `?v=` を新しい番号に上げる**。
  上げ忘れは CI の `scripts/check_cachebust.py` が検出して止める。

## 手動 push（Windowsに鍵が無いのでWSL経由）
`wsl.exe -d Ubuntu -u airi -e bash -c "cd /mnt/c/Users/airic/Desktop/video-navi && git push origin main"`

## 落とし穴（configに書かれない前提知識）
- **毎晩の自動更新**（`scripts/run_daily_local.sh`）が videos.js を再生成する。手動修正は上書きされうる:
  - 日付 → `scripts/fix_member_dates.py` の `MANUAL_DATE_OVERRIDES`（vid_id→日付）で固定
  - カテゴリ → エントリの `cat_v2: true`（`recategorize.py` が再処理しない）で保護
  - 要約 → 空でなければ `fill_missing_summaries.py` は上書きしない。文面ルールは同ファイルの `SUMMARY_GUIDE`
- **同じ動画が2つのYouTube IDを持つ**ことがある（公開版＋メンバー再アップ版）。メンバー限定動画は
  「限定チャンネルに実際に投稿されたID」を使う（`validate_videos.py --discord` で不一致を検出）。
- 動画の除外は `update_videos.py` の `EXCLUDE_TITLE_PATTERNS` / `EXCLUDE_VIDEO_IDS`。
- FTPは稀に失敗するので deploy.yml は最大5回リトライ。デプロイ状況は `python scripts/wait_deploy.py`。
