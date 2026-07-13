"""
メンバー限定動画の「公開日」を実際のメンバー版公開日に補正する。

背景:
  メンバー限定動画は、よすがが Discord に貼る用の「限定公開(unlisted)コピー」の
  URL / vid_id で登録されている。この限定コピーの YouTube 投稿日（= Discord に
  出した日）が videos.js の date になっているが、これは本チャンネルで実際に
  メンバーへ公開された日（メンバー版動画の公開日）とズレることがある。

対応:
  チャンネルの「動画」タブ（メンバー版も公開表示される）をページネーション付きで
  スクレイピングし、[タイトル -> メンバー版vid_id] を作る。videos.js の各メンバー
  動画をタイトル完全一致で照合し、別IDのメンバー版が見つかれば、その publishedAt を
  YouTube Data API で取得して date を上書きする。

  ※ タイトルが一致しない/チャンネルに残っていない動画は変更しない（安全側）。
  ※ スクレイピングが失敗しても pipeline を止めないよう、例外は握りつぶす。
"""

import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
import update_videos as uv  # read_videos_js / write_videos_js / 定数を再利用

INNERTUBE_BROWSE = "https://www.youtube.com/youtubei/v1/browse"
MAX_PAGES = 70  # 1ページ約30本 → 最大約2100本（全動画を確実にカバー）

# 自動補正で拾えないイレギュラー動画の手動指定（vid_id -> 正しい公開日）。
# 例: 元動画と同名で9/15にも再公開されており、チャンネル走査で元版が特定できないもの。
MANUAL_DATE_OVERRIDES = {
    "mbii2hXJzwY": "2022-12-21",  # 正直に答えます「FXって楽に稼げるんでしょ？」【コラム動画】
    # 「10万→1000万」ライブ配信企画（#0〜#12.5）。メンバー版の実際のライブ配信日に手動固定。
    "wFjOER3w9Ig": "2023-06-21",  # #0 10万→1000万にする
    "AXcasWro9J0": "2023-07-05",  # #1 10万→1000万にする
    "LNePlXjMJlE": "2023-07-12",  # #2 10万→1000万にする
    "_z8mWhaJ3ms": "2023-07-19",  # #3 10万→1000万にする
    "vHgeqfPgsIo": "2023-07-26",  # #4 10万→1000万にする
    "w44E1vymFNg": "2023-08-02",  # #5 10万→1000万にする
    "z8hV14oWCIA": "2023-08-09",  # #6 10万→1000万にする
    "o74CauRB1eI": "2023-08-16",  # #7 200万達成を皆で見守る会
    "QWQieHRkRCM": "2023-08-23",  # #8 さて、あといくらかな…？
    "OP3WHTOmRZY": "2023-09-06",  # #9 アストロトレーダーを知ってるかい？
    "silWs6trsUQ": "2023-09-14",  # #10 オートライン、結構革命じゃない？
    "koK8UtYMNJc": "2023-09-20",  # #11 これで皆シナリオ構築マスター
    "d9r15v17DA8": "2023-09-25",  # #12 明日から強化合宿です
    "-jgTEUJpHc0": "2023-09-30",  # #12.5 強化合宿がヤバかった
    "2bpljB4sKI4": "2023-10-06",  # #ラスト 10万→604万でFINISH
    # 「10万→1000万」以前の過去ライブ配信（手動追加・メンバー版の実際の公開日に固定）
    "Nbuky8i7omk": "2022-12-09",  # ここが始まりの地
    "boRHzCBsMTY": "2022-12-25",  # 今年を振り返って来年に備える（Discord投稿=メンバー版ID）
}


def _balanced_json(html: str, anchor: str) -> dict | None:
    i = html.find(anchor)
    if i < 0:
        return None
    start = html.find("{", i)
    depth = 0
    in_str = False
    esc = False
    for j, ch in enumerate(html[start:], start):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : j + 1])
                except Exception:
                    return None
    return None


def _extract_videos(node, out: list, seen: set) -> None:
    """ytInitialData / browse レスポンスから lockupViewModel(新) を集める。"""
    if isinstance(node, dict):
        lv = node.get("lockupViewModel")
        if isinstance(lv, dict):
            vid = lv.get("contentId", "")
            title = (
                lv.get("metadata", {})
                .get("lockupMetadataViewModel", {})
                .get("title", {})
                .get("content", "")
            )
            if vid and title and len(vid) == 11 and "/" not in vid and vid not in seen:
                seen.add(vid)
                out.append((vid, title))
        # 旧形式のフォールバック
        vr = node.get("videoRenderer")
        if isinstance(vr, dict) and vr.get("videoId"):
            runs = vr.get("title", {}).get("runs", [])
            title = runs[0].get("text", "") if runs else ""
            if vr["videoId"] not in seen and title:
                seen.add(vr["videoId"])
                out.append((vr["videoId"], title))
        for v in node.values():
            _extract_videos(v, out, seen)
    elif isinstance(node, list):
        for v in node:
            _extract_videos(v, out, seen)


def _find_continuation(node):
    if isinstance(node, dict):
        cc = node.get("continuationCommand")
        if isinstance(cc, dict) and cc.get("token"):
            return cc["token"]
        for v in node.values():
            t = _find_continuation(v)
            if t:
                return t
    elif isinstance(node, list):
        for v in node:
            t = _find_continuation(v)
            if t:
                return t
    return None


def scrape_all_channel_videos() -> list[tuple[str, str]]:
    """チャンネル「動画」タブを継続トークンで全ページ走査して [(vid, title)] を返す。"""
    try:
        r = requests.get(uv.CHANNEL_VIDEOS_URL, headers=uv.REQUEST_HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"  WARNING: チャンネルページ取得失敗: {e}", file=sys.stderr)
        return []

    html = r.text
    data = _balanced_json(html, "ytInitialData")
    if not data:
        print("  WARNING: ytInitialData 取得失敗", file=sys.stderr)
        return []

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    _extract_videos(data, out, seen)
    token = _find_continuation(data)

    key_m = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html)
    ver_m = re.search(r'"INNERTUBE_CONTEXT_CLIENT_VERSION":"([^"]+)"', html) or re.search(
        r'"clientVersion":"([^"]+)"', html
    )
    if not (key_m and ver_m):
        return out  # 継続不可でも初期30件は返す

    key = key_m.group(1)
    ctx = {"client": {"clientName": "WEB", "clientVersion": ver_m.group(1), "hl": "ja", "gl": "JP"}}
    headers = {**uv.REQUEST_HEADERS, "Content-Type": "application/json"}

    page = 0
    while token and page < MAX_PAGES:
        page += 1
        j = None
        for attempt in range(3):  # 継続取得は稀に失敗するのでリトライ
            try:
                resp = requests.post(
                    f"{INNERTUBE_BROWSE}?key={key}",
                    headers=headers,
                    json={"context": ctx, "continuation": token},
                    timeout=30,
                )
                j = resp.json()
                break
            except Exception:
                time.sleep(1.5)
        if j is None:
            print(f"  WARNING: 継続取得失敗(page {page}) — 打ち切り", file=sys.stderr)
            break
        before = len(out)
        _extract_videos(j, out, seen)
        token = _find_continuation(j)
        time.sleep(0.4)  # レート制限回避
        if len(out) == before and not token:
            break

    return out


def main() -> None:
    videos, rest = uv.read_videos_js()
    members = [v for v in videos if v.get("method") == "メンバーシップ限定公開"]
    if not members:
        print("メンバー動画なし")
        return

    scraped = scrape_all_channel_videos()
    print(f"チャンネルから {len(scraped)}本を取得")
    if not scraped:
        print("スクレイピング0件のため補正スキップ")
        return

    # 正規化タイトル -> そのタイトルの全vid_id（同一動画の再アップ違いも束ねる）
    # 記号・空白を除去して英数字＋日本語だけ残す。日付番号は残るので週次動画も区別できる。
    def norm(t: str) -> str:
        return re.sub(r"[^0-9A-Za-z぀-ヿ一-鿿]", "", t or "")

    norm_map: dict[str, set] = {}
    for vid, title in scraped:
        norm_map.setdefault(norm(title), set()).add(vid)

    # 各メンバー動画について、同一タイトルの別ID候補を集める
    # （その中で最も古い publishedAt = 本来の公開日）
    candidates = []  # (video_entry, [other_ids])
    for v in members:
        others = norm_map.get(norm(v.get("title") or ""), set()) - {v.get("vid_id")}
        if others:
            candidates.append((v, list(others)))

    print(f"同一タイトルの別バージョンが見つかった動画: {len(candidates)}本")
    if not candidates:
        return

    # 候補IDの publishedAt をまとめて取得
    all_ids = list({i for _, ids in candidates for i in ids})
    pub: dict[str, str] = {}
    for i in range(0, len(all_ids), 50):
        chunk = all_ids[i : i + 50]
        try:
            rr = requests.get(
                "https://www.googleapis.com/youtube/v3/videos"
                f"?part=snippet&id={','.join(chunk)}&key={uv.YOUTUBE_API_KEY}",
                timeout=30,
            ).json()
        except Exception as e:
            print(f"  WARNING: publishedAt取得失敗: {e}", file=sys.stderr)
            continue
        for it in rr.get("items", []):
            pub[it["id"]] = it["snippet"]["publishedAt"][:10]

    changed = 0
    for v, ids in candidates:
        # 現在の date（=Discordコピーの投稿日）と別バージョンの中で最古の日付を採用。
        # 日付を後ろにずらすことはせず、より古い「本来の公開日」が見つかった時だけ上書き。
        found = sorted(pub[i] for i in ids if i in pub)
        if not found:
            continue
        oldest = found[0]
        if oldest < (v.get("date") or "9999"):
            print(f"  {v['date']} -> {oldest} | {v['title'][:40]}")
            v["date"] = oldest
            changed += 1

    # 手動オーバーライド（自動で拾えないイレギュラー動画）
    for v in videos:
        ov = MANUAL_DATE_OVERRIDES.get(v.get("vid_id"))
        if ov and v.get("date") != ov:
            print(f"  [手動] {v['date']} -> {ov} | {v['title'][:40]}")
            v["date"] = ov
            changed += 1

    if changed:
        # 並び順は変えず date だけ更新（表示順はクライアント側でソートされる）
        uv.write_videos_js(videos, rest)
        print(f"{changed}本の公開日を本来の公開日に補正しました")
    else:
        print("補正対象なし（全て一致）")


if __name__ == "__main__":
    main()
