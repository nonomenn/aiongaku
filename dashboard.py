"""
AMPS（AI Music Production System）Streamlitダッシュボード。

`streamlit run dashboard.py` で起動する。

- ホーム：全体サマリー・ジャンル比率・定期実行の手動トリガ
- 新規企画：テーマとジャンルを指定して制作パイプラインを実行する
- レビューキュー：品質チェック待ちの曲を確認し、承認／差し戻しする（人の承認ゲート）
- 曲詳細：1曲の成果物（ブリーフ・歌詞・楽曲設計・Sunoプロンプト・QC履歴・実行ログ）を閲覧する

APIキー（ANTHROPIC_API_KEY）が無くても起動・閲覧はできる。
パイプラインを実際に実行する操作（新規企画の制作開始・定期実行の手動トリガ）にのみAPIキーが必要。
エージェントの振る舞いはすべて agents/*.md 側の責務であり、このファイルには一切書かない。
"""

import hmac
import json

import streamlit as st

import config
import db
import pipeline
import scheduler

# =================================================================
# 初期設定
# =================================================================

st.set_page_config(page_title="AMPS ダッシュボード", page_icon="🎵", layout="wide")


def require_login() -> bool:
    """
    ログインゲート。アクセスを許可する場合にTrueを返す。

    - AUTH_REQUIREDがTrueなのにDASHBOARD_PASSWORDが未設定の場合は、
      設定不備としてアクセスを拒否する（フェイルクローズ）。
    - DASHBOARD_PASSWORDが未設定でAUTH_REQUIREDもFalseの場合は、
      ローカル利用とみなしてそのまま許可する（ただし警告は表示する）。
    - それ以外（パスワードが設定されている）はログインを必須にする。
    """
    if config.AUTH_REQUIRED and not config.DASHBOARD_PASSWORD:
        st.error(
            "このデプロイ環境ではログインが必須（AMPS_AUTH_REQUIRED=true）に"
            "設定されていますが、AMPS_DASHBOARD_PASSWORD が設定されていません。\n\n"
            "管理者はデプロイ環境の環境変数に AMPS_DASHBOARD_PASSWORD を設定してください。"
        )
        return False

    if not config.DASHBOARD_PASSWORD:
        st.sidebar.warning(
            "⚠️ 認証が無効になっています（AMPS_DASHBOARD_PASSWORDが未設定）。\n\n"
            "このままインターネットに公開しないでください。"
        )
        return True

    if st.session_state.get("authenticated", False):
        if st.sidebar.button("ログアウト"):
            st.session_state["authenticated"] = False
            st.rerun()
        return True

    st.title("🎵 AMPS ダッシュボード")
    st.subheader("ログイン")
    with st.form("login_form"):
        entered_password = st.text_input("パスワード", type="password")
        login_submitted = st.form_submit_button("ログイン")

    if login_submitted:
        if hmac.compare_digest(entered_password, config.DASHBOARD_PASSWORD):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("パスワードが違います。")

    return False


if not require_login():
    st.stop()

db.init_db()

STATUS_LABELS = {
    "planned": "企画済み",
    "brief_done": "ブリーフ完了",
    "lyrics_done": "作詞完了",
    "composed": "楽曲設計完了",
    "prompted": "プロンプト完了",
    "qc_pending": "品質チェック待ち",
    "qc_passed": "承認済み",
}


def status_label(status: str) -> str:
    """ステータスの生値を、日本語ラベル＋生値付きの読みやすい表記にする。"""
    label = STATUS_LABELS.get(status, status)
    return f"{label} ({status})"


def _score_display(score) -> str:
    """quality_scoreの表示用文字列。Noneなら "—"。"""
    return f"{score}点" if score is not None else "—"


def _render_breakdown_table(breakdown_json: str | None) -> list[dict]:
    """breakdown_jsonをパースし、表示用の行リストを返す（壊れたJSONは空リストにする）。"""
    if not breakdown_json:
        return []
    try:
        breakdown = json.loads(breakdown_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(breakdown, list):
        return []
    rows = []
    for item in breakdown:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "項目": item.get("item", ""),
                "配点": item.get("max", ""),
                "点数": item.get("score", ""),
                "コメント": item.get("comment", ""),
            }
        )
    return rows


def _show_suno_prompt_blocks(prompt: dict) -> None:
    """Sunoプロンプト（style_prompt / formatted_lyrics）を、コピーボタン付きで表示する。"""
    st.caption("各ブロック右上のコピーアイコンから、Sunoの該当欄へそのまま貼り付けできます。")
    st.markdown("**Style Prompt（Sunoのスタイル欄へ）**")
    st.code(prompt.get("style_prompt") or "", language=None)
    st.markdown("**歌詞（Sunoの歌詞欄へ）**")
    st.code(prompt.get("formatted_lyrics") or "", language=None)


# =================================================================
# サイドバー
# =================================================================

st.sidebar.title("AMPS ダッシュボード")

if not config.ANTHROPIC_API_KEY:
    st.sidebar.warning(
        "ANTHROPIC_API_KEY が設定されていません。\n\n"
        ".env.example を .env にコピーし、ANTHROPIC_API_KEY を設定してください。\n\n"
        "（APIキーが無くても既存データの閲覧はできます。制作パイプラインの実行にのみ必要です）"
    )

page = st.sidebar.radio(
    "ページ", ["ホーム", "新規企画", "レビューキュー", "曲詳細"]
)


# =================================================================
# ページ：ホーム
# =================================================================


def page_home() -> None:
    st.title("🎵 AMPS ダッシュボード")
    st.header("ホーム")

    songs = db.list_songs()

    scores = [s["quality_score"] for s in songs if s.get("quality_score") is not None]
    avg_score = f"{sum(scores) / len(scores):.1f}" if scores else "—"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("総曲数", len(songs))
    m2.metric("承認済み(qc_passed)", sum(1 for s in songs if s["status"] == "qc_passed"))
    m3.metric("レビュー待ち(qc_pending)", sum(1 for s in songs if s["status"] == "qc_pending"))
    m4.metric("平均QCスコア", avg_score)

    st.subheader("今週の曲一覧")
    if not songs:
        st.info("曲がまだありません。「新規企画」ページから作成してください。")
    else:
        rows = [
            {
                "曲ID": s["song_id"],
                "タイトル": s.get("title") or "無題",
                "ジャンル": s.get("genre") or "—",
                "ステータス": status_label(s["status"]),
                "QCスコア": _score_display(s.get("quality_score")),
                "更新日時": s.get("updated_at"),
            }
            for s in songs
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("ジャンル比率")
    counts = db.count_by_genre()
    total = sum(counts.values())
    for key, label in config.GENRES.items():
        count = counts.get(key, 0)
        actual_ratio = (count / total) if total > 0 else 0.0
        target_ratio = config.GENRE_TARGETS.get(key, 0.0)
        delta_pp = (actual_ratio - target_ratio) * 100
        st.write(
            f"**{label}**：実績 {count}曲（{actual_ratio * 100:.1f}%） / "
            f"目標 {target_ratio * 100:.0f}%（差分 {delta_pp:+.1f}pt）"
        )
        st.progress(min(max(actual_ratio, 0.0), 1.0))

    with st.expander("定期実行（手動トリガ）"):
        st.caption(
            "Phase 1ではAPSchedulerによる自動実行の代わりに、ここから手動でトリガできます。"
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("週次：CEO Agentで制作曲を決定"):
                with st.spinner("CEO Agentを実行しています…"):
                    try:
                        path = scheduler.run_weekly_ceo()
                    except Exception as exc:
                        st.error(f"週次レポートの作成に失敗しました：{exc}")
                    else:
                        st.success(f"週次レポートを作成しました：{path}")
        with col2:
            if st.button("日次：市場調査レポートを生成"):
                with st.spinner("Market Research Agentを実行しています…"):
                    try:
                        path = scheduler.run_daily_market_research()
                    except Exception as exc:
                        st.error(f"市場調査レポートの作成に失敗しました：{exc}")
                    else:
                        st.success(f"市場調査レポートを作成しました：{path}")


# =================================================================
# ページ：新規企画
# =================================================================


def page_new_song() -> None:
    st.title("新規企画")
    st.write("テーマとジャンルを指定して、企画〜品質チェックまでのパイプラインを実行します。")

    with st.form("new_song_form"):
        theme = st.text_input("テーマ", placeholder="帰り道")
        genre_label = st.selectbox("ジャンル", options=list(config.GENRES.values()))
        week_of = st.text_input("週（任意）", placeholder="例：2026-W32")
        submitted = st.form_submit_button("制作開始")

    if not submitted:
        return

    if not theme.strip():
        st.error("テーマを入力してください。")
        return

    try:
        config.require_api_key()
    except RuntimeError as exc:
        st.error(str(exc))
        return

    song_id = pipeline.start_song(theme.strip(), genre_label, week_of.strip() or None)

    st.warning(
        "制作パイプラインの実行には数分かかり、複数回のClaude API呼び出しが発生します。"
        "ブラウザを閉じずにお待ちください。"
    )

    with st.status("制作中…", expanded=True) as status_box:
        st.write(f"song_id={song_id} の制作を開始します。")

        def _progress(message: str) -> None:
            st.write(message)

        try:
            result = pipeline.run_full(song_id, progress=_progress)
        except Exception as exc:
            status_box.update(label="エラーが発生しました", state="error")
            st.error(f"制作パイプラインの実行中にエラーが発生しました：{exc}")
            st.exception(exc)
            return

        status_box.update(label="制作完了", state="complete")

    st.success(
        f"品質チェックが完了しました（song_id={song_id}）。"
        f"スコア {result['score']}点／{result['rounds']}ラウンド。"
    )
    if result["needs_improvement"]:
        st.warning(
            "3回のリトライでも合格ラインに届かなかったため重点確認が必要です（要改善フラグ）。"
        )
    st.info("「レビューキュー」ページへ移動して、内容を確認のうえ承認してください。")


# =================================================================
# ページ：レビューキュー
# =================================================================


def page_review_queue() -> None:
    st.title("レビューキュー")

    songs = db.list_by_status("qc_pending")
    if not songs:
        st.info("レビュー待ちの曲はありません。")
        return

    for song in songs:
        song_id = song["song_id"]
        title = song.get("title") or "無題"
        genre = song.get("genre") or "—"
        score_str = _score_display(song.get("quality_score"))

        with st.expander(f"#{song_id}　{title}　・　{genre}　・　QC {score_str}"):
            tab_lyrics, tab_prompt, tab_qc = st.tabs(["歌詞", "Sunoプロンプト", "QC採点"])

            with tab_lyrics:
                lyrics = db.get_latest_lyrics(song_id)
                if lyrics:
                    st.caption(f"バージョン {lyrics['version']}")
                    st.markdown(lyrics.get("content") or "")
                else:
                    st.info("歌詞データがまだありません。")

            with tab_prompt:
                prompt = db.get_latest_prompt(song_id)
                if prompt:
                    _show_suno_prompt_blocks(prompt)
                else:
                    st.info("Sunoプロンプトデータがまだありません。")

            with tab_qc:
                reviews = db.list_reviews(song_id)
                if not reviews:
                    st.info("QC採点データがまだありません。")
                else:
                    latest = reviews[-1]
                    st.metric("合計スコア", _score_display(latest.get("score")))
                    st.write(f"判定：{latest.get('verdict') or '—'}")
                    rows = _render_breakdown_table(latest.get("breakdown_json"))
                    if rows:
                        st.dataframe(rows, use_container_width=True, hide_index=True)
                    else:
                        st.info("採点内訳データがありません。")
                    notes = latest.get("notes") or ""
                    if notes:
                        if "要改善フラグ" in notes:
                            st.warning(notes)
                        else:
                            st.text(notes)

            st.divider()
            st.subheader("承認 / 差し戻し")
            col_approve, col_reject = st.columns(2)

            with col_approve:
                if st.button("✅ 承認", key=f"approve_{song_id}"):
                    try:
                        pipeline.approve(song_id)
                    except Exception as exc:
                        st.error(f"承認に失敗しました：{exc}")
                    else:
                        st.success(f"song_id={song_id} を承認しました（qc_passed）。")
                        st.rerun()

            with col_reject:
                comment = st.text_area("差戻しコメント", key=f"reject_comment_{song_id}")
                if st.button("↩ 差戻し", key=f"reject_{song_id}"):
                    try:
                        pipeline.reject(song_id, comment)
                    except Exception as exc:
                        st.error(f"差し戻しに失敗しました：{exc}")
                    else:
                        st.warning(
                            f"song_id={song_id} を差し戻しました。"
                            "ステータスは brief_done に戻り、次回実行時に "
                            "Lyrics 以降（Lyrics → Composition → Sunoプロンプト → QC）が再実行されます。"
                        )
                        st.rerun()

            st.caption("差戻しコメントは、次回のLyrics Agent実行時に申し送られます。")


# =================================================================
# ページ：曲詳細
# =================================================================


def page_song_detail() -> None:
    st.title("曲詳細")

    songs = db.list_songs()
    if not songs:
        st.info("曲がまだありません。「新規企画」ページから作成してください。")
        st.stop()

    options = {
        f"#{s['song_id']} {s.get('title') or '無題'} ({status_label(s['status'])})": s["song_id"]
        for s in songs
    }
    choice = st.selectbox("曲を選択", list(options.keys()))
    song_id = options[choice]
    song = db.get_song(song_id)

    st.subheader(f"#{song['song_id']}　{song.get('title') or '無題'}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ジャンル", song.get("genre") or "—")
    col2.metric("ステータス", status_label(song["status"]))
    col3.metric("QCスコア", _score_display(song.get("quality_score")))
    col4.metric("週(week_of)", song.get("week_of") or "—")
    st.caption(f"テーマ：{song.get('theme') or '—'}")
    st.caption(
        f"作成日時：{song.get('created_at') or '—'}　/　更新日時：{song.get('updated_at') or '—'}"
    )

    try:
        # create=False：閲覧しただけで空フォルダを作らないようにする
        folder = pipeline.song_dir(song_id, create=False)
        if folder is not None:
            st.caption(f"保存先フォルダ：{folder}")
    except Exception:
        pass

    (
        tab_brief,
        tab_lyrics,
        tab_composition,
        tab_prompt,
        tab_qc,
        tab_logs,
    ) = st.tabs(
        ["企画ブリーフ", "歌詞（版履歴）", "楽曲設計", "Sunoプロンプト", "QC履歴", "実行ログ"]
    )

    with tab_brief:
        brief = db.get_brief(song_id)
        if brief:
            st.markdown(brief)
        else:
            st.info("企画ブリーフのデータがまだありません。")

    with tab_lyrics:
        versions = db.list_lyrics_versions(song_id)
        if not versions:
            st.info("歌詞のデータがまだありません。")
        else:
            for i, v in enumerate(reversed(versions)):
                with st.expander(
                    f"バージョン {v['version']}（{v.get('created_at') or '—'}）",
                    expanded=(i == 0),
                ):
                    if v.get("revision_notes"):
                        st.caption(f"改訂メモ：{v['revision_notes']}")
                    st.markdown(v.get("content") or "")

    with tab_composition:
        composition = db.get_composition(song_id)
        if not composition:
            st.info("楽曲設計のデータがまだありません。")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("BPM", composition.get("bpm") or "—")
            c2.metric("Key", composition.get("key") or "—")
            c3.metric("構成", composition.get("structure") or "—")
            st.markdown(composition.get("content") or "")

    with tab_prompt:
        prompt = db.get_latest_prompt(song_id)
        if not prompt:
            st.info("Sunoプロンプトのデータがまだありません。")
        else:
            _show_suno_prompt_blocks(prompt)

    with tab_qc:
        reviews = db.list_reviews(song_id)
        if not reviews:
            st.info("QC履歴のデータがまだありません。")
        else:
            for r in reviews:
                st.markdown(f"#### Review {r['round']}回目　—　{_score_display(r.get('score'))}　—　{r.get('verdict') or '—'}")
                rows = _render_breakdown_table(r.get("breakdown_json"))
                if rows:
                    st.dataframe(rows, use_container_width=True, hide_index=True)
                notes = r.get("notes") or ""
                if notes:
                    if "要改善フラグ" in notes:
                        st.warning(notes)
                    else:
                        st.text(notes)

    with tab_logs:
        runs = db.list_agent_runs(song_id)
        if not runs:
            st.info("実行ログのデータがまだありません。")
        else:
            rows = [
                {
                    "日時": r.get("created_at"),
                    "エージェント": r.get("agent"),
                    "出力の先頭": (r.get("output_summary") or "")[:100],
                }
                for r in runs
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)


# =================================================================
# ルーティング
# =================================================================

if page == "ホーム":
    page_home()
elif page == "新規企画":
    page_new_song()
elif page == "レビューキュー":
    page_review_queue()
elif page == "曲詳細":
    page_song_detail()
