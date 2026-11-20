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
LEMON_PRO = os.environ.get("LEMON_PRO_URL", "https://lemonsqueezy.com")
LEMON_SCALE = os.environ.get("LEMON_SCALE_URL", "https://lemonsqueezy.com")
LEMON_ENT = os.environ.get("LEMON_ENTERPRISE_URL", "https://lemonsqueezy.com")
RAW_DB = os.environ.get("DATABASE_URL", "").strip().removeprefix("psql ").strip().strip("'\"")

USE_PG = bool(RAW_DB.startswith("postgres") and psycopg2)
shield = CogniShieldLayer()
http = httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=5.0), limits=httpx.Limits(max_keepalive_connections=50, max_connections=200))
CACHE: Dict[str, str] = {}

def get_db():
    if USE_PG:
        try:
            return psycopg2.connect(RAW_DB), "%s"
        except Exception:
            pass
    return sqlite3.connect("optimax_rbac_edge.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, name TEXT, plan_tier TEXT, lemon_squeezy_sub_id TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS workspace_members (workspace_id TEXT, user_id TEXT, role TEXT, PRIMARY KEY (workspace_id, user_id))")
    cur.execute("CREATE TABLE IF NOT EXISTS api_keys (api_key TEXT PRIMARY KEY, workspace_id TEXT, user_id TEXT, key_type TEXT, rate_limit_rpm INTEGER DEFAULT 60, monthly_budget_limit REAL DEFAULT 500.0, current_spend REAL DEFAULT 0.0, created_at TEXT)")
    # Zero-Payload Logging: Strictly metadata—no prompt or completion columns
    cur.execute("CREATE TABLE IF NOT EXISTS request_logs (id TEXT PRIMARY KEY, workspace_id TEXT, user_id TEXT, device_id TEXT, reason TEXT, model TEXT, tokens INTEGER, latency_ms REAL, pii_count INTEGER, saved_usd REAL, cache_hit INTEGER DEFAULT 0)")
    now = datetime.utcnow().isoformat()
    if ph == "%s":
        cur.execute("INSERT INTO workspaces VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING", ("ws_solo_01", "Solo Dev Workspace", "pro_49", ""))
        cur.execute("INSERT INTO workspaces VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING", ("ws_team_99", "Acme Robotics Fleet", "team_499", "sub_ls_9981"))
        cur.execute("INSERT INTO workspace_members VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", ("ws_solo_01", "dev@solo.io", "owner"))
        cur.execute("INSERT INTO workspace_members VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", ("ws_team_99", "admin@acme.io", "owner"))
        cur.execute("INSERT INTO api_keys VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING", ("optx_free_trial_user", "ws_solo_01", "dev@solo.io", "ide", 60, 500.0, 4.10, now))
        cur.execute("INSERT INTO api_keys VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING", ("optx_team_iot_fleet_01", "ws_team_99", "admin@acme.io", "iot_fleet", 120, 5000.0, 18.50, now))
    else:
        cur.execute("INSERT OR IGNORE INTO workspaces VALUES (?,?,?,?)", ("ws_solo_01", "Solo Dev Workspace", "pro_49", ""))
        cur.execute("INSERT OR IGNORE INTO workspaces VALUES (?,?,?,?)", ("ws_team_99", "Acme Robotics Fleet", "team_499", "sub_ls_9981"))
        cur.execute("INSERT OR IGNORE INTO workspace_members VALUES (?,?,?)", ("ws_solo_01", "dev@solo.io", "owner"))
        cur.execute("INSERT OR IGNORE INTO workspace_members VALUES (?,?,?)", ("ws_team_99", "admin@acme.io", "owner"))
        cur.execute("INSERT OR IGNORE INTO api_keys VALUES (?,?,?,?,?,?,?,?)", ("optx_free_trial_user", "ws_solo_01", "dev@solo.io", "ide", 60, 500.0, 4.10, now))
        cur.execute("INSERT OR IGNORE INTO api_keys VALUES (?,?,?,?,?,?,?,?)", ("optx_team_iot_fleet_01", "ws_team_99", "admin@acme.io", "iot_fleet", 120, 5000.0, 18.50, now))
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

def _bg_log_meta(ws_id: str, uid: str, dev_id: Optional[str], reason: str, model: str, toks: int, lat: float, pii: int, saved: float, spend: float, cache_hit: bool, api_key: str):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE api_keys SET current_spend = current_spend + {ph} WHERE api_key = {ph}", (spend, api_key))
    cur.execute(f"INSERT INTO request_logs VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})", (secrets.token_hex(6), ws_id, uid, dev_id, reason, model, toks, lat, pii, saved, 1 if cache_hit else 0))
    conn.commit()
    cur.close()
    conn.close()

async def log_meta_async(ws_id: str, uid: str, dev_id: Optional[str], reason: str, model: str, toks: int, lat: float, pii: int, saved: float, spend: float, cache_hit: bool, api_key: str):
    await asyncio.to_thread(_bg_log_meta, ws_id, uid, dev_id, reason, model, toks, lat, pii, saved, spend, cache_hit, api_key)

async def get_auth_context(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.strip().removeprefix("Bearer ").strip()
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT k.workspace_id, k.user_id, k.key_type, k.rate_limit_rpm, k.monthly_budget_limit, k.current_spend,
               w.name, w.plan_tier, COALESCE(m.role, 'developer')
        FROM api_keys k
        JOIN workspaces w ON k.workspace_id = w.id
        LEFT JOIN workspace_members m ON m.workspace_id = k.workspace_id AND m.user_id = k.user_id
        WHERE k.api_key = {ph}
    """, (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid Virtual API Key.")
    ws_id, uid, ktype, rpm, budget, spend, ws_name, plan, role = row
    if float(spend) >= float(budget):
        raise HTTPException(status_code=402, detail="Monthly workspace budget limit reached.")
    return {"token": token, "workspace_id": ws_id, "user_id": uid, "key_type": ktype, "rpm": int(rpm), "ws_name": ws_name, "plan_tier": plan, "role": role}

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
    for fname in os.listdir("."):
        if fname.endswith(".html"):
            with open(fname, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>No .html file found</h1>")

@app.get("/api/dashboard/me")
async def dashboard_me(ctx: dict = Depends(get_auth_context)):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT COALESCE(SUM(saved_usd),0), COALESCE(SUM(tokens),0), COALESCE(SUM(pii_count),0) FROM request_logs WHERE user_id = {ph}", (ctx["user_id"],))
    saved, toks, pii = cur.fetchone()
    cur.execute(f"SELECT api_key, key_type, rate_limit_rpm, current_spend, monthly_budget_limit FROM api_keys WHERE user_id = {ph}", (ctx["user_id"],))
    keys = [{"key": k[:14] + "...", "full_key": k, "type": t, "rpm": r, "spend": float(s), "budget": float(b)} for k, t, r, s, b in cur.fetchall()]
    cur.execute(f"SELECT reason, model, tokens, latency_ms, device_id, saved_usd, cache_hit FROM request_logs WHERE user_id = {ph} ORDER BY rowid DESC LIMIT 8", (ctx["user_id"],))
