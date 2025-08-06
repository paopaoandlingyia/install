import os
import json
import sys
import subprocess
import requests
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

# --- 全局配置 ---
HOME_DIR = Path.home()
CONFIG_FILE = HOME_DIR / 'config.json'
STATE_FILE = HOME_DIR / 'state.json' # 新增状态文件路径
SIGNER_DIR = HOME_DIR / '.signer'
API_URL = 'http://27.106.127.108:9990/ce/apis.php'
# 3.5分钟 = 210秒。我们先等待200秒，然后开始轮询。
POLLING_INTERVAL_SECONDS = 2 # 轮询新结果的间隔时间
RETRY_INTERVAL_SECONDS = 30 # API请求失败后的重试间隔
AWARD_INTERVAL_SECONDS = 210 # 官方开奖间隔 (3.5分钟)
POLL_AHEAD_SECONDS = 10 # 提前多少秒开始轮询

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
        # 使用新的 'issue' 字段来验证返回数据
        if 'issue' in data and 'sum' in data and 'time' in data:
            return data
        else:
            print(f"警告: API返回的数据格式不正确，缺少 'issue', 'sum' 或 'time' 字段。返回内容: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"错误: 请求API失败: {e}")
        return None
    except json.JSONDecodeError:
        print(f"错误: 解析API返回的JSON数据失败。内容: {response.text}")
        return None

def send_bet_command(chat_id, message):
    """使用 tg-signer 发送下注命令。"""
    command = ['tg-signer', 'send-text']

    # 根据 tg-signer 的用法, CHAT_ID 和 TEXT 是位置参数。
    # 如果 chat_id 是负数, 需要在前面加上 '--' 以防止其被解析为选项。
    if int(chat_id) < 0:
        command.append('--')
    
    command.extend([str(chat_id), message])

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

def save_state(state):
    """将当前状态保存到 state.json 文件。"""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4)
        # print("状态已保存。") # 频繁保存时可以注释掉此行，避免刷屏
    except IOError as e:
        print(f"警告: 保存状态到 {STATE_FILE} 失败: {e}")

def run_bot(config, state):
    """运行机器人的主循环。"""
    print("\n--- 机器人开始运行 (按 Ctrl+C 退出) ---")

    # 如果状态是新创建的（没有上一期记录），则需要先获取一次初始结果
    if not state.get('last_period_issue'):
        print("未找到历史状态，正在获取初始开奖结果...")
        while True:
            initial_result = get_latest_result()
            if initial_result:
                state['last_period_issue'] = initial_result['issue']
                state['last_period_sum'] = initial_result['sum']
                state['last_award_time_str'] = initial_result['time']
                print(f"获取到初始结果: 期号={state['last_period_issue']}, 和值={state['last_period_sum']}, 时间={state['last_award_time_str']}")
                save_state(state) # 保存初始状态
                break
            else:
                print(f"获取初始结果失败，{RETRY_INTERVAL_SECONDS} 秒后重试...")
                time.sleep(RETRY_INTERVAL_SECONDS)
    else:
        print("成功从 state.json 加载历史状态。")

    # 主循环
    while True:
        print("\n" + "="*40)
        print(f"当前状态: 连胜 {state['win_streak']} 场 | 下次下注金额 {state['current_bet']}")
        
        # 1. 根据上一期结果，决定并下注本期
        bet_type = "大" if state['last_period_sum'] >= 14 else "小"
        bet_amount = state['current_bet']
        bet_message = f"{bet_type}{bet_amount}"
        state['last_bet_type'] = bet_type # 记录下注，用于之后核对

        print(f"根据上一期和值 [{state['last_period_sum']}], 准备下注: {bet_message}")
        if not send_bet_command(config['chat_id'], bet_message):
            print(f"下注失败，将在 {RETRY_INTERVAL_SECONDS} 秒后重试...")
            time.sleep(RETRY_INTERVAL_SECONDS)
            continue # 如果下注失败，则重新开始本轮循环

        # 2. 根据上一期开奖时间，计算并等待到下一期开奖前夕 (时区安全)
        try:
            # 定义API所在的时区 (中国标准时间, UTC+8)
            API_TIMEZONE = timezone(timedelta(hours=8))

            # 解析API返回的时间字符串，并附加时区信息使其成为“感知型”时间对象
            naive_last_award_time = datetime.strptime(f"{datetime.now().year}-{state['last_award_time_str']}", "%Y-%m-%d %H:%M:%S")
            aware_last_award_time = naive_last_award_time.replace(tzinfo=API_TIMEZONE)

            # 计算下一次开奖时间
            aware_next_award_time = aware_last_award_time + timedelta(seconds=AWARD_INTERVAL_SECONDS)

            # 获取当前的UTC时间 (感知型)
            now_utc = datetime.now(timezone.utc)
            
            # 将下一次开奖时间也转换为UTC，以便进行 apples-to-apples 比较
            next_award_time_utc = aware_next_award_time.astimezone(timezone.utc)
            
            # 计算应该休眠到哪个UTC时间点
            sleep_until_utc = next_award_time_utc - timedelta(seconds=POLL_AHEAD_SECONDS)

            if now_utc < sleep_until_utc:
                sleep_duration = (sleep_until_utc - now_utc).total_seconds()
                # 为了友好显示，将下次开奖时间转换回API时区进行打印
                display_next_award_time = next_award_time_utc.astimezone(API_TIMEZONE)
                display_sleep_until = sleep_until_utc.astimezone(API_TIMEZONE)
                
                print(f"下注成功。预计下期开奖时间 (UTC+8): {display_next_award_time.strftime('%H:%M:%S')}")
                print(f"将休眠 {sleep_duration:.1f} 秒，到 {display_sleep_until.strftime('%H:%M:%S')} (UTC+8) 再开始轮询...")
                time.sleep(sleep_duration)
            else:
                print("警告: 计算出的下次轮询时间已过或非常接近，立即开始轮询。")

        except ValueError:
            print(f"警告: 无法解析时间 '{state['last_award_time_str']}'。回退到固定时间等待。")
            # 在时区计算失败时，使用一个安全的、较短的固定等待
            time.sleep(AWARD_INTERVAL_SECONDS - POLL_AHEAD_SECONDS if AWARD_INTERVAL_SECONDS > POLL_AHEAD_SECONDS else 60)

        print("休眠结束，开始轮询新一期结果...")
        new_result = None
        while True:
            result = get_latest_result()
            if result and result['issue'] != state['last_period_issue']:
                new_result = result
                print(f"获取到新一期结果: 期号={new_result['issue']}, 和值={new_result['sum']}")
                break
            else:
                current_issue = state['last_period_issue'] if not result else result['issue']
                print(f"结果未更新 (当前期号 {current_issue})，{POLLING_INTERVAL_SECONDS} 秒后再次查询...")
                time.sleep(POLLING_INTERVAL_SECONDS)
        
        # 3. 核对输赢
        last_bet_was_big = (state['last_bet_type'] == '大')
        new_result_was_big = (new_result['sum'] >= 14)
        
        print(f"核对结果: 下注[{state['last_bet_type']}], 开奖和值[{new_result['sum']}] -> [{'大' if new_result_was_big else '小'}]")

        if last_bet_was_big == new_result_was_big:
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

        # 4. 更新状态，为下一轮做准备
        state['last_period_issue'] = new_result['issue']
        state['last_period_sum'] = new_result['sum']
        state['last_award_time_str'] = new_result['time']
        
        # 在每个周期结束时保存状态
        save_state(state)


def load_state(config):
    """加载状态，如果文件不存在或无效，则创建新状态。"""
    if Path(STATE_FILE).is_file():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: 读取状态文件 {STATE_FILE} 失败: {e}。将创建新状态。")
    
    # 如果文件不存在或读取失败，创建并返回一个全新的状态
    return {
        'current_bet': config['initial_bet'],
        'win_streak': 0,
        'last_period_sum': None,
        'last_period_issue': None,
        'last_award_time_str': None,
        'last_bet_type': None
    }

def main():
    """主函数"""
    # 检查是否只进行配置
    if '--config-only' in sys.argv:
        print("--- 进入交互式配置模式 ---")
        load_config()
        print("\n配置完成。现在您可以使用 './run.sh start' 来启动机器人。")
        sys.exit(0)

    # 检查配置文件是否存在，如果不存在则提示用户
    if not Path(CONFIG_FILE).is_file():
        print("错误: 配置文件 'config.json' 不存在。")
        print("请先运行 './run.sh config' 来进行初始化配置。")
        sys.exit(1)

    config = load_config()
    
    print("\n配置加载成功:")
    print(f"  - 目标 Chat ID: {config['chat_id']}")
    print(f"  - 初始下注金额: {config['initial_bet']}")
    print(f"  - 最高盈利轮数: {config['max_win_streak']}")
    
    # 从文件加载状态，或创建新状态
    state = load_state(config)
    
    try:
        run_bot(config, state)
    except KeyboardInterrupt:
        print("\n\n检测到 Ctrl+C，程序已安全退出。")
        sys.exit(0)

if __name__ == '__main__':
    main()
