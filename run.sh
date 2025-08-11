#!/bin/bash
#
# Canada28 控制面板启动脚本（精简版）
# 仅提供一个子命令：web
# 用法:
#   ./run.sh web   - 启动 Web 面板 (前台运行)
#

set -euo pipefail

# --- 配置 ---
PYTHON_CMD="python3.9"
if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
  fi
fi

# --- 颜色定义 ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'

cd "$HOME"

function get_port() {
  "$PYTHON_CMD" - <<'PY'
from canada28_bot import load_config
cfg = load_config()
print(cfg.get("web", {}).get("port", 8787))
PY
}

function get_auth() {
  "$PYTHON_CMD" - <<'PY'
from canada28_bot import load_config
cfg = load_config()
auth = cfg.get("web", {}).get("auth", {})
print(auth.get("username","admin"), auth.get("password","admin123"))
PY
}

function start_uvicorn() {
  local port="$1"
  if command -v uvicorn >/dev/null 2>&1; then
    exec uvicorn web.app:app --host 0.0.0.0 --port "$port"
  else
    exec "$PYTHON_CMD" -m uvicorn web.app:app --host 0.0.0.0 --port "$port"
  fi
}

case "${1:-}" in
  web)
    if [ ! -f "$HOME/canada28_bot.py" ]; then
      echo -e "${C_RED}未找到 canada28_bot.py，请确认安装是否完成。${C_RESET}"
      exit 1
    fi
    if [ ! -f "$HOME/web/app.py" ]; then
      echo -e "${C_RED}未找到 web/app.py，请确认安装是否完成。${C_RESET}"
      exit 1
    fi

    PORT="$(get_port)"
    read -r USERNAME PASSWORD < <(get_auth)

    echo -e "${C_BLUE}即将启动 Web 面板...${C_RESET}"
    echo -e "访问地址: ${C_GREEN}http://0.0.0.0:${PORT}/${C_RESET} （同机可用 http://127.0.0.1:${PORT}/）"
    echo -e "登录账号: ${C_YELLOW}${USERNAME}${C_RESET}"
    echo -e "登录密码: ${C_YELLOW}${PASSWORD}${C_RESET}"
    echo -e "提示：关闭该终端或按 Ctrl+C 将停止 Web 面板（面板内可启动/停止机器人引擎）"
    start_uvicorn "$PORT"
    ;;
  *)
    echo "用法: $0 web"
    exit 1
    ;;
esac
