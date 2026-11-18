import time, os, sqlite3, hmac, hashlib, secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
from cognishield_layer import CogniShieldLayer
from openai import OpenAI
from google import genai

try:
    import psycopg2
except ImportError:
    psycopg2 = None

app = FastAPI(title="OptiMax: Intelligent AI API Cost Management Router")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
LEMON_CHECKOUT_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
LEMON_WEBHOOK_SECRET = os.environ.get("LEMON_WEBHOOK_SECRET", "")
RAW_DB_URL = os.environ.get("DATABASE_URL", "").strip().removeprefix("psql ").strip().strip("'\"")

USE_POSTGRES = bool(RAW_DB_URL.startswith("postgres") and psycopg2)
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
shield = CogniShieldLayer()
TRIAL_DAYS = 14

def get_db():
    if USE_POSTGRES:
        try:
            return psycopg2.connect(RAW_DB_URL), "%s"
        except Exception:
            pass
    return sqlite3.connect("optimax_fallback.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (api_key TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, tier TEXT, created_at TEXT, usage_count INTEGER DEFAULT 0)")
    now_iso = datetime.utcnow().isoformat()
    starters = [
        ("optx_live_dev_78x92", "Alpha Tech Ventures", "dev@alphatech.io", "premium", now_iso, 0),
        ("optx_live_scale_11a42", "Nexus AI Core", "admin@nexusai.io", "premium", now_iso, 0),
        ("optx_free_trial_user", "Standard Sandbox User", "trial@user.com", "trial", now_iso, 0)
    ]
    for u in starters:
        sql = "INSERT INTO users (api_key, name, email, tier, created_at, usage_count) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (api_key) DO NOTHING" if ph == "%s" else "INSERT OR IGNORE INTO users (api_key, name, email, tier, created_at, usage_count) VALUES (?, ?, ?, ?, ?, ?)"
        cur.execute(sql, u)
    conn.commit()
    cur.close()
    conn.close()

init_db()

class PromptRequest(BaseModel):
    prompt: str
    preferred_model: Optional[str] = "auto"

DASHBOARD_HTML = '<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>OptiMax AI Router</title><style>body{font-family:Segoe UI,sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:30px}.container{max-width:850px;margin:0 auto;background:#161b22;padding:25px;border-radius:8px;border:1px solid #30363d}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #30363d;padding-bottom:15px}.logo{width:40px;height:40px;background:linear-gradient(135deg,#1f6feb,#3fb950);border-radius:8px;display:inline-flex;align-items:center;justify-content:center;font-weight:bold;color:#fff;margin-right:10px}h1{color:#58a6ff;margin:0;display:inline;font-size:22px}.badge{padding:5px 12px;background:rgba(63,185,80,0.15);color:#3fb950;border-radius:20px;font-size:13px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px;margin:20px 0}.box{background:#21262d;padding:15px;border-radius:6px;border:1px solid #30363d;text-align:center}.val{font-size:20px;font-weight:bold;color:#3fb950;margin-top:5px}.card{background:#21262d;padding:20px;border-radius:6px;border:1px solid #30363d;margin-top:15px}.btn{display:inline-block;background:#238636;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;font-weight:bold;border:none;cursor:pointer;font-size:14px}.blue{background:#1f6feb}input{padding:10px;border-radius:6px;border:1px solid #30363d;background:#0d1117;color:#fff;width:35%;margin-right:8px}pre{background:#0d1117;padding:12px;border-radius:6px;border:1px solid #30363d;color:#79c0ff;overflow-x:auto;font-size:12px}</style></head><body><div class="container"><div class="header"><div><span class="logo">OX</span><h1>OptiMax AI Router & Gateway</h1></div><span class="badge">● Multi-LLM & 14-Day Trial Live</span></div><div class="grid"><div class="box"><div>Trial Period</div><div class="val">14 Days</div></div><div class="box"><div>AI Models</div><div class="val">GPT-4o / Gemini</div></div><div class="box"><div>Billing</div><div class="val" style="color:#58a6ff">Lemon + Payoneer</div></div></div><div class="card"><h3>1. Start Your Free 2-Week Trial</h3><form action="/start-trial" method="post"><input type="text" name="name" placeholder="Your Name" required><input type="email" name="email" placeholder="Work Email" required><button type="submit" class="btn blue">Get 14-Day Trial Key</button></form></div><div class="card"><h3>2. Developer API Endpoint</h3><pre>POST https://onrender.com | Header: Authorization: Bearer YOUR_KEY</pre></div><div class="card" style="text-align:center"><h3>3. Test & Upgrade</h3><a class="btn blue" href="/docs" style="margin-right:10px">Open API Playground</a><a class="btn" href="/upgrade">Upgrade Account ($49/mo)</a></div></div></body></html>'

async def verify_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token. Use 'Bearer optx_free_trial_user'")
    token = authorization.strip().removeprefix("Bearer ").strip()
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT name, tier, created_at, usage_count FROM users WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Invalid API Key.")
    name, tier, created_str, usage = row
    if tier == "trial" and datetime.utcnow() > datetime.fromisoformat(created_str) + timedelta(days=TRIAL_DAYS):
        cur.close()
        conn.close()
        raise HTTPException(status_code=402, detail="14-day trial expired. Visit /upgrade.")
    new_usage = usage + 1
    cur.execute(f"UPDATE users SET usage_count = {ph} WHERE api_key = {ph}", (new_usage, token))
    conn.commit()
    cur.close()
    conn.close()
    return {"name": name, "tier": tier, "usage_count": new_usage}

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)

@app.post("/start-trial", response_class=HTMLResponse)
async def start_trial(name: str = Form(...), email: str = Form(...)):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT api_key, created_at FROM users WHERE email = {ph}", (email,))
    existing = cur.fetchone()
    if existing:
        api_key, created_at = existing
    else:
        api_key = f"optx_trial_{secrets.token_hex(8)}"
        created_at = datetime.utcnow().isoformat()
        cur.execute(f"INSERT INTO users (api_key, name, email, tier, created_at, usage_count) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})", (api_key, name, email, "trial", created_at, 0))
        conn.commit()
    cur.close()
    conn.close()
    return HTMLResponse(content=f"<body style='background:#0d1117;color:#c9d1d9;font-family:sans-serif;text-align:center;padding:50px'><h2 style='color:#3fb950'>14-Day Trial Active!</h2><p>Your API Key: <b style='color:#58a6ff'>{api_key}</b></p><a href='/docs' style='color:#58a6ff'>Open API Playground</a></body>")

@app.get("/upgrade")
async def upgrade():
    return RedirectResponse(url=LEMON_CHECKOUT_URL, status_code=303)

@app.post("/webhook/lemonsqueezy")
async def webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("X-Signature", "")
    if LEMON_WEBHOOK_SECRET:
        digest = hmac.new(LEMON_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest, sig):
            raise HTTPException(status_code=401, detail="Invalid signature.")
    data = await request.json()
    if data.get("meta", {}).get("event_name") in ["order_created", "subscription_created"]:
        email = data.get("data", {}).get("attributes", {}).get("user_email")
        if email:
            conn, ph = get_db()
            cur = conn.cursor()
            cur.execute(f"UPDATE users SET tier = 'premium' WHERE email = {ph}", (email,))
            conn.commit()
            cur.close()
            conn.close()
    return {"status": "ok"}

@app.post("/v1/route")
async def route_prompt(request: PromptRequest, user: dict = Depends(verify_user)):
    start = time.time()
    verdict = shield.inspect_payload(request.prompt)
    if not verdict.get("safe", True):
        raise HTTPException(status_code=400, detail=f"Blocked: {verdict.get('reason')}")
    provider = request.preferred_model if request.preferred_model != "auto" else ("gemini" if len(request.prompt.split()) < 15 else "openai")
    try:
        if provider == "gemini":
            if not gemini_client:
                raise HTTPException(status_code=503, detail="GEMINI_API_KEY missing.")
            res = gemini_client.models.generate_content(model="gemini-2.5-flash", contents=request.prompt)
            text, model = res.text, "gemini-2.5-flash"
        elif provider == "openai":
            if not openai_client:
                raise HTTPException(status_code=503, detail="OPENAI_API_KEY missing.")
            res = openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": request.prompt}])
            text, model = res.choices[0].message.content, "gpt-4o-mini"
        else:
            raise HTTPException(status_code=400, detail="Invalid model.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
