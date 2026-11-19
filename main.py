import time, os, re, json, httpx, sqlite3, hmac, hashlib, secrets
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

APP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<meta name="theme-color" content="#0b0f17">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>OptiMax Console | AI Gateway</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0b0f17;color:#e2e8f0;display:flex;min-height:100vh}
.sidebar{width:240px;background:#111827;border-right:1px solid #1f2937;padding:20px 14px;display:flex;flex-direction:column;justify-content:space-between}
.brand{display:flex;align-items:center;gap:10px;padding:0 8px 20px;border-bottom:1px solid #1f2937;font-weight:700;font-size:18px;color:#fff}
.logo{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,#3b82f6,#10b981);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:14px}
.nav{margin-top:18px;display:flex;flex-direction:column;gap:6px}
.nav button{background:transparent;border:none;color:#9ca3af;padding:11px 12px;border-radius:8px;text-align:left;font-size:14px;font-weight:500;cursor:pointer;display:flex;align-items:center;gap:10px;transition:.15s}
.nav button:hover,.nav button.active{background:#1f2937;color:#fff}
.nav button.active{border-left:3px solid #3b82f6}
.main{flex:1;display:flex;flex-direction:column;overflow-x:hidden}
.topbar{height:60px;background:#111827;border-bottom:1px solid #1f2937;padding:0 24px;display:flex;align-items:center;justify-content:space-between}
.pill{background:rgba(16,185,129,.12);color:#10b981;padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600}
.content{padding:24px;max-width:1050px;width:100%;margin:0 auto}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px}
.kpi{background:#111827;border:1px solid #1f2937;padding:16px;border-radius:10px}
.kpi-lbl{font-size:12px;color:#9ca3af}
.kpi-val{font-size:22px;font-weight:700;color:#fff;margin-top:4px}
.panel{display:none;background:#111827;border:1px solid #1f2937;border-radius:12px;padding:22px}
.panel.active{display:block}
input,select,textarea{width:100%;padding:11px;border-radius:8px;border:1px solid #374151;background:#0b0f17;color:#fff;margin-top:6px;margin-bottom:14px;font-size:14px}
.row{display:grid;grid-template-columns:2fr 1fr;gap:12px}
.btn{background:#2563eb;color:#fff;border:none;padding:11px 20px;border-radius:8px;font-weight:600;cursor:pointer;font-size:14px;text-decoration:none;display:inline-block}
.btn:hover{background:#1d4ed8}
.btn-green{background:#059669}
pre{background:#0b0f17;border:1px solid #1f2937;padding:16px;border-radius:8px;color:#34d399;white-space:pre-wrap;font-size:13px;min-height:110px;margin-top:14px}
.row-item{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid #1f2937;font-size:14px}
@media(max-width:768px){body{flex-direction:column}.sidebar{width:100%;padding:12px}.nav{flex-direction:row;overflow-x:auto}.kpis{grid-template-columns:repeat(2,1fr)}.row{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="sidebar">
  <div>
    <div class="brand"><div class="logo">OX</div>OptiMax Proxy</div>
    <div class="nav">
      <button class="active" onclick="tab('play',this)">⚡ Playground</button>
      <button onclick="tab('keys',this)">🔑 API Keys & Trial</button>
      <button onclick="tab('models',this)">🧠 Models & Routing</button>
      <button onclick="tab('sdk',this)">💻 1-Line SDK Setup</button>
    </div>
  </div>
  <div style="padding:10px 8px;border-top:1px solid #1f2937">
    <a href="/upgrade" class="btn btn-green" style="width:100%;text-align:center">Upgrade Pro ($49)</a>
  </div>
</div>
<div class="main">
  <div class="topbar">
    <div style="font-weight:600;font-size:15px" id="pageTitle">Interactive Model Playground</div>
    <span class="pill">● Gateway Healthy • CogniShield Active</span>
  </div>
  <div class="content">
    <div class="kpis">
      <div class="kpi"><div class="kpi-lbl">Active Models</div><div class="kpi-val">Gemini / GPT-4o</div></div>
      <div class="kpi"><div class="kpi-lbl">Semantic Cache</div><div class="kpi-val" style="color:#10b981">Enabled</div></div>
      <div class="kpi"><div class="kpi-lbl">Free Trial</div><div class="kpi-val">14 Days</div></div>
      <div class="kpi"><div class="kpi-lbl">Firewall</div><div class="kpi-val" style="color:#60a5fa">Zero-Trust</div></div>
    </div>

    <div id="play" class="panel active">
      <h3 style="margin-top:0">Test Unified LLM Gateway</h3>
      <div class="row">
        <div><label style="font-size:12px;color:#9ca3af">Virtual API Key</label><input id="key" value="optx_free_trial_user"></div>
        <div><label style="font-size:12px;color:#9ca3af">Routing Strategy</label><select id="mod"><option value="auto">Smart Auto-Route (Cost + Speed)</option><option value="gemini">Google Gemini 2.5 Flash</option><option value="openai">OpenAI GPT-4o Mini</option></select></div>
      </div>
      <label style="font-size:12px;color:#9ca3af">Prompt</label>
      <textarea id="prm" rows="3" placeholder="Enter a prompt to test latency, model routing, and semantic caching..."></textarea>
      <button onclick="runAI()" class="btn">Send Request →</button>
      <pre id="out">// Live JSON telemetry and AI response will stream here...</pre>
    </div>

    <div id="keys" class="panel">
      <h3 style="margin-top:0">Generate Virtual Trial API Key</h3>
      <p style="font-size:13px;color:#9ca3af">Create a 14-day multi-model key backed by cloud PostgreSQL.</p>
