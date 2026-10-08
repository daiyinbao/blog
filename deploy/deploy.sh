#!/usr/bin/env bash
# 本地构建 + rsync 上传。服务器上不需要装 Hugo。
#
# 用法：
#   REMOTE=root@1.2.3.4 TARGET=/var/www/blog BASE_URL=https://blog.example.com/ ./deploy/deploy.sh
#
# 也可以在 deploy/deploy.env 里写死这些变量（见 README）。
set -euo pipefail

cd "$(dirname "$0")/.."

# 读取可选的配置文件
[ -f deploy/deploy.env ] && . deploy/deploy.env

REMOTE="${REMOTE:?请设置 REMOTE，例如 root@1.2.3.4}"
TARGET="${TARGET:-/var/www/blog}"
BASE_URL="${BASE_URL:?请设置 BASE_URL，例如 https://blog.example.com/}"
SSH_PORT="${SSH_PORT:-22}"

echo "==> 构建（baseURL = $BASE_URL）"
hugo --gc --minify --cleanDestinationDir --baseURL "$BASE_URL"

echo "==> 为带图片的文章打包 zip（供「下载文章包」使用）"
python3 scripts/make-zips.py public --clean

echo "==> 上传 public/ → $REMOTE:$TARGET"
rsync -avz --delete -e "ssh -p $SSH_PORT" public/ "$REMOTE:$TARGET/"

echo "==> 完成：$BASE_URL"
