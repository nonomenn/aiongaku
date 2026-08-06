"""
AMPS（AI Music Production System）のデータベースアクセス層。

標準ライブラリの sqlite3 のみを使用する。
テーブル定義・CRUD関数をここに集約し、他のモジュール（パイプライン・ダッシュボード等）は
このモジュール経由でのみデータベースにアクセスする。
"""

import json
import sqlite3
from contextlib import contextmanager

import config

# --- スキーマ定義 ---

_SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
    song_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    genre TEXT,
    theme TEXT,
    status TEXT NOT NULL,
    quality_score INTEGER,
    week_of TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS briefs (
    song_id INTEGER PRIMARY KEY,
    content TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lyrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id INTEGER,
    version INTEGER,
    content TEXT,
    revision_notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS compositions (
    song_id INTEGER PRIMARY KEY,
    bpm INTEGER,
    "key" TEXT,
    structure TEXT,
    content TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS suno_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id INTEGER,
    version INTEGER,
    style_prompt TEXT,
    formatted_lyrics TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quality_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id INTEGER,
    round INTEGER,
    score INTEGER,
    breakdown_json TEXT,
    verdict TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id INTEGER,
    agent TEXT,
    input_summary TEXT,
    output_summary TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def connect() -> sqlite3.Connection:
    """データベースに接続する。存在しなければdatabase/ディレクトリを作成する。"""
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _conn():
    """接続をopenし、正常終了時はcommit、例外時はrollbackしてcloseするコンテキスト。"""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """sqlite3.Row を dict に変換する（Noneはそのまま返す）。"""
    return dict(row) if row is not None else None


def init_db() -> None:
    """全テーブルを作成する（既に存在する場合は何もしない・冪等）。"""
    with _conn() as conn:
        conn.executescript(_SCHEMA)


# --- songs ---


def create_song(title, genre, theme, status="planned", week_of=None) -> int:
    """
    新しい楽曲レコードを作成する。
    genreはキー（"love"等）・日本語ラベル（"ラブソング"等）どちらでも受け付け、
    正規化した日本語ラベルをgenreカラムに保存する。
    戻り値: 作成されたsong_id
    """
    key = config.genre_key(genre)
    genre_label = config.GENRES[key]
    with _conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO songs (title, genre, theme, status, week_of)
            VALUES (?, ?, ?, ?, ?)
            """,
            (title, genre_label, theme, status, week_of),
        )
        return cursor.lastrowid


def update_status(song_id, status) -> None:
    """楽曲のステータスを更新する。config.STATUSESに無い値はエラーとする。"""
    if status not in config.STATUSES:
        raise ValueError(
            f"不正なステータスです: {status!r}。有効な値は {config.STATUSES} のみです。"
        )
    with _conn() as conn:
        conn.execute(
            """
            UPDATE songs
            SET status = ?, updated_at = datetime('now')
            WHERE song_id = ?
            """,
            (status, song_id),
        )


def update_song_title(song_id, title) -> None:
    """楽曲のタイトルを更新する。"""
    with _conn() as conn:
        conn.execute(
            """
            UPDATE songs
            SET title = ?, updated_at = datetime('now')
            WHERE song_id = ?
            """,
            (title, song_id),
        )


def update_song_genre(song_id, genre) -> None:
    """楽曲のジャンルを更新する。3ジャンル以外の値はエラーとする。"""
    key = config.genre_key(genre)
    with _conn() as conn:
        conn.execute(
            """
            UPDATE songs
            SET genre = ?, updated_at = datetime('now')
            WHERE song_id = ?
            """,
            (config.GENRES[key], song_id),
        )


def get_song(song_id) -> dict | None:
    """song_idに対応する楽曲レコードを取得する。存在しなければNone。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM songs WHERE song_id = ?", (song_id,)
        ).fetchone()
        return _row_to_dict(row)


def list_songs() -> list[dict]:
    """全楽曲を新しい順（song_id降順）で取得する。"""
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM songs ORDER BY song_id DESC").fetchall()
        return [dict(row) for row in rows]


def list_by_status(status) -> list[dict]:
    """指定ステータスの楽曲一覧を新しい順で取得する。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM songs WHERE status = ? ORDER BY song_id DESC", (status,)
        ).fetchall()
        return [dict(row) for row in rows]


def count_by_genre() -> dict:
    """
    ジャンルごとの楽曲数を集計する。
    戻り値は内部キー（"love"等）をキーとする辞書で、3ジャンル全てを0埋めして含む。
    """
    counts = {key: 0 for key in config.GENRES}
    with _conn() as conn:
        rows = conn.execute(
            "SELECT genre, COUNT(*) AS cnt FROM songs GROUP BY genre"
        ).fetchall()
        for row in rows:
            label = row["genre"]
            if label in config.GENRE_LABEL_TO_KEY:
                counts[config.GENRE_LABEL_TO_KEY[label]] = row["cnt"]
    return counts


# --- briefs ---


def save_brief(song_id, content) -> None:
    """企画書（brief）を保存する。既存があれば上書き（UPSERT）。"""
    with _conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO briefs (song_id, content, created_at)
            VALUES (
                ?, ?,
                COALESCE((SELECT created_at FROM briefs WHERE song_id = ?), datetime('now'))
            )
            """,
            (song_id, content, song_id),
        )


def get_brief(song_id) -> str | None:
    """song_idに対応する企画書の本文を取得する。存在しなければNone。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT content FROM briefs WHERE song_id = ?", (song_id,)
        ).fetchone()
        return row["content"] if row is not None else None


# --- lyrics ---


def _next_version(conn: sqlite3.Connection, table: str, song_id) -> int:
    """指定テーブル・song_idにおける次のバージョン番号（現在の最大値+1、無ければ1）を返す。"""
    row = conn.execute(
        f"SELECT MAX(version) AS max_version FROM {table} WHERE song_id = ?",
        (song_id,),
    ).fetchone()
    max_version = row["max_version"]
    return (max_version or 0) + 1


def save_lyrics(song_id, content, revision_notes=None) -> int:
    """
    歌詞を新しいバージョンとして保存する。
    戻り値: 採番されたバージョン番号
    """
    with _conn() as conn:
        version = _next_version(conn, "lyrics", song_id)
        conn.execute(
            """
            INSERT INTO lyrics (song_id, version, content, revision_notes)
            VALUES (?, ?, ?, ?)
            """,
            (song_id, version, content, revision_notes),
        )
        return version


def get_latest_lyrics(song_id) -> dict | None:
    """最新バージョンの歌詞を取得する。存在しなければNone。"""
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM lyrics
            WHERE song_id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (song_id,),
        ).fetchone()
        return _row_to_dict(row)


def list_lyrics_versions(song_id) -> list[dict]:
    """song_idの歌詞を全バージョン、古い順（version昇順）で取得する。"""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM lyrics
            WHERE song_id = ?
            ORDER BY version ASC
            """,
            (song_id,),
        ).fetchall()
        return [dict(row) for row in rows]


# --- compositions ---


def save_composition(song_id, bpm, key, structure, content) -> None:
    """楽曲構成（作曲設計）を保存する。既存があれば上書き（UPSERT）。"""
    with _conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO compositions (song_id, bpm, "key", structure, content, created_at)
            VALUES (
                ?, ?, ?, ?, ?,
                COALESCE((SELECT created_at FROM compositions WHERE song_id = ?), datetime('now'))
            )
            """,
            (song_id, bpm, key, structure, content, song_id),
        )


def get_composition(song_id) -> dict | None:
    """song_idに対応する楽曲構成を取得する。存在しなければNone。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM compositions WHERE song_id = ?", (song_id,)
        ).fetchone()
        return _row_to_dict(row)


# --- suno_prompts ---


def save_prompt(song_id, style_prompt, formatted_lyrics) -> int:
    """
    Sunoプロンプトを新しいバージョンとして保存する。
    戻り値: 採番されたバージョン番号
    """
    with _conn() as conn:
        version = _next_version(conn, "suno_prompts", song_id)
        conn.execute(
            """
            INSERT INTO suno_prompts (song_id, version, style_prompt, formatted_lyrics)
            VALUES (?, ?, ?, ?)
            """,
            (song_id, version, style_prompt, formatted_lyrics),
        )
        return version


def get_latest_prompt(song_id) -> dict | None:
    """最新バージョンのSunoプロンプトを取得する。存在しなければNone。"""
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM suno_prompts
            WHERE song_id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (song_id,),
        ).fetchone()
        return _row_to_dict(row)


# --- quality_reviews ---


def save_review(song_id, round, score, breakdown, verdict, notes) -> None:
    """
    品質レビュー結果を保存する。breakdownはlist/dict等をJSON文字列化して保存する。
    songs.quality_scoreも合わせて更新する。
    """
    breakdown_json = json.dumps(breakdown, ensure_ascii=False)
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO quality_reviews (song_id, round, score, breakdown_json, verdict, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (song_id, round, score, breakdown_json, verdict, notes),
        )
        conn.execute(
            """
            UPDATE songs
            SET quality_score = ?, updated_at = datetime('now')
            WHERE song_id = ?
            """,
            (score, song_id),
        )


def list_reviews(song_id) -> list[dict]:
    """song_idの品質レビューを全ラウンド、古い順（round昇順）で取得する。"""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM quality_reviews
            WHERE song_id = ?
            ORDER BY round ASC
            """,
            (song_id,),
        ).fetchall()
        return [dict(row) for row in rows]


# --- agent_runs ---


def log_agent_run(song_id, agent, input_summary, output_summary) -> None:
    """エージェント実行ログを記録する。各サマリーは2000文字に切り詰めて保存する。"""
    input_summary = (input_summary or "")[:2000]
    output_summary = (output_summary or "")[:2000]
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO agent_runs (song_id, agent, input_summary, output_summary)
            VALUES (?, ?, ?, ?)
            """,
            (song_id, agent, input_summary, output_summary),
        )


def list_agent_runs(song_id) -> list[dict]:
    """song_idのエージェント実行ログを古い順（id昇順）で取得する。"""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM agent_runs
            WHERE song_id = ?
            ORDER BY id ASC
            """,
            (song_id,),
        ).fetchall()
        return [dict(row) for row in rows]
