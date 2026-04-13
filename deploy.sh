#!/usr/bin/env bash
set -euo pipefail

APP_NAME="new-api-scheduler-web"
APP_DIR="/home/ubuntu/apps/new-api-scheduler/webapp"
DATA_DIR="$APP_DIR/data"
PORT_BIND="127.0.0.1:8000:8000"
BRANCH="${1:-main}"

echo "[1/6] 进入项目目录: $APP_DIR"
cd "$APP_DIR"

echo "[2/6] 拉取最新代码: origin/$BRANCH"
git pull origin "$BRANCH"

echo "[3/6] 构建镜像: $APP_NAME:latest"
docker build -t "$APP_NAME" .

echo "[4/6] 停止旧容器"
docker stop "$APP_NAME" >/dev/null 2>&1 || true
docker rm "$APP_NAME" >/dev/null 2>&1 || true

echo "[5/6] 启动新容器"
docker run -d \
  --name "$APP_NAME" \
  -p "$PORT_BIND" \
  -v "$DATA_DIR:/app/data" \
  -e APP_DATA_DIR=/app/data \
  --restart unless-stopped \
  "$APP_NAME"

echo "[6/6] 当前容器状态"
docker ps --filter "name=$APP_NAME"
echo
echo "最近日志:"
docker logs --tail 50 "$APP_NAME"
