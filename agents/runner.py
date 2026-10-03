"""AMPS: agents/*.md をシステムプロンプトとしてClaude APIを呼ぶ共通実行器。"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import db  # noqa: E402

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds, exponential backoff


def _load_system_prompt(agent_name: str) -> str:
    path = config.AGENTS_DIR / f"{agent_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"agent definition not found: {path}")
    return path.read_text(encoding="utf-8")


def _load_brand_guideline() -> str:
    if config.BRAND_GUIDELINE_PATH.exists():
        return config.BRAND_GUIDELINE_PATH.read_text(encoding="utf-8")
    return ""


def run_agent(agent_name: str, upstream_text: str, extra_context: str = "",
              song_id: Optional[int] = None, max_tokens: int = 16000) -> str:
    """`agent_name`（拡張子なし、例: "lyrics_agent"）を実行し、テキスト出力を返す。

    1. agents/{agent_name}.md をシステムプロンプトとして読み込む。
    2. brand_guideline.md を判断基準として添える。
    3. 上流成果物 (upstream_text) と追加コンテキストをユーザーメッセージとして渡す。
    4. Anthropic SDKで呼び出し、agent_runs にログを残す。
    5. 失敗時・応答が空だった場合は指数バックオフでリトライする。

    max_tokens について：
    Sonnet 5 / Opus 5 系は thinking を省略すると適応思考がONになる。
    思考が max_tokens を使い切ると本文が空のまま返るため、小さすぎる値は危険。
    実際に 4000 だった頃、品質チェック（最も推論が重い）が2回連続で空を返し、
    それが「0点」として扱われて歌詞からの作り直しが2周空回りした。
    """
    system_prompt = _load_system_prompt(agent_name)
    brand = _load_brand_guideline()
    if brand:
        system_prompt = f"{system_prompt}\n\n---\n## brand/brand_guideline.md（判断基準）\n{brand}"

    user_message = upstream_text
    if extra_context:
        user_message = f"{upstream_text}\n\n---\n## 追加コンテキスト\n{extra_context}"

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY が未設定です。.env に設定してください（.env.example 参照）。"
        )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=config.AMPS_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            output_text = "".join(
                block.text for block in response.content if getattr(block, "type", "") == "text"
            ).strip()

            # 応答が空のまま返ることがある（思考にmax_tokensを使い切った場合など）。
            # これを正常な戻り値として返すと、呼び出し側で「0点・やり直し」と解釈され、
            # 技術的な失敗なのに高価な作り直しが無言で走る。失敗として扱いリトライする。
            if not output_text:
                raise RuntimeError(
                    f"{agent_name} の応答が空だった"
                    f"（stop_reason={getattr(response, 'stop_reason', '?')}, "
                    f"出力トークン={getattr(getattr(response, 'usage', None), 'output_tokens', '?')}）。"
                    "max_tokens を増やす必要がある可能性が高い"
                )

            # 途中で打ち切られた応答は不完全なので、気づけるようにログへ残す
            if getattr(response, "stop_reason", None) == "max_tokens":
                db.log_agent_run(
                    song_id, agent_name, user_message,
                    f"[WARN] max_tokensで打ち切られた（不完全な可能性あり）\n{output_text}",
                )
                return output_text

            db.log_agent_run(song_id, agent_name, user_message, output_text)
            return output_text
        except Exception as exc:  # noqa: BLE001 - リトライのため意図的に広く捕捉
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            continue

    db.log_agent_run(song_id, agent_name, user_message, f"[FAILED] {last_error}")
    raise RuntimeError(f"{agent_name} の実行に失敗しました（{MAX_RETRIES}回リトライ後）: {last_error}") from last_error
