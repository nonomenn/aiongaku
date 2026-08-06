"""
エージェント実行ランタイム。

agents/*.md に書かれたエージェント定義をシステムプロンプトとしてそのまま使い、
Claude APIを呼び出して結果を返す。エージェントの振る舞い・出力フォーマットは
一切ここに書かない（すべて agents/*.md 側の責務）。

このモジュールはインポート時にAPIキーを要求しない
（実際にAPIを呼ぶ run_agent() / romanize_slug() の中でのみ必要になる）。
"""

import re
import time

import anthropic

import config
import db

# ブランドガイドラインの内容はプロセス内で使い回す（毎回ディスクを読みに行かない）
_brand_guideline_cache: str | None = None

# Anthropicクライアントは遅延生成し、一度作ったら使い回す
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Anthropicクライアントを遅延生成して返す（モジュールimport時には生成しない）。"""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _resolve_agent_path(agent_name: str):
    """
    エージェント名からagents/*.mdのパスを解決する。
    `{agent_name}.md` → `{agent_name}_agent.md` の順に探し、
    どちらも無ければ利用可能なエージェント一覧を添えてFileNotFoundErrorを送出する。
    """
    candidates = [
        config.AGENTS_DIR / f"{agent_name}.md",
        config.AGENTS_DIR / f"{agent_name}_agent.md",
    ]
    for path in candidates:
        if path.exists():
            return path

    available = sorted(p.stem for p in config.AGENTS_DIR.glob("*.md"))
    raise FileNotFoundError(
        f"エージェント定義が見つかりません: {agent_name!r}。"
        f"利用可能なエージェント: {available}"
    )


def _get_brand_guideline() -> str:
    """brand/brand_guideline.md の内容を取得する（初回のみディスクから読み込みキャッシュする）。"""
    global _brand_guideline_cache
    if _brand_guideline_cache is None:
        try:
            _brand_guideline_cache = config.BRAND_GUIDELINE_PATH.read_text(
                encoding="utf-8"
            )
        except FileNotFoundError:
            _brand_guideline_cache = ""
    return _brand_guideline_cache


def _build_system_prompt(agent_path) -> str:
    """エージェント定義ファイル本文 + ブランドガイドラインを結合してシステムプロンプトを作る。"""
    agent_instructions = agent_path.read_text(encoding="utf-8")
    brand_guideline = _get_brand_guideline()
    return (
        f"{agent_instructions}\n\n"
        "---\n"
        "## ブランドガイドライン（判断に迷ったときはこの基準に従うこと）\n\n"
        f"{brand_guideline}"
    )


def _build_user_message(upstream_text: str, extra_context: str) -> str:
    """上流成果物（upstream_text）に、必要であれば追加コンテキストを付加したユーザーメッセージを作る。"""
    if extra_context:
        return f"{upstream_text}\n\n## 追加コンテキスト\n{extra_context}"
    return upstream_text


def _extract_text(response) -> str:
    """レスポンスのcontentブロックからtype=='text'のものだけを連結して返す。"""
    return "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )


def run_agent(
    agent_name: str,
    upstream_text: str,
    extra_context: str = "",
    song_id: int | None = None,
) -> str:
    """
    指定エージェントを1回実行する。

    agent_name: agents/{agent_name}.md または agents/{agent_name}_agent.md を探す。
    upstream_text: 上流エージェントの成果物（ユーザーメッセージの本体）。
    extra_context: 追加で伝えたい情報（QCフィードバックなど）。空文字なら付加しない。
    song_id: ログ記録用の楽曲ID（Noneでも可）。

    戻り値: エージェントの出力テキスト（前後の空白を除去済み）。
    """
    config.require_api_key()

    # ファイルが無い場合は即座に送出する（リトライ対象外）
    agent_path = _resolve_agent_path(agent_name)
    system_prompt = _build_system_prompt(agent_path)
    user_message = _build_user_message(upstream_text, extra_context)

    client = _get_client()

    last_exc: Exception | None = None
    for attempt in range(config.MAX_RETRIES):
        try:
            response = client.messages.create(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                temperature=config.TEMPERATURE,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            text = _extract_text(response).strip()

            try:
                db.log_agent_run(song_id, agent_name, user_message, text)
            except Exception:
                # ログ記録の失敗でパイプライン自体を止めない
                pass

            return text

        except anthropic.AuthenticationError:
            # APIキーが無効な場合はリトライしても無駄なので即座に送出する
            raise
        except Exception as exc:
            # anthropic.APIStatusError / APIConnectionError / RateLimitError を含む
            # あらゆる例外を対象に、指数バックオフで再試行する
            last_exc = exc
            if attempt == config.MAX_RETRIES - 1:
                raise
            time.sleep(2**attempt)

    # ここには到達しないはずだが、念のため
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("run_agentが予期せず終了しました。")


def romanize_slug(text: str, fallback: str = "song") -> str:
    """
    日本語などのテーマ文字列を、フォルダ名に使える短い小文字ASCIIローマ字スラッグに変換する。
    （これはエージェントの振る舞いではなく、フォルダ命名のためのインフラ用ユーティリティ）

    例：「帰り道」 -> "kaerimichi"

    text が既に純粋なASCIIならAPI呼び出しなしでそのまま変換する。
    それ以外（日本語など）の場合のみ、ヘボン式ローマ字表記を尋ねる最小限の1回のClaude呼び出しを行う。
    失敗時・変換結果が空になった場合は例外を送出せず fallback を返す。
    """
    if not text:
        return fallback

    if text.isascii():
        slug = text.lower()
        slug = re.sub(r"[^a-z0-9]+", "_", slug)
        slug = slug.strip("_")[:30]
        return slug or fallback

    try:
        client = _get_client()
        # ファイル名生成のためだけの最小限の問い合わせ（エージェントの振る舞いではない）。
        # ヘボン式ローマ字1トークンのみを1行で要求する。
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=50,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "次の語をヘボン式ローマ字で、小文字アルファベットとアンダースコアのみの"
                        f"1トークンで出力してください。説明・記号は一切不要です: {text}"
                    ),
                }
            ],
        )
        raw = _extract_text(response)
        slug = raw.lower()
        slug = re.sub(r"[^a-z0-9_]+", "", slug)
        slug = re.sub(r"_+", "_", slug).strip("_")[:30]
        return slug or fallback
    except Exception:
        return fallback
