"""
Fill missing summaries for existing videos using Gemini API.
One-time script: run locally or via GitHub Actions.
"""

import json
import os
import re
import sys
import time

import requests
from youtube_transcript_api import YouTubeTranscriptApi

VIDEOS_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "videos.js")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
FORCE_ALL = os.environ.get("FORCE_ALL", "0").lower() in ("1", "true")  # 全件強制再生成モード

EXISTING_CATEGORIES = [
    "手法", "基礎", "リアルトレード", "雑談", "メンタル", "実践",
    "資金管理", "プロップファーム", "シナリオ", "実績", "企画",
    "インタビュー", "トレード環境", "ゼロプロ(旧プレアストロ)", "過去検証",
    "YTT", "相場", "税金", "インジケーター", "ライン", "チャートパターン",
    "その他手法", "プライスアクション", "ナウキャスト", "あるある", "CFD",
    "損切", "大会", "コミュニティ", "SIRIUS",
]
LEVEL_OPTIONS = ["超初心者", "初心者", "中級", "上級"]

# カテゴリ判定ガイド（Geminiの精度を上げるための定義とトリガー）
# 「テーマ(内容)」だけでなく「形式(フォーマット)」も必ず考慮して該当を全て付ける。
CATEGORY_GUIDE = """### カテゴリ判定ガイド
動画の「内容テーマ」と「形式」の両面から、該当するものを**すべて**付ける（通常2〜4個）。
特に形式カテゴリ（インタビュー/リアルトレード/実績/雑談/企画/あるある/コラム）は見落としやすいので必ず確認する。

【形式で判定するカテゴリ】
- インタビュー: ★厳格判定★ ゲスト・第三者が**実際にその場に登場して対話/対談している回のみ**。合図: 「〜さんインタビュー」「対談」「ゲスト」「〜に聞いてみた/全部聞く」「密着」「〜と会った」。
  ❌ その場にいない有名トレーダー(cis, レイ・バロス, タートルズ等)や事象・書籍を『解説・分析・紹介』しているだけの回は**インタビューではない**（本人が登場して話していなければ付けない）。
  ❌ 詐欺の暴露・対決・追及・警告の回も**インタビューではない**。
  → 迷ったら「本人が画面に登場して話しているか？」で判断し、登場しないなら付けない。
- リアルトレード: 実際のトレードや週間トレードの振り返り・解説。合図: 「リアルトレード」「今週の」「お手本トレード」「実況」
- 実績: 成績・結果・利益/損失の報告。合図: 「+○%」「○万円」「結果」「成績」「達成」
- 企画: 検証・チャレンジ・実験など企画もの。合図: 「やってみた」「検証」「チャレンジ」「○日間」
- あるある: 初心者あるある等のネタ。合図: 「あるある」
- 雑談: 雑談・トーク・近況・考え方の共有（コラム的な回もここ）。合図: 「雑談」「コラム」「トーク」「〜について思うこと」
- 大会: トレード大会・コンテスト関連
- インタビュー/実績/リアルトレードは内容テーマ(手法など)と**併記**する

【内容テーマで判定するカテゴリ】
- 手法: よすが式の手法・トレード手法全般 / その他手法: よすが式以外の手法
- ライン: 水平線・トレンドライン / チャートパターン: 三尊・ダブル等の形 / プライスアクション: ローソク足の値動き読み
- ダウ・ナウキャスト: ダウ理論・ナウキャスト手法 → ナウキャスト
- インジケーター: 各種インジ / トレード環境: 環境認識・MTF・通貨ペア選定
- 資金管理 / 損切: ロット・リスク管理・損切り / メンタル: 心理・マインド
- 基礎: 初心者向け基礎知識 / 相場: 相場観・地合い・値動き解説
- プロップファーム: Fintokei/Fundora/FTO等のプロップ / CFD / 税金 / 過去検証: 過去チャートの検証
- YTT: よすがトレードツール / SIRIUS / コミュニティ: FX SPACE等コミュニティ / ゼロプロ(旧プレアストロ)

【例】
- 「🔰初心者が3か月で爆速プロになってたから何したか全部聞く」→ ["インタビュー", "実践", "メンタル"]（他人に聞く=インタビュー必須）
- 「Fintokeiの社長と会ったら革命的だった話」→ ["インタビュー", "プロップファーム"]
- 「【7/3〜7/7】今週の全リアルトレード解説」→ ["リアルトレード", "実践"]
- 「損切りラインの決め方」→ ["損切", "手法", "基礎"]
- 「総資産400億トレーダーCISの真実」→ ["実践", "メンタル", "手法"]（cis本人は登場せず解説のみ＝インタビュー付けない）
- 「レイ・バロスがたった1つ変えて人生逆転」→ ["メンタル", "実績", "資金管理"]（本人不在の事例解説＝インタビュー付けない）
- 「FX詐欺コンサルの手口を暴露！Zoom対決で追及」→ ["雑談", "基礎"]（暴露・対決＝インタビュー付けない）"""


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


def get_transcript(video_id):
    """字幕テキストを返す。(text, blocked) のタプル。
    blocked=True は YouTube による IPブロック/レート制限（リトライしても無駄）"""
    api = YouTubeTranscriptApi()
    blocked = False
    for langs in (["ja"], None):
        try:
            if langs:
                transcript = api.fetch(video_id, languages=langs)
            else:
                transcript = api.fetch(video_id)
            return " ".join(e.text for e in transcript), False
        except Exception as e:
            # IpBlocked / RequestBlocked / TooManyRequests = IP起因の失敗
            if any(k in type(e).__name__ for k in ("Blocked", "TooManyRequests")):
                blocked = True
                break
    return None, blocked


def generate_metadata(title, transcript, need_full):
    """
    need_full=True: summary + levels + categories を生成
    need_full=False: summary のみ
    """
    context = transcript[:8000] if transcript else f"(字幕なし) タイトル: {title}"

    summary_instruction = """
## summary の書き方（最重要）
- タイトルの言い換えは禁止。字幕テキストから読み取れる「具体的な内容・手法・ポイント」を書く
- 例: 「損切りラインの決め方3パターンと、エントリー後のメンタル管理について解説している。」
- 「〜を解説している」「〜について紹介している」のような体言止めの文体
- 1〜2文、日本語80文字以内"""

    if need_full:
        prompt = f"""あなたはFXトレード教育チャンネル「@fxyosuga」の動画メタデータを生成するアシスタントです。

## 動画タイトル
{title}

## 動画の内容（字幕テキスト）
{context}

## 出力フォーマット（JSONのみ、他のテキストなし）
{{
  "summary": "字幕から読み取れる具体的な内容を1〜2文で",
  "levels": ["該当するレベルを配列で"],
  "categories": ["該当するカテゴリを配列で"]
}}
{summary_instruction}
## レベル選択肢（1つ以上選択）
{", ".join(LEVEL_OPTIONS)}

## 既存カテゴリ一覧（原則ここから選ぶ。該当が本当に無い場合のみ新規作成可）
{", ".join(EXISTING_CATEGORIES)}

{CATEGORY_GUIDE}

## その他注意
- levelsは対象視聴者のレベル（複数可）
- categoriesは「内容テーマ」と「形式」の両面から該当を**すべて**選ぶ（通常2〜4個）
- インタビュー・リアルトレード・実績・企画・あるある等の**形式カテゴリを見落とさない**
- JSONのみ出力（マークダウンのコードブロックなし）"""
    else:
        prompt = f"""あなたはFXトレード教育チャンネル「@fxyosuga」の動画メタデータを生成するアシスタントです。

## 動画タイトル
{title}

## 動画の内容（字幕テキスト）
{context}
{summary_instruction}
JSONのみ出力: {{"summary": "要約文"}}
マークダウンのコードブロックなし"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512 if need_full else 256},
    }

    max_retries = 5
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 429 and attempt < max_retries:
                delay_sec = 30
                is_daily_quota = False
                try:
                    err_data = resp.json()
                    for detail in err_data.get("error", {}).get("details", []):
                        if "retryDelay" in detail:
                            m = re.match(r"(\d+)", detail["retryDelay"])
                            if m:
                                delay_sec = int(m.group(1)) + 3
                                break
                        # 日次クォータ枯渇の場合は諦める
                        if detail.get("reason") == "RATE_LIMIT_EXCEEDED" and delay_sec > 300:
                            is_daily_quota = True
                except Exception:
                    pass
                if is_daily_quota:
                    print(f"  日次クォータ枯渇。終了します。", file=sys.stderr)
                    return None  # Noneで日次枯渇を通知
                print(f"  429: {delay_sec}s 待機中... (attempt {attempt+1}/{max_retries})", file=sys.stderr)
                time.sleep(delay_sec)
                continue
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return json.loads(text)
        except Exception as e:
            if attempt == max_retries:
                print(f"  WARNING: Gemini error (最終): {e}", file=sys.stderr)
                return {}
            time.sleep(5)
    return {}


def main():
    if not GEMINI_API_KEY:
        sys.exit("ERROR: Set GEMINI_API_KEY environment variable")

    videos, rest = read_videos_js()

    if FORCE_ALL:
        # 全件対象（ショート除く、transcript_ok フラグ未設定のもの）
        missing = [(i, v) for i, v in enumerate(videos)
                   if not v.get("is_short", False) and not v.get("transcript_ok", False)]
        total_remaining = len(missing)
        # YouTubeのIPブロック（短時間に大量の字幕取得で発生）を避けるため
        # 1回の実行で処理する件数を制限。毎晩の実行で数日かけて収束する
        batch_limit = int(os.environ.get("FORCE_ALL_BATCH", "60"))
        missing = missing[:batch_limit]
        print(f"[FORCE_ALL] 再生成対象: 残り{total_remaining}件中 今回{len(missing)}件を処理 / 全{len(videos)}件")
    else:
        def needs_fix(v):
            no_summary = not v.get("summary", "").strip()
            cats = v.get("categories") or []
            levels = v.get("levels") or []
            # 「未分類」だけでなく、空配列・キー欠損も補完対象にする
            unclassified = not cats or cats == ["未分類"]
            return no_summary or unclassified or not levels
        missing = [(i, v) for i, v in enumerate(videos) if needs_fix(v)]
        print(f"要約/カテゴリ補完対象: {len(missing)}件 / 全{len(videos)}件")

    if not missing:
        print("対象動画がありません。")
        return

    updated = 0
    consecutive_failures = 0
    consecutive_blocked = 0
    for count, (idx, video) in enumerate(missing, 1):
        title = video["title"]
        vid_id = video.get("vid_id", "")
        # カテゴリが「未分類」/空/欠損、またはレベルが空の場合は levels/categories も再生成
        cats = video.get("categories") or []
        need_full = not cats or cats == ["未分類"] or not (video.get("levels") or [])
        print(f"[{count}/{len(missing)}] {title} (full={need_full})")

        try:
            transcript, blocked = get_transcript(vid_id) if vid_id else (None, False)
            if blocked:
                consecutive_blocked += 1
                print("  YouTubeにIPブロックされています（スキップ）", file=sys.stderr)
                if consecutive_blocked >= 3:
                    print("3件連続IPブロック: 本日は字幕取得不可。翌日の実行で再試行します。")
                    break
                time.sleep(10)
                continue
            consecutive_blocked = 0
            if transcript:
                print(f"  字幕: {len(transcript)}文字")
            else:
                print("  字幕なし（タイトルから生成）")
            if FORCE_ALL and not transcript:
                # FORCE_ALLは「字幕ベースで再生成する」モード。
                # 字幕が取れない動画はタイトルから上書きせず、翌日に再試行する
                print("  FORCE_ALL: 字幕なしのためスキップ（既存の要約を維持）")
                time.sleep(3)  # YouTubeへの連続アクセスを抑制
                continue

            result = generate_metadata(title, transcript, need_full)
            if result is None:
                print("  日次クォータ枯渇。処理を終了します。", file=sys.stderr)
                break
            changed = False
            if result.get("summary"):
                videos[idx]["summary"] = result["summary"]
                print(f"  要約: {result['summary']}")
                changed = True
            if need_full and result.get("categories"):
                videos[idx]["categories"] = result["categories"]
                print(f"  カテゴリ: {result['categories']}")
                changed = True
            if need_full and result.get("levels"):
                videos[idx]["levels"] = result["levels"]
                print(f"  レベル: {result['levels']}")
                changed = True
            if changed:
                updated += 1
                consecutive_failures = 0
                if FORCE_ALL:
                    videos[idx]["transcript_ok"] = True  # 処理済みマーク
            else:
                consecutive_failures += 1
                print("  生成失敗（スキップ）")
        except Exception as e:
            consecutive_failures += 1
            print(f"  エラー（スキップ）: {e}")

        # 5件連続失敗 = Geminiクォータ枯渇とみなして早期終了
        if consecutive_failures >= 5:
            print("5件連続失敗: Geminiクォータ枯渇と判断。翌日の実行で再試行します。")
            break

        # Gemini無料枠: 15RPM。FORCE_ALL時はYouTube字幕取得の間隔も空ける
        time.sleep(10 if FORCE_ALL else 5)

        # 10件ごとに中間保存
        if updated > 0 and updated % 10 == 0:
            write_videos_js(videos, rest)
            print(f"  (中間保存: {updated}件)")

    write_videos_js(videos, rest)
    print(f"\n完了: {updated}件の要約を追加しました")


if __name__ == "__main__":
    main()
