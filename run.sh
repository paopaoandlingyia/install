#!/bin/bash
#
# Canada28 控制面板 - 服务管理脚本
#
# 用法:
#   ./run.sh start    - 在后台启动 Web 面板
#   ./run.sh stop     - 停止在后台运行的 Web 面板
#   ./run.sh status   - 查看 Web 面板的运行状态
#   ./run.sh log      - 实时查看 Web 面板日志
#   ./run.sh restart  - 重启 Web 面板
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

# 切换到主目录以确保相对路径正确
cd "$HOME"

LOG_FILE="$HOME/web.log"
# 用于 pgrep/pkill 的唯一进程标识
PROCESS_PATTERN="uvicorn web.app:app"

# --- 颜色定义 ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'

# --- 辅助函数 ---
check_running() {
    if pgrep -f "$PROCESS_PATTERN" > /dev/null; then
        return 0 # 正在运行
    else
        return 1 # 未运行
    fi
}

get_port() {
  "$PYTHON_CMD" -c 'from canada28_bot import load_config; print(load_config().get("web", {}).get("port", 8787))' | tail -n 1
}

get_auth() {
  "$PYTHON_CMD" -c 'from canada28_bot import load_config; auth = load_config().get("web", {}).get("auth", {}); print(auth.get("username","admin"), auth.get("password","admin123"))' | tail -n 1
}

# --- 主逻辑 ---
case "${1:-}" in
    start)
        echo -e "${C_BLUE}正在启动 Web 面板...${C_RESET}"
        if check_running; then
            echo -e "${C_YELLOW}Web 面板已经在运行中。${C_RESET}"
            exit 1
        fi

        if [ ! -f "$HOME/web/app.py" ]; then
            echo -e "${C_RED}错误: 主脚本 'web/app.py' 不存在。${C_RESET}"
            exit 1
        fi

        PORT="$(get_port)"
        read -r USERNAME PASSWORD < <(get_auth)

        # 使用 nohup 在后台启动，-u 参数确保日志实时写入
        nohup "$PYTHON_CMD" -m uvicorn web.app:app --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &

        # 短暂等待后再次检查，确保启动成功
        sleep 2
        if check_running; then
            echo -e "${C_GREEN}Web 面板启动成功。${C_RESET}"
            echo -e "访问地址: ${C_YELLOW}http://<你的服务器IP>:${PORT}/${C_RESET}"
            echo -e "登录账号: ${C_YELLOW}${USERNAME}${C_RESET}"
            echo -e "登录密码: ${C_YELLOW}${PASSWORD}${C_RESET}"
            echo -e "日志将记录在 ${C_GREEN}$LOG_FILE${C_RESET}"
            echo -e "您可以使用 './run.sh log' 来查看实时日志。"
        else
            echo -e "${C_RED}Web 面板启动失败，请检查 ${LOG_FILE} 文件以获取错误信息。${C_RESET}"
        fi
        ;;

    stop)
        echo -e "${C_BLUE}正在停止 Web 面板...${C_RESET}"
        if ! check_running; then
            echo -e "${C_YELLOW}Web 面板当前未在运行。${C_RESET}"
            exit 1
        fi

        # 使用 pkill 优雅地终止进程
        pkill -f "$PROCESS_PATTERN"
        sleep 1

        if ! check_running; then
            echo -e "${C_GREEN}Web 面板已成功停止。${C_RESET}"
        else
            echo -e "${C_RED}停止 Web 面板失败，请手动检查进程。${C_RESET}"
        fi
        ;;

    status)
        echo -e "${C_BLUE}正在检查 Web 面板状态...${C_RESET}"
        if check_running; then
            PID=$(pgrep -f "$PROCESS_PATTERN")
            echo -e "${C_GREEN}Web 面板正在运行。 (PID: $PID)${C_RESET}"
        else
            echo -e "${C_YELLOW}Web 面板已停止。${C_RESET}"
        fi
        ;;

    log)
        echo -e "${C_BLUE}正在显示实时日志 (按 Ctrl+C 退出)...${C_RESET}"
        if [ ! -f "$LOG_FILE" ]; then
            echo -e "${C_YELLOW}日志文件 $LOG_FILE 不存在。Web 面板可能还未运行过。${C_RESET}"
            exit 1
        fi
        tail -f "$LOG_FILE"
        ;;

    restart)
        echo -e "${C_BLUE}正在重启 Web 面板...${C_RESET}"
        # 这里直接调用脚本自身的 stop 和 start 命令
        "$0" stop
        sleep 2
        "$0" start
        ;;

    *)
        echo "用法: $0 {start|stop|status|log|restart}"
        exit 1
        ;;
esac

exit 0
