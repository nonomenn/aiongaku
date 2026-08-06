"""
AMPS（AI Music Production System）の共通設定モジュール。

プロジェクト全体で使うパス・定数・環境変数の読み込みをここに集約する。
.env が存在しない状態でも import 自体は失敗しないようにしてある
（APIキーが必要な処理を呼ぶ直前に require_api_key() でチェックする）。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# --- パス設定 ---

BASE_DIR = Path(__file__).resolve().parent

AGENTS_DIR = BASE_DIR / "agents"
BRAND_DIR = BASE_DIR / "brand"
SONGS_DIR = BASE_DIR / "songs"
DATABASE_DIR = BASE_DIR / "database"
REPORTS_DIR = BASE_DIR / "reports"
CONNECTORS_DIR = BASE_DIR / "connectors"

BRAND_GUIDELINE_PATH = BRAND_DIR / "brand_guideline.md"
DB_PATH = DATABASE_DIR / "amps.db"

# .env を読み込む（BASE_DIR直下に置く想定）
load_dotenv(BASE_DIR / ".env")

# --- 環境変数 ---

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("AMPS_MODEL", "claude-opus-5")

# --- Claude API呼び出しの既定パラメータ ---

MAX_TOKENS = 8000
TEMPERATURE = 1.0
MAX_RETRIES = 3  # エージェント呼び出しの再試行回数

# --- ジャンル定義（このプロジェクトで扱う3ジャンルのみ） ---

GENRES = {
    "love": "ラブソング",
    "cheer": "応援ソング",
    "vocaloid": "ボカロ系",
}

# 月間の制作比率の目標値
GENRE_TARGETS = {
    "love": 0.70,
    "cheer": 0.20,
    "vocaloid": 0.10,
}

# 日本語ラベル → 内部キー の逆引き辞書
GENRE_LABEL_TO_KEY = {label: key for key, label in GENRES.items()}

# --- 品質管理 ---

QC_PASS_SCORE = 80  # この点数未満は要改善
QC_MAX_RETRY = 3  # 最低レビュー回数（再制作の上限）

# --- 楽曲ステータス（工程順） ---

STATUSES = [
    "planned",
    "brief_done",
    "lyrics_done",
    "composed",
    "prompted",
    "qc_pending",
    "qc_passed",
]


def ensure_dirs() -> None:
    """データ保存に必要なディレクトリを作成する（存在すれば何もしない）。"""
    for directory in (DATABASE_DIR, SONGS_DIR, REPORTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def genre_key(value: str) -> str:
    """
    ジャンルの内部キー（例: "love"）またはジャンルの日本語ラベル（例: "ラブソング"）を
    受け取り、内部キーに正規化して返す。

    このプロジェクトで扱うジャンルは GENRES に定義された3種類のみであり、
    それ以外の値が渡された場合はエラーとする。
    """
    if value in GENRES:
        return value
    if value in GENRE_LABEL_TO_KEY:
        return GENRE_LABEL_TO_KEY[value]
    raise ValueError(
        f"不正なジャンルです: {value!r}。"
        f"有効なジャンルは {list(GENRES.keys())} または {list(GENRES.values())} のみです。"
    )


def require_api_key() -> None:
    """
    ANTHROPIC_API_KEY が設定されていない場合にエラーを送出する。

    APIキーが実際に必要な処理（Claude API呼び出しなど）の直前で呼び出すこと。
    config のimport自体はAPIキーが無くても成功する。
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY が設定されていません。"
            ".env.example を .env にコピーし、APIキーを設定してください。"
        )
