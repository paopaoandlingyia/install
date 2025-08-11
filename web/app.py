import json
import base64
from pathlib import Path
from typing import Optional, Dict, Any, List

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
)

app = FastAPI(title="Canada28 控制面板", version="0.1.0")
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
    # 返回给前端时不回传明文密码
    result = json.loads(json.dumps(cfg))  # 深拷贝
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
    if not p.is_file():
        return {"exists": False, "strategies": {}, "last_period_issue": None, "last_period_sum": None, "last_award_time_str": None}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {
            "exists": True,
            "strategies": data.get("strategies", {}),
            "last_period_issue": data.get("last_period_issue"),
            "last_period_sum": data.get("last_period_sum"),
            "last_award_time_str": data.get("last_award_time_str"),
        }
    except Exception as e:
        return {"exists": False, "error": str(e)}


def list_signer_users() -> List[Dict[str, Any]]:
    users_dir = Path(SIGNER_DIR) / "users"
    result: List[Dict[str, Any]] = []
    if not users_dir.is_dir():
        return result
    for d in users_dir.iterdir():
        if not d.is_dir():
            continue
        me = d / "me.json"
        item: Dict[str, Any] = {"user_dir": d.name, "display_name": None, "username": None, "first_name": None, "last_name": None}
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


def read_latest_chats_for_user(user_dir: str) -> List[Dict[str, Any]]:
    users_dir = Path(SIGNER_DIR) / "users"
    chats_path = users_dir / user_dir / "latest_chats.json"
    if not chats_path.is_file():
        return []
    try:
        chats = json.loads(chats_path.read_text(encoding="utf-8"))
        # 统一裁剪字段
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
    except Exception:
        return []


@app.get("/", response_class=HTMLResponse)
def dashboard(_: None = Depends(verify_basic_auth)):
    # 简易内嵌前端（轻量）
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
  </style>
</head>
<body>
  <h1>Canada28 控制面板 <span id="engine-badge" class="badge off">停止</span></h1>
  <div class="row">
    <div class="col card">
      <h3>运行控制</h3>
      <div>
        <button id="btn-start">启动机器人</button>
        <button id="btn-stop">停止机器人</button>
        <button id="btn-refresh">刷新状态</button>
      </div>
      <div style="margin-top:8px;">
        <div id="state-summary" class="muted">状态加载中...</div>
      </div>
      <div class="muted" style="margin-top:8px;">
        提示：修改配置后建议先“停止”，保存配置，再“启动”使其生效。
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
      <div style="margin-top:12px;">
        <button id="btn-save-config">保存配置</button>
      </div>
      <div class="muted" style="margin-top:8px;">
        兼容模式全局 chat_id (可留空)：<input type="text" id="legacy-chat" style="width:160px;" />
      </div>
    </div>
  </div>

  <div class="card">
    <h3>账户池</h3>
    <div style="margin-bottom:8px;">
      <button id="btn-add-account">新增账户</button>
      <button id="btn-import-signers">从本机已登录账户导入(昵称)</button>
    </div>
    <table id="acct-table">
      <thead>
        <tr>
          <th>启用</th>
          <th>别名(alias，用于 tg-signer -a)</th>
          <th>显示名(昵称)</th>
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

  <div class="card">
    <h3>最近对话辅助</h3>
    <div>
      <button id="btn-load-all-chats">扫描所有账户的最近对话</button>
    </div>
    <table id="chats-table" style="margin-top:8px;">
      <thead>
        <tr>
          <th>用户目录</th>
          <th>标题</th>
          <th>chat_id</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
    <div class="muted">提示：可点击上表某一行快速将 chat_id 复制到剪贴板，再粘贴到上方“账户池”对应行。</div>
  </div>

  <div class="overlay" id="overlay">
    <div class="modal">
      <h3>选择聊天</h3>
      <div class="muted">从所有账户的最近对话中选择。</div>
      <table id="modal-chats" style="margin-top:8px;">
        <thead>
          <tr><th>用户目录</th><th>标题</th><th>chat_id</th><th>选择</th></tr>
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

  document.getElementById("legacy-chat").value = cfg.chat_id || "";
  renderAccounts();
}

function renderAccounts() {
  const tbody = document.querySelector("#acct-table tbody");
  tbody.innerHTML = "";
  (cfg.accounts || []).forEach((acc, idx) => {
    const tr = document.createElement("tr");

    // enabled
    const td0 = document.createElement("td");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!acc.enabled;
    cb.onchange = () => { acc.enabled = cb.checked; };
    td0.appendChild(cb);

    // alias
    const td1 = document.createElement("td");
    const in1 = document.createElement("input");
    in1.type = "text"; in1.value = acc.alias || "";
    in1.onchange = () => acc.alias = in1.value.trim();
    td1.appendChild(in1);

    // display name
    const td2 = document.createElement("td");
    const in2 = document.createElement("input");
    in2.type = "text"; in2.value = acc.display_name || "";
    in2.onchange = () => acc.display_name = in2.value.trim();
    td2.appendChild(in2);

    // chat_id
    const td3 = document.createElement("td");
    const in3 = document.createElement("input");
    in3.type = "text"; in3.value = acc.chat_id !== undefined && acc.chat_id !== null ? acc.chat_id : "";
    in3.onchange = () => acc.chat_id = in3.value.trim();
    td3.appendChild(in3);

    // ops
    const td4 = document.createElement("td");
    const btnChat = document.createElement("button");
    btnChat.textContent = "选择聊天";
    btnChat.onclick = () => openChatPicker(idx);
    const btnDel = document.createElement("button");
    btnDel.style.marginLeft = "8px";
    btnDel.textContent = "删除";
    btnDel.onclick = () => { cfg.accounts.splice(idx, 1); renderAccounts(); };
    td4.appendChild(btnChat);
    td4.appendChild(btnDel);

    tr.appendChild(td0); tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3); tr.appendChild(td4);
    tbody.appendChild(tr);
  });
}

async function refreshAll() {
  try {
    cfg = await api("/api/config");
    stateSummary = await api("/api/state");
    setEngineBadge(!!stateSummary.running);
    document.getElementById("state-summary").textContent =
      `期号: ${stateSummary.last_period_issue || '-'} | 和值: ${stateSummary.last_period_sum || '-'} | 开奖时间: ${stateSummary.last_award_time_str || '-'}`;
    renderConfig();
  } catch (e) {
    console.error(e);
    alert("加载失败: " + e.message);
  }
}

async function startBot() {
  try {
    await api("/api/bot/start", {method:"POST"});
    await refreshAll();
  } catch (e) { alert("启动失败: " + e.message); }
}
async function stopBot() {
  try {
    await api("/api/bot/stop", {method:"POST"});
    await refreshAll();
  } catch (e) { alert("停止失败: " + e.message); }
}

function collectConfigFromUI() {
  const bsEnabled = document.getElementById("bs-enabled").checked;
  const bsInitial = parseInt(document.getElementById("bs-initial").value || "1");
  const bsMax = parseInt(document.getElementById("bs-max").value || "3");

  const oeEnabled = document.getElementById("oe-enabled").checked;
  const oeInitial = parseInt(document.getElementById("oe-initial").value || "1");
  const oeMax = parseInt(document.getElementById("oe-max").value || "3");

  const legacyChat = document.getElementById("legacy-chat").value.trim();
  const accountsSan = (cfg.accounts || []).map(a => ({
    enabled: !!a.enabled,
    alias: (a.alias || "").trim(),
    display_name: (a.display_name || "").trim(),
    chat_id: (a.chat_id === null || a.chat_id === undefined) ? "" : ("" + a.chat_id).trim()
  }));

  return {
    strategies: {
      big_small: { enabled: bsEnabled, initial_bet: bsInitial, max_win_streak: bsMax },
      odd_even: { enabled: oeEnabled, initial_bet: oeInitial, max_win_streak: oeMax }
    },
    accounts: accountsSan,
    chat_id: legacyChat || null
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
    // 将 signer 的 display_name 预填到 display_name 字段，alias 留空待用户手动填写
    arr.forEach(u => addAccountRow({enabled:true, alias:"", display_name: u.display_name || u.user_dir, chat_id:""}));
    alert("已导入昵称到账户池，请为每行填写别名(alias)并绑定 chat_id");
  } catch (e) {
    alert("导入失败: " + e.message);
  }
}

async function loadAllChats(toModalTableId) {
  const tbody = document.querySelector(toModalTableId + " tbody");
  tbody.innerHTML = "";
  try {
    const signers = await api("/api/signers");
    for (const s of signers) {
      const chats = await api(`/api/signers/${encodeURIComponent(s.user_dir)}/latest_chats`);
      (chats || []).forEach(c => {
        const tr = document.createElement("tr");
        const tdA = document.createElement("td"); tdA.textContent = s.user_dir;
        const tdB = document.createElement("td"); tdB.textContent = c.title;
        const tdC = document.createElement("td"); tdC.textContent = c.id;
        tr.appendChild(tdA); tr.appendChild(tdB); tr.appendChild(tdC);
        tbody.appendChild(tr);
      });
    }
  } catch (e) {
    alert("扫描失败: " + e.message);
  }
}

async function openChatPicker(idx) {
  const tbody = document.querySelector("#modal-chats tbody");
  tbody.innerHTML = "";
  await loadAllChats("#modal-chats");
  // 每行加选择按钮
  Array.from(tbody.children).forEach(tr => {
    const td = document.createElement("td");
    const btn = document.createElement("button");
    btn.textContent = "选择";
    btn.onclick = () => {
      const chatId = tr.children[2].textContent.trim();
      cfg.accounts[idx].chat_id = chatId;
      renderAccounts();
      hideOverlay();
    };
    td.appendChild(btn);
    tr.appendChild(td);
  });
  showOverlay();
}

function showOverlay() { document.getElementById("overlay").style.display = "flex"; }
function hideOverlay() { document.getElementById("overlay").style.display = "none"; }

async function loadChatsToTable() {
  const tbody = document.querySelector("#chats-table tbody");
  tbody.innerHTML = "";
  await loadAllChats("#chats-table");
  // 点击复制 chat_id
  Array.from(tbody.children).forEach(tr => {
    tr.style.cursor = "pointer";
    tr.onclick = () => {
      const id = tr.children[2].textContent.trim();
      navigator.clipboard.writeText(id).then(() => {
        alert("已复制 chat_id: " + id);
      });
    };
  });
}

document.getElementById("btn-refresh").onclick = refreshAll;
document.getElementById("btn-start").onclick = startBot;
document.getElementById("btn-stop").onclick = stopBot;
document.getElementById("btn-save-config").onclick = saveConfig;
document.getElementById("btn-add-account").onclick = () => addAccountRow({enabled:true, alias:"", display_name:"", chat_id:""});
document.getElementById("btn-import-signers").onclick = importSigners;
document.getElementById("btn-load-all-chats").onclick = loadChatsToTable;

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
    # 仅允许更新 strategies / accounts / chat_id / web.port 与 web.auth 未来可拓展
    strategies = body.get("strategies")
    accounts = body.get("accounts")
    chat_id = body.get("chat_id", None)

    if strategies is not None:
        if not isinstance(strategies, dict):
            raise HTTPException(400, "strategies 必须为对象")
        # 粗略校验
        for key in ["big_small", "odd_even"]:
            if key not in strategies: continue
            s = strategies[key]
            if not isinstance(s, dict): raise HTTPException(400, f"{key} 必须为对象")

    if accounts is not None:
        if not isinstance(accounts, list):
            raise HTTPException(400, "accounts 必须为数组")
        # 仅保留必要字段，并做简单清洗
        cleaned = []
        for a in accounts:
            if not isinstance(a, dict): continue
            cleaned.append({
                "enabled": bool(a.get("enabled", True)),
                "alias": str(a.get("alias", "")).strip(),
                "display_name": str(a.get("display_name", "")).strip(),
                "chat_id": str(a.get("chat_id", "")).strip() if a.get("chat_id") not in (None, "") else None
            })
        accounts = cleaned

    # 覆盖到 cfg
    if strategies is not None:
        cfg["strategies"] = {**cfg.get("strategies", {}), **strategies}
    if accounts is not None:
        cfg["accounts"] = accounts
    cfg["chat_id"] = chat_id if chat_id not in ("", None) else None

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


@app.get("/api/signers")
def api_signers(_: None = Depends(verify_basic_auth)):
    return list_signer_users()


@app.get("/api/signers/{user_dir}/latest_chats")
def api_latest_chats(
    user_dir: str = FPath(..., description="~/.signer/users 下的子目录名"),
    _: None = Depends(verify_basic_auth)
):
    return read_latest_chats_for_user(user_dir)
