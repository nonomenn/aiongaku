# Render.com（Docker runtime の Web サービス）へのデプロイ用。
# 永続ディスクは /data にマウントする想定（render.yaml を参照）。
# ローカル開発ではこれを使わず、通常どおり `streamlit run dashboard.py` でよい。

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Render は起動時に $PORT を注入する。ローカルでこのイメージを直接動かす場合の既定値。
ENV PORT=8501

# 依存を先に入れてレイヤーキャッシュを効かせる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 永続ディスクのマウントポイント
RUN mkdir -p /data

EXPOSE 8501

# $PORT を展開させるためシェル形式にする（exec形式では展開されない）。
# XSRF保護・CORSは無効化しない。
CMD streamlit run dashboard.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
