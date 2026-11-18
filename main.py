import time, os, psycopg2, hmac, hashlib, secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
from cognishield_layer import CogniShieldLayer
from openai import OpenAI
from google import genai

app = FastAPI(title="OptiMax: Intelligent AI API Cost Management Router")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
LEMON_CHECKOUT_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
LEMON_WEBHOOK_SECRET = os.environ.get("LEMON_WEBHOOK_SECRET", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
shield = CogniShieldLayer()
TRIAL_DAYS = 14

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL:
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (api_key TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, tier TEXT, created_at TEXT, usage_count INTEGER DEFAULT 0)")
    now_iso = datetime.utcnow().isoformat()
    starters = [
        ("optx_live_dev_78x92", "Alpha Tech Ventures", "dev@alphatech.io", "premium", now_iso, 0),
        ("optx_live_scale_11a42", "Nexus AI Core", "admin@nexusai.io", "premium", now_iso, 0),
        ("optx_free_trial_user", "Standard Sandbox User", "trial@user.com", "trial", now_iso, 0)
    ]
    for u in starters:
        cur.execute("INSERT INTO users (api_key, name, email, tier, created_at, usage_count) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (api_key) DO NOTHING", u)
    conn.commit()
    cur.close()
    conn.close()

init_db()

class PromptRequest(BaseModel):
    prompt: str
    preferred_model: Optional[str] = "auto"

async def verify_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    parts = authorization.split(" ")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Invalid header format.")
    token = parts
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name, tier, created_at, usage_count FROM users WHERE api_key = %s", (token,))
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
    cur.execute("UPDATE users SET usage_count = %s WHERE api_key = %s", (new_usage, token))
    conn.commit()
    cur.close()
    conn.close()
    return {"name": name, "tier": tier, "usage_count": new_usage}

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.post("/start-trial", response_class=HTMLResponse)
async def start_trial(name: str = Form(...), email: str = Form(...)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT api_key, created_at FROM users WHERE email = %s", (email,))
    existing = cur.fetchone()
    if existing:
        api_key, created_at = existing
    else:
        api_key = f"optx_trial_{secrets.token_hex(8)}"
        created_at = datetime.utcnow().isoformat()
        cur.execute("INSERT INTO users (api_key, name, email, tier, created_at, usage_count) VALUES (%s, %s, %s, %s, %s, %s)", (api_key, name, email, "trial", created_at, 0))
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
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE users SET tier = 'premium' WHERE email = %s", (email,))
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
            text, model = res.choices.message.content, "gpt-4o-mini"
        else:
            raise HTTPException(status_code=400, detail="Invalid model.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "success", "tenant": user["name"], "tier": user["tier"], "requests_used": user["usage_count"], "latency_ms": round((time.time() - start) * 1000, 2), "model": model, "response": text}
