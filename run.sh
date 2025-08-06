#!/bin/bash
#
# 加拿大28机器人 - 服务管理脚本
#
# 用法:
#   ./run.sh start    - 在后台启动机器人
#   ./run.sh stop     - 停止在后台运行的机器人
#   ./run.sh status   - 查看机器人的运行状态
#   ./run.sh log      - 实时查看机器人日志
#

# --- 配置 ---
PYTHON_CMD="python3.9"
MAIN_SCRIPT_NAME="canada28_bot.py"
MAIN_SCRIPT_PATH="$HOME/$MAIN_SCRIPT_NAME"
LOG_FILE="$HOME/bot.log"

# --- 颜色定义 ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'

# --- 辅助函数 ---
check_running() {
    # 使用 pgrep 检查进程是否存在。-f 选项匹配完整命令行。
    if pgrep -f "$MAIN_SCRIPT_NAME" > /dev/null; then
        return 0 # 正在运行
    else
        return 1 # 未运行
    fi
}

# --- 主逻辑 ---
case "$1" in
    start)
        echo "正在启动机器人..."
        if check_running; then
            echo -e "${C_YELLOW}机器人已经在运行中。${C_RESET}"
            exit 1
        fi
        
        # 检查主脚本是否存在
        if [ ! -f "$MAIN_SCRIPT_PATH" ]; then
            echo -e "${C_RED}错误: 主脚本 '$MAIN_SCRIPT_PATH' 不存在。${C_RESET}"
            exit 1
        fi

        # 使用 nohup 在后台启动，并将标准输出和错误输出重定向到日志文件
        nohup "$PYTHON_CMD" "$MAIN_SCRIPT_PATH" > "$LOG_FILE" 2>&1 &
        
        # 短暂等待后再次检查，确保启动成功
        sleep 2
        if check_running; then
            echo -e "${C_GREEN}机器人启动成功。日志将记录在 $LOG_FILE ${C_RESET}"
            echo "您可以使用 './run.sh log' 来查看实时日志。"
        else
            echo -e "${C_RED}机器人启动失败，请检查 $LOG_FILE 文件以获取错误信息。${C_RESET}"
        fi
        ;;
    stop)
        echo "正在停止机器人..."
        if ! check_running; then
            echo -e "${C_YELLOW}机器人当前未在运行。${C_RESET}"
            exit 1
        fi
        
        # 使用 pkill 优雅地终止进程
        pkill -f "$MAIN_SCRIPT_NAME"
        sleep 1
        
        if ! check_running; then
            echo -e "${C_GREEN}机器人已成功停止。${C_RESET}"
        else
            echo -e "${C_RED}停止机器人失败，请手动检查进程。${C_RESET}"
        fi
        ;;
    status)
        echo "正在检查机器人状态..."
        if check_running; then
            PID=$(pgrep -f "$MAIN_SCRIPT_NAME")
            echo -e "${C_GREEN}机器人正在运行。 (PID: $PID)${C_RESET}"
        else
            echo -e "${C_YELLOW}机器人已停止。${C_RESET}"
        fi
        ;;
    log)
        echo "正在显示实时日志 (按 Ctrl+C 退出)..."
        if [ ! -f "$LOG_FILE" ]; then
            echo -e "${C_YELLOW}日志文件 $LOG_FILE 不存在。机器人可能还未运行过。${C_RESET}"
            exit 1
        fi
        tail -f "$LOG_FILE"
        ;;
    *)
        echo "用法: $0 {start|stop|status|log}"
        exit 1
        ;;
esac

exit 0
