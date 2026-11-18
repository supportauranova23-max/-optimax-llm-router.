import time, os, re, json, math, httpx, sqlite3, hmac, hashlib, secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from cognishield_layer import CogniShieldLayer

try:
    import psycopg2
except ImportError:
    psycopg2 = None

app = FastAPI(title="OptiMax v9.0 Edge & Distributed Gateway")

KEYS = {
    "openai": os.environ.get("OPENAI_API_KEY", ""),
    "gemini": os.environ.get("GEMINI_API_KEY", ""),
    "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
    "deepseek": os.environ.get("DEEPSEEK_API_KEY", ""),
    "groq": os.environ.get("GROQ_API_KEY", "")
}
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
LEMON_CHECKOUT_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
LEMON_WEBHOOK_SECRET = os.environ.get("LEMON_WEBHOOK_SECRET", "")
RAW_DB_URL = os.environ.get("DATABASE_URL", "").strip().removeprefix("psql ").strip().strip("'\"")

USE_POSTGRES = bool(RAW_DB_URL.startswith("postgres") and psycopg2)
shield = CogniShieldLayer()
http_pool = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_connections=200, max_keepalive_connections=50))
TRIAL_DAYS = 14
LOCAL_CACHE: Dict[str, str] = {}
LOCAL_LOOPS: Dict[str, List[float]] = {}

# ---> DISTRIBUTED UPSTASH REDIS HELPERS (With Local Fallback)
async def redis_cmd(*args):
    if UPSTASH_URL and UPSTASH_TOKEN:
        try:
            r = await http_pool.post(UPSTASH_URL, headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, json=list(args), timeout=2.0)
            if r.status_code == 200:
                return r.json().get("result")
        except Exception:
            pass
    return None

async def cache_get(key: str) -> Optional[str]:
    val = await redis_cmd("GET", f"cache:{key}")
    return val if val is not None else LOCAL_CACHE.get(key)

async def cache_set(key: str, val: str):
    LOCAL_CACHE[key] = val
    await redis_cmd("SETEX", f"cache:{key}", 86400, val)

async def check_distributed_circuit(token: str, prompt: str):
    p_hash = hashlib.md5(prompt.strip().lower().encode()).hexdigest()
    r_key = f"loop:{token}:{p_hash}"
    count = await redis_cmd("INCR", r_key)
    if count is not None:
        if count == 1:
            await redis_cmd("EXPIRE", r_key, 15)
        if count >= 4:
            raise HTTPException(status_code=429, detail="DISTRIBUTED CIRCUIT BREAKER: Loop detected across edge nodes.")
        return
    now = time.time()
    hits = [t for t in LOCAL_LOOPS.get(r_key, []) if now - t < 15.0]
    if len(hits) >= 3:
        raise HTTPException(status_code=429, detail="CIRCUIT BREAKER: Loop detected (4x in 15s).")
    hits.append(now)
    LOCAL_LOOPS[r_key] = hits

def get_db():
    if USE_POSTGRES:
        try:
            return psycopg2.connect(RAW_DB_URL), "%s"
        except Exception:
            pass
    return sqlite3.connect("optimax_v9.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users_v9 (api_key TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, tier TEXT, created_at TEXT, usage_count INTEGER DEFAULT 0, saved_usd REAL DEFAULT 0.0, budget_limit_usd REAL DEFAULT 25.0)")
    now_iso = datetime.utcnow().isoformat()
    starters = [
        ("optx_live_dev_78x92", "Alpha Edge Enterprise", "dev@alphatech.io", "enterprise", now_iso, 250, 2140.50, 5000.0),
        ("optx_free_trial_user", "Developer Sandbox", "trial@user.com", "trial", now_iso, 0, 0.0, 15.0)
    ]
    for u in starters:
        sql = "INSERT INTO users_v9 VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING" if ph == "%s" else "INSERT OR IGNORE INTO users_v9 VALUES (?,?,?,?,?,?,?,?)"
        cur.execute(sql, u)
    conn.commit()
    cur.close()
    conn.close()

init_db()

class PromptRequest(BaseModel):
    prompt: str
    preferred_model: Optional[str] = "auto"
    stream: Optional[bool] = False

class OpenAIChatRequest(BaseModel):
    model: Optional[str] = "auto"
    messages: List[Dict[str, Any]]
    stream: Optional[bool] = False

def deep_scan_and_redact(text: str):
    if re.search(r"(sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z-_]{35})", text):
        raise HTTPException(status_code=400, detail="GOVERNANCE BLOCK: Secret API Key Leak Prevented.")
    verdict = shield.inspect_payload(text)
    if not verdict.get("safe", True):
        raise HTTPException(status_code=400, detail=f"COGNISHIELD BLOCK: {verdict.get('reason')}")
    vault = {}
    for label, pat in {"EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "CARD": r"\b(?:\d[ -]*?){13,16}\b"}.items():
        for i, m in enumerate(re.findall(pat, text)):
            tok = f"[{label}_{i}]"
            vault[tok] = m
            text = text.replace(m, tok, 1)
    return " ".join(text.split()), vault

def restore_pii(text: str, vault: Dict[str, str]):
    for k, v in vault.items():
        text = text.replace(k, v)
    return text

# ---> TRUE UPSTREAM SSE STREAMING GENERATOR
async def true_upstream_stream(prompt: str, pref: str, vault: Dict[str, str], cache_key: str):
    cached = await cache_get(cache_key)
    if cached:
        restored = restore_pii(cached, vault)
        for w in restored.split(" "):
            yield f"data: {json.dumps({'choices': [{'delta': {'content': w + ' '}}], 'optimax_cache': True})}\n\n"
        yield "data: [DONE]\n\n"
        return

    primary = pref if pref in ["openai", "gemini", "groq", "deepseek"] else ("gemini" if len(prompt.split()) < 20 else "openai")
    full_collected = []

    if primary == "gemini" and KEYS["gemini"]:
        url = f"https://googleapis.com{KEYS['gemini']}"
        async with http_pool.stream("POST", url, json={"contents": [{"parts": [{"text": prompt}]}]}) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    try:
                        chunk_json = json.loads(line[6:])
                        txt = chunk_json["candidates"]["content"]["parts"]["text"]
                        full_collected.append(txt)
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': restore_pii(txt, vault)}}], 'model': 'gemini-2.5-flash'})}\n\n"
                    except Exception:
                        continue
    elif KEYS["openai"]:
        url = "https://openai.com"
        async with http_pool.stream("POST", url, headers={"Authorization": f"Bearer {KEYS['openai']}"}, json={"model": "gpt-4o-mini", "stream": True, "messages": [{"role": "user", "content": prompt}]}) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        chunk_json = json.loads(line[6:])
                        txt = chunk_json["choices"]["delta"].get("content", "")
                        if txt:
                            full_collected.append(txt)
                            yield f"data: {json.dumps({'choices': [{'delta': {'content': restore_pii(txt, vault)}}], 'model': 'gpt-4o-mini'})}\n\n"
                    except Exception:
                        continue

    if full_collected:
        await cache_set(cache_key, "".join(full_collected))
    yield "data: [DONE]\n\n"

async def verify_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.strip().removeprefix("Bearer ").strip()
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT name, tier, created_at, usage_count, saved_usd FROM users_v9 WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Invalid API Key.")
    name, tier, created_str, usage, saved = row
    if tier == "trial" and datetime.utcnow() > datetime.fromisoformat(created_str) + timedelta(days=TRIAL_DAYS):
        cur.close()
        conn.close()
        raise HTTPException(status_code=402, detail="14-day trial expired. Visit /upgrade.")
    cur.close()
    conn.close()
    return {"token": token, "name": name, "tier": tier, "usage": usage, "saved": saved}

