# CLAUDE.md — AMPS（AI Music Production System）

このリポジトリは、AI楽曲を大量生産するためのものではありません。
**音楽制作会社が持つ「企画・制作・品質管理・分析・改善」の仕組みをClaude Code上に再現する**プロジェクトです。
Claude Code はこのファイルを最初に読み、以下の原則に従って作業してください。

---

## プロジェクトの目的

- 月30曲を「ブランド資産」として積み上げる。量産ではなく1曲ごとの完成度を最優先。
- 目標：Spotify / Apple Music / YouTube Music 等で継続的に聴かれる「5年後も残る曲」。
- 毎回「なぜこの曲を作るのか」を論理的に説明できる状態を保つ。

## 制作ジャンル（これ以外は制作・提案しない）

1. ラブソング（約70%）
2. 応援ソング（約20%）
3. ボカロ系（約10%）

EDM / HipHop / Trap / K-POP / 演歌 / ジャズ 等は対象外。

## エージェント運用の鉄則

- 12のエージェント定義は `agents/*.md` にある。**各エージェントの振る舞いはそのmdをシステムプロンプトとして使う**こと。ロジックをコードに直書きしない。
- エージェントは前後で成果物をリレーする：
  `market_research → trend_analysis → ceo → music_director(brief) → lyrics → composition → suno_prompt → quality_check → branding → release → analytics → learning`
- 判断に迷ったら `brand/brand_guideline.md` に従う。

## 品質と承認

- Quality Check Agentは100点満点で評価し、80点未満は改善して再制作（最低3回レビュー）。
- **人の承認ゲートを2箇所置く**：①QC後（試聴して承認/差戻し）②公開前。ここは自動化しない。

## コンプライアンス（必須）

- 歌詞・楽曲はオリジナルのみ。既存曲の歌詞・メロディ、実在アーティストの模倣をしない。
- 市場調査は公開情報の傾向把握に留め、他者の文章を複製しない。
- 配信時はAI支援であることを正直に開示する。配信は間隔を空け、重複・水増しをしない。

## 実装スコープ

- 現在は **Phase 1**：企画→作詞→楽曲設計→Sunoプロンプト→品質評価までを半自動化し、ダッシュボードで承認する。
- 詳細仕様は `AMPS_Phase1_実装指示書.md` に従う。
- 投稿（配信/SNS）と分析の自動化は Phase 2 以降。`connectors/` を後付けできる構造にしておく。

## 技術スタック（Phase 1・確定）

- Python / anthropic SDK / Streamlit / APScheduler / SQLite / python-dotenv
- APIキーは `.env`（`ANTHROPIC_API_KEY`）。リポジトリにコミットしない。

## ディレクトリ

```
agents/   … 12エージェント定義（システムプロンプト）
brand/    … brand_guideline.md（判断の憲法）
songs/    … 曲ごとの成果物（brief/lyrics/composition/suno_prompt/quality_review）
database/ … 楽曲・歌詞・分析のマスタ（SQLite: amps.db）
reports/  … 月次学習レポート
```

## 参考：完成した1曲の出力例

`songs/2026-07/001_kaerimichi/` に、テーマ「帰り道」で企画→歌詞→設計→Sunoプロンプト→QC評価まで通した**実例**が入っている。各エージェントの出力フォーマットの基準として参照すること。
