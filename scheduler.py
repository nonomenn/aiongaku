"""
AMPS（AI Music Production System）の定期実行スケジューラ。

週次のCEO Agent（今週制作する曲の決定）と、日次のMarket Research Agent（市場調査レポート）を
APSchedulerで定期実行するためのモジュール。

Phase 1では「ダッシュボードのボタンから手動トリガできれば十分」という方針のため、
run_weekly_ceo() / run_daily_market_research() は単体でも呼び出せる関数として提供する。
本ファイルを直接 `python scheduler.py` として実行した場合のみ、常駐スケジューラプロセスとして
動作する（importしただけではスケジューラは起動しない）。

エージェントの振る舞い・出力フォーマットは agents/*.md 側の責務であり、
このモジュールでは日付や集計値などの「事実」のみをアップストリームメッセージとして渡す。
"""

from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import db
from agents import runner


def run_weekly_ceo() -> Path:
    """
    CEO Agentを実行し、週次制作リストをレポートとして保存する。

    アップストリームメッセージには、今日の日付・現在のジャンルごとの曲数・
    目標ジャンル比率・総曲数という「事実」のみを渡す（判断ロジックはceo_agent.md側）。

    戻り値: 書き込んだレポートファイルのPath。
    """
    config.require_api_key()

    today = datetime.now().strftime("%Y-%m-%d")
    counts = db.count_by_genre()
    total = sum(counts.values())

    lines = [f"今日の日付：{today}", f"総曲数：{total}曲", "", "現在のジャンル別曲数："]
    for key, label in config.GENRES.items():
        count = counts.get(key, 0)
        target_ratio = config.GENRE_TARGETS.get(key, 0)
        lines.append(f"- {label}：{count}曲（目標比率 {target_ratio * 100:.0f}%）")
    upstream = "\n".join(lines)

    text = runner.run_agent("ceo_agent", upstream)

    config.ensure_dirs()
    path = config.REPORTS_DIR / f"weekly_{today}.md"
    path.write_text(text, encoding="utf-8")
    return path


def run_daily_market_research() -> Path:
    """
    Market Research Agentを実行し、市場調査レポートを保存する。

    Phase 1メモ：これは単純なログ付きレポート生成であり、外部データソースとの
    連携はまだ行っていない（connectors/ 経由での実データ接続はPhase 2で追加予定）。

    戻り値: 書き込んだレポートファイルのPath。
    """
    config.require_api_key()

    today = datetime.now().strftime("%Y-%m-%d")
    target_genres = "、".join(config.GENRES.values())
    upstream = f"今日の日付：{today}\n対象ジャンル：{target_genres}"

    text = runner.run_agent("market_research_agent", upstream)

    config.ensure_dirs()
    path = config.REPORTS_DIR / f"market_{today}.md"
    path.write_text(text, encoding="utf-8")
    return path


def build_scheduler() -> BlockingScheduler:
    """
    週次CEO Agent（毎週月曜9:00）と日次Market Research Agent（毎日8:00）を
    登録したBlockingSchedulerを構築して返す。スケジューラの起動はしない。
    """
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_weekly_ceo,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_ceo",
        replace_existing=True,
    )
    scheduler.add_job(
        run_daily_market_research,
        trigger=CronTrigger(hour=8, minute=0),
        id="daily_market_research",
        replace_existing=True,
    )
    return scheduler


def main() -> None:
    """スケジューラを構築し、登録済みジョブを表示してから常駐起動する。"""
    scheduler = build_scheduler()

    print("AMPS スケジューラを起動します。登録済みジョブ：")
    for job in scheduler.get_jobs():
        print(f"  - {job.id}: {job.trigger}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("停止要求を受け取りました。スケジューラを終了します。")


if __name__ == "__main__":
    main()
