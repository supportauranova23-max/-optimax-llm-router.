import time, os, re, json, asyncio, httpx, sqlite3, hashlib, secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict
from cognishield_layer import CogniShieldLayer
from edge_gateway import check_device_rate_limit, get_edge_cache, set_edge_cache, ROGUE_LOOPS_BLOCKED

try:
    import psycopg2
except ImportError:
    psycopg2 = None

app = FastAPI(title="OptiMax Quantum Enterprise & Edge Gateway")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LEMON_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
RAW_DB = os.environ.get("DATABASE_URL", "").strip().removeprefix("psql ").strip().strip("'\"")

USE_PG = bool(RAW_DB.startswith("postgres") and psycopg2)
shield = CogniShieldLayer()
http = httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=5.0), limits=httpx.Limits(max_keepalive_connections=50, max_connections=200))

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
    cur.execute("CREATE TABLE IF NOT EXISTS litellm_keys (api_key TEXT PRIMARY KEY, key_alias TEXT, email TEXT, tier TEXT, created_at TEXT, requests INTEGER DEFAULT 0, spend_usd REAL DEFAULT 0.0, saved_usd REAL DEFAULT 0.0, max_budget_usd REAL DEFAULT 25.0)")
    cur.execute("CREATE TABLE IF NOT EXISTS edge_meta_logs (id TEXT PRIMARY KEY, api_key TEXT, device_id TEXT, reason TEXT, model TEXT, tokens INTEGER, latency_ms REAL, pii_count INTEGER, saved_usd REAL, cache_hit INTEGER DEFAULT 0)")
    now = datetime.utcnow().isoformat()
    starters = [
        ("optx_free_trial_user", "default-sandbox-key", "trial@user.com", "trial", now, 0, 0.0, 0.0, 15.0),
        ("optx_live_prod_99x1", "production-iot-fleet", "prod@enterprise.io", "enterprise", now, 142, 4.18, 12.10, 5000.0)
    ]
    for s in starters:
        sql = "INSERT INTO litellm_keys VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING" if ph == "%s" else "INSERT OR IGNORE INTO litellm_keys VALUES (?,?,?,?,?,?,?,?,?)"
        cur.execute(sql, s)
    conn.commit()
    cur.close()
    conn.close()

init_db()

class PromptReq(BaseModel):
    prompt: str
    preset: Optional[str] = "max_savings"

class EdgeChatReq(BaseModel):
    device_id: str
    prompt: str
    max_tokens: Optional[int] = 100

def pii_redact(text: str):
    vault = {}
    for label, pat in {"SECRET": r"(?:sk-|AIza|gsk_|optx_)[a-zA-Z0-9_-]{16,}", "EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "CARD": r"\b(?:\d[ -]*?){13,16}\b"}.items():
        for i, m in enumerate(re.findall(pat, text)):
            tok = f"[{label}_{i}]"
            vault[tok] = m
            text = text.replace(m, tok, 1)
    return " ".join(text.split()), vault

def pii_restore(text: str, vault: Dict[str, str]):
    for k, v in vault.items():
        text = text.replace(k, v)
    return text

def _bg_log_meta(api_key: str, dev_id: Optional[str], reason: str, model: str, toks: int, lat: float, pii: int, saved: float, spend: float, cache_hit: bool):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE litellm_keys SET requests = requests + 1, spend_usd = spend_usd + {ph}, saved_usd = saved_usd + {ph} WHERE api_key = {ph}", (spend, saved, api_key))
    cur.execute(f"INSERT INTO edge_meta_logs VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})", (secrets.token_hex(6), api_key, dev_id, reason, model, toks, lat, pii, saved, 1 if cache_hit else 0))
    conn.commit()
    cur.close()
    conn.close()

async def log_meta_async(api_key: str, dev_id: Optional[str], reason: str, model: str, toks: int, lat: float, pii: int, saved: float, spend: float, cache_hit: bool):
    await asyncio.to_thread(_bg_log_meta, api_key, dev_id, reason, model, toks, lat, pii, saved, spend, cache_hit)

async def verify_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.strip().removeprefix("Bearer ").strip()
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT key_alias, email, tier, created_at, requests, spend_usd, saved_usd, max_budget_usd FROM litellm_keys WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid Virtual Key.")
    alias, email, tier, created_str, reqs, spend, saved, budget = row
    if tier == "trial" and datetime.utcnow() > datetime.fromisoformat(created_str) + timedelta(days=14):
        raise HTTPException(status_code=402, detail="14-day trial expired. Visit /upgrade.")
    if float(spend) >= float(budget):
        raise HTTPException(status_code=402, detail=f"Max Budget Exceeded (${spend}/{budget}).")
    return {"token": token, "alias": alias, "email": email, "tier": tier, "reqs": int(reqs), "spend": float(spend), "saved": float(saved), "budget": float(budget)}

async def fast_llm_call(clean_p: str, max_tokens: int = 400):
    if GEMINI_KEY:
        r = await http.post(f"https://googleapis.com{GEMINI_KEY}", json={"contents": [{"parts": [{"text": clean_p}]}], "generationConfig": {"maxOutputTokens": max_tokens}})
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"], "google/gemini-2.5-flash"
    if OPENAI_KEY:
        r = await http.post("https://openai.com", headers={"Authorization": f"Bearer {OPENAI_KEY}"}, json={"model": "gpt-4o-mini", "max_tokens": max_tokens, "messages": [{"role": "user", "content": clean_p}]})
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"], "openai/gpt-4o-mini"
    if OPENROUTER_KEY:
        r = await http.post("https://openrouter.ai", headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, json={"model": "meta-llama/llama-3.3-70b-instruct:free", "max_tokens": max_tokens, "messages": [{"role": "user", "content": clean_p}]})
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"], "meta-llama/llama-3.3-70b:free"
    raise HTTPException(status_code=502, detail="Configure GEMINI_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY in Render.")

@app.get("/", response_class=HTMLResponse)
async def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/upgrade")
async def upgrade():
    return RedirectResponse(url=LEMON_URL, status_code=303)

@app.post("/webhook/lemonsqueezy")
async def webhook(request: Request):
    data = await request.json()
    if data.get("meta", {}).get("event_name") in ["order_created", "subscription_created"]:
        email = data.get("data", {}).get("attributes", {}).get("user_email")
        if email:
            conn, ph = get_db()
            cur = conn.cursor()
            cur.execute(f"UPDATE litellm_keys SET tier = 'enterprise', max_budget_usd = 5000.0 WHERE email = {ph}", (email,))
            conn.commit()
            cur.close()
            conn.close()
    return {"status": "ok"}

@app.post("/start-trial", response_class=HTMLResponse)
async def start_trial(name: str = Form(...), email: str = Form(...)):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT api_key FROM litellm_keys WHERE email = {ph}", (email,))
    row = cur.fetchone()
    if row:
        (key,) = row
    else:
        key = f"optx_trial_{secrets.token_hex(8)}"
        cur.execute(f"INSERT INTO litellm_keys VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})", (key, name, email, "trial", datetime.utcnow().isoformat(), 0, 0.0, 0.0, 25.0))
        conn.commit()
    cur.close()
    conn.close()
    return HTMLResponse(content=f"<body style='background:#030712;color:#fff;font-family:sans-serif;text-align:center;padding:60px'><h2 style='color:#00f5d4'>14-Day Trial Key Ready!</h2><p>Copy Key: <b style='color:#38bdf8'>{key}</b></p><a href='/' style='color:#38bdf8'>← Back to Dashboard</a></body>")

@app.get("/api/dashboard/me")
async def dashboard_me(user: dict = Depends(verify_user)):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(pii_count),0) FROM edge_meta_logs WHERE api_key = {ph}", (user["token"],))
    toks, pii = cur.fetchone()
    cur.execute(f"SELECT reason, model, tokens, latency_ms, device_id, saved_usd, cache_hit FROM edge_meta_logs WHERE api_key = {ph} ORDER BY rowid DESC LIMIT 8", (user["token"],))
    logs = [{"reason": rsn, "model": mdl, "tokens": tk, "latency": lat, "device_id": dev or "IDE", "saved": round(float(sv), 4), "cache_hit": bool(ch)} for rsn, mdl, tk, lat, dev, sv, ch in cur.fetchall()]
    cur.close()
    conn.close()
    return {"view": "personal", "alias": user["alias"], "tier": user["tier"], "saved_usd": round(user["saved"], 2), "tokens_routed": int(toks), "pii_masked": int(pii), "logs": logs}

@app.get("/api/dashboard/org")
async def dashboard_org(user: dict = Depends(verify_user)):
    if user["tier"] != "enterprise":
        return JSONResponse(status_code=403, content={"upgrade_required": True, "current_tier": user["tier"]})
    conn, _ = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(saved_usd),0) FROM litellm_keys")
    (org_saved,) = cur.fetchone()
    cur.execute("SELECT COUNT(DISTINCT device_id), COALESCE(AVG(cache_hit),0) FROM edge_meta_logs WHERE device_id IS NOT NULL")
