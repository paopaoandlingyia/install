import os
import json
import sys
import subprocess
import requests
import time
import random
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone

# --- 全局/路径配置 ---
HOME_DIR = Path.home()
CONFIG_FILE = HOME_DIR / 'config.json'
STATE_FILE = HOME_DIR / 'state.json'
SIGNER_DIR = HOME_DIR / '.signer'

# --- 业务常量 ---
API_URL = 'http://27.106.127.108:9990/ce/apis.php'
POLLING_INTERVAL_SECONDS = 2   # 轮询新结果的间隔
RETRY_INTERVAL_SECONDS = 30    # API请求失败后的重试间隔
AWARD_INTERVAL_SECONDS = 210   # 官方开奖间隔 (3.5分钟)
POLL_AHEAD_SECONDS = 10        # 提前多少秒开始轮询
BET_DELAY_SECONDS = 30         # 开奖后等待多少秒再下注，确保盘口开放

# 轻量版默认配置（首次启动或缺失字段时写入/补齐）
DEFAULT_CONFIG = {
    "web": {
        "port": 8787,
        "auth": {
            "username": "admin",
            "password": "admin123"
        }
    },
    # 账户池：[{ alias, display_name, chat_id, enabled }]
    "accounts": [],
    # 策略与旧版结构保持兼容
    "strategies": {
        "big_small": {
            "enabled": False,
            "initial_bet": 1,
            "max_win_streak": 3
        },
        "odd_even": {
            "enabled": False,
            "initial_bet": 1,
            "max_win_streak": 3
        }
    },
}


def atomic_write_json(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    tmp.replace(path)


def ensure_default_config(cfg: dict) -> dict:
    """将缺失的默认字段补齐，不覆盖已有值。"""
    # web
    cfg.setdefault("web", {})
    cfg["web"].setdefault("port", DEFAULT_CONFIG["web"]["port"])
    cfg["web"].setdefault("auth", {})
    cfg["web"]["auth"].setdefault("username", DEFAULT_CONFIG["web"]["auth"]["username"])
    cfg["web"]["auth"].setdefault("password", DEFAULT_CONFIG["web"]["auth"]["password"])
    # accounts
    cfg.setdefault("accounts", [])
    # strategies
    cfg.setdefault("strategies", {})
    for k, v in DEFAULT_CONFIG["strategies"].items():
        cfg["strategies"].setdefault(k, {})
        for sk, sv in v.items():
            cfg["strategies"][k].setdefault(sk, sv)
    # 移除旧的 chat_id 兼容字段
    if "chat_id" in cfg:
        del cfg["chat_id"]
    return cfg


def load_config() -> dict:
    """加载配置，如果不存在则创建默认配置；若缺字段则补齐。"""
    if not CONFIG_FILE.is_file():
        cfg = ensure_default_config({})
        atomic_write_json(CONFIG_FILE, cfg)
        print(f"已创建默认配置: {CONFIG_FILE}")
        return cfg

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"警告: 读取配置失败({e})，写入并使用默认配置。")
        cfg = {}
    cfg = ensure_default_config(cfg)
    # 将补齐的字段写回
    try:
        atomic_write_json(CONFIG_FILE, cfg)
    except OSError as e:
        print(f"警告: 无法写回配置文件: {e}")
    return cfg


def save_state(state: dict):
    """保存运行时 state.json"""
    try:
        atomic_write_json(STATE_FILE, state)
    except OSError as e:
        print(f"警告: 保存状态失败: {e}")


def get_latest_result():
    """从API获取最新的开奖结果。"""
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        if 'issue' in data and 'sum' in data and 'time' in data:
            return data
        else:
            print(f"警告: API返回的数据格式不正确，缺少 'issue', 'sum' 或 'time'。返回: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"错误: 请求API失败: {e}")
        return None
    except json.JSONDecodeError:
        print(f"错误: 解析API返回的JSON失败。")
        return None


def send_bet_command(alias: str, chat_id: str, message: str) -> bool:
    """
    使用 tg-signer 发送下注命令。
    - 指定账户别名 alias（-a）
    - 按注独立，逐条发送
    - 兼容负 chat_id 时添加 '--'
    """
    command = ['tg-signer']
    if alias:
        command.extend(['-a', str(alias)])
    command.append('send-text')

    if int(chat_id) < 0:
        command.append('--')

    command.extend([str(chat_id), message])

    try:
        print(f"执行命令: {' '.join(command)}")
        subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        print("命令执行成功")
        return True
    except FileNotFoundError:
        print("\n错误: 未找到 'tg-signer' 命令，请先安装并确保在 PATH 中。")
        return False
    except subprocess.CalledProcessError as e:
        print(f"\n错误: tg-signer 执行失败。code={e.returncode}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False


def load_state(config: dict) -> dict:
    """加载状态，如果文件不存在或无效，则创建新状态。"""
    if STATE_FILE.is_file():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            if 'strategies' in state:
                return state
            else:
                print(f"警告: 状态文件结构不正确，重建。")
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: 读取状态失败: {e}，将创建新状态。")

    # 构建初始策略状态（仅为启用策略创建条目）
    initial_strategies_state = {}
    for name, strategy_config in config['strategies'].items():
        if strategy_config.get('enabled'):
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


def pick_random_account(config: dict):
    """
    从配置的账户池中随机选择一个“启用且已绑定chat_id”的账户。
    返回 (alias, chat_id, display_name) 或 None
    """
    candidates = []
    for acc in config.get('accounts', []):
        if acc.get('enabled') and acc.get('chat_id'):
            candidates.append(acc)
    if not candidates:
        return None
    acc = random.choice(candidates)
    return acc.get('alias'), str(acc.get('chat_id')), acc.get('display_name')


class BotEngine:
    """
    轻量引擎：在后台线程运行，与 Web 面板交互：
    - start(): 启动线程
    - stop(): 优雅停止
    - is_running: 运行状态
    """
    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self):
        with self._lock:
            if self._running:
                print("引擎已在运行")
                return
            print("准备启动引擎...")
            self._stop_event.clear()
            self._running = True  # 在启动线程前就设置状态，防止并发
            self._thread = threading.Thread(target=self._run_wrapper, name="Canada28BotEngine", daemon=True)
            self._thread.start()
            print(f"引擎线程已启动 (ID: {self._thread.ident})")

    def stop(self):
        with self._lock:
            if not self._running:
                print("引擎未在运行")
                return
            print("正在请求引擎停止...")
            self._stop_event.set()
        # 等待线程退出
        if self._thread:
            self._thread.join(timeout=5)
        with self._lock:
            self._running = False
            self._thread = None
        print("引擎已停止")

    def _sleep_with_stop(self, seconds: float):
        """可中断睡眠，便于快速停止"""
        end = time.time() + max(0, seconds)
        while not self._stop_event.is_set() and time.time() < end:
            time.sleep(min(0.5, end - time.time()))

    def _run_wrapper(self):
        thread_id = threading.get_ident()
        print(f"引擎运行循环开始 (线程 ID: {thread_id})")
        try:
            self._run_loop()
        except Exception as e:
            print(f"引擎异常退出 (线程 ID: {thread_id}): {e}")
        finally:
            with self._lock:
                self._running = False
            print(f"引擎运行循环结束 (线程 ID: {thread_id})")

    def _run_loop(self):
        print("\n--- 机器人开始运行 (Web面板可停止) ---")

        config = load_config()
        state = load_state(config)

        # 1) 初始化：若无历史期号，则先获取一次初始结果
        if not state.get('last_period_issue'):
            print("未找到历史状态，正在获取初始开奖结果...")
            while not self._stop_event.is_set():
                initial_result = get_latest_result()
                if initial_result:
                    state['last_period_issue'] = initial_result['issue']
                    state['last_period_sum'] = initial_result['sum']
                    state['last_award_time_str'] = initial_result['time']
                    print(f"获取到初始结果: 期号={state['last_period_issue']}, 和值={state['last_period_sum']}, 时间={state['last_award_time_str']}")
                    save_state(state)
                    break
                else:
                    print(f"获取初始结果失败，{RETRY_INTERVAL_SECONDS} 秒后重试...")
                    self._sleep_with_stop(RETRY_INTERVAL_SECONDS)
            if self._stop_event.is_set():
                return
        else:
            print("成功从 state.json 加载历史状态。")

        # 主循环
        while not self._stop_event.is_set():
            print("\n" + "=" * 50)
            # 打印策略状态
            for name, strategy_state in state['strategies'].items():
                print(f"策略 [{name}]: 连胜 {strategy_state['win_streak']} 场 | 下次下注金额 {strategy_state['current_bet']}")

            # 2) 等待盘口开放
            try:
                API_TZ = timezone(timedelta(hours=8))
                last_award_time_aware = datetime.strptime(f"{datetime.now().year}-{state['last_award_time_str']}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=API_TZ)
                betting_opens_time_aware = last_award_time_aware + timedelta(seconds=BET_DELAY_SECONDS)
                now_aware = datetime.now(API_TZ)
                if now_aware < betting_opens_time_aware:
                    delay_duration = (betting_opens_time_aware - now_aware).total_seconds()
                    if delay_duration > 0:
                        print(f"上一期结果已出，等待 {delay_duration:.1f} 秒以确保盘口开放...")
                        self._sleep_with_stop(delay_duration)
                        if self._stop_event.is_set():
                            break
            except (ValueError, KeyError) as e:
                print(f"警告: 计算下注延迟时出错 ({e})。跳过延迟。")

            # 3) 基于上一期结果组装下注文本（大小/单双）
            bet_texts = []
            last_sum = state['last_period_sum']

            # 大小
            if config['strategies']['big_small']['enabled']:
                bet_type = "大" if (last_sum is not None and last_sum >= 14) else "小"
                bet_amount = state['strategies']['big_small']['current_bet']
                bet_texts.append(f"{bet_type}{bet_amount}")

            # 单双
            if config['strategies']['odd_even']['enabled']:
                if last_sum is None:
                    # 没有可参考和值，默认下“单1”
                    bet_type = "单"
                else:
                    bet_type = "双" if (last_sum % 2 == 0) else "单"
                bet_amount = state['strategies']['odd_even']['current_bet']
                bet_texts.append(f"{bet_type}{bet_amount}")

            if not bet_texts:
                print("没有启用的下注策略。请在 Web 面板中启用策略后再启动。")
                break

            # 4) 按注独立随机账号逐条发送（每条下注文本独立随机选择一个账号）
            for txt in bet_texts:
                # 优先从账户池随机
                picked = pick_random_account(config)
                if picked:
                    alias, chat_id, display_name = picked
                    print(f"将使用账户[{display_name or alias}] 发送下注: {txt} -> chat_id={chat_id}")
                    ok = send_bet_command(alias=alias, chat_id=chat_id, message=txt)
                else:
                    print("错误: 账户池为空或所有可用账户均未绑定 chat_id，跳过本注。")
                    ok = False

                if not ok:
                    print(f"下注发送失败: {txt}。")
                    # 失败后不再自动重试，等待下一轮


                if self._stop_event.is_set():
                    break

            if self._stop_event.is_set():
                break

            # 5) 等待下一期开奖的时间点
            try:
                API_TZ = timezone(timedelta(hours=8))
                aware_last_award_time = datetime.strptime(f"{datetime.now().year}-{state['last_award_time_str']}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=API_TZ)
                aware_next_award_time = aware_last_award_time + timedelta(seconds=AWARD_INTERVAL_SECONDS)
                now_utc = datetime.now(timezone.utc)
                next_award_time_utc = aware_next_award_time.astimezone(timezone.utc)
                sleep_until_utc = next_award_time_utc - timedelta(seconds=POLL_AHEAD_SECONDS)
                if now_utc < sleep_until_utc:
                    sleep_duration = (sleep_until_utc - now_utc).total_seconds()
                    display_next_award = next_award_time_utc.astimezone(API_TZ)
                    display_sleep_until = sleep_until_utc.astimezone(API_TZ)
                    print(f"下注阶段结束。预计下期开奖 (UTC+8): {display_next_award.strftime('%H:%M:%S')}")
                    print(f"将休眠 {sleep_duration:.1f} 秒，到 {display_sleep_until.strftime('%H:%M:%S')} (UTC+8) 再开始轮询开奖结果...")
                    self._sleep_with_stop(sleep_duration)
                else:
                    print("警告: 计算出的下次轮询时间已过或过近，立即开始轮询。")
            except ValueError:
                print(f"警告: 无法解析时间 '{state['last_award_time_str']}'。回退到固定时间等待。")
                self._sleep_with_stop(max(0, AWARD_INTERVAL_SECONDS - POLL_AHEAD_SECONDS if AWARD_INTERVAL_SECONDS > POLL_AHEAD_SECONDS else 60))

            if self._stop_event.is_set():
                break

            # 6) 轮询直到获取到新一期
            print("开始轮询新一期结果...")
            new_result = None
            while not self._stop_event.is_set():
                result = get_latest_result()
                if result and result['issue'] != state['last_period_issue']:
                    new_result = result
                    print(f"新一期结果: 期号={new_result['issue']}, 和值={new_result['sum']}, 时间={new_result.get('time')}")
                    break
                else:
                    current_issue = state['last_period_issue'] if not result else result['issue']
                    print(f"结果未更新 (当前期号 {current_issue})，{POLLING_INTERVAL_SECONDS} 秒后再次查询...")
                    self._sleep_with_stop(POLLING_INTERVAL_SECONDS)

            if self._stop_event.is_set():
                break

            # 7) 判定输赢并更新策略状态
            new_sum = new_result['sum']

            # 大小
            if config['strategies']['big_small']['enabled']:
                strategy_state = state['strategies'].setdefault('big_small', {
                    'current_bet': config['strategies']['big_small']['initial_bet'],
                    'win_streak': 0
                })
                last_bet_was_big = ("大" if (last_sum is not None and last_sum >= 14) else "小") == "大"
                new_result_was_big = new_sum >= 14
                if last_bet_was_big == new_result_was_big:
                    print("策略 [大小]: 胜利")
                    strategy_state['win_streak'] += 1
                    if strategy_state['win_streak'] >= config['strategies']['big_small']['max_win_streak']:
                        strategy_state['win_streak'] = 0
                        strategy_state['current_bet'] = config['strategies']['big_small']['initial_bet']
                    else:
                        strategy_state['current_bet'] *= 2
                else:
                    print("策略 [大小]: 失败")
                    strategy_state['win_streak'] = 0
                    strategy_state['current_bet'] = config['strategies']['big_small']['initial_bet']

            # 单双
            if config['strategies']['odd_even']['enabled']:
                strategy_state = state['strategies'].setdefault('odd_even', {
                    'current_bet': config['strategies']['odd_even']['initial_bet'],
                    'win_streak': 0
                })
                last_bet_was_even = ("双" if (last_sum is not None and last_sum % 2 == 0) else "单") == "双"
                new_result_was_even = new_sum % 2 == 0
                if last_bet_was_even == new_result_was_even:
                    print("策略 [单双]: 胜利")
                    strategy_state['win_streak'] += 1
                    if strategy_state['win_streak'] >= config['strategies']['odd_even']['max_win_streak']:
                        strategy_state['win_streak'] = 0
                        strategy_state['current_bet'] = config['strategies']['odd_even']['initial_bet']
                    else:
                        strategy_state['current_bet'] *= 2
                else:
                    print("策略 [单双]: 失败")
                    strategy_state['win_streak'] = 0
                    strategy_state['current_bet'] = config['strategies']['odd_even']['initial_bet']

            # 8) 更新期号与时间
            state['last_period_issue'] = new_result['issue']
            state['last_period_sum'] = new_result['sum']
            state['last_award_time_str'] = new_result.get('time', state['last_award_time_str'])
            save_state(state)


# 提供一个全局引擎单例，便于 Web 面板复用
ENGINE = BotEngine()


def main():
    """
    兼容 CLI 运行（不经 Web 面板）。为了简化：
    - 不再交互式配置（initial_setup 移除），缺配置则生成默认配置。
    - 直接前台运行引擎（Ctrl+C 退出）。
    """
    cfg = load_config()
    print("\n配置加载成功:")
    for name, strategy_config in cfg['strategies'].items():
        status = "已启用" if strategy_config.get('enabled') else "已禁用"
        print(f"  - [{name}] {status}: 初始金额={strategy_config['initial_bet']}, 最大连胜={strategy_config['max_win_streak']}")
    if cfg.get("accounts"):
        print(f"  - 账户池数量: {len(cfg['accounts'])}")

    try:
        ENGINE.start()
        while ENGINE.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n检测到 Ctrl+C，正在停止...")
    finally:
        ENGINE.stop()
        print("程序已退出。")


if __name__ == '__main__':
    main()
