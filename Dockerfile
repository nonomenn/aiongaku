# このDockerfileはRender.com（Docker runtimeのWebサービス）へのデプロイ用。
# 永続ディスクは /data にマウントする想定（render.yaml参照）。
# ローカル開発ではこのDockerfileを使わず、通常どおり `streamlit run dashboard.py` でよい。

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Renderは起動時に$PORTを注入する。ローカルでこのイメージを直接動かす場合の既定値。
ENV PORT=8501

# 依存関係を先にコピーしてインストールすることで、レイヤーキャッシュを効かせる
# （requirements.txtが変わらない限り、コード変更のたびに再インストールしない）。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 残りのソースコードをコピーする
COPY . .

# 永続ディスクのマウントポイントを作成しておく
RUN mkdir -p /data

# Streamlitのデフォルトポート（ローカル参考用。実際のバインド先は$PORT）
EXPOSE 8501

# シェル形式のCMDにすることで$PORTが展開される（exec形式では展開されない）。
# XSRF保護・CORSは無効化しない（デフォルトのまま）。
CMD streamlit run dashboard.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
