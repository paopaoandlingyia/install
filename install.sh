#!/bin/bash
#
# 自动化部署与环境安装脚本 (专为Linux设计)
#
# 使用方法:
# bash -c "$(curl -fsSL https://raw.githubusercontent.com/paopaoandlingyia/install/main/install.sh)"
#

# --- 配置 ---
# !!! 请将下面的地址替换为您自己仓库的 raw 文件地址 !!!
REPO_BASE_URL="https://raw.githubusercontent.com/paopaoandlingyia/install/main"
# 将文件直接安装到用户主目录
INSTALL_DIR="$HOME"
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
print_info "将在您的主目录 ('$INSTALL_DIR') 中安装机器人脚本..."
# 确保主目录存在并进入
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR" || { print_error "无法进入主目录 '$INSTALL_DIR'。"; exit 1; }

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

# 4. 检查并配置Python环境
PYTHON_CMD=""

# 检查系统现有的python3版本是否满足要求
function check_existing_python() {
    print_info "正在检查现有的 Python 3 版本..."
    if ! command -v python3 &> /dev/null; then
        print_info "未找到 'python3' 命令。"
        return 1
    fi

    PY_VERSION=$("python3" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

    if [[ "$PY_MAJOR" -lt 3 || ("$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 9) ]]; then
        print_warn "找到的 Python 版本 ($PY_VERSION) 过低，需要 >= 3.9。"
        return 1
    else
        print_success "检测到符合要求的 Python 版本: $PY_VERSION"
        PYTHON_CMD="python3"
        return 0
    fi
}

# 主安装逻辑
print_info "正在配置 Python 环境..."
if check_existing_python; then
    print_info "使用系统中已有的 Python 环境。"
else
    print_info "需要安装或升级 Python。尝试自动安装..."
    if [[ $EUID -ne 0 ]]; then
       print_info "需要 root 权限来安装软件包，请输入您的密码。"
       sudo -v || { print_error "获取 root 权限失败。"; exit 1; }
    fi

    case $PKG_MANAGER in
        apt)
            sudo apt-get update
            # 安装通用的python3包，而不是指定版本
            sudo apt-get install -y python3 python3-venv python3-pip
            ;;
        dnf|yum)
            # dnf/yum 通常直接提供 python3 包
            sudo "$PKG_MANAGER" install -y python3
            ;;
    esac

    if [ $? -ne 0 ]; then
        print_error "Python 自动安装失败。请检查错误信息并尝试手动安装。"
        exit 1
    fi
    print_success "Python 安装/更新成功。"
    # 再次检查以确认
    check_existing_python || { print_error "安装后仍无法找到合适的Python版本。"; exit 1; }
fi

# 5. 安装Python库
print_info "正在使用 pip 安装必要的 Python 库 (tg-signer, requests)..."
if [ -z "$PYTHON_CMD" ]; then
    print_error "未能确定要使用的 Python 命令，无法安装库。脚本无法继续。"
    exit 1
fi

if ! "$PYTHON_CMD" -m pip install -U tg-signer requests; then
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
echo -e "1. ${C_YELLOW}请运行以下命令登录您的 Telegram 账户:${C_RESET}"
echo -e "   (系统会提示您输入手机号、密码和验证码)"
echo -e "   ${C_YELLOW}重要提示: 输入手机号时，请务必包含国家代码，例如: +861234567890${C_RESET}"
echo -e "   ${C_GREEN}tg-signer login${C_RESET}"
echo
print_info "2. 确保机器人在您的对话列表。"
echo
print_info "3. 最后, 运行启动脚本来开始自动下注:"
echo -e "   (如果不在主目录, 请使用 'cd ~' 命令返回)"
echo -e "   ${C_GREEN}./run.sh${C_RESET}"
echo "------------------------------------------------------------------"
echo

exit 0
