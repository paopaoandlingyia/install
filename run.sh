#!/bin/bash
#
# 日常运行脚本
#

PYTHON_CMD="python3.9"
MAIN_SCRIPT="canada28_bot.py"

# 确保脚本从其所在目录运行
cd "$(dirname "$0")"

# 检查 python 命令是否存在
if ! command -v $PYTHON_CMD &> /dev/null; then
    echo "错误: 未找到 '$PYTHON_CMD' 命令。尝试使用 'python3'..."
    PYTHON_CMD="python3"
    if ! command -v $PYTHON_CMD &> /dev/null; then
        echo "错误: 也未找到 'python3' 命令。"
        echo "请确保您已经成功运行了 install.sh 并正确配置了环境。"
        exit 1
    fi
fi

# 检查主脚本是否存在
if [ ! -f "$MAIN_SCRIPT" ]; then
    echo "错误: 主脚本 '$MAIN_SCRIPT' 不存在。"
    echo "请确保 run.sh 和 canada28_bot.py 在同一个目录下。"
    exit 1
fi

# 运行主程序
echo "启动加拿大28自动下注机器人..."
$PYTHON_CMD $MAIN_SCRIPT