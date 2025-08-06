#!/bin/bash
#
# 自动化部署与环境安装脚本 (专为Linux设计)
#
# 使用方法:
# bash -c "$(curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/install.sh)"
#

# --- 配置 ---
# !!! 请将下面的地址替换为您自己仓库的 raw 文件地址 !!!
REPO_BASE_URL="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main"
INSTALL_DIR="$HOME/canada28_bot"
FILES_TO_DOWNLOAD=("run.sh" "canada28_bot.py")

# --- 颜色定义 ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'

# --- 函数 ---
function print_info() {
    echo -e "${C_BLUE}INFO: $1${C_RESET}"
}

function print_success() {
    echo -e "${C_GREEN}SUCCESS: $1${C_RESET}"
}

function print_error() {
    echo -e "${C_RED}ERROR: $1${C_RESET}" >&2
}

# --- 主逻辑 ---
echo "============================================="
echo "  加拿大28机器人 - 自动化部署与安装程序  "
echo "============================================="
echo

# 1. 创建并进入安装目录
print_info "将在 '$INSTALL_DIR' 目录中安装机器人..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR" || { print_error "无法创建或进入目录 '$INSTALL_DIR'。"; exit 1; }

# 2. 下载必要的脚本文件
print_info "正在从GitHub仓库下载脚本文件..."
for file in "${FILES_TO_DOWNLOAD[@]}"; do
    print_info "  -> 下载 $file..."
    if ! curl -sSL "${REPO_BASE_URL}/${file}" -o "$file"; then
        print_error "下载 '$file' 失败。请检查您的网络连接和仓库URL。"
        exit 1
    fi
done
print_success "所有脚本文件下载完成。"

# 3. 确定包管理器
print_info "正在检测Linux发行版和包管理器..."
if command -v apt-get &> /dev/null; then
    PKG_MANAGER="apt"
    print_info "检测到 Debian/Ubuntu (使用 apt)"
elif command -v dnf &> /dev/null; then
    PKG_MANAGER="dnf"
    print_info "检测到 Fedora/CentOS 8+ (使用 dnf)"
elif command -v yum &> /dev/null; then
    PKG_MANAGER="yum"
    print_info "检测到 CentOS 7 (使用 yum)"
else
    print_error "无法确定您的包管理器 (apt, dnf, yum)。"
    print_error "请手动安装 Python 3.9+ 和 python3-pip。"
    exit 1
fi

# 2. 安装Python和pip
print_info "正在安装 Python 3.9+ 和 pip..."
# 检查一个常见的python3.9命令是否存在
if ! command -v python3.9 &> /dev/null; then
    print_info "未找到 python3.9，尝试自动安装..."
    # 切换到root权限执行安装
    if [[ $EUID -ne 0 ]]; then
       print_info "需要 root 权限来安装软件包，请输入您的密码。"
       # 使用 sudo -v 预先获取权限
       sudo -v
       if [ $? -ne 0 ]; then
           print_error "获取 root 权限失败，请以 root 用户或使用 sudo 运行此脚本。"
           exit 1
       fi
    fi

    case $PKG_MANAGER in
        apt)
            sudo apt-get update
            sudo apt-get install -y python3.9 python3.9-venv python3-pip
            ;;
        dnf)
            sudo dnf install -y python39
            ;;
        yum)
            print_error "CentOS 7/8 的自动安装较为复杂，建议您手动安装 Python 3.9+ 后再运行此脚本。"
            exit 1
            ;;
    esac
    if [ $? -ne 0 ]; then
        print_error "Python 安装失败。请检查错误信息并尝试手动安装。"
        exit 1
    fi
    print_success "Python 安装成功。"
else
    print_info "已检测到 Python 3.9+。"
fi

# 确保python3命令指向新版本
PYTHON_CMD="python3.9"
if ! command -v $PYTHON_CMD &> /dev/null; then
    PYTHON_CMD="python3" # 回退到 python3
fi

# 3. 安装Python库
print_info "正在使用 pip 安装必要的 Python 库 (tg-signer, requests)..."
if ! $PYTHON_CMD -m pip install -U tg-signer requests; then
    print_error "使用 pip 安装库失败。请检查pip配置和网络连接。"
    exit 1
fi

print_success "所有依赖库均已成功安装！"

# 赋予运行脚本执行权限
print_info "正在为 run.sh 添加执行权限..."
chmod +x run.sh

echo
echo "------------------------------------------------------------------"
print_success "部署与环境配置全部完成!"
echo
print_info "下一步操作:"
echo -e "1. ${C_YELLOW}请进入您的专属目录:${C_RESET}"
echo -e "   ${C_GREEN}cd $INSTALL_DIR${C_RESET}"
echo
echo -e "2. ${C_YELLOW}运行以下命令登录您的 Telegram 账户:${C_RESET}"
echo -e "   ${C_GREEN}tg-signer login${C_RESET}"
echo
print_info "3. 登录成功后, 与您要下注的机器人进行一次任意对话。"
echo
print_info "4. 最后, 运行启动脚本来开始自动下注:"
echo -e "   ${C_GREEN}./run.sh${C_RESET}"
echo "------------------------------------------------------------------"
echo

exit 0
