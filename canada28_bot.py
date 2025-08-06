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
BET_DELAY_SECONDS = 30 # 开奖后等待多少秒再下注，确保盘口开放

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

def get_strategy_config(strategy_name):
    """获取单个策略的配置。"""
    print(f"\n--- 配置 [{strategy_name}] 玩法 ---")
    while True:
        enable = input(f"是否启用 [{strategy_name}] 玩法? (y/n): ").lower()
        if enable in ['y', 'n']:
            break
        print("无效输入，请输入 'y' 或 'n'。")

    if enable == 'n':
        return {"enabled": False}

    while True:
        try:
            initial_bet = int(input(f"  - 请输入 [{strategy_name}] 的初始下注金额 (正整数): "))
            if initial_bet > 0:
                break
            else:
                print("金额必须是大于零的正整数。")
        except ValueError:
            print("无效的输入，请输入一个数字。")

    while True:
        try:
            max_win_streak = int(input(f"  - 请输入 [{strategy_name}] 的最高连续盈利轮数 (正整数): "))
            if max_win_streak > 0:
                break
            else:
                print("轮数必须是大于零的正整数。")
        except ValueError:
            print("无效的输入，请输入一个数字。")
    
    return {
        "enabled": True,
        "initial_bet": initial_bet,
        "max_win_streak": max_win_streak
    }

def initial_setup():
    """执行首次运行的交互式配置。"""
    print("\n--- 首次运行配置 ---")
    
    chat_id = select_chat_interactively()

    config = {
        'chat_id': chat_id,
        'strategies': {
            'big_small': get_strategy_config('大小'),
            'odd_even': get_strategy_config('单双')
        }
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
        # 检查新的结构是否完整
        if 'chat_id' in config and 'strategies' in config and \
           'big_small' in config['strategies'] and 'odd_even' in config['strategies']:
            print(f"已从 {CONFIG_FILE} 加载配置。")
            return config
        else:
            print(f"警告: {CONFIG_FILE} 文件不完整或格式已过时，将重新开始配置。")
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
        print("\n" + "="*50)
        # 打印所有启用策略的当前状态
        for name, strategy_state in state['strategies'].items():
            print(f"策略 [{name}]: 连胜 {strategy_state['win_streak']} 场 | 下次下注金额 {strategy_state['current_bet']}")

        # 1. 等待下注盘口开放
        try:
            API_TIMEZONE = timezone(timedelta(hours=8))
            last_award_time_aware = datetime.strptime(f"{datetime.now().year}-{state['last_award_time_str']}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=API_TIMEZONE)
            betting_opens_time_aware = last_award_time_aware + timedelta(seconds=BET_DELAY_SECONDS)
            now_aware = datetime.now(API_TIMEZONE)
            if now_aware < betting_opens_time_aware:
                delay_duration = (betting_opens_time_aware - now_aware).total_seconds()
                if delay_duration > 0:
                    print(f"上一期结果已出，等待 {delay_duration:.1f} 秒以确保盘口开放...")
                    time.sleep(delay_duration)
        except (ValueError, KeyError) as e:
            print(f"警告: 计算下注延迟时出错 ({e})。跳过延迟。")

        # 2. 根据上一期结果，为所有启用的策略生成下注指令
        bet_messages = []
        last_sum = state['last_period_sum']
        
        # -- 大小策略 --
        if config['strategies']['big_small']['enabled']:
            bet_type = "大" if last_sum >= 14 else "小"
            bet_amount = state['strategies']['big_small']['current_bet']
            bet_messages.append(f"{bet_type}{bet_amount}")
        
        # -- 单双策略 --
        if config['strategies']['odd_even']['enabled']:
            bet_type = "双" if last_sum % 2 == 0 else "单"
            bet_amount = state['strategies']['odd_even']['current_bet']
            bet_messages.append(f"{bet_type}{bet_amount}")

        if not bet_messages:
            print("没有启用的下注策略，脚本将暂停。请使用 './run.sh config' 重新配置。")
            break # 退出主循环

        final_bet_message = " ".join(bet_messages)
        print(f"根据上一期和值 [{last_sum}], 准备下注: {final_bet_message}")
        if not send_bet_command(config['chat_id'], final_bet_message):
            print(f"下注失败，将在 {RETRY_INTERVAL_SECONDS} 秒后重试...")
            time.sleep(RETRY_INTERVAL_SECONDS)
            continue

        # 3. 等待下一期开奖
        try:
            API_TIMEZONE = timezone(timedelta(hours=8))
            aware_last_award_time = datetime.strptime(f"{datetime.now().year}-{state['last_award_time_str']}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=API_TIMEZONE)
            aware_next_award_time = aware_last_award_time + timedelta(seconds=AWARD_INTERVAL_SECONDS)
            now_utc = datetime.now(timezone.utc)
            next_award_time_utc = aware_next_award_time.astimezone(timezone.utc)
            sleep_until_utc = next_award_time_utc - timedelta(seconds=POLL_AHEAD_SECONDS)
            if now_utc < sleep_until_utc:
                sleep_duration = (sleep_until_utc - now_utc).total_seconds()
                display_next_award_time = next_award_time_utc.astimezone(API_TIMEZONE)
                display_sleep_until = sleep_until_utc.astimezone(API_TIMEZONE)
                print(f"下注成功。预计下期开奖时间 (UTC+8): {display_next_award_time.strftime('%H:%M:%S')}")
                print(f"将休眠 {sleep_duration:.1f} 秒，到 {display_sleep_until.strftime('%H:%M:%S')} (UTC+8) 再开始轮询...")
                time.sleep(sleep_duration)
            else:
                print("警告: 计算出的下次轮询时间已过或非常接近，立即开始轮询。")
        except ValueError:
            print(f"警告: 无法解析时间 '{state['last_award_time_str']}'。回退到固定时间等待。")
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
        
        # 4. 独立核对每个策略的输赢
        new_sum = new_result['sum']
        
        # -- 大小策略 --
        if config['strategies']['big_small']['enabled']:
            strategy_state = state['strategies']['big_small']
            last_bet_was_big = ("大" if last_sum >= 14 else "小") == "大"
            new_result_was_big = new_sum >= 14
            if last_bet_was_big == new_result_was_big:
                print("策略 [大小]: [胜利!]")
                strategy_state['win_streak'] += 1
                if strategy_state['win_streak'] >= config['strategies']['big_small']['max_win_streak']:
                    strategy_state['win_streak'] = 0
                    strategy_state['current_bet'] = config['strategies']['big_small']['initial_bet']
                else:
                    strategy_state['current_bet'] *= 2
            else:
                print("策略 [大小]: [失败!]")
                strategy_state['win_streak'] = 0
                strategy_state['current_bet'] = config['strategies']['big_small']['initial_bet']

        # -- 单双策略 --
        if config['strategies']['odd_even']['enabled']:
            strategy_state = state['strategies']['odd_even']
            last_bet_was_even = ("双" if last_sum % 2 == 0 else "单") == "双"
            new_result_was_even = new_sum % 2 == 0
            if last_bet_was_even == new_result_was_even:
                print("策略 [单双]: [胜利!]")
                strategy_state['win_streak'] += 1
                if strategy_state['win_streak'] >= config['strategies']['odd_even']['max_win_streak']:
                    strategy_state['win_streak'] = 0
                    strategy_state['current_bet'] = config['strategies']['odd_even']['initial_bet']
                else:
                    strategy_state['current_bet'] *= 2
            else:
                print("策略 [单双]: [失败!]")
                strategy_state['win_streak'] = 0
                strategy_state['current_bet'] = config['strategies']['odd_even']['initial_bet']

        # 5. 更新全局状态
        state['last_period_issue'] = new_result['issue']
        state['last_period_sum'] = new_result['sum']
        state['last_award_time_str'] = new_result['time']
        
        save_state(state)


def load_state(config):
    """加载状态，如果文件不存在或无效，则创建新状态。"""
    if Path(STATE_FILE).is_file():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            # 简单校验一下状态文件结构
            if 'strategies' in state and 'big_small' in state['strategies']:
                 return state
            else:
                print(f"警告: 状态文件 {STATE_FILE} 格式不正确。将创建新状态。")
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: 读取状态文件 {STATE_FILE} 失败: {e}。将创建新状态。")
    
    # 如果文件不存在或读取失败，创建并返回一个全新的状态
    initial_strategies_state = {}
    for name, strategy_config in config['strategies'].items():
        if strategy_config['enabled']:
            initial_strategies_state[name] = {
                'current_bet': strategy_config['initial_bet'],
                'win_streak': 0
            }

    return {
        'strategies': initial_strategies_state,
        'last_period_sum': None,
        'last_period_issue': None,
        'last_award_time_str': None,
    }

def main():
    """主函数"""
    # 检查是否只进行配置
    if '--config-only' in sys.argv:
        print("--- 进入交互式配置模式 ---")
        # 直接调用 initial_setup() 来强制进行重新配置
        initial_setup()
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
    for name, strategy_config in config['strategies'].items():
        if strategy_config['enabled']:
            print(f"  - [{name}] 玩法已启用: 初始金额={strategy_config['initial_bet']}, 最大连胜={strategy_config['max_win_streak']}")
        else:
            print(f"  - [{name}] 玩法已禁用。")
    
    # 从文件加载状态，或创建新状态
    state = load_state(config)
    
    try:
        run_bot(config, state)
    except KeyboardInterrupt:
        print("\n\n检测到 Ctrl+C，程序已安全退出。")
        sys.exit(0)

if __name__ == '__main__':
    main()
