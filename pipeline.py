"""
AMPS（AI Music Production System）のパイプライン制御モジュール。

エージェントの実行順序（ステータスマシン）、各エージェント出力のパース、
songs/ 以下への成果物保存、品質チェック不合格時の再制作ループを担当する。

エージェントの振る舞い・出力フォーマットそのものは agents/*.md にのみ書かれており、
このモジュールはその成果物を「受け渡す・保存する・パースする」だけに徹する。
"""

import re
from datetime import datetime
from pathlib import Path

import config
import db
from agents import runner

# song_idごとのフォルダ名スラッグをキャッシュする（romanize_slugの呼び出しを最小限にする）
_slug_cache: dict[int, str] = {}


# =================================================================
# パーサー
# =================================================================


def parse_title(brief_text: str) -> str:
    """
    企画ブリーフの本文からタイトルを抽出する。
    `# 制作ブリーフ：帰り道（仮）` のような見出し行から「帰り道（仮）」を取り出す。
    見出しはあるがコロンが無い場合は見出しテキストそのものを返す。
    見出しすら見つからない場合は "無題" を返す。
    """
    if not brief_text:
        return "無題"
    for line in brief_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        heading = stripped.lstrip("#").strip()
        if not heading:
            continue
        for sep in ("：", ":"):
            if sep in heading:
                return heading.split(sep, 1)[1].strip()
        return heading
    return "無題"


def parse_genre(brief_text: str) -> str | None:
    """
    企画ブリーフの本文から `ジャンル：ラブソング` のような行を探し、
    config.GENRES に定義された正規の日本語ラベルを返す。
    見つからなければ None。
    """
    if not brief_text:
        return None
    for line in brief_text.splitlines():
        if "ジャンル" not in line:
            continue
        for sep in ("：", ":"):
            if sep not in line:
                continue
            value = line.split(sep, 1)[1].strip()
            for label in config.GENRES.values():
                if label in value:
                    return label
    return None


def parse_composition(composition_text: str) -> tuple[int | None, str | None, str | None]:
    """
    楽曲設計の本文から (bpm, key, structure) を抽出する。
    それぞれ見つからない場合は None を返す（例外は送出しない）。
    """
    bpm: int | None = None
    key: str | None = None
    structure: str | None = None
    if not composition_text:
        return bpm, key, structure

    lines = composition_text.splitlines()

    for line in lines:
        if bpm is None and "BPM" in line:
            m = re.search(r"\d+", line)
            if m:
                bpm = int(m.group())
        if key is None and re.search(r"key", line, re.IGNORECASE):
            for sep in ("：", ":"):
                if sep in line:
                    candidate = line.split(sep, 1)[1].strip()
                    if candidate:
                        key = candidate
                    break

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") and "構成" in stripped:
            for following in lines[i + 1 :]:
                if following.strip():
                    structure = following.strip()
                    break
            break

    return bpm, key, structure


def parse_suno_prompt(prompt_text: str) -> tuple[str, str]:
    """
    Sunoプロンプトの本文から (style_prompt, formatted_lyrics) を抽出する。
    `Style Prompt` / `Formatted Lyrics` を含む見出し行で緩く分割する。
    分割に失敗した場合は (本文全体, "") を返す。
    """
    if not prompt_text:
        return prompt_text or "", ""

    lines = prompt_text.splitlines()
    style_start = None
    lyrics_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if style_start is None and "Style Prompt" in stripped:
            style_start = i
        elif lyrics_start is None and "Formatted Lyrics" in stripped:
            lyrics_start = i

    if style_start is None or lyrics_start is None:
        return prompt_text.strip(), ""

    style_prompt = "\n".join(lines[style_start + 1 : lyrics_start]).strip()
    formatted_lyrics = "\n".join(lines[lyrics_start + 1 :]).strip()
    return style_prompt, formatted_lyrics


def _parse_markdown_table_rows(text: str) -> list[list[str]]:
    """
    Markdownテーブルの行を `|` で分割したセルのリストとして返す。
    区切り行（|---|---|...）は除外する。
    """
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        inner = stripped.strip("|")
        if re.fullmatch(r"[\s\-:|]+", inner):
            continue
        cells = [c.strip().strip("*").strip() for c in inner.split("|")]
        rows.append(cells)
    return rows


def parse_quality_review(review_text: str) -> tuple[int, list[dict], str, str]:
    """
    品質レビューの本文から (score, breakdown, verdict, notes) を抽出する。

    score: 0〜100点。合計行 → `合計：NN` 表記 → `NN/100` 表記 → 0 の優先順位で探す。
    breakdown: 採点表の各行を {"item","max","score","comment"} の辞書にしたリスト。
    verdict: "合格" / "再制作"。判定行が無ければスコアから推定する。
    notes: 判定行以降のテキスト（改善指示など）。
    """
    if not review_text:
        return 0, [], "", ""

    lines = review_text.splitlines()

    # --- score ---
    score: int | None = None
    for line in lines:
        if "合計" in line:
            nums = [int(x) for x in re.findall(r"\d+", line)]
            if nums:
                if len(nums) >= 2 and 100 in nums:
                    nums = nums.copy()
                    nums.remove(100)  # 配点列の100点満点表記を1つだけ除外
                if nums:
                    score = nums[-1]
            break
    if score is None:
        m = re.search(r"合計[：:]\s*(\d+)", review_text)
        if m:
            score = int(m.group(1))
    if score is None:
        m = re.search(r"(\d+)\s*/\s*100", review_text)
        if m:
            score = int(m.group(1))
    if score is None:
        score = 0

    # --- breakdown ---
    breakdown: list[dict] = []
    for cells in _parse_markdown_table_rows(review_text):
        if len(cells) < 3:
            continue
        item = cells[0]
        if not item or item == "項目" or "合計" in item:
            continue
        try:
            max_score = int(re.sub(r"\D", "", cells[1]))
            got_score = int(re.sub(r"\D", "", cells[2]))
        except ValueError:
            continue
        comment = cells[3] if len(cells) > 3 else ""
        breakdown.append(
            {"item": item, "max": max_score, "score": got_score, "comment": comment}
        )

    # --- verdict / notes ---
    verdict = ""
    notes = ""
    for i, line in enumerate(lines):
        if "判定" not in line:
            continue
        if "再制作" in line or "不合格" in line:
            verdict = "再制作"
        elif "合格" in line:
            verdict = "合格"
        notes = "\n".join(lines[i:]).strip()
        break
    if not verdict:
        verdict = "合格" if score >= config.QC_PASS_SCORE else "再制作"

    return score, breakdown, verdict, notes


def parse_retarget_agent(review_text: str) -> str:
    """
    品質チェックの不合格時に、どのエージェントを再実行すべきか判定する。
    "lyrics_agent" または "composition_agent" のいずれかを返す（例外は送出しない）。
    """
    if not review_text:
        return "lyrics_agent"

    for line in review_text.splitlines():
        if "対象エージェント" not in line:
            continue
        has_lyrics = ("Lyrics" in line) or ("歌詞" in line)
        has_composition = any(k in line for k in ("Composition", "構成", "作曲"))
        if has_lyrics and not has_composition:
            return "lyrics_agent"
        if has_composition and not has_lyrics:
            return "composition_agent"
        break

    _, breakdown, _, _ = parse_quality_review(review_text)
    lyric_keywords = ("歌詞", "歌いやす", "中毒", "独自")
    composition_keywords = ("メロディ", "構成", "Spotify", "TikTok")
    lyric_lost = 0
    composition_lost = 0
    for row in breakdown:
        lost = row.get("max", 0) - row.get("score", 0)
        item = row.get("item", "")
        if any(k in item for k in lyric_keywords):
            lyric_lost += lost
        elif any(k in item for k in composition_keywords):
            composition_lost += lost

    if composition_lost > lyric_lost:
        return "composition_agent"
    return "lyrics_agent"


# =================================================================
# ファイル出力
# =================================================================


def _latest_reject_comment(song_id: int) -> str:
    """
    直近の差し戻し（human_review）コメントのうち、まだ作詞に反映されていないものを返す。

    最後の差し戻しが最後の lyrics_agent 実行より後であれば「未反映」とみなす。
    これにより、一度反映したコメントが以降の再実行で毎回蒸し返されるのを防ぐ。
    反映すべきコメントが無ければ空文字を返す。
    """
    runs = db.list_agent_runs(song_id)
    last_reject = -1
    last_lyrics = -1
    for i, run in enumerate(runs):
        agent = run.get("agent")
        if agent == "human_review":
            last_reject = i
        elif agent == "lyrics_agent":
            last_lyrics = i

    if last_reject >= 0 and last_reject > last_lyrics:
        return runs[last_reject].get("input_summary") or ""
    return ""


def _month_folder_for(song: dict) -> str:
    """楽曲のcreated_atから `YYYY-MM` を求める。日付らしくなければ現在のローカル日付を使う。"""
    created_at = song.get("created_at") or ""
    if len(created_at) >= 7 and created_at[:4].isdigit() and created_at[4] == "-":
        return created_at[:7]
    return datetime.now().strftime("%Y-%m")


def _slug_for(song_id: int, theme: str) -> str:
    """song_idごとにフォルダ名スラッグをキャッシュしつつ取得する。"""
    if song_id not in _slug_cache:
        _slug_cache[song_id] = runner.romanize_slug(theme or "", fallback=f"song{song_id}")
    return _slug_cache[song_id]


def song_dir(song_id: int, create: bool = True) -> Path | None:
    """
    楽曲の成果物保存先フォルダ（songs/{YYYY-MM}/{NNN}_{slug}/）を返す。
    既に採番済みのフォルダがあればそれを再利用する。

    create=True（既定）: 未作成なら新規採番して作成する。
    create=False: 参照のみ。未作成の場合はフォルダを作らずNoneを返す。
        （ダッシュボードの閲覧など、副作用で空フォルダを作りたくない用途で使う）
    """
    song = db.get_song(song_id)
    if song is None:
        raise ValueError(f"song_id={song_id} の楽曲が見つかりません。")

    month = _month_folder_for(song)
    month_dir = config.SONGS_DIR / month
    if not month_dir.exists():
        if not create:
            return None
        month_dir.mkdir(parents=True, exist_ok=True)

    # スラッグ確定にAPI呼び出しが要る場合があるため、参照のみのときは
    # マーカーファイルから逆引きしてAPI呼び出しを避ける
    if not create:
        for existing in sorted(month_dir.iterdir()):
            if not existing.is_dir():
                continue
            marker = existing / ".song_id"
            if marker.exists() and marker.read_text(encoding="utf-8").strip() == str(song_id):
                return existing
        return None

    slug = _slug_for(song_id, song.get("theme") or "")

    for existing in sorted(month_dir.glob(f"*_{slug}")):
        if not existing.is_dir():
            continue
        marker = existing / ".song_id"
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == str(song_id):
            return existing

    # 既存フォルダの連番の最大値+1を採番する（フォルダ削除があっても既存を上書きしない）
    max_seq = 0
    for existing in month_dir.iterdir():
        if not existing.is_dir():
            continue
        m = re.match(r"(\d+)_", existing.name)
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    seq = max_seq + 1
    new_dir = month_dir / f"{seq:03d}_{slug}"
    new_dir.mkdir(parents=True, exist_ok=True)
    (new_dir / ".song_id").write_text(str(song_id), encoding="utf-8")
    return new_dir


def write_artifact(song_id: int, filename: str, content: str) -> Path:
    """song_dir(song_id)/filename にUTF-8でcontentを書き込み、そのパスを返す。"""
    path = song_dir(song_id) / filename
    path.write_text(content, encoding="utf-8")
    return path


def _build_upstream_sections(*sections: tuple[str, str]) -> str:
    """(見出し, 本文) のペアをMarkdown見出し付きで連結し、次のエージェントへ渡す文章を作る。"""
    parts = [f"## {heading}\n{body.strip()}" for heading, body in sections]
    return "\n\n".join(parts)


# =================================================================
# メイン関数
# =================================================================


def advance(song_id: int) -> str:
    """
    楽曲の現在のステータスに応じて、次の1つのエージェントだけを実行する。
    成果物をDBとsongs/の両方に保存し、ステータスを更新して新しいステータスを返す。
    """
    song = db.get_song(song_id)
    if song is None:
        raise ValueError(f"song_id={song_id} の楽曲が見つかりません。")
    status = song["status"]

    if status == "planned":
        theme = song.get("theme") or ""
        genre_label = song.get("genre") or ""
        upstream = f"テーマ：{theme}\nジャンル：{genre_label}"
        brief_text = runner.run_agent("music_director_agent", upstream, song_id=song_id)
        db.save_brief(song_id, brief_text)
        write_artifact(song_id, "brief.md", brief_text)

        title = parse_title(brief_text)
        db.update_song_title(song_id, title)
        parsed_genre = parse_genre(brief_text)
        if parsed_genre is not None and parsed_genre in config.GENRES.values():
            db.update_song_genre(song_id, parsed_genre)

        db.update_status(song_id, "brief_done")
        return "brief_done"

    if status == "brief_done":
        brief_text = db.get_brief(song_id) or ""
        # 人による差し戻しコメントが未反映であれば、作詞エージェントへ申し送る
        reject_comment = _latest_reject_comment(song_id)
        extra_context = ""
        revision_notes = None
        if reject_comment:
            extra_context = (
                "前回の人によるレビューで差し戻されました。"
                f"次の指摘を反映して改稿してください：\n{reject_comment}"
            )
            revision_notes = f"人による差し戻しを反映：{reject_comment}"
        lyrics_text = runner.run_agent(
            "lyrics_agent", brief_text, extra_context=extra_context, song_id=song_id
        )
        db.save_lyrics(song_id, lyrics_text, revision_notes=revision_notes)
        write_artifact(song_id, "lyrics.md", lyrics_text)
        db.update_status(song_id, "lyrics_done")
        return "lyrics_done"

    if status == "lyrics_done":
        brief_text = db.get_brief(song_id) or ""
        lyrics_row = db.get_latest_lyrics(song_id) or {}
        upstream = _build_upstream_sections(
            ("制作ブリーフ", brief_text),
            ("歌詞", lyrics_row.get("content") or ""),
        )
        composition_text = runner.run_agent("composition_agent", upstream, song_id=song_id)
        bpm, key, structure = parse_composition(composition_text)
        db.save_composition(song_id, bpm, key, structure, composition_text)
        write_artifact(song_id, "composition.md", composition_text)
        db.update_status(song_id, "composed")
        return "composed"

    if status == "composed":
        brief_text = db.get_brief(song_id) or ""
        lyrics_row = db.get_latest_lyrics(song_id) or {}
        composition_row = db.get_composition(song_id) or {}
        upstream = _build_upstream_sections(
            ("制作ブリーフ", brief_text),
            ("歌詞", lyrics_row.get("content") or ""),
            ("楽曲設計", composition_row.get("content") or ""),
        )
        prompt_text = runner.run_agent("suno_prompt_agent", upstream, song_id=song_id)
        style_prompt, formatted_lyrics = parse_suno_prompt(prompt_text)
        db.save_prompt(song_id, style_prompt, formatted_lyrics)
        write_artifact(song_id, "suno_prompt.md", prompt_text)
        db.update_status(song_id, "prompted")
        return "prompted"

    if status == "prompted":
        lyrics_row = db.get_latest_lyrics(song_id) or {}
        composition_row = db.get_composition(song_id) or {}
        prompt_row = db.get_latest_prompt(song_id) or {}
        prompt_text = (
            f"## Style Prompt\n{prompt_row.get('style_prompt') or ''}\n\n"
            f"## Formatted Lyrics\n{prompt_row.get('formatted_lyrics') or ''}"
        )
        upstream = _build_upstream_sections(
            ("歌詞", lyrics_row.get("content") or ""),
            ("楽曲設計", composition_row.get("content") or ""),
            ("Sunoプロンプト", prompt_text),
        )
        review_text = runner.run_agent("quality_check_agent", upstream, song_id=song_id)
        next_round = len(db.list_reviews(song_id)) + 1
        score, breakdown, verdict, notes = parse_quality_review(review_text)
        db.save_review(song_id, next_round, score, breakdown, verdict, notes)
        write_artifact(song_id, "quality_review.md", review_text)
        db.update_status(song_id, "qc_pending")
        return "qc_pending"

    if status == "qc_pending":
        raise ValueError(
            "この楽曲は品質チェック待ち（qc_pending）です。"
            "人による承認（approve）または差し戻し（reject）が必要です。"
        )
    if status == "qc_passed":
        raise ValueError("この楽曲はすでに承認済み（qc_passed）で、工程は終了しています。")

    raise ValueError(f"未対応のステータスです: {status!r}")


def run_full(song_id: int, progress=None) -> dict:
    """
    楽曲の現在のステータスから qc_pending に達するまで一気に実行し、
    品質チェック不合格の場合は再制作ループ（最大 config.QC_MAX_RETRY 回）を回す。

    progress: 進捗を報告するための callable(message: str)。省略可能。
    戻り値: {"song_id", "status", "score", "rounds", "needs_improvement"}
    """

    def _report(message: str) -> None:
        if progress is None:
            return
        try:
            progress(message)
        except Exception:
            # 進捗コールバックの失敗でパイプライン本体を止めない
            pass

    song = db.get_song(song_id)
    if song is None:
        raise ValueError(f"song_id={song_id} の楽曲が見つかりません。")
    status = song["status"]

    step_messages = {
        "planned": "Music Director Agentで企画ブリーフを作成しています…",
        "brief_done": "Lyrics Agentで歌詞を作成しています…",
        "lyrics_done": "Composition Agentで楽曲設計をしています…",
        "composed": "Suno Prompt Agentでプロンプトを作成しています…",
        "prompted": "Quality Check Agentで品質チェックをしています…",
    }

    while status not in ("qc_pending", "qc_passed"):
        _report(step_messages.get(status, f"{status} を処理しています…"))
        status = advance(song_id)

    reviews = db.list_reviews(song_id)
    latest_review = reviews[-1] if reviews else None
    score = latest_review["score"] if latest_review else 0
    round_no = latest_review["round"] if latest_review else 1

    if status == "qc_passed":
        # 既に人による承認済み。再制作ループは回さない。
        return {
            "song_id": song_id,
            "status": status,
            "score": score,
            "rounds": round_no,
            "needs_improvement": False,
        }

    retry_count = 0
    while score < config.QC_PASS_SCORE and retry_count < config.QC_MAX_RETRY:
        review_path = song_dir(song_id) / "quality_review.md"
        review_text = (
            review_path.read_text(encoding="utf-8")
            if review_path.exists()
            else (latest_review.get("notes") if latest_review else "")
        )

        target = parse_retarget_agent(review_text)
        _report(
            f"品質チェックのスコアが基準未満（{score}点）のため、"
            f"{target} を再実行しています…"
        )

        brief_text = db.get_brief(song_id) or ""

        if target == "lyrics_agent":
            new_lyrics = runner.run_agent(
                "lyrics_agent", brief_text, extra_context=review_text, song_id=song_id
            )
            db.save_lyrics(
                song_id,
                new_lyrics,
                revision_notes=f"Review {round_no}回目の指摘を受けて改稿",
            )
            write_artifact(song_id, "lyrics.md", new_lyrics)

        if target == "composition_agent":
            lyrics_row = db.get_latest_lyrics(song_id) or {}
            composition_row = db.get_composition(song_id) or {}
            upstream = _build_upstream_sections(
                ("制作ブリーフ", brief_text),
                ("歌詞", lyrics_row.get("content") or ""),
                ("現在の楽曲設計", composition_row.get("content") or ""),
            )
            new_composition = runner.run_agent(
                "composition_agent", upstream, extra_context=review_text, song_id=song_id
            )
            bpm, key, structure = parse_composition(new_composition)
            db.save_composition(song_id, bpm, key, structure, new_composition)
            write_artifact(song_id, "composition.md", new_composition)

        # 歌詞・楽曲設計のどちらかが変わったので、Sunoプロンプトを作り直す
        lyrics_row = db.get_latest_lyrics(song_id) or {}
        composition_row = db.get_composition(song_id) or {}
        upstream = _build_upstream_sections(
            ("制作ブリーフ", brief_text),
            ("歌詞", lyrics_row.get("content") or ""),
            ("楽曲設計", composition_row.get("content") or ""),
        )
        _report("Suno Prompt Agentでプロンプトを再生成しています…")
        prompt_text = runner.run_agent("suno_prompt_agent", upstream, song_id=song_id)
        style_prompt, formatted_lyrics = parse_suno_prompt(prompt_text)
        db.save_prompt(song_id, style_prompt, formatted_lyrics)
        write_artifact(song_id, "suno_prompt.md", prompt_text)

        # 品質チェックを次のラウンドとして再実行する
        round_no += 1
        lyrics_row = db.get_latest_lyrics(song_id) or {}
        composition_row = db.get_composition(song_id) or {}
        upstream = _build_upstream_sections(
            ("歌詞", lyrics_row.get("content") or ""),
            ("楽曲設計", composition_row.get("content") or ""),
            ("Sunoプロンプト", prompt_text),
        )
        _report(f"Quality Check Agentで再評価しています（Review {round_no}回目）…")
        new_review_text = runner.run_agent("quality_check_agent", upstream, song_id=song_id)
        score, breakdown, verdict, notes = parse_quality_review(new_review_text)

        retry_count += 1
        is_last_allowed_retry = retry_count >= config.QC_MAX_RETRY
        if score < config.QC_PASS_SCORE and is_last_allowed_retry:
            # 要改善フラグ：DBに専用カラムは持たず、レビューのnotesに記録する
            marker = (
                f"[要改善フラグ] {config.QC_MAX_RETRY}回のレビューを終えてもスコアが"
                f"合格ライン（{config.QC_PASS_SCORE}点）未満です。人による重点確認を推奨します。"
            )
            notes = f"{notes}\n\n{marker}" if notes else marker

        db.save_review(song_id, round_no, score, breakdown, verdict, notes)
        write_artifact(song_id, "quality_review.md", new_review_text)
        latest_review = db.list_reviews(song_id)[-1]

    needs_improvement = score < config.QC_PASS_SCORE

    return {
        "song_id": song_id,
        "status": "qc_pending",
        "score": score,
        "rounds": round_no,
        "needs_improvement": needs_improvement,
    }


def approve(song_id: int) -> None:
    """人による承認ゲート。qc_pendingの楽曲のみ qc_passed にできる。"""
    song = db.get_song(song_id)
    if song is None:
        raise ValueError(f"song_id={song_id} の楽曲が見つかりません。")
    if song["status"] != "qc_pending":
        raise ValueError(
            f"承認できません。現在のステータスは {song['status']!r} です。"
            "品質チェック待ち（qc_pending）の楽曲のみ承認できます。"
        )
    db.update_status(song_id, "qc_passed")


def reject(song_id: int, comment: str = "") -> str:
    """
    人による差し戻し。qc_pendingの楽曲のみ受け付ける。

    ステータスを brief_done に戻すことで、次の実行で Lyrics → Composition →
    Suno Prompt → Quality Check がすべて再実行される（実装計画書のゴール
    「差戻しでLyrics・Compositionを再実行」に合わせている）。
    コメントは agent_runs に記録し、次回のLyrics実行時に申し送られる。
    戻り値は新しいステータス。
    """
    song = db.get_song(song_id)
    if song is None:
        raise ValueError(f"song_id={song_id} の楽曲が見つかりません。")
    if song["status"] != "qc_pending":
        raise ValueError(
            f"差し戻しできません。現在のステータスは {song['status']!r} です。"
            "品質チェック待ち（qc_pending）の楽曲のみ差し戻せます。"
        )
    db.log_agent_run(song_id, "human_review", comment, "差戻し")
    db.update_status(song_id, "brief_done")
    return "brief_done"


def start_song(theme: str, genre: str, week_of: str | None = None) -> int:
    """新しい楽曲レコードを status='planned' で作成し、song_idを返す。"""
    db.init_db()
    return db.create_song(title=theme, genre=genre, theme=theme, status="planned", week_of=week_of)
