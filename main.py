import time, os, json, httpx, sqlite3, hmac, hashlib, secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict
from cognishield_layer import CogniShieldLayer

try:
    import psycopg2
except ImportError:
    psycopg2 = None

app = FastAPI(title="OptiMax Enterprise Console")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
LEMON_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
LEMON_SECRET = os.environ.get("LEMON_WEBHOOK_SECRET", "")
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
    return sqlite3.connect("optimax_app.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (api_key TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, tier TEXT, created_at TEXT, usage_count INTEGER DEFAULT 0, saved_usd REAL DEFAULT 0.0)")
    now = datetime.utcnow().isoformat()
    sql = "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING" if ph == "%s" else "INSERT OR IGNORE INTO users VALUES (?,?,?,?,?,?,?)"
    cur.execute(sql, ("optx_free_trial_user", "Sandbox Workspace", "trial@user.com", "trial", now, 0, 0.0))
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
    cur.execute(f"SELECT name, tier, created_at, usage_count, saved_usd FROM users WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid API Key.")
    name, tier, created_str, usage, saved = row
    if tier == "trial" and datetime.utcnow() > datetime.fromisoformat(created_str) + timedelta(days=14):
        raise HTTPException(status_code=402, detail="14-day trial expired. Visit /upgrade.")
    return {"token": token, "name": name, "tier": tier, "usage": usage, "saved": saved}

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
                ans = r.json()["candidates"]["content"]["parts"]["text"]
                CACHE[c_key] = ans
                return ans, "gemini-2.5-flash", False
            if prov == "openai" and OPENAI_KEY:
                r = await http.post("https://openai.com", headers={"Authorization": f"Bearer {OPENAI_KEY}"}, json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]})
                r.raise_for_status()
                ans = r.json()["choices"]["message"]["content"]
                CACHE[c_key] = ans
                return ans, "gpt-4o-mini", False
        except Exception as e:
            last_err = str(e)
    raise HTTPException(status_code=502, detail=f"AI Provider Error: {last_err}")

APP_HTML = (
    "<!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>OptiMax Console</title><style>"
    "*{box-sizing:border-box}body{margin:0;font-family:sans-serif;background:#0b0f17;color:#e2e8f0;display:flex;min-height:100vh}"
    ".side{width:220px;background:#111827;border-right:1px solid #1f2937;padding:18px;display:flex;flex-direction:column;justify-content:space-between}"
    ".brand{font-weight:700;font-size:18px;color:#fff;padding-bottom:15px;border-bottom:1px solid #1f2937}"
    ".nav{margin-top:15px;display:flex;flex-direction:column;gap:6px}"
    ".nav button{background:none;border:none;color:#9ca3af;padding:10px;border-radius:8px;text-align:left;font-size:14px;cursor:pointer}"
    ".nav button.active,.nav button:hover{background:#1f2937;color:#fff}"
    ".main{flex:1;padding:24px;max-width:950px;margin:0 auto;width:100%}"
    ".kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px}"
    ".kpi{background:#111827;border:1px solid #1f2937;padding:14px;border-radius:10px}"
    ".panel{display:none;background:#111827;border:1px solid #1f2937;border-radius:12px;padding:20px}.panel.active{display:block}"
    "input,select,textarea{width:100%;padding:10px;border-radius:8px;border:1px solid #374151;background:#0b0f17;color:#fff;margin:6px 0 12px}"
    ".btn{background:#2563eb;color:#fff;border:none;padding:10px 18px;border-radius:8px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}"
    ".green{background:#059669;width:100%;text-align:center}"
    "pre{background:#0b0f17;border:1px solid #1f2937;padding:14px;border-radius:8px;color:#34d399;white-space:pre-wrap;min-height:90px}"
    "@media(max-width:768px){body{flex-direction:column}.side{width:100%}.nav{flex-direction:row}}"
    "</style></head><body>"
    "<div class='side'><div><div class='brand'>⚡ OptiMax Proxy</div><div class='nav'>"
    "<button class='active' onclick=\"tab('play',this)\">Playground</button>"
    "<button onclick=\"tab('keys',this)\">Trial Keys</button>"
    "<button onclick=\"tab('sdk',this)\">SDK Setup</button>"
    "</div></div><a href='/upgrade' class='btn green'>Upgrade ($49)</a></div>"
    "<div class='main'><div class='kpis'>"
    "<div class='kpi'><small style='color:#9ca3af'>Models</small><div style='font-weight:700;margin-top:4px'>Gemini / GPT-4o</div></div>"
    "<div class='kpi'><small style='color:#9ca3af'>Cache</small><div style='font-weight:700;color:#10b981;margin-top:4px'>Semantic Active</div></div>"
    "<div class='kpi'><small style='color:#9ca3af'>Security</small><div style='font-weight:700;color:#60a5fa;margin-top:4px'>CogniShield</div></div>"
    "</div>"
    "<div id='play' class='panel active'><h3 style='margin-top:0'>Live Model Playground</h3>"
    "<input id='key' value='optx_free_trial_user'><select id='mod'><option value='auto'>Auto Route</option><option value='gemini'>Gemini 2.5 Flash</option><option value='openai'>GPT-4o Mini</option></select>"
    "<textarea id='prm' rows='3' placeholder='Ask anything...'></textarea>"
    "<button onclick='runAI()' class='btn'>Send Request</button><pre id='out'>Ready...</pre></div>"
    "<div id='keys' class='panel'><h3 style='margin-top:0'>14-Day Free Trial Key</h3>"
    "<form action='/start-trial' method='post'><input name='name' placeholder='Name' required><input name='email' type='email' placeholder='Email' required>"
    "<button type='submit' class='btn'>Generate Key</button></form></div>"
    "<div id='sdk' class='panel'><h3 style='margin-top:0'>cURL Integration</h3>"
    "<pre style='color:#93c5fd'>curl -X POST https://onrender.com -H 'Authorization: Bearer optx_free_trial_user' -H 'Content-Type: application/json' -d '{\"prompt\":\"Hello\"}'</pre></div>"
    "</div><script>"
    "function tab(id,b){document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');b.classList.add('active')}"
    "async function runAI(){const o=document.getElementById('out');o.textContent='Routing...';const r=await fetch('/v1/route',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+document.getElementById('key').value.trim()},body:JSON.stringify({prompt:document.getElementById('prm').value,model:document.getElementById('mod').value})});const d=await r.json();o.style.color=r.ok?'#34d399':'#f87171';o.textContent=JSON.stringify(d,null,2)}"
    "</script></body></html>"
)

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(content=APP_HTML)

@app.post("/start-trial", response_class=HTMLResponse)
async def start_trial(name: str = Form(...), email: str = Form(...)):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT api_key FROM users WHERE email = {ph}", (email,))
    row = cur.fetchone()
    if row:
        key = row
    else:
        key = f"optx_trial_{secrets.token_hex(8)}"
        cur.execute(f"INSERT INTO users VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})", (key, name, email, "trial", datetime.utcnow().isoformat(), 0, 0.0))
        conn.commit()
    cur.close()
    conn.close()
    return HTMLResponse(content=f"<body style='background:#0b0f17;color:#fff;font-family:sans-serif;text-align:center;padding:50px'><h2 style='color:#10b981'>Trial Key Ready!</h2><p>Key: <b style='color:#60a5fa'>{key}</b></p><a href='/' style='color:#60a5fa'>Back to Console</a></body>")

@app.get("/upgrade")
async def upgrade():
