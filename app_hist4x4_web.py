# -*- coding: utf-8 -*-
"""
Hist4x4 超傻瓜网页版（Google 登录 / 免登录 + 昵称）
右键：自动 读取剪贴板 → 粘贴 → 预测 → 清空
显示：前四/后四（不重=绿，重复=红）

✅ 兼容 Responses API 最新参数：
   - 首选严格结构化：text.format = {"type":"json_schema", ...}
   - 若模型不支持 → 自动降级：text.format = {"type":"json_object"}
   - 若模型不支持 temperature → 自动去掉后重试

网络：环境变量 / Windows系统代理 / 常见端口探测（HTTP & SOCKS5）
启动：
  uvicorn app_hist4x4_web:app --host 127.0.0.1 --port 8000

依赖（与一键脚本一致）：
  pip install fastapi "uvicorn[standard]" requests[socks] authlib itsdangerous
"""

import os, re, json, socket, sys
from typing import List, Optional, Tuple
import requests
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

# ---------- 基本配置 ----------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
USE_GOOGLE = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

API_URL = "https://api.openai.com/v1/responses"
MODEL = os.environ.get("GPT_MODEL", "gpt-5-mini")
WIN = 16

# ---------- 代理自动识别（环境变量 / Windows 系统代理 / 常见端口） ----------
def _mk_proxies(url: Optional[str]):
    return {"http": url, "https": url} if url else None

def _reachable(host: str, port: int, timeout=1.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def _from_env() -> Optional[str]:
    p = os.environ.get("PROXY_URL", "").strip()
    if p: return p
    for k in ("ALL_PROXY","HTTPS_PROXY","HTTP_PROXY","all_proxy","https_proxy","http_proxy"):
        v = os.environ.get(k, "").strip()
        if v: return v
    return None

def _from_windows_sysproxy() -> Optional[str]:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            try:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if int(enabled) == 1:
                    server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    s = str(server)
                    if "http=" in s or "https=" in s or "socks=" in s:
                        parts = {}
                        for seg in s.split(";"):
                            if "=" in seg:
                                k,v = seg.split("=",1); parts[k.lower()] = v
                        if "https" in parts: return "http://"+parts["https"]
                        if "http"  in parts: return "http://"+parts["http"]
                        if "socks" in parts:
                            hp = parts["socks"]
                            return "socks5h://"+hp if not hp.startswith("socks") else hp
                    else:
                        return "http://"+s
            except Exception:
                pass
    except Exception:
        return None

def _probe_common() -> Optional[str]:
    cands=[]
    for port in (7890,10809,1080,10808,8889,2080,9999):
        if _reachable("127.0.0.1", port):
            cands += [f"http://127.0.0.1:{port}", f"socks5h://127.0.0.1:{port}"]
    for url in cands:
        try:
            r = requests.get("https://www.google.com/generate_204",
                             proxies=_mk_proxies(url), timeout=2.5)
            if r.status_code in (204,200):
                return url
        except Exception:
            continue
    return None

PROXY_URL = _from_env() or _from_windows_sysproxy() or _probe_common()
PROXIES = _mk_proxies(PROXY_URL) if PROXY_URL else None
print(f"[proxy] {'DIRECT' if not PROXY_URL else PROXY_URL}")

# ---------- FastAPI / OAuth ----------
app = FastAPI(title="Hist4x4 超傻瓜网页版")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET","hist4x4-secret"))

if USE_GOOGLE:
    from authlib.integrations.starlette_client import OAuth
    oauth = OAuth()
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        client_kwargs={"scope": "openid email profile"},
    )

def need_login(request: Request):
    # 两按钮：Google 登录 或 免登录（访客）
    if not USE_GOOGLE:
        return
    if request.session.get("user") or request.session.get("guest"):
        return
    raise HTTPException(status_code=401, detail="请先点击：用Google登录 或 免登录")

# ---------- 工具 ----------
_LAST5_RE = re.compile(r"(\d{5})(?=\D*$)")
def extract_last5(raw_text: str) -> List[str]:
    nums = []
    for line in raw_text.strip().splitlines():
        m = _LAST5_RE.search(line.strip())
        if m: nums.append(m.group(1))
    return nums

# 结构化输出 schema（前四/后四 + 置信 + 距τ*）
RESP_SCHEMA = {
    "name": "Hist4x4Prediction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "front": {"type": "string", "enum": ["重号", "不重", "重复"]},
            "back":  {"type": "string", "enum": ["重号", "不重", "重复"]},
            "front_confidence":     {"type": "number", "minimum": 0, "maximum": 1},
            "back_confidence":      {"type": "number", "minimum": 0, "maximum": 1},
            "front_tau_distance":   {"type": "number", "minimum": 0, "maximum": 1},
            "back_tau_distance":    {"type": "number", "minimum": 0, "maximum": 1},
            "notes": {"type": "string"}
        },
        "required": [
            "front","back","front_confidence","back_confidence",
            "front_tau_distance","back_tau_distance"
        ],
        "additionalProperties": False
    }
}

def _http_post(payload: dict) -> dict:
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    r = requests.post(API_URL, headers=headers, json=payload, timeout=60, proxies=PROXIES)
    if r.status_code >= 400:
        raise RuntimeError(f"OpenAI API 错误 {r.status_code}: {r.text[:400]}")
    data = r.json()
    text = data.get("output_text")
    if not text and "choices" in data:  # 个别网关兼容
        text = data["choices"][0]["message"]["content"]
    if not text:
        segs=[]
        for item in data.get("output", []):
            for c in item.get("content", []):
                if c.get("type") in ("output_text","input_text","text"):
                    segs.append(c.get("text",""))
        text = "".join(segs)
    return json.loads(text)

def _send_with_adaptive_params(payload: dict) -> dict:
    """
    尝试发送；若提示 temperature 不支持→去掉重试。
    """
    try:
        return _http_post(payload)
    except RuntimeError as e:
        msg = str(e)
        if ("Unsupported parameter" in msg or "invalid_request_error" in msg) and "temperature" in msg:
            # 去掉 temperature 再试
            if "temperature" in payload:
                payload = dict(payload)  # 复制一个，避免副作用
                payload.pop("temperature", None)
                return _http_post(payload)
        raise

def call_gpt(series_lines: List[str]) -> dict:
    if not OPENAI_API_KEY:
        raise RuntimeError("缺少 OPENAI_API_KEY")
    system_prompt = (
        "你是老马的预测助手（GPT-5 Thinking）。\n"
        "给你按时间顺序的历史5位号码（每行一个）。请预测下一期(N+1) 的【前四/后四】是否“重号”。\n"
        "定义：前四=第1~4位；后四=第2~5位；若该4位中存在重复数字则为“重号/重复”，否则为“不重”。\n"
        "从近期频率、位置分布、转移倾向等模式出发，给出判断与置信度(0~1)。\n"
        "另外估计与决策阈值的相对距离(0~1，越大越远离边界)。\n"
        "严格以 JSON 返回，字段见 schema。不要输出多余文本。"
    )
    series_text = "\n".join(series_lines[-max(WIN+1, 64):])
    user_prompt = (
        "历史序列（每行5位，时间由旧到新）：\n"
        f"{series_text}\n\n"
        "请输出字段：front, back, front_confidence, back_confidence, "
        "front_tau_distance, back_tau_distance, notes（可选）。"
    )

    # 基础负载（不含 text.format、temperature）
    base = {
        "model": MODEL,
        "input": [
            {"role":"system","content":[{"type":"input_text","text": system_prompt}]},
            {"role":"user","content":[{"type":"input_text","text": user_prompt}]}
        ]
    }

    # ① 首选严格结构化 json_schema + temperature
    payload = dict(base)
    payload["text"] = { "format": { "type": "json_schema", "json_schema": RESP_SCHEMA } }
    payload["temperature"] = 0.2
    try:
        return _send_with_adaptive_params(payload)
    except RuntimeError as e:
        msg = str(e)

        # ② 若模型/版本不支持 json_schema → 降级到 json_object，再尝试（同样带 temperature，失败则自动移除）
        if ("json_schema" in msg) or ("text.format" in msg) or ("Unsupported parameter" in msg and "json_schema" in msg) or ("not supported" in msg):
            payload2 = dict(base)
            payload2["text"] = { "format": { "type": "json_object" } }
            payload2["temperature"] = 0.2
            # 强调只输出对象
            payload2["input"][0]["content"][0]["text"] += "\n务必只以JSON对象输出上述字段，不要多余文字。"
            return _send_with_adaptive_params(payload2)

        # 其它错误抛出
        raise

# ---------- 页面（两按钮 + 昵称 + 右键自动粘贴/预测/清空） ----------
HTML_INDEX = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Hist4x4 超傻瓜网页版</title>
<style>
  :root{--green:#16c60c;--red:#ff3b3b;--muted:#666}
  body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;padding:24px;max-width:960px}
  textarea{width:100%;height:280px;font-family:ui-monospace,Consolas,monospace;border-radius:12px;border:1px solid #ddd;padding:12px}
  .row{display:flex;gap:12px;align-items:center;margin:10px 0 18px}
  button,a.btn{padding:12px 16px;border-radius:12px;border:0;background:#111;color:#fff;cursor:pointer;text-decoration:none}
  .btn-secondary{background:#444}
  .muted{color:var(--muted);font-size:13px}
  .card{background:#fafafa;border:1px solid #eee;border-radius:14px;padding:14px;margin-top:12px}
  .big-red{color:var(--red);font-size:44px;font-weight:900;letter-spacing:2px}
  .big-green{color:var(--green);font-size:44px;font-weight:900;letter-spacing:2px}
  .pill{padding:2px 8px;border-radius:999px;border:1px solid #eee;background:#fff;margin-left:8px;font-size:12px}
  #toast{position:fixed;left:50%;top:16px;transform:translateX(-50%);background:#111;color:#fff;padding:8px 12px;border-radius:10px;display:none}
  input#nick{flex:1 1 240px;padding:10px;border-radius:10px;border:1px solid #ddd}
</style>
</head>
<body>
  <div id="toast"></div>
  <h2>Hist4x4 → GPT-5 Thinking（前四/后四·不重/重复）</h2>
  <div class="muted">在任何位置<b>右键</b>：自动从剪贴板粘贴 → 预测 → 清空。</div>

  <div class="row" id="authrow">
    <span class="muted" id="status">未选择登录方式</span>
    <a id="btnLogin" class="btn" href="javascript:void(0)">用 Google 登录</a>
    <a id="btnGuest" class="btn btn-secondary" href="javascript:void(0)">免登录</a>
    <a id="btnLogout" class="btn btn-secondary" href="javascript:void(0)" style="display:none">退出</a>
  </div>

  <div class="row">
    <input id="nick" placeholder="设置你的昵称（仅本机）">
    <button id="btnSaveNick">保存昵称</button>
  </div>

  <textarea id="txt" placeholder="例：\n251019-0750 17806\n251019-0751 82048\n..."></textarea>
  <div class="row">
    <span class="muted">预测对象：下一期 (N+1)</span>
    <button id="btnPredict">预测</button>
    <button id="btnClear" class="btn btn-secondary">清空</button>
  </div>

  <div id="result" class="card" style="display:none">
    <div class="muted" id="notes"></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px">
      <div id="frontBox" class="card">
        <div class="muted">前四</div>
        <div id="front" class="big-green">—</div>
        <div class="muted">置信 <span id="fc">—</span> <span class="pill">距τ* <span id="fd">—</span></span></div>
      </div>
      <div id="backBox" class="card">
        <div class="muted">后四</div>
        <div id="back" class="big-green">—</div>
        <div class="muted">置信 <span id="bc">—</span> <span class="pill">距τ* <span id="bd">—</span></span></div>
      </div>
    </div>
  </div>

<script>
const USE_GOOGLE = %USE_GOOGLE%;
const $ = (id)=>document.getElementById(id);
function toast(s, ms=1600){ const t=$('toast'); t.textContent=s; t.style.display='block'; setTimeout(()=>t.style.display='none', ms); }

async function whoami(){ const r = await fetch('/whoami'); return r.ok ? r.json() : {ok:false}; }
async function login(){ if(!USE_GOOGLE){ alert('未配置 Google 登录，建议“免登录”'); return; } location.href='/login'; }
async function guest(){ const r = await fetch('/guest', {method:'POST'}); if(r.ok){ paintAuth({mode:'guest'}); toast('已切换为免登录'); } else { alert('切换失败'); } }
async function logout(){ const r = await fetch('/logout'); if(r.ok){ paintAuth({mode:'none'}); toast('已退出'); } }

function paintAuth(state){
  const s = $('status'), L=$('btnLogin'), G=$('btnGuest'), O=$('btnLogout');
  if(state.user && state.user.email){ s.textContent = '已登录：' + state.user.email; L.style.display='none'; G.style.display='inline-block'; O.style.display='inline-block'; }
  else if(state.mode==='guest'){ s.textContent = '游客模式'; L.style.display='inline-block'; G.style.display='inline-block'; O.style.display='inline-block'; }
  else{ s.textContent = USE_GOOGLE ? '请选择：登录 或 免登录' : '未配置 Google，建议“免登录”'; L.style.display='inline-block'; G.style.display='inline-block'; O.style.display='none'; }
}

function zhLabel(v){ return (v==='重号'||v==='重复')?'重复':'不重'; }
function paintSide(side, value, conf, dist){
  const el = $(side);
  const label = zhLabel(value);
  el.className = (label==='重复')?'big-red':'big-green';
  el.textContent = label;
  $(side==='front'?'fc':'bc').textContent = (conf||0).toFixed(3);
  $(side==='front'?'fd':'bd').textContent = (dist||0).toFixed(3);
}

async function predict(){
  const text = $('txt').value || '';
  const r = await fetch('/predict', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})});
  if(!r.ok){ const msg = await r.text(); alert('预测失败：' + msg); return false; }
  const j = await r.json();
  paintSide('front', j.front, j.front_confidence, j.front_tau_distance);
  paintSide('back',  j.back,  j.back_confidence,  j.back_tau_distance);
  $('notes').textContent = j.notes || '';
  $('result').style.display='block';
  return true;
}

function clearBox(){ $('txt').value=''; }

// 昵称：保存到本机 localStorage，同步到会话
function applyNickUI(nick){
  const s = $('status');
  const saved = nick && nick.trim();
  if(saved){
    if(s.textContent.startsWith('未选择') || s.textContent.includes('未配置') || s.textContent.includes('游客')){
      s.textContent = '游客（' + saved + '）';
    }else{
      if(!s.textContent.includes(saved)) s.textContent = s.textContent + ' · ' + saved;
    }
  }
  $('nick').value = saved || '';
}
async function syncNickToServer(nick){
  await fetch('/setnick', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({nick})});
}

$('btnLogin').onclick = login;
$('btnGuest').onclick = guest;
$('btnLogout').onclick = logout;
$('btnPredict').onclick = async ()=>{ if(await predict()) toast('预测完成'); };
$('btnClear').onclick = clearBox;

$('btnSaveNick').onclick = async ()=>{
  const nick = $('nick').value.trim();
  localStorage.setItem('hist4x4_nick', nick);
  await syncNickToServer(nick);
  applyNickUI(nick);
  alert(nick ? ('已保存昵称：' + nick) : '已清除昵称');
};

// 初始化：状态 + 昵称
(async ()=>{
  const localNick = localStorage.getItem('hist4x4_nick') || '';
  if(localNick) await syncNickToServer(localNick);
  const w = await whoami();
  paintAuth({user:w.user, mode:w.guest?'guest':'user'});
  applyNickUI(w.nick || localNick || '');
})();

// 右键：读取剪贴板 → 粘贴 → 预测 → 清空
document.addEventListener('contextmenu', async (e)=>{
  e.preventDefault();
  try{
    const clip = await navigator.clipboard.readText();
    if(!clip || !clip.trim()){ toast('剪贴板为空'); return; }
    $('txt').value = clip;
    const ok = await predict();
    if(ok){ $('txt').value=''; toast('已用剪贴板预测并清空'); }
  }catch(err){
    alert('无法读取剪贴板。请允许“读取剪贴板”权限，或先 Ctrl+V 粘贴再点“预测”。');
  }
});
</script>
</body></html>
""".replace("%USE_GOOGLE%", "true" if USE_GOOGLE else "false")

# ---------- 路由 ----------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return HTML_INDEX

@app.post("/setnick")
async def setnick(request: Request, data: dict = Body(default={})):
    nick = (data.get("nick") or "").strip()[:40]
    if not nick:
        request.session.pop("nick", None)
        return {"ok": True, "nick": None}
    request.session["nick"] = nick
    return {"ok": True, "nick": nick}

@app.get("/whoami")
async def whoami(request: Request):
    return {
        "ok": True,
        "user": request.session.get("user"),
        "guest": bool(request.session.get("guest")),
        "nick": request.session.get("nick"),
    }

@app.get("/login")
async def login(request: Request):
    if not USE_GOOGLE:
        return RedirectResponse("/")
    redirect_uri = request.url_for("auth")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.route("/auth")
async def auth(request: Request):
    if not USE_GOOGLE:
        return RedirectResponse("/")
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo")
    request.session["user"] = {"email": user_info["email"], "name": user_info.get("name")}
    request.session.pop("guest", None)
    return RedirectResponse("/")

@app.post("/guest")
async def guest(request: Request):
    request.session["guest"] = True
    request.session.pop("user", None)
    return {"ok": True}

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")

@app.post("/predict")
async def predict(request: Request):
    need_login(request)
    body = await request.json()
    text = (body.get("text") or "").strip()
    nums = extract_last5(text)
    if len(nums) < WIN + 1:
        raise HTTPException(status_code=400, detail=f"有效行不足：{len(nums)}；至少需要 {WIN+1}")
    try:
        data = call_gpt(nums)
        return JSONResponse(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
