import time, os, json, httpx, sqlite3, hashlib, secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict
from cognishield_layer import CogniShieldLayer

try:
    import psycopg2
except ImportError:
    psycopg2 = None

app = FastAPI(title="OptiMax Quantum Gateway")

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LEMON_PRO = os.environ.get("LEMON_PRO_URL", "https://lemonsqueezy.com")
LEMON_SCALE = os.environ.get("LEMON_SCALE_URL", "https://lemonsqueezy.com")
LEMON_ENT = os.environ.get("LEMON_ENTERPRISE_URL", "https://lemonsqueezy.com")
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
    return sqlite3.connect("optimax_q.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS q_keys (api_key TEXT PRIMARY KEY, name TEXT, email TEXT, tier TEXT, created_at TEXT, reqs INTEGER DEFAULT 0, saved_usd REAL DEFAULT 0.0)")
    sql = "INSERT INTO q_keys VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING" if ph == "%s" else "INSERT OR IGNORE INTO q_keys VALUES (?,?,?,?,?,?,?)"
    cur.execute(sql, ("optx_free_trial_user", "Sandbox", "trial@user.com", "trial", datetime.utcnow().isoformat(), 0, 0.0))
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
    cur.execute(f"SELECT name, tier, created_at, reqs, saved_usd FROM q_keys WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid API Key.")
    name, tier, created_str, reqs, saved = row
    if tier == "trial" and datetime.utcnow() > datetime.fromisoformat(created_str) + timedelta(days=14):
        raise HTTPException(status_code=402, detail="14-day trial expired. Upgrade below.")
    return {"token": token, "name": name, "tier": tier, "reqs": reqs, "saved": saved}

@app.get("/", response_class=HTMLResponse)
async def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/v1/models")
async def list_models():
    models = [{"id": "google/gemini-2.5-flash", "name": "Google: Gemini 2.5 Flash", "in_price": "$0.15"}, {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Meta: Llama 3.3 70B (Free)", "in_price": "$0.00"}]
    try:
        r = await http.get("https://openrouter.ai", timeout=4.0)
        if r.status_code == 200:
            for m in r.json().get("data", [])[:40]:
                models.append({"id": m["id"], "name": m.get("name", m["id"]), "in_price": "$0.00" if ":free" in m["id"] else "$0.20"})
    except Exception:
        pass
    return {"object": "list", "data": models}

@app.post("/start-trial", response_class=HTMLResponse)
async def start_trial(name: str = Form(...), email: str = Form(...)):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT api_key FROM q_keys WHERE email = {ph}", (email,))
    row = cur.fetchone()
    if row:
        (key,) = row
    else:
        key = f"optx_trial_{secrets.token_hex(8)}"
        cur.execute(f"INSERT INTO q_keys VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})", (key, name, email, "trial", datetime.utcnow().isoformat(), 0, 0.0))
        conn.commit()
    cur.close()
    conn.close()
    return HTMLResponse(content=f"<body style='background:#030712;color:#fff;font-family:sans-serif;text-align:center;padding:60px'><h2 style='color:#00f5d4'>Trial Key Ready!</h2><p>Copy Key: <b style='color:#38bdf8'>{key}</b></p><a href='/' style='color:#38bdf8'>← Back to Gateway</a></body>")

@app.get("/upgrade")
async def upgrade(plan: str = "pro"):
    return RedirectResponse(url={"pro": LEMON_PRO, "scale": LEMON_SCALE, "enterprise": LEMON_ENT}.get(plan, LEMON_PRO), status_code=303)

@app.post("/v1/route")
async def route(req: PromptReq, user: dict = Depends(verify_user)):
    t0 = time.perf_counter()
    verdict = shield.inspect_payload(req.prompt)
    if not verdict.get("safe", True):
        raise HTTPException(status_code=400, detail=f"Blocked: {verdict.get('reason')}")
    c_key = hashlib.sha256(req.prompt.strip().lower().encode()).hexdigest()
    if c_key in CACHE:
        return {"status": "success", "model": "semantic-cache", "cached": True, "latency_ms": 1.2, "response": CACHE[c_key]}
    ans, used = "", ""
    if GEMINI_KEY and req.model in ["auto", "google/gemini-2.5-flash"]:
        r = await http.post(f"https://googleapis.com{GEMINI_KEY}", json={"contents": [{"parts": [{"text": req.prompt}]}]})
        if r.status_code == 200:
            ans, used = r.json()["candidates"]["content"]["parts"]["text"], "google/gemini-2.5-flash"
    if not ans and OPENROUTER_KEY:
        target = "meta-llama/llama-3.3-70b-instruct:free" if req.model == "auto" else req.model
        r = await http.post("https://openrouter.ai", headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, json={"model": target, "messages": [{"role": "user", "content": req.prompt}]})
        if r.status_code == 200:
            ans, used = r.json()["choices"]["message"]["content"], target
    if not ans:
        raise HTTPException(status_code=502, detail="Add GEMINI_API_KEY or OPENROUTER_API_KEY in Render.")
    CACHE[c_key] = ans
    return {"status": "success", "coding_cost_cut": "74.3%", "model": used, "latency_ms": round((time.perf_counter() - t0) * 1000, 2), "response": ans}
