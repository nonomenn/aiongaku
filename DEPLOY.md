# AMPS デプロイ手順（Render.com）

## ⚠️ 最初に必ず読むこと

- このダッシュボードは「新規企画」ページの**制作開始のたびにClaude APIを複数回呼び出し**、
  Anthropicのクレジットを消費します。認証なしで公開URLに誰でもアクセスできる状態にすると、
  第三者に勝手に制作を実行されてAPI利用料を消費される危険があります。
- 公開デプロイでは **必ず強力な `AMPS_DASHBOARD_PASSWORD` を設定**し、
  `AMPS_AUTH_REQUIRED=true` にしてください（render.yamlでは既定でtrueにしています）。
- `.env` は絶対にGitへコミットしないでください（`.gitignore`で除外済みです。念のため
  コミット前に `git status` で確認する習慣をつけてください）。

---

## なぜVercelではダメなのか

- VercelはサーバーレスFunctions前提のプラットフォームで、Streamlitのような
  **常駐プロセス（persistent process）を継続実行する仕組みに向いていません**。
- StreamlitはWebSocketで双方向通信（画面の再描画・進捗表示など）を行いますが、
  Vercelのサーバーレス環境は基本的にWebSocketを維持できません。
- ファイルシステムも実行のたびに初期化される一時的（ephemeral）なもので、SQLiteのDBや
  生成した曲データを永続化できず、さらに実行時間にも上限があるため、
  数分かかる制作パイプラインの実行と相性が悪いです。

このため、**常駐プロセス＋永続ディスクを持つRender.com**を採用します。

---

## Renderへのデプロイ手順

1. このリポジトリをGitHubにpushする。
2. Renderのダッシュボードで **New > Blueprint** を選択する。
3. 対象のGitHubリポジトリを選択する。
4. リポジトリ直下の `render.yaml` が自動的に読み込まれ、サービス構成
  （Dockerランタイム・永続ディスク・環境変数の枠）が作成される。
5. `sync: false` になっている環境変数は自動入力されないため、Renderの管理画面で手入力する。
   - `ANTHROPIC_API_KEY`：Anthropic Consoleで発行したAPIキー
   - `AMPS_DASHBOARD_PASSWORD`：ダッシュボードのログインパスワード（強力なものを設定）
6. 「Deploy」を実行する。ビルドが完了すると、Render発行のURLでダッシュボードにアクセスできる。

---

## 永続ディスクとコスト

- 永続ディスクは `/data` にマウントされ、`amps.db`（SQLiteデータベース）・`songs/`（曲ごとの
  成果物）・`reports/`（月次レポート）を保存する。コンテナが再デプロイ・再起動されても
  このデータは消えない。
- `render.yaml` では `plan: starter` を指定している。永続ディスクは有料プランでのみ利用でき、
  無料プランでは使えない。**starterプランは目安として月額7ドル程度＋ディスク費用**とされているが、
  料金は変更される可能性があるため、必ずRenderの公式料金ページで最新の金額を確認すること。

---

## ローカルでの実行（変更なし）

ローカル開発の手順はこれまでと同じで、変更は不要。

```
streamlit run dashboard.py
```

`AMPS_DATA_DIR` を設定しなければ、`config.DATA_DIR` はプロジェクト直下（`BASE_DIR`）になり、
`database/` `songs/` `reports/` は従来どおりプロジェクトフォルダ内に保存される。

ローカルで `AMPS_DASHBOARD_PASSWORD` を設定しなければ、`AMPS_AUTH_REQUIRED` が未設定
（false）である限りログイン不要でそのままダッシュボードを使える
（サイドバーに認証無効の警告が表示される）。

---

## scheduler.py について（Phase 2）

`scheduler.py`（APSchedulerによる定期実行）は、このWebサービス（`amps-dashboard`）内では
実行されない。ダッシュボードの「定期実行（手動トリガ）」から手動で実行する運用となる。

Renderで自動的な定期実行を行いたい場合は、Phase 2として以下のいずれかを別途構築すること。

- 独立した **Background Worker サービス**（`scheduler.py` を常駐実行）
- **Render Cron Job**（決まった時刻に単発実行するジョブ）

いずれの場合も `AMPS_DATA_DIR=/data` を指定し、Webサービスと同じ永続ディスクを
共有できるように構成する必要がある。
