import json
import os
import base64
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Depends, HTTPException, status, Path as FPath, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# 复用机器人核心与配置/路径
from canada28_bot import (
    ENGINE,
    load_config,
    atomic_write_json,
    ensure_default_config,
    CONFIG_FILE,
    STATE_FILE,
    SIGNER_DIR,
    AWARD_INTERVAL_SECONDS,
)

app = FastAPI(title="Canada28 控制面板", version="0.4.0")
security = HTTPBasic()


def get_current_config() -> Dict[str, Any]:
    return load_config()


def verify_basic_auth(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    cfg = get_current_config()
    auth = cfg.get("web", {}).get("auth", {})
    username = auth.get("username")
    password = auth.get("password")
    if not (credentials.username == username and credentials.password == password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


def mask_auth(cfg: Dict[str, Any]) -> Dict[str, Any]:
    result = json.loads(json.dumps(cfg))
    try:
        if "web" in result and "auth" in result["web"] and "password" in result["web"]["auth"]:
            result["web"]["auth"]["password"] = "********"
    except Exception:
        pass
    return result


def write_config(cfg: Dict[str, Any]) -> None:
    cfg = ensure_default_config(cfg or {})
    atomic_write_json(Path(CONFIG_FILE), cfg)


def read_state_summary() -> Dict[str, Any]:
    p = Path(STATE_FILE)
    summary = {"exists": False, "strategies": {}, "last_period_issue": None, "last_period_sum": None, "last_award_time_str": None, "next_award_time_str": None, "seconds_to_next_award": -1}
    if not p.is_file():
        return summary
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        summary.update({
            "exists": True,
            "strategies": data.get("strategies", {}),
            "last_period_issue": data.get("last_period_issue"),
            "last_period_sum": data.get("last_period_sum"),
            "last_award_time_str": data.get("last_award_time_str"),
        })
        # 计算下次开奖时间
        if summary["last_award_time_str"]:
            API_TZ = timezone(timedelta(hours=8))
            last_award_time = datetime.strptime(f"{datetime.now().year}-{summary['last_award_time_str']}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=API_TZ)
            next_award_time = last_award_time + timedelta(seconds=AWARD_INTERVAL_SECONDS)
            summary["next_award_time_str"] = next_award_time.strftime('%H:%M:%S')
            summary["seconds_to_next_award"] = max(0, (next_award_time - datetime.now(API_TZ)).total_seconds())
        return summary
    except Exception as e:
        summary["error"] = str(e)
        return summary


def list_signer_users() -> List[Dict[str, Any]]:
    users_dir = Path(SIGNER_DIR) / "users"
    result: List[Dict[str, Any]] = []
    if not users_dir.is_dir():
        return result
    for d in users_dir.iterdir():
        if not d.is_dir():
            continue
        me = d / "me.json"
        item: Dict[str, Any] = {"user_id": d.name, "display_name": d.name, "username": None, "first_name": None, "last_name": None}
        try:
            if me.is_file():
                j = json.loads(me.read_text(encoding="utf-8"))
                first_name = j.get("first_name") or ""
                last_name = j.get("last_name") or ""
                username = j.get("username") or ""
                display = (f"{first_name} {last_name}").strip() or username or d.name
                item.update({
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "display_name": display
                })
        except Exception:
            pass
        result.append(item)
    return result


def format_chats(chats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    norm = []
    for c in chats or []:
        title = c.get("title")
        if not title:
            fn = c.get("first_name", "") or ""
            ln = c.get("last_name", "") or ""
            title = (f"{fn} {ln}").strip() or f"未知对话(ID:{c.get('id')})"
        norm.append({
            "id": c.get("id"),
            "title": title
        })
    return norm


@app.get("/", response_class=HTMLResponse)
def dashboard(_: None = Depends(verify_basic_auth)):
    html = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Canada28 控制面板</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    body { font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif; padding: 16px; }
    h1 { margin-bottom: 8px; }
    .card { border:1px solid #ddd; border-radius:8px; padding:12px; margin:12px 0; }
    .row { display:flex; gap:12px; flex-wrap:wrap; }
    .col { flex: 1 1 320px; }
    table { width:100%; border-collapse: collapse; }
    th, td { border:1px solid #eee; padding:8px; text-align:left; }
    th { background:#fafafa; }
    button { padding:6px 12px; cursor:pointer; }
    input[type="text"], input[type="number"] { width: 100%; box-sizing: border-box; padding:6px; }
    .badge { display:inline-block; padding:2px 8px; border-radius:12px; font-size:12px; margin-left:8px; }
    .on { background:#e6ffed; color:#1a7f37; border:1px solid #b7eb8f; }
    .off { background:#fff1f0; color:#a8071a; border:1px solid #ffa39e; }
    .overlay { position: fixed; inset:0; background: rgba(0,0,0,.4); display:none; align-items:center; justify-content:center; }
    .modal { background:#fff; border-radius:8px; padding:12px; max-width: 720px; width: 90%; max-height: 80vh; overflow:auto; }
    .muted { color:#666; font-size: 12px; }
    .state-grid { display:grid; grid-template-columns: auto 1fr; gap: 4px 12px; }
  </style>
</head>
<body>
  <h1>Canada28 控制面板 <span id="engine-badge" class="badge off">停止</span></h1>
  <div class="row">
    <div class="col card">
      <h3>运行控制</h3>
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        <button id="btn-start">启动机器人</button>
        <button id="btn-stop">停止机器人</button>
        <button id="btn-save-config">保存配置</button>
        <button id="btn-clear-state">清空缓存</button>
        <button id="btn-refresh">刷新状态</button>
      </div>
      <div style="margin-top:12px;" class="state-grid" id="state-summary">
        <div>状态:</div><div class="muted">加载中...</div>
      </div>
    </div>

    <div class="col card">
      <h3>策略设置</h3>
      <div>
        <label><input type="checkbox" id="bs-enabled"> 启用[大小]</label>
        <div class="row">
          <div class="col">
            <label>大小-初始金额</label>
            <input type="number" id="bs-initial" min="1" step="1" />
          </div>
          <div class="col">
            <label>大小-最大连胜</label>
            <input type="number" id="bs-max" min="1" step="1" />
          </div>
        </div>
      </div>
      <hr />
      <div>
        <label><input type="checkbox" id="oe-enabled"> 启用[单双]</label>
        <div class="row">
          <div class="col">
            <label>单双-初始金额</label>
            <input type="number" id="oe-initial" min="1" step="1" />
          </div>
          <div class="col">
            <label>单双-最大连胜</label>
            <input type="number" id="oe-max" min="1" step="1" />
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>账户池</h3>
    <div style="margin-bottom:8px;">
      <button id="btn-add-account">新增账户</button>
      <button id="btn-import-signers">从本机已登录账户导入</button>
    </div>
    <table id="acct-table">
      <thead>
        <tr>
          <th>启用</th>
          <th>别名(alias)</th>
          <th>显示名(昵称)</th>
          <th>User ID</th>
          <th>chat_id</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
    <div class="muted" style="margin-top:8px;">
      说明：请先通过命令登录：tg-signer -a <别名> login。然后在此为该别名绑定 chat_id。
    </div>
  </div>

  <div class="overlay" id="overlay">
    <div class="modal">
      <h3>选择聊天</h3>
      <div class="muted" id="modal-subtitle">正在加载...</div>
      <table id="modal-chats" style="margin-top:8px;">
        <thead>
          <tr><th>标题</th><th>chat_id</th><th>选择</th></tr>
        </thead>
        <tbody></tbody>
      </table>
      <div style="margin-top:8px; text-align:right;">
        <button onclick="hideOverlay()">关闭</button>
      </div>
    </div>
  </div>

<script>
let cfg = null;
let stateSummary = null;
let countdownTimer = null;

async function api(path, opts) {
  const res = await fetch(path, opts || {});
  if (res.status === 401) {
    alert("认证失败或需要登录，请刷新页面并输入账号/密码");
    throw new Error("401");
  }
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || ("HTTP " + res.status));
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res.text();
}

function setEngineBadge(running) {
  const el = document.getElementById("engine-badge");
  if (running) {
    el.classList.add("on"); el.classList.remove("off");
    el.textContent = "运行中";
  } else {
    el.classList.add("off"); el.classList.remove("on");
    el.textContent = "停止";
  }
}

function renderConfig() {
  if (!cfg) return;
  const bs = cfg.strategies.big_small;
  const oe = cfg.strategies.odd_even;

  document.getElementById("bs-enabled").checked = !!bs.enabled;
  document.getElementById("bs-initial").value = bs.initial_bet;
  document.getElementById("bs-max").value = bs.max_win_streak;

  document.getElementById("oe-enabled").checked = !!oe.enabled;
  document.getElementById("oe-initial").value = oe.initial_bet;
  document.getElementById("oe-max").value = oe.max_win_streak;

  renderAccounts();
}

function renderAccounts() {
  const tbody = document.querySelector("#acct-table tbody");
  tbody.innerHTML = "";
  (cfg.accounts || []).forEach((acc, idx) => {
    const tr = document.createElement("tr");
    tr.dataset.idx = idx;
    tr.dataset.userId = acc.user_id || "";

    const td0 = document.createElement("td");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !!acc.enabled;
    cb.onchange = () => { acc.enabled = cb.checked; };
    td0.appendChild(cb);

    const td1 = document.createElement("td");
    const in1 = document.createElement("input");
    in1.type = "text"; in1.value = acc.alias || ""; in1.className = "alias-input";
    in1.onchange = () => acc.alias = in1.value.trim();
    td1.appendChild(in1);

    const td2 = document.createElement("td");
    const in2 = document.createElement("input");
    in2.type = "text"; in2.value = acc.display_name || "";
    in2.onchange = () => acc.display_name = in2.value.trim();
    td2.appendChild(in2);

    const td3 = document.createElement("td");
    const in3 = document.createElement("input");
    in3.type = "text"; in3.value = acc.user_id || ""; in3.readOnly = true; in3.style.background = "#f5f5f5";
    td3.appendChild(in3);

    const td4 = document.createElement("td");
    const in4 = document.createElement("input");
    in4.type = "text"; in4.value = acc.chat_id !== undefined && acc.chat_id !== null ? acc.chat_id : "";
    in4.onchange = () => acc.chat_id = in4.value.trim();
    td4.appendChild(in4);

    const td5 = document.createElement("td");
    const btnChat = document.createElement("button");
    btnChat.textContent = "选择聊天";
    btnChat.onclick = () => openChatPicker(idx);
    const btnDel = document.createElement("button");
    btnDel.style.marginLeft = "8px"; btnDel.textContent = "删除";
    btnDel.onclick = () => { cfg.accounts.splice(idx, 1); renderAccounts(); };
    td5.appendChild(btnChat);
    td5.appendChild(btnDel);

    tr.appendChild(td0); tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3); tr.appendChild(td4); tr.appendChild(td5);
    tbody.appendChild(tr);
  });
}

function startCountdown(seconds) {
    if (countdownTimer) clearInterval(countdownTimer);
    let remaining = Math.round(seconds);
    const el = document.getElementById("countdown");
    if (!el) return;
    
    const update = () => {
        if (remaining > 0) {
            el.textContent = `(${remaining} 秒后)`;
            remaining--;
        } else {
            el.textContent = "(已开奖)";
            clearInterval(countdownTimer);
        }
    };
    update();
    countdownTimer = setInterval(update, 1000);
}

function renderState() {
    const el = document.getElementById("state-summary");
    if (!stateSummary) {
        el.innerHTML = '<div>状态:</div><div class="muted">加载失败</div>';
        return;
    }
    let html = `
        <div>上期期号:</div><div>${stateSummary.last_period_issue || '-'}</div>
        <div>上期和值:</div><div>${stateSummary.last_period_sum || '-'}</div>
        <div>开奖时间:</div><div>${stateSummary.last_award_time_str || '-'}</div>
        <div>预计下期开奖:</div><div>${stateSummary.next_award_time_str || '-'} <span id="countdown"></span></div>
    `;
    el.innerHTML = html;
    if (stateSummary.seconds_to_next_award > 0) {
        startCountdown(stateSummary.seconds_to_next_award);
    }
}

async function refreshAll() {
  try {
    cfg = await api("/api/config");
    stateSummary = await api("/api/state");
    setEngineBadge(!!stateSummary.running);
    renderState();
    renderConfig();
  } catch (e) {
    console.error(e);
    alert("加载失败: " + e.message);
  }
}

async function startBot() {
  const btn = document.getElementById("btn-start");
  btn.disabled = true;
  btn.textContent = "启动中...";
  try {
    await api("/api/bot/start", {method:"POST"});
    await refreshAll();
  } catch (e) {
    alert("启动失败: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "启动机器人";
  }
}
async function stopBot() {
  const btn = document.getElementById("btn-stop");
  btn.disabled = true;
  btn.textContent = "停止中...";
  try {
    await api("/api/bot/stop", {method:"POST"});
    await refreshAll();
  } catch (e) {
    alert("停止失败: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "停止机器人";
  }
}

async function clearState() {
    if (!confirm("确定要清空所有运行缓存吗？这将重置连胜记录和期号信息。")) return;
    try {
        await api("/api/clear_state", {method:"POST"});
        alert("缓存已清空");
        await refreshAll();
    } catch (e) {
        alert("操作失败: " + e.message);
    }
}

function collectConfigFromUI() {
  const bsEnabled = document.getElementById("bs-enabled").checked;
  const bsInitial = parseInt(document.getElementById("bs-initial").value || "1");
  const bsMax = parseInt(document.getElementById("bs-max").value || "3");

  const oeEnabled = document.getElementById("oe-enabled").checked;
  const oeInitial = parseInt(document.getElementById("oe-initial").value || "1");
  const oeMax = parseInt(document.getElementById("oe-max").value || "3");

  const accountsSan = (cfg.accounts || []).map(a => ({
    enabled: !!a.enabled,
    alias: (a.alias || "").trim(),
    display_name: (a.display_name || "").trim(),
    user_id: (a.user_id || "").trim(),
    chat_id: (a.chat_id === null || a.chat_id === undefined) ? "" : ("" + a.chat_id).trim()
  }));

  return {
    strategies: {
      big_small: { enabled: bsEnabled, initial_bet: bsInitial, max_win_streak: bsMax },
      odd_even: { enabled: oeEnabled, initial_bet: oeInitial, max_win_streak: oeMax }
    },
    accounts: accountsSan,
  };
}

async function saveConfig() {
  try {
    const payload = collectConfigFromUI();
    await api("/api/config", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    });
    alert("保存成功");
    await refreshAll();
  } catch (e) {
    alert("保存失败: " + e.message);
  }
}

function addAccountRow(acc) {
  cfg.accounts = cfg.accounts || [];
  cfg.accounts.push({
    enabled: acc.enabled ?? true,
    alias: acc.alias ?? "",
    display_name: acc.display_name ?? "",
    user_id: acc.user_id ?? "",
    chat_id: acc.chat_id ?? ""
  });
  renderAccounts();
}

async function importSigners() {
  try {
    const arr = await api("/api/signers");
    if (!arr || !Array.isArray(arr) || arr.length === 0) {
      alert("未发现本机 tg-signer 登录账户目录");
      return;
    }
    arr.forEach(u => addAccountRow({
        enabled:true,
        alias:"",
        display_name: u.display_name || u.user_id,
        user_id: u.user_id,
        chat_id:""
    }));
    alert("已导入账户，请为每行填写别名(alias)并绑定 chat_id");
  } catch (e) {
    alert("导入失败: " + e.message);
  }
}

async function openChatPicker(idx) {
  const row = document.querySelector(`#acct-table tr[data-idx='${idx}']`);
  const aliasInput = row.querySelector('.alias-input');
  const alias = aliasInput.value.trim();
  const userId = row.dataset.userId;

  if (!alias) {
    alert("请先为该行填写别名(alias)");
    aliasInput.focus();
    return;
  }
  if (!userId) {
    alert("该行缺少 User ID，请尝试重新导入账户。");
    return;
  }

  const modalSubtitle = document.getElementById("modal-subtitle");
  const tbody = document.querySelector("#modal-chats tbody");
  tbody.innerHTML = "";
  modalSubtitle.textContent = `正在为别名 [${alias}] 获取最近对话...`;
  showOverlay();

  try {
    const chats = await api(`/api/refresh_chats`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ alias: alias, user_id: userId })
    });

    if (!chats || chats.length === 0) {
      modalSubtitle.textContent = `别名 [${alias}] 未获取到最近对话。请确认该账户已登录并与机器人有过对话。`;
      return;
    }
    modalSubtitle.textContent = `请为别名 [${alias}] 选择一个对话：`;
    chats.forEach(c => {
      const tr = document.createElement("tr");
      const tdTitle = document.createElement("td"); tdTitle.textContent = c.title;
      const tdId = document.createElement("td"); tdId.textContent = c.id;
      const tdBtn = document.createElement("td");
      const btn = document.createElement("button");
      btn.textContent = "选择";
      btn.onclick = () => {
        cfg.accounts[idx].chat_id = c.id;
        renderAccounts();
        hideOverlay();
      };
      tdBtn.appendChild(btn);
      tr.appendChild(tdTitle); tr.appendChild(tdId); tr.appendChild(tdBtn);
      tbody.appendChild(tr);
    });
  } catch (e) {
    modalSubtitle.textContent = `获取对话失败: ${e.message}`;
  }
}

function showOverlay() { document.getElementById("overlay").style.display = "flex"; }
function hideOverlay() { document.getElementById("overlay").style.display = "none"; }

document.getElementById("btn-refresh").onclick = refreshAll;
document.getElementById("btn-start").onclick = startBot;
document.getElementById("btn-stop").onclick = stopBot;
document.getElementById("btn-save-config").onclick = saveConfig;
document.getElementById("btn-clear-state").onclick = clearState;
document.getElementById("btn-add-account").onclick = () => addAccountRow({enabled:true, alias:"", display_name:"", user_id:"", chat_id:""});
document.getElementById("btn-import-signers").onclick = importSigners;

refreshAll();
</script>
</body>
</html>
    """
    return HTMLResponse(html)


@app.get("/api/config")
def api_get_config(_: None = Depends(verify_basic_auth)):
    cfg = get_current_config()
    return JSONResponse(mask_auth(cfg))


@app.put("/api/config")
def api_put_config(
    _: None = Depends(verify_basic_auth),
    body: Dict[str, Any] = Body(...)
):
    cfg = get_current_config()
    strategies = body.get("strategies")
    accounts = body.get("accounts")

    if strategies is not None:
        cfg["strategies"] = {**cfg.get("strategies", {}), **strategies}

    if accounts is not None:
        if not isinstance(accounts, list):
            raise HTTPException(400, "accounts 必须为数组")
        cleaned = []
        for a in accounts:
            if not isinstance(a, dict): continue
            cleaned.append({
                "enabled": bool(a.get("enabled", True)),
                "alias": str(a.get("alias", "")).strip(),
                "display_name": str(a.get("display_name", "")).strip(),
                "user_id": str(a.get("user_id", "")).strip(),
                "chat_id": str(a.get("chat_id", "")).strip() if a.get("chat_id") not in (None, "") else None
            })
        cfg["accounts"] = cleaned

    write_config(cfg)
    return {"ok": True}


@app.get("/api/state")
def api_state(_: None = Depends(verify_basic_auth)):
    s = read_state_summary()
    return {
        "running": ENGINE.is_running,
        **s
    }


@app.post("/api/bot/start")
def api_start(_: None = Depends(verify_basic_auth)):
    if ENGINE.is_running:
        return {"ok": True, "message": "已在运行"}
    ENGINE.start()
    return {"ok": True}


@app.post("/api/bot/stop")
def api_stop(_: None = Depends(verify_basic_auth)):
    if not ENGINE.is_running:
        return {"ok": True, "message": "已停止"}
    ENGINE.stop()
    return {"ok": True}


@app.post("/api/clear_state")
def api_clear_state(_: None = Depends(verify_basic_auth)):
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        return {"ok": True, "message": "状态缓存已清空"}
    except OSError as e:
        raise HTTPException(500, f"清空缓存失败: {e}")


@app.get("/api/signers")
def api_signers(_: None = Depends(verify_basic_auth)):
    return list_signer_users()


@app.post("/api/refresh_chats")
def api_refresh_chats(
    body: Dict[str, str] = Body(...),
    _: None = Depends(verify_basic_auth)
):
    alias = body.get("alias")
    user_id = body.get("user_id")
    if not alias or not user_id:
        raise HTTPException(400, "需要提供 alias 和 user_id")

    command = ['tg-signer', '-a', alias, 'login', '-n', '20']
    try:
        print(f"执行命令: {' '.join(command)}")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8',
            input='\n',
            timeout=30
        )
        print(f"命令输出: {result.stdout}")
    except FileNotFoundError:
        raise HTTPException(500, "'tg-signer' 命令未找到。")
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "执行 tg-signer login 超时，请检查网络或手动执行。")
    except subprocess.CalledProcessError as e:
        print(f"错误: 执行 tg-signer login 失败。")
        print(f"返回码: {e.returncode}")
        print(f"输出: {e.stdout}")
        print(f"错误输出: {e.stderr}")
        pass

    time.sleep(1)

    chats_file = Path(SIGNER_DIR) / "users" / user_id / 'latest_chats.json'
    if not chats_file.is_file():
        raise HTTPException(404, f"未找到 latest_chats.json (路径: {chats_file})。请确认命令执行成功且账户已登录。")

    try:
        chats_data = json.loads(chats_file.read_text(encoding='utf-8'))
        return format_chats(chats_data)
    except Exception as e:
        raise HTTPException(500, f"读取或解析 latest_chats.json 失败: {str(e)}")
