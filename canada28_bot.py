import os
import json
import sys
import subprocess
import requests
import time
from pathlib import Path

# --- 全局配置 ---
CONFIG_FILE = 'config.json'
SIGNER_DIR = '.signer'
API_URL = 'http://27.106.127.108:9990/ce/apis.php'
LOOP_INTERVAL_SECONDS = 60 # 主循环间隔时间（秒）
RETRY_INTERVAL_SECONDS = 30 # 失败或等待新期数时的重试间隔

def find_latest_chats_file():
    """在 .signer/users/ 目录下查找 latest_chats.json 文件。"""
    # 使用 Pathlib 提高路径操作的健壮性
    signer_path = Path(SIGNER_DIR)
    users_dir = signer_path / 'users'
    
    if not users_dir.is_dir():
        return None

    # 查找所有用户子目录
    user_subdirs = [d for d in users_dir.iterdir() if d.is_dir()]
    if not user_subdirs:
        return None

    # 优先选择修改时间最新的用户目录
    latest_user_dir = max(user_subdirs, key=lambda p: p.stat().st_mtime)
    chats_file = latest_user_dir / 'latest_chats.json'

    if chats_file.is_file():
        print(f"找到聊天记录文件: {chats_file}")
        return chats_file
    return None

def select_chat_interactively():
    """交互式地让用户选择一个 chat_id。"""
    chats_file = find_latest_chats_file()
    if not chats_file:
        print("\n错误：在 .signer 目录中找不到任何 tg-signer 用户信息。")
        print("请确保您已经完成以下步骤：")
        print("1. 成功运行了 'tg-signer login' 并登录了您的账户。")
        print("2. 与您想下注的机器人或群组进行过至少一次对话。")
        sys.exit(1)

    with open(chats_file, 'r', encoding='utf-8') as f:
        try:
            chats = json.load(f)
        except json.JSONDecodeError:
            print(f"错误：无法解析聊天记录文件 {chats_file}。文件可能已损坏。")
            sys.exit(1)

    if not chats:
        print("错误：最近的对话列表为空。请先与您的目标机器人进行一次对话。")
        sys.exit(1)

    print("\n检测到以下最近对话，请选择您要下注的目标：")
    for i, chat in enumerate(chats):
        # 优先使用 title，否则尝试拼接 first_name 和 last_name
        title = chat.get('title')
        if not title:
            first_name = chat.get('first_name', '')
            last_name = chat.get('last_name', '')
            title = f"{first_name} {last_name}".strip()
        if not title:
            title = f"未知对话 (ID: {chat['id']})"
        print(f"  {i + 1}: {title} (ID: {chat['id']})")

    while True:
        try:
            choice_str = input(f"\n请输入选择的编号 (1-{len(chats)}): ")
            choice = int(choice_str)
            if 1 <= choice <= len(chats):
                return chats[choice - 1]['id']
            else:
                print(f"无效的输入，请输入 1 到 {len(chats)} 之间的数字。")
        except ValueError:
            print("无效的输入，请输入一个数字。")

def initial_setup():
    """执行首次运行的交互式配置。"""
    print("\n--- 首次运行配置 ---")
    
    chat_id = select_chat_interactively()

    while True:
        try:
            initial_bet = int(input("请输入初始下注金额 (必须是正整数, 例如: 1): "))
            if initial_bet > 0:
                break
            else:
                print("金额必须是大于零的正整数。")
        except ValueError:
            print("无效的输入，请输入一个数字。")

    while True:
        try:
            max_win_streak = int(input("请输入最高连续盈利轮数 (必须是正整数, 例如: 10): "))
            if max_win_streak > 0:
                break
            else:
                print("轮数必须是大于零的正整数。")
        except ValueError:
            print("无效的输入，请输入一个数字。")
            
    config = {
        'chat_id': chat_id,
        'initial_bet': initial_bet,
        'max_win_streak': max_win_streak
    }

    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)
    
    print(f"\n配置已成功保存到 {CONFIG_FILE}。")
    return config

def load_config():
    """加载配置，如果配置文件不存在或不完整则执行首次配置。"""
    if not Path(CONFIG_FILE).is_file():
        return initial_setup()
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        if 'chat_id' in config and 'initial_bet' in config and 'max_win_streak' in config:
            print(f"已从 {CONFIG_FILE} 加载配置。")
            return config
        else:
            print(f"警告: {CONFIG_FILE} 文件不完整，将重新开始配置。")
            return initial_setup()
    except (json.JSONDecodeError, IOError) as e:
        print(f"警告: 读取 {CONFIG_FILE} 失败: {e}。将重新开始配置。")
        return initial_setup()

def get_latest_result():
    """从API获取最新的开奖结果。"""
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        if 'sum' in data and 'time' in data:
            return data
        else:
            print("警告: API返回的数据格式不正确，缺少 'sum' 或 'time' 字段。")
            return None
    except requests.exceptions.RequestException as e:
        print(f"错误: 请求API失败: {e}")
        return None
    except json.JSONDecodeError:
        print(f"错误: 解析API返回的JSON数据失败。内容: {response.text}")
        return None

def send_bet_command(chat_id, message):
    """使用 tg-signer 发送下注命令。"""
    command = ['tg-signer', 'send-text', '--chat_id', str(chat_id), '--text', message]
    try:
        print(f"执行命令: {' '.join(command)}")
        # 使用 check=True 会在命令失败时抛出异常
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        print("命令执行成功。")
        return True
    except FileNotFoundError:
        print("\n错误: 'tg-signer' 命令未找到。")
        print("请确保您已成功运行 install.sh 并且 'tg-signer' 在您的系统路径中。")
        return False
    except subprocess.CalledProcessError as e:
        print(f"\n错误: 执行 tg-signer 命令失败。")
        print(f"返回码: {e.returncode}")
        print(f"输出: {e.stdout}")
        print(f"错误输出: {e.stderr}")
        return False

def run_bot(config, state):
    """运行机器人的主循环。"""
    print("\n--- 机器人开始运行 (按 Ctrl+C 退出) ---")
    while True:
        print("\n" + "="*40)
        print(f"当前状态: 连胜 {state['win_streak']} 场 | 下次下注金额 {state['current_bet']}")
        
        print("正在获取最新开奖结果...")
        result = get_latest_result()

        if not result:
            print(f"获取结果失败，将在 {RETRY_INTERVAL_SECONDS} 秒后重试...")
            time.sleep(RETRY_INTERVAL_SECONDS)
            continue

        if result['time'] == state['last_period_time']:
            print(f"等待新的开奖结果... (当前期数: {result['time']})")
            time.sleep(RETRY_INTERVAL_SECONDS)
            continue
        
        previous_sum = state['last_period_sum']
        previous_bet_type = state.get('last_bet_type')
        
        state['last_period_sum'] = result['sum']
        state['last_period_time'] = result['time']
        print(f"获取到新结果: 时间={result['time']}, 和值={result['sum']}")

        # 从第二次循环开始，根据上一期的结果判断输赢
        if previous_sum is not None and previous_bet_type is not None:
            last_bet_was_big = (previous_bet_type == '大')
            last_result_was_big = (previous_sum >= 14)
            
            print(f"核对上一期结果: 下注[{previous_bet_type}], 开奖和值[{previous_sum}] -> [{'大' if last_result_was_big else '小'}]")

            if last_bet_was_big == last_result_was_big:
                print("结果: [胜利]!")
                state['win_streak'] += 1
                if state['win_streak'] >= config['max_win_streak']:
                    print(f"达到最大连胜次数 {config['max_win_streak']}！重置金额和连胜。")
                    state['win_streak'] = 0
                    state['current_bet'] = config['initial_bet']
                else:
                    state['current_bet'] *= 2
                    print(f"连胜 {state['win_streak']} 场，下注金额翻倍至 {state['current_bet']}。")
            else:
                print("结果: [失败]!")
                state['win_streak'] = 0
                state['current_bet'] = config['initial_bet']
                print(f"连胜中断，下注金额重置为 {state['current_bet']}。")

        # 准备本期的下注指令
        current_bet_type = "大" if result['sum'] >= 14 else "小"
        bet_amount = state['current_bet']
        bet_message = f"{current_bet_type}{bet_amount}"
        
        state['last_bet_type'] = current_bet_type # 记录本次下注类型以备下次核对

        print(f"准备下注: {bet_message}")
        
        if send_bet_command(config['chat_id'], bet_message):
            print(f"下注成功，等待 {LOOP_INTERVAL_SECONDS} 秒进入下一轮...")
            time.sleep(LOOP_INTERVAL_SECONDS)
        else:
            print(f"下注失败，将在 {RETRY_INTERVAL_SECONDS} 秒后重试...")
            # 如果发送失败，不更新状态，直接重试
            time.sleep(RETRY_INTERVAL_SECONDS)

def main():
    """主函数"""
    config = load_config()
    
    print("\n配置加载成功:")
    print(f"  - 目标 Chat ID: {config['chat_id']}")
    print(f"  - 初始下注金额: {config['initial_bet']}")
    print(f"  - 最高盈利轮数: {config['max_win_streak']}")
    
    # 初始化状态
    state = {
        'current_bet': config['initial_bet'],
        'win_streak': 0,
        'last_period_sum': None,
        'last_period_time': None,
        'last_bet_type': None
    }
    
    try:
        run_bot(config, state)
    except KeyboardInterrupt:
        print("\n\n检测到 Ctrl+C，程序已安全退出。")
        sys.exit(0)

if __name__ == '__main__':
    main()