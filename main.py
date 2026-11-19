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

app = FastAPI(title="OptiMax AI Gateway")

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
    return sqlite3.connect("optimax.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (api_key TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, tier TEXT, created_at TEXT, usage_count INTEGER DEFAULT 0, saved_usd REAL DEFAULT 0.0)")
    now = datetime.utcnow().isoformat()
    sql = "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING" if ph == "%s" else "INSERT OR IGNORE INTO users VALUES (?,?,?,?,?,?,?)"
    cur.execute(sql, ("optx_free_trial_user", "Sandbox User", "trial@user.com", "trial", now, 0, 0.0))
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
    last_err = "No AI API keys configured in Render."
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

HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OptiMax AI Gateway</title>
<style>
body{font-family:Segoe UI,sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:20px}
.box{max-width:850px;margin:auto;background:#161b22;padding:25px;border-radius:10px;border:1px solid #30363d}
h1{color:#58a6ff;margin-top:0}
.badge{background:rgba(63,185,80,0.15);color:#3fb950;padding:4px 12px;border-radius:20px;font-size:12px}
.card{background:#21262d;padding:20px;border-radius:8px;border:1px solid #30363d;margin-top:16px}
input,select,textarea{padding:10px;border-radius:6px;border:1px solid #30363d;background:#0d1117;color:#fff;margin-bottom:10px;font-family:inherit}
.btn{background:#1f6feb;color:#fff;padding:10px 20px;border:none;border-radius:6px;font-weight:bold;cursor:pointer;text-decoration:none;display:inline-block}
.green{background:#238636}
pre{background:#0d1117;padding:14px;border-radius:6px;border:1px solid #30363d;color:#3fb950;white-space:pre-wrap;min-height:60px}
</style>
</head>
<body>
<div class="box">
<div style="display:flex;justify-content:space-between;align-items:center">
<h1>OptiMax AI Gateway</h1>
<span class="badge">● Online & Protected</span>
</div>
<div class="card">
<h3>1. Start Your 14-Day Free Trial</h3>
<form action="/start-trial" method="post">
<input name="name" placeholder="Your Name" style="width:35%;margin-right:8px" required>
<input name="email" type="email" placeholder="Work Email" style="width:35%;margin-right:8px" required>
<button type="submit" class="btn">Get Trial Key</button>
</form>
</div>
<div class="card">
<h3>2. Dark-Mode AI Playground</h3>
<input id="key" value="optx_free_trial_user" placeholder="Paste API Key" style="width:55%;margin-right:8px">
<select id="mod" style="width:38%">
<option value="auto">Smart Auto-Route</option>
<option value="gemini">Gemini 2.5 Flash</option>
<option value="openai">GPT-4o Mini</option>
</select>
<textarea id="prm" rows="3" placeholder="Ask anything to test your AI router..." style="width:96%"></textarea>
<button onclick="runAI()" class="btn">Send Live Prompt</button>
<pre id="out">Output will appear here...</pre>
</div>
<div class="card" style="text-align:center">
<h3>3. Unlimited Enterprise Access</h3>
<a href="/upgrade" class="btn green">Upgrade Account ($49/mo)</a>
</div>
</div>
<script>
async function runAI(){
  const out=document.getElementById('out');
  out.style.color='#58a6ff';
  out.textContent='Routing through CogniShield...';
  try{
    const r=await fetch('/v1/route',{
      method:'POST',
      headers:{'Content-Type':'application/json','Authorization':'Bearer '+document.getElementById('key').value.trim()},
      body:JSON.stringify({prompt:document.getElementById('prm').value,model:document.getElementById('mod').value})
    });
    const d=await r.json();
    out.style.color=r.ok?'#3fb950':'#f85149';
    out.textContent=JSON.stringify(d,null,2);
  }catch(e){
    out.style.color='#f85149';
    out.textContent=e.toString();
  }
}
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(content=HTML_PAGE)

@app.post("/start-trial", response_class=HTMLResponse)
async def start_trial(name: str = Form(...), email: str = Form(...)):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT api_key FROM users WHERE email = {ph}", (email,))
    row = cur.fetchone()
    if row:
        key = row[0]
    else:
        key = f"optx_trial_{secrets.token_hex(8)}"
        cur.execute(f"INSERT INTO users VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})", (key, name, email, "trial", datetime.utcnow().isoformat(), 0, 0.0))
        conn.commit()
    cur.close()
    conn.close()
    return HTMLResponse(content=f"<body style='background:#0d1117;color:#fff;font-family:sans-serif;text-align:center;padding:50px'><h2 style='color:#3fb950'>14-Day Trial Active!</h2><p>Your API Key: <b style='color:#58a6ff'>{key}</b></p><a href='/' style='color:#58a6ff'>Back to Playground</a></body>")

@app.get("/upgrade")
async def upgrade():
    return RedirectResponse(url=LEMON_URL, status_code=303)

@app.post("/webhook/lemonsqueezy")
async def webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("X-Signature", "")
    if LEMON_SECRET:
        digest = hmac.new(LEMON_SECRET.encode(), payload, hashlib.sha256).hexdigest()
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
async def route(req: PromptReq, user: dict = Depends(verify_user)):
    t0 = time.perf_counter()
    verdict = shield.inspect_payload(req.prompt)
    if not verdict.get("safe", True):
        raise HTTPException(status_code=400, detail=f"Blocked by CogniShield: {verdict.get('reason')}")
    ans, used_model, cached = await route_ai(req.prompt, req.model)
    lat = round((time.perf_counter() - t0) * 1000, 2)
    saved = round(user["saved"] + 0.015, 4)
    conn, ph = get_db()
    cur = conn.cursor()
