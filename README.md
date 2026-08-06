# AMPS — はじめに読む（Claude Codeへの渡し方）

このフォルダは AMPS（AI Music Production System）一式です。
PC上のClaude Codeにこのフォルダごと渡して、Phase 1を実装・運用します。

## 使い方（3ステップ）

1. このフォルダ（`amps/`）をPCの好きな場所に置く。
2. Claude Codeでこのフォルダを開く。
3. Claude Codeにこう伝える：
   > 「このプロジェクトの `AMPS_Phase1_実装指示書.md` の通りに Phase 1 を実装して。
   > `CLAUDE.md` と `agents/*.md`、`brand/brand_guideline.md` を前提に進めて。」

実装後の最初のテスト：ダッシュボードの新規企画にテーマ「帰り道」を入れ、
`songs/2026-07/001_kaerimichi/` と同じ流れ（企画→歌詞→設計→Sunoプロンプト→QC）が
自動で再現されるか確認する。

## 中身

```
amps/
├── README.md                    ← このファイル
├── CLAUDE.md                    ← Claude Codeが最初に読む全体指示
├── AMPS_システム設計書.md         ← 全体設計（12エージェント・ワークフロー）
├── AMPS_Phase1_実装指示書.md      ← Phase 1の実装仕様（Claude Codeはこれ通りに作る）
├── agents/                      ← 12エージェントのプロンプト定義
├── brand/brand_guideline.md     ← 全エージェントの判断軸（ブランド憲法）
├── songs/2026-07/001_kaerimichi/ ← 完成した1曲の実例（出力フォーマット基準）
├── database/                    ← SQLite等が入る（自動生成）
├── reports/                     ← 月次学習レポート
└── connectors/                  ← Phase 2以降の外部連携用（今は空）
```

## 事前に用意するもの

- Python 3.11+
- Anthropic APIキー（`.env` に `ANTHROPIC_API_KEY=...` として設定。Claude Codeが `.env.example` を作る）

## 注意

- ブランド名など `brand/brand_guideline.md` の `[　]` は運営者が埋める箇所です。
- Phase 1は「制作〜品質評価＋人の承認」まで。配信・SNS投稿・分析の自動化はPhase 2以降。
- 歌詞・楽曲はオリジナルのみ。配信時はAI支援であることを正直に開示する方針です。
```
