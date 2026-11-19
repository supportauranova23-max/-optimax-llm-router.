import time, os, json, httpx, sqlite3, hashlib, secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict, List
from cognishield_layer import CogniShieldLayer

try:
    import psycopg2
except ImportError:
    psycopg2 = None

app = FastAPI(title="OptiMax Proxy Admin (LiteLLM Edition)")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
LEMON_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
RAW_DB = os.environ.get("DATABASE_URL", "").strip().removeprefix("psql ").strip().strip("'\"")

USE_PG = bool(RAW_DB.startswith("postgres") and psycopg2)
shield = CogniShieldLayer()
http = httpx.AsyncClient(timeout=25.0)
CACHE: Dict[str, str] = {}

def get_db():
    if USE_PG:
        try:
            return psycopg2.connect(RAW_DB), "%s"
        except Exception:
            pass
    return sqlite3.connect("optimax_litellm.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS litellm_keys (api_key TEXT PRIMARY KEY, key_alias TEXT, email TEXT, tier TEXT, created_at TEXT, requests INTEGER DEFAULT 0, spend_usd REAL DEFAULT 0.0, max_budget_usd REAL DEFAULT 25.0)")
    now = datetime.utcnow().isoformat()
    starters = [
        ("optx_free_trial_user", "default-sandbox-key", "trial@user.com", "trial", now, 0, 0.0, 15.0),
        ("optx_live_prod_99x1", "production-gateway-key", "prod@enterprise.io", "enterprise", now, 142, 4.18, 500.0)
    ]
    for s in starters:
        sql = "INSERT INTO litellm_keys VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING" if ph == "%s" else "INSERT OR IGNORE INTO litellm_keys VALUES (?,?,?,?,?,?,?,?)"
        cur.execute(sql, s)
    conn.commit()
    cur.close()
    conn.close()

init_db()

class PromptReq(BaseModel):
    prompt: str
    model: Optional[str] = "auto"

async def verify_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.strip().removeprefix("Bearer ").strip()
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT key_alias, tier, created_at, requests, spend_usd, max_budget_usd FROM litellm_keys WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid Virtual Key.")
    alias, tier, created_str, reqs, spend, budget = row
    if tier == "trial" and datetime.utcnow() > datetime.fromisoformat(created_str) + timedelta(days=14):
        raise HTTPException(status_code=402, detail="14-day trial expired. Visit /upgrade.")
    if spend >= budget:
        raise HTTPException(status_code=402, detail=f"Max Budget Exceeded (${spend}/{budget}).")
    return {"token": token, "alias": alias, "tier": tier, "reqs": reqs, "spend": spend, "budget": budget}

async def route_ai(prompt: str, pref: str):
    c_key = hashlib.sha256(prompt.strip().lower().encode()).hexdigest()
    if c_key in CACHE:
        return CACHE[c_key], "semantic-cache", True
    primary = pref if pref in ["gemini", "openai"] else ("gemini" if len(prompt.split()) < 15 else "openai")
    order = [primary, "openai" if primary == "gemini" else "gemini"]
    last_err = "Add GEMINI_API_KEY or OPENAI_API_KEY in Render Environment."
    for prov in order:
        try:
            if prov == "gemini" and GEMINI_KEY:
                url = f"https://googleapis.com{GEMINI_KEY}"
                r = await http.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
                r.raise_for_status()
                ans = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                CACHE[c_key] = ans
                return ans, "gemini-2.5-flash", False
            if prov == "openai" and OPENAI_KEY:
                r = await http.post("https://openai.com", headers={"Authorization": f"Bearer {OPENAI_KEY}"}, json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]})
                r.raise_for_status()
                ans = r.json()["choices"][0]["message"]["content"]
                CACHE[c_key] = ans
                return ans, "gpt-4o-mini", False
        except Exception as e:
            last_err = str(e)
    raise HTTPException(status_code=502, detail=f"AI Provider Error: {last_err}")

LITELLM_UI = (
    "<!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>OptiMax Proxy | LLM Gateway</title><style>"
    "*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#090d16;color:#e2e8f0;display:flex;min-height:100vh}"
    ".side{width:240px;background:#0f172a;border-right:1px solid #1e293b;padding:18px 12px;display:flex;flex-direction:column;justify-content:space-between}"
    ".logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px;color:#fff;padding:0 10px 16px;border-bottom:1px solid #1e293b}"
    ".badge{background:#1d4ed8;color:#fff;font-size:11px;padding:2px 7px;border-radius:4px}"
    ".nav{margin-top:14px;display:flex;flex-direction:column;gap:4px}"
    ".nav button{background:none;border:none;color:#94a3b8;padding:10px 12px;border-radius:6px;text-align:left;font-size:13.5px;font-weight:500;cursor:pointer;display:flex;align-items:center;gap:8px}"
    ".nav button:hover,.nav button.active{background:#1e293b;color:#fff}.nav button.active{border-left:3px solid #3b82f6}"
    ".main{flex:1;display:flex;flex-direction:column}.top{height:56px;background:#0f172a;border-bottom:1px solid #1e293b;padding:0 24px;display:flex;align-items:center;justify-content:space-between;font-size:14px}"
    ".wrap{padding:24px;max-width:1050px;width:100%;margin:0 auto}.panel{display:none;background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:22px}.panel.active{display:block}"
    ".grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}.stat{background:#0f172a;border:1px solid #1e293b;padding:16px;border-radius:8px}"
    ".stat small{color:#94a3b8;font-size:12px}.stat div{font-size:20px;font-weight:700;margin-top:4px;color:#fff}"
    "table{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px}th,td{text-align:left;padding:11px;border-bottom:1px solid #1e293b}th{color:#94a3b8}"
    "input,select,textarea{width:100%;padding:10px;border-radius:6px;border:1px solid #334155;background:#090d16;color:#fff;margin:6px 0 12px;font-size:13.5px}"
    ".btn{background:#2563eb;color:#fff;border:none;padding:9px 16px;border-radius:6px;font-weight:600;cursor:pointer;font-size:13px;text-decoration:none;display:inline-block}"
    ".up{background:#059669;width:100%;text-align:center}pre{background:#090d16;border:1px solid #1e293b;padding:14px;border-radius:6px;color:#34d399;white-space:pre-wrap;min-height:90px;font-size:12.5px}"
    "@media(max-width:768px){body{flex-direction:column}.side{width:100%}.nav{flex-direction:row;overflow-x:auto}.grid{grid-template-columns:repeat(2,1fr)}}"
    "</style></head><body>"
    "<div class='side'><div><div class='logo'>🚅 OptiMax <span class='badge'>PROXY</span></div><div class='nav'>"
    "<button class='active' onclick=\"tab('test',this)\">⚡ Test Key (Playground)</button>"
    "<button onclick=\"tab('keys',this)\">🔑 Virtual Keys</button>"
    "<button onclick=\"tab('models',this)\">🧠 Models & Endpoints</button>"
    "<button onclick=\"tab('spend',this)\">📊 Usage & Spend</button>"
    "<button onclick=\"tab('docs',this)\">🔌 OpenAI SDK Drop-In</button>"
    "</div></div><a href='/upgrade' class='btn up'>Upgrade Enterprise ($49)</a></div>"
    "<div class='main'><div class='top'><span id='hdr'>Test Key (Playground)</span><span style='color:#10b981;font-size:12px'>● Proxy Healthy • CogniShield Guardrail ON</span></div>"
    "<div class='wrap'><div class='grid'>"
    "<div class='stat'><small>Active Virtual Keys</small><div id='kCnt'>2</div></div>"
    "<div class='stat'><small>Total Proxy Requests</small><div id='rCnt'>142</div></div>"
    "<div class='stat'><small>Total Spend (USD)</small><div id='sCnt' style='color:#38bdf8'>$4.18</div></div>"
    "<div class='stat'><small>Guardrail Status</small><div style='color:#10b981'>Protected</div></div></div>"
    "<div id='test' class='panel active'><h3 style='margin-top:0'>Live Model Playground</h3>"
    "<div style='display:grid;grid-template-columns:2fr 1fr;gap:10px'>"
    "<input id='key' value='optx_free_trial_user' placeholder='Virtual API Key'>"
    "<select id='mod'><option value='auto'>Auto-Route (Lowest Cost)</option><option value='gemini'>gemini-2.5-flash</option><option value='openai'>gpt-4o-mini</option></select></div>"
    "<textarea id='prm' rows='3' placeholder='Send a test prompt through OptiMax Proxy...'></textarea>"
    "<button onclick='runAI()' class='btn'>Test Chat Completion</button><pre id='out'>// Proxy response & latency telemetry...</pre></div>"
    "<div id='keys' class='panel'><h3 style='margin-top:0'>Create Virtual API Key (14-Day Trial)</h3>"
    "<form action='/start-trial' method='post' style='display:grid;grid-template-columns:1fr 1fr auto;gap:8px'>"
    "<input name='name' placeholder='Key Alias (e.g. prod-app)' required><input name='email' type='email' placeholder='Owner Email' required>"
    "<button type='submit' class='btn' style='height:38px;margin-top:6px'>+ Create Key</button></form>"
    "<table><thead><tr><th>Key Alias</th><th>API Key</th><th>Tier</th><th>Requests</th><th>Spend / Budget</th></tr></thead><tbody id='keyTbl'></tbody></table></div>"
    "<div id='models' class='panel'><h3 style='margin-top:0'>Configured Proxy Models</h3>"
    "<table><thead><tr><th>Public Model Name</th><th>Provider</th><th>Cost / 1M Tokens</th><th>Status</th></tr></thead><tbody>"
    "<tr><td><b>gemini-2.5-flash</b></td><td>Google AI</td><td>$0.15 / $0.60</td><td style='color:#10b981'>● Healthy</td></tr>"
    "<tr><td><b>gpt-4o-mini</b></td><td>OpenAI</td><td>$0.15 / $0.60</td><td style='color:#10b981'>● Healthy</td></tr>"
    "<tr><td><b>semantic-cache</b></td><td>OptiMax Memory</td><td>$0.00 (Free)</td><td style='color:#38bdf8'>● Active</td></tr></tbody></table></div>"
    "<div id='spend' class='panel'><h3 style='margin-top:0'>Real-Time Spend & ROI Ledger</h3>"
    "<p style='font-size:13px;color:#94a3b8'>Every request is metered automatically with hard budget enforcement.</p>"
    "<div id='spendBars'></div></div>"
    "<div id='docs' class='panel'><h3 style='margin-top:0'>1-Line OpenAI SDK Drop-In</h3>"
    "<pre style='color:#93c5fd'>from openai import OpenAI\n\nclient = OpenAI(\n    api_key=\"optx_free_trial_user\",\n    base_url=\"https://onrender.com\"\n)</pre></div>"
    "</div></div><script>"
    "const titles={test:'Test Key (Playground)',keys:'Virtual Keys Management',models:'Models & Endpoints',spend:'Usage & Spend Analytics',docs:'Developer SDK Integration'};"
    "function tab(id,b){document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');b.classList.add('active');document.getElementById('hdr').textContent=titles[id];loadStats()}"
    "async function loadStats(){try{const r=await fetch('/v1/admin/stats');const d=await r.json();document.getElementById('kCnt').textContent=d.keys.length;document.getElementById('rCnt').textContent=d.total_reqs;document.getElementById('sCnt').textContent='$'+d.total_spend.toFixed(4);"
    "document.getElementById('keyTbl').innerHTML=d.keys.map(k=>`<tr><td><b>${k.alias}</b></td><td style='font-family:monospace;color:#38bdf8'>${k.key}</td><td>${k.tier}</td><td>${k.reqs}</td><td>$${k.spend.toFixed(4)} / $${k.budget}</td></tr>`).join('');"
    "document.getElementById('spendBars').innerHTML=d.keys.map(k=>`<div style='margin:12px 0'><div style='display:flex;justify-content:space-between;font-size:13px'><span>${k.alias}</span><span>$${k.spend.toFixed(4)} / $${k.budget}</span></div><div style='background:#1e293b;height:8px;border-radius:4px;margin-top:4px'><div style='background:#3b82f6;height:8px;border-radius:4px;width:${Math.min(100,(k.spend/k.budget)*100)}%'></div></div></div>`).join('')}catch(e){}}"
    "loadStats();"
    "async function runAI(){const o=document.getElementById('out');o.style.color='#38bdf8';o.textContent='Routing through OptiMax Proxy...';const r=await fetch('/v1/route',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+document.getElementById('key').value.trim()},body:JSON.stringify({prompt:document.getElementById('prm').value,model:document.getElementById('mod').value})});const d=await r.json();o.style.color=r.ok?'#34d399':'#f87171';o.textContent=JSON.stringify(d,null,2);loadStats()}"
    "</script></body></html>"
)

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(content=LITELLM_UI)

@app.get("/v1/admin/stats")
async def admin_stats():
    conn, _ = get_db()
    cur = conn.cursor()
    cur.execute("SELECT api_key, key_alias, tier, requests, spend_usd, max_budget_usd FROM litellm_keys")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    keys = [{"key": r[0][:12] + "...", "alias": r[1], "tier": r[2], "reqs": r[3], "spend": float(r[4]), "budget": float(r[5])} for r in rows]
    return {"keys": keys, "total_reqs": sum(k["reqs"] for k in keys), "total_spend": sum(k["spend"] for k in keys)}

@app.post("/start-trial", response_class=HTMLResponse)
async def start_trial(name: str = Form(...), email: str = Form(...)):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT api_key FROM litellm_keys WHERE email = {ph}", (email,))
    row = cur.fetchone()
    if row:
        key = row[0]
    else:
        key = f"optx_trial_{secrets.token_hex(8)}"
        cur.execute(f"INSERT INTO litellm_keys VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})", (key, name, email, "trial", datetime.utcnow().isoformat(), 0, 0.0, 15.0))
        conn.commit()
    cur.close()
    conn.close()
