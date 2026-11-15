"""診断レポート生成スクリプト（整体院向け・A4 1枚）

使い方:
    python seitai/diagnosis/make_report.py seitai/diagnosis/samples/sample_input.json
    → 同じフォルダに <院名>_診断レポート.html を出力。
       ブラウザで開いて「印刷 → PDFに保存」（A4・余白なし）でPDFにする。

入力JSONの書き方は checklist.md を参照。標準ライブラリだけで動く。
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 点検項目の定義（checklist.md と対応。ここを変えたら checklist.md も直す）
# id: (領域, 項目名, なぜ大事か, 改善策の定型文)
# ---------------------------------------------------------------------------
AREAS = {
    "gmap": "Googleマップ",
    "hp": "ホームページ",
    "line": "LINE・予約",
}

ITEMS: dict[str, tuple[str, str, str, str]] = {
    "gm_hours": ("gmap", "営業時間・定休日が正しい",
                 "「営業中」と出て行ったら閉まっていた、が一番の失点になる",
                 "営業時間・臨時休業をマップに反映し、毎月確認する"),
    "gm_photos": ("gmap", "写真が十分にある（10枚以上・1年以内）",
                  "初めての人は写真で院の雰囲気と清潔さを判断する",
                  "外観・入口・施術室・院長の写真を撮り直して掲載する"),
    "gm_reply": ("gmap", "口コミに返信している",
                 "返信がある院は「ちゃんと見てくれる」印象になる",
                 "すべての口コミにお礼と一言の返信を付ける"),
    "gm_website": ("gmap", "ホームページへのリンクがある",
                   "マップで見つけた人が詳しい情報にたどり着けない",
                   "マップに公式ホームページのURLを登録する"),
    "gm_booking": ("gmap", "予約リンクがある",
                   "見つけたその場で予約できないと、他院に流れる",
                   "マップの予約リンクにLINE予約を登録する"),
    "gm_desc": ("gmap", "説明文・メニューが入っている",
                "何をしてくれる院か分からないと比較の土俵に乗らない",
                "院の特徴・対象の悩み・料金をマップの説明に入れる"),
    "hp_exists": ("hp", "自院のホームページがある",
                  "ポータルサイトだけだと掲載料に依存し続けることになる",
                  "5ページ前後の自院ホームページを用意する"),
    "hp_mobile": ("hp", "スマホで読みやすい",
                  "整体院を探す人の大半はスマホから見ている",
                  "スマホ表示に対応したデザインに作り直す"),
    "hp_price": ("hp", "料金が明記されている",
                 "料金が分からない院は不安で予約されにくい",
                 "初回料金・通常料金・回数券を表で明記する"),
    "hp_first": ("hp", "初回の流れ・所要時間が分かる",
                 "初めての人の「何をされるか分からない」不安を消す",
                 "初回の流れを5ステップ程度で写真付きで載せる"),
    "hp_cta": ("hp", "予約まで1タップで行ける",
               "予約の手間が1つ増えるごとに離脱が増える",
               "スマホ画面の下に電話・LINE予約ボタンを常に表示する"),
    "hp_fresh": ("hp", "情報が新しい",
                 "古いお知らせが残っていると「営業しているのか」と不安になる",
                 "古いお知らせを整理し、営業時間・料金を最新にする"),
    "hp_ssl": ("hp", "安全な接続（鍵マーク・https）",
               "ブラウザに「保護されていない通信」と表示される",
               "SSL（https）を有効にする"),
    "ln_account": ("line", "LINE公式アカウントがある",
                   "来店したお客様と、次につながる連絡手段がない",
                   "LINE公式アカウントを開設し、院内とHPで案内する"),
    "ln_link": ("line", "HP・マップからLINEへの導線がある",
                "アカウントがあっても見つけてもらえず、友だちが増えない",
                "HP・マップ・院内POPにLINEの友だち追加ボタンを置く"),
    "ln_online": ("line", "自院のネット予約ができる",
                  "電話だけだと施術中の予約を取りこぼす",
                  "LINEから空き枠を見て予約できるようにする"),
    "ln_follow": ("line", "来店後のフォロー配信がある",
                  "2回目の来店を促す仕組みがないと新規集客に頼り続ける",
                  "来店翌日のお礼と1か月後の案内をLINEで自動配信する"),
}

# 「×」のときに改善ポイントの見出しとして使う文言
PROBLEM = {
    "gm_hours": "Googleマップの営業時間が実際と違う",
    "gm_photos": "Googleマップの写真が少ない・古い",
    "gm_reply": "口コミに返信していない",
    "gm_website": "Googleマップからホームページに行けない",
    "gm_booking": "Googleマップから予約できない",
    "gm_desc": "Googleマップに院の説明・メニューがない",
    "hp_exists": "自院のホームページがない",
    "hp_mobile": "ホームページがスマホで読みにくい",
    "hp_price": "ホームページに料金が書かれていない",
    "hp_first": "初回の流れ・所要時間が分からない",
    "hp_cta": "ホームページから予約までが遠い",
    "hp_fresh": "ホームページの情報が古い",
    "hp_ssl": "ホームページが「保護されていない通信」になっている",
    "ln_account": "LINE公式アカウントがない",
    "ln_link": "LINEへの入口が見つからない",
    "ln_online": "電話以外で予約できない",
    "ln_follow": "来店後のフォローの仕組みがない",
}
assert set(PROBLEM) == set(ITEMS)

STATUS = {
    # status: (記号, 表示名, 点数, CSSクラス)
    "ok": ("◎", "できている", 2, "ok"),
    "warn": ("△", "もう一歩", 1, "warn"),
    "ng": ("×", "未対応", 0, "ng"),
    "unknown": ("？", "要確認", None, "unknown"),
}


def area_score(checks: dict[str, dict]) -> dict[str, int | None]:
    """領域ごとの点数（100点換算）。要確認の項目は計算から除く。"""
    result = {}
    for area in AREAS:
        pts = [STATUS[c["status"]][2] for iid, c in checks.items()
               if ITEMS[iid][0] == area and STATUS[c["status"]][2] is not None]
        result[area] = round(sum(pts) / (len(pts) * 2) * 100) if pts else None
    return result


def pick_top_issues(data: dict, checks: dict[str, dict]) -> list[dict]:
    """改善ポイント3つ。JSONで指定があればそれを使い、なければ×→△の順で自動選定。"""
    if data.get("top_issues"):
        return data["top_issues"][:3]
    order = [iid for iid in ITEMS if checks[iid]["status"] == "ng"]
    order += [iid for iid in ITEMS if checks[iid]["status"] == "warn"]
    issues = []
    for iid in order[:3]:
        _, label, why, fix = ITEMS[iid]
        note = checks[iid].get("note", "")
        issues.append({
            "title": PROBLEM[iid] if checks[iid]["status"] == "ng" else f"{label}（もう一歩）",
            "detail": f"{note}。{why}。" if note else f"{why}。",
            "fix": fix,
        })
    return issues


def load(path: Path) -> tuple[dict, dict[str, dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    checks: dict[str, dict] = {}
    for iid in ITEMS:
        c = data.get("checks", {}).get(iid, {"status": "unknown"})
        if isinstance(c, str):
            c = {"status": c}
        if c.get("status") not in STATUS:
            raise ValueError(f"{iid}: status は ok / warn / ng / unknown のどれか（入力: {c.get('status')}）")
        checks[iid] = c
    unknown_ids = set(data.get("checks", {})) - set(ITEMS)
    if unknown_ids:
        raise ValueError(f"定義にない項目IDがあります: {sorted(unknown_ids)}")
    return data, checks


def render(data: dict, checks: dict[str, dict]) -> str:
    e = html.escape
    scores = area_score(checks)
    issues = pick_top_issues(data, checks)

    area_blocks = []
    for area, area_name in AREAS.items():
        rows = []
        for iid, (a, label, _, _) in ITEMS.items():
            if a != area:
                continue
            c = checks[iid]
            mark, sname, _, cls = STATUS[c["status"]]
            note = f'<div class="note">{e(c["note"])}</div>' if c.get("note") else ""
            rows.append(f'<li class="{cls}"><span class="mark">{mark}</span>'
                        f'<div><div class="label">{e(label)}</div>{note}</div></li>')
        s = scores[area]
        score_txt = f"{s}<small>点</small>" if s is not None else "—"
        area_blocks.append(
            f'<div class="area"><div class="area-head"><h3>{e(area_name)}</h3>'
            f'<div class="score">{score_txt}</div></div><ul>{"".join(rows)}</ul></div>')

    issue_blocks = []
    for i, it in enumerate(issues, 1):
        issue_blocks.append(
            f'<div class="issue"><div class="num">{i}</div><div>'
            f'<div class="issue-title">{e(it["title"])}</div>'
            f'<div class="issue-detail">{e(it["detail"])}</div>'
            f'<div class="issue-fix">→ {e(it["fix"])}</div></div></div>')

    sim_html = ""
    sim = data.get("simulation")
    if sim:
        price = int(sim["unit_price"])
        plus = int(sim["extra_repeat_per_month"])
        monthly = price * plus
        sim_html = (
            '<div class="sim"><h2>試算：2回目の来店が増えると</h2>'
            f'<p>2回目の来店が<strong>月{plus}人</strong>増えた場合（1回{price:,}円として）'
            f'<span class="big">月 +{monthly:,}円 ／ 年 +{monthly * 12:,}円</span></p>'
            '<p class="caveat">※仮の数字による試算で、成果を保証するものではありません。'
            '実際の数字は導入前後の予約数で一緒に確認します。</p></div>')

    sender = data.get("sender", {})
    unknown_note = ""
    if any(c["status"] == "unknown" for c in checks.values()):
        unknown_note = "「？」は外から確認できない項目です。お話の中で伺わせてください。"

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<title>{e(data['clinic_name'])} 様 Web集客診断レポート</title>
<style>{CSS}</style></head>
<body><div class="page">
<header>
  <div>
    <div class="kicker">無料 Web集客診断レポート</div>
    <h1>{e(data['clinic_name'])} 様</h1>
    <div class="meta">{e(data.get('area', ''))}　｜　確認日 {e(data['checked_on'])}　｜　公開情報をもとに確認</div>
  </div>
  <div class="legend">◎ できている　△ もう一歩　× 未対応　？ 要確認</div>
</header>

<p class="summary">{e(data.get('summary', ''))}</p>

<section class="areas">{''.join(area_blocks)}</section>

<section>
  <h2>まず手を付けたい3つ</h2>
  <div class="issues">{''.join(issue_blocks)}</div>
</section>

{sim_html}

<footer>
  <div class="next">
    <strong>次のステップ</strong>　15〜30分のオンライン面談で、改善の進め方と見本をお見せします。<br>
    料金は月額制・縛りなし・解約はいつでも可能、ホームページのドメインは院の名義で取得します。{e(unknown_note)}
  </div>
  <div class="sender">{e(sender.get('name', ''))}<br>{e(sender.get('contact', ''))}</div>
</footer>
</div></body></html>
"""


CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Hiragino Kaku Gothic ProN","Noto Sans JP","Yu Gothic",sans-serif;
       color: #222; background: #eee; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 210mm; height: 297mm; margin: 0 auto; background: #fff; padding: 10mm 12mm 8mm;
        display: flex; flex-direction: column; gap: 3.5mm; overflow: hidden; }
@media print { body { background: #fff; } .page { margin: 0; } }
header { display: flex; justify-content: space-between; align-items: flex-end;
         border-bottom: 3px solid #2f7d6d; padding-bottom: 3mm; }
.kicker { color: #2f7d6d; font-weight: 700; font-size: 10pt; letter-spacing: .1em; }
h1 { margin: 1mm 0; font-size: 20pt; }
.meta { font-size: 8pt; color: #666; }
.legend { font-size: 8pt; color: #666; white-space: nowrap; }
.summary { margin: 0; font-size: 9.5pt; line-height: 1.6; background: #f1f7f5; padding: 3mm 4mm;
           border-left: 4px solid #2f7d6d; }
h2 { font-size: 12pt; margin: 0 0 2mm; color: #1f5a4e; }
.areas { display: grid; grid-template-columns: repeat(3, 1fr); gap: 3mm; }
.area { border: 1px solid #ddd; border-radius: 3mm; padding: 3mm; }
.area-head { display: flex; justify-content: space-between; align-items: baseline;
             border-bottom: 1px solid #eee; padding-bottom: 1.5mm; margin-bottom: 1.5mm; }
.area h3 { margin: 0; font-size: 11pt; }
.score { font-size: 16pt; font-weight: 700; color: #2f7d6d; }
.score small { font-size: 8pt; }
.area ul { list-style: none; margin: 0; padding: 0; }
.area li { display: grid; grid-template-columns: 5mm 1fr; gap: 1.5mm; padding: 1mm 0;
           border-bottom: 1px dashed #eee; font-size: 8.5pt; line-height: 1.45; }
.area li:last-child { border-bottom: 0; }
.mark { font-weight: 700; text-align: center; }
.ok .mark { color: #2f7d6d; } .warn .mark { color: #d08a1e; }
.ng .mark { color: #c8402e; } .unknown .mark { color: #888; }
.note { color: #777; font-size: 7.5pt; }
.issues { display: grid; gap: 2mm; }
.issue { display: grid; grid-template-columns: 8mm 1fr; gap: 3mm; border: 1px solid #e6d3c0;
         background: #fffaf3; border-radius: 3mm; padding: 2.5mm 3mm; }
.num { width: 8mm; height: 8mm; border-radius: 50%; background: #c8402e; color: #fff;
       display: flex; align-items: center; justify-content: center; font-weight: 700; }
.issue-title { font-weight: 700; font-size: 10.5pt; }
.issue-detail { font-size: 8.5pt; color: #555; line-height: 1.5; }
.issue-fix { font-size: 9pt; color: #1f5a4e; font-weight: 700; margin-top: .5mm; }
.sim { background: #1f5a4e; color: #fff; border-radius: 3mm; padding: 3mm 4mm; }
.sim h2 { color: #fff; }
.sim p { margin: 0; font-size: 9.5pt; }
.sim .big { display: block; font-size: 16pt; font-weight: 700; margin: 1mm 0; }
.sim .caveat { font-size: 7.5pt; opacity: .85; }
footer { margin-top: auto; display: flex; justify-content: space-between; gap: 6mm;
         border-top: 1px solid #ddd; padding-top: 3mm; font-size: 8.5pt; line-height: 1.6; }
.sender { text-align: right; max-width: 62mm; color: #444; }
"""


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    src = Path(sys.argv[1])
    data, checks = load(src)
    out = src.with_name(f"{data['clinic_name']}_診断レポート.html")
    out.write_text(render(data, checks), encoding="utf-8")
    print(f"出力: {out}")


if __name__ == "__main__":
    main()
