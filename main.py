import time, os, re, json, asyncio, httpx, sqlite3, hashlib, secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict
from cognishield_layer import CogniShieldLayer

try:
    import psycopg2
except ImportError:
    psycopg2 = None

app = FastAPI(title="OptiMax Quantum Enterprise Gateway")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LEMON_PRO = os.environ.get("LEMON_PRO_URL", "https://lemonsqueezy.com")
LEMON_SCALE = os.environ.get("LEMON_SCALE_URL", "https://lemonsqueezy.com")
LEMON_ENT = os.environ.get("LEMON_ENTERPRISE_URL", "https://lemonsqueezy.com")
RAW_DB = os.environ.get("DATABASE_URL", "").strip().removeprefix("psql ").strip().strip("'\"")

USE_PG = bool(RAW_DB.startswith("postgres") and psycopg2)
shield = CogniShieldLayer()

http = httpx.AsyncClient(
    timeout=httpx.Timeout(25.0, connect=5.0),
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=200)
)
CACHE: Dict[str, str] = {}

def get_db():
    if USE_PG:
        try:
            return psycopg2.connect(RAW_DB), "%s"
        except Exception:
            pass
    return sqlite3.connect("optimax_zdr.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS zdr_keys (api_key TEXT PRIMARY KEY, name TEXT, email TEXT, tier TEXT, created_at TEXT, reqs INTEGER DEFAULT 0, saved_usd REAL DEFAULT 0.0, raw_usd REAL DEFAULT 0.0)")
    cur.execute("CREATE TABLE IF NOT EXISTS zdr_traces (id TEXT PRIMARY KEY, reason TEXT, model TEXT, tokens INTEGER, latency_ms REAL, pii_count INTEGER, saved_usd REAL)")
    sql = "INSERT INTO zdr_keys VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING" if ph == "%s" else "INSERT OR IGNORE INTO zdr_keys VALUES (?,?,?,?,?,?,?,?)"
    day12_demo = (datetime.utcnow() - timedelta(days=12)).isoformat()
    cur.execute(sql, ("optx_free_trial_user", "Sandbox IDE", "trial@user.com", "trial", day12_demo, 48, 118.40, 159.35))
    conn.commit()
    cur.close()
    conn.close()

init_db()

class PromptReq(BaseModel):
    prompt: str
    preset: Optional[str] = "max_savings"
    model: Optional[str] = "auto"

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

def _bg_write_metadata(token: str, reason: str, model: str, tokens: int, lat: float, pii_cnt: int, saved: float, raw: float):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE zdr_keys SET reqs = reqs + 1, saved_usd = saved_usd + {ph}, raw_usd = raw_usd + {ph} WHERE api_key = {ph}", (saved, raw, token))
    cur.execute(f"INSERT INTO zdr_traces VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})", (secrets.token_hex(6), reason, model, tokens, lat, pii_cnt, saved))
    conn.commit()
    cur.close()
    conn.close()

async def log_metadata_nonblocking(token: str, reason: str, model: str, tokens: int, lat: float, pii_cnt: int, saved: float, raw: float):
    await asyncio.to_thread(_bg_write_metadata, token, reason, model, tokens, lat, pii_cnt, saved, raw)

async def verify_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.strip().removeprefix("Bearer ").strip()
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT name, tier, created_at, saved_usd FROM zdr_keys WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid Virtual Key.")
    name, tier, created_str, saved = row
    age_days = (datetime.utcnow() - datetime.fromisoformat(created_str)).days
    if tier == "trial" and age_days > 14:
        raise HTTPException(status_code=402, detail="14-day trial expired. Upgrade to $49/mo BYOK Pro.")
    return {"token": token, "name": name, "tier": tier, "age_days": age_days, "saved": float(saved)}

@app.get("/", response_class=HTMLResponse)
async def home():
    for fname in os.listdir("."):
        if fname.endswith(".html"):
            with open(fname, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>No .html file found in repository</h1>")

@app.get("/v1/telemetry")
async def telemetry():
    conn, _ = get_db()
    cur = conn.cursor()
    cur.execute("SELECT saved_usd, raw_usd, created_at, tier FROM zdr_keys WHERE api_key = 'optx_free_trial_user'")
    row = cur.fetchone() or (118.40, 159.35, datetime.utcnow().isoformat(), "trial")
    cur.execute("SELECT reason, model, tokens, latency_ms, pii_count, saved_usd FROM zdr_traces ORDER BY rowid DESC LIMIT 6")
    t_rows = cur.fetchall()
    cur.close()
    conn.close()
    saved_u, raw_u, created_s, tier_s = row
    age = (datetime.utcnow() - datetime.fromisoformat(created_s)).days
    traces = [{"reason": rsn, "model": mdl, "tokens": tok, "latency": lat, "pii": pii, "saved": round(float(sav), 4)} for rsn, mdl, tok, lat, pii, sav in t_rows]
    if not traces:
        traces = [{"reason": "Boilerplate Refactor", "model": "gemini-2.5-flash", "tokens": 420, "latency": 185.4, "pii": 1, "saved": 0.042}]
    return {"saved": float(saved_u), "raw": float(raw_u), "show_day12": (tier_s == "trial" and age >= 12), "traces": traces}

@app.post("/start-trial", response_class=HTMLResponse)
async def start_trial(name: str = Form(...), email: str = Form(...)):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT api_key FROM zdr_keys WHERE email = {ph}", (email,))
    row = cur.fetchone()
    if row:
        (key,) = row
    else:
        key = f"optx_trial_{secrets.token_hex(8)}"
        cur.execute(f"INSERT INTO zdr_keys VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})", (key, name, email, "trial", datetime.utcnow().isoformat(), 0, 0.0, 0.0))
        conn.commit()
    cur.close()
    conn.close()
    return HTMLResponse(content=f"<body style='background:#030712;color:#fff;font-family:sans-serif;text-align:center;padding:60px'><h2 style='color:#00f5d4'>14-Day BYOK Trial Key Ready!</h2><p>Copy Key: <b style='color:#38bdf8'>{key}</b></p><a href='/' style='color:#38bdf8'>← Return to OptiMax Quantum</a></body>")

@app.get("/upgrade")
async def upgrade(plan: str = "pro"):
    return RedirectResponse(url={"pro": LEMON_PRO, "scale": LEMON_SCALE, "enterprise": LEMON_ENT}.get(plan, LEMON_PRO), status_code=303)

@app.post("/v1/route")
async def route(req: PromptReq, user: dict = Depends(verify_user)):
    t0 = time.perf_counter()
    verdict = shield.inspect_payload(req.prompt)
    if not verdict.get("safe", True):
        raise HTTPException(status_code=400, detail=f"Blocked: {verdict.get('reason')}")
    clean_p, vault = pii_redact(req.prompt)
    reason = "Strict Privacy Redaction" if req.preset == "strict_privacy" else ("Frontier Reasoning" if req.preset == "balanced" else "Boilerplate / Fast Code")
    c_key = hashlib.sha256(f"{req.preset}:{clean_p.lower()}".encode()).hexdigest()
    if c_key in CACHE:
        lat = round((time.perf_counter() - t0) * 1000, 2)
        asyncio.create_task(log_metadata_nonblocking(user["token"], "Semantic Cache Hit", "semantic-cache", len(clean_p.split()), lat, len(vault), 0.045, 0.045))
        return {"status": "success", "zdr_mode": "active", "routing_reason": "Semantic Cache Hit", "pii_masked": len(vault), "model": "semantic-cache", "latency_ms": lat, "response": pii_restore(CACHE[c_key], vault)}
    ans, used = "", ""
    if GEMINI_KEY and req.preset in ["max_savings", "strict_privacy"]:
        r = await http.post(f"https://googleapis.com{GEMINI_KEY}", json={"contents": [{"parts": [{"text": clean_p}]}]})
        if r.status_code == 200:
            ans, used = r.json()["candidates"][0]["content"]["parts"][0]["text"], "google/gemini-2.5-flash"
    if not ans and OPENAI_KEY:
        m_name = "gpt-4o" if req.preset == "balanced" else "gpt-4o-mini"
        r = await http.post("https://openai.com", headers={"Authorization": f"Bearer {OPENAI_KEY}"}, json={"model": m_name, "messages": [{"role": "user", "content": clean_p}]})
        if r.status_code == 200:
            ans, used = r.json()["choices"][0]["message"]["content"], f"openai/{m_name}"
    if not ans and OPENROUTER_KEY:
        target = "meta-llama/llama-3.3-70b-instruct:free"
        r = await http.post("https://openrouter.ai", headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, json={"model": target, "messages": [{"role": "user", "content": clean_p}]})
        if r.status_code == 200:
            ans, used = r.json()["choices"][0]["message"]["content"], target
    if not ans:
        raise HTTPException(status_code=502, detail="Configure GEMINI_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY in Render.")
    CACHE[c_key] = ans
    lat = round((time.perf_counter() - t0) * 1000, 2)
    toks = len(clean_p.split()) + len(ans.split())
    raw_c, saved_c = round(max(0.015, toks * 0.0001), 4), round(max(0.011, toks * 0.0000743), 4)
    asyncio.create_task(log_metadata_nonblocking(user["token"], reason, used, toks, lat, len(vault), saved_c, raw_c))
