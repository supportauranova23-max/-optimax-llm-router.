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

app = FastAPI(title="OptiMax Proxy Admin | Cut AI Coding Costs by 74%")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
LEMON_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
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
    return sqlite3.connect("optimax_litellm.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS litellm_keys (api_key TEXT PRIMARY KEY, key_alias TEXT, email TEXT, tier TEXT, created_at TEXT, requests INTEGER DEFAULT 0, spend_usd REAL DEFAULT 0.0, saved_usd REAL DEFAULT 0.0, max_budget_usd REAL DEFAULT 25.0)")
    now = datetime.utcnow().isoformat()
    starters = [
        ("optx_free_trial_user", "default-sandbox-key", "trial@user.com", "trial", now, 0, 0.0, 0.0, 15.0),
        ("optx_live_prod_99x1", "production-coding-bot", "prod@enterprise.io", "enterprise", now, 142, 4.18, 12.10, 500.0)
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
    model: Optional[str] = "auto"

async def verify_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.strip().removeprefix("Bearer ").strip()
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT key_alias, tier, created_at, requests, spend_usd, saved_usd, max_budget_usd FROM litellm_keys WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid Virtual Key.")
    alias, tier, created_str, reqs, spend, saved, budget = row
    if tier == "trial" and datetime.utcnow() > datetime.fromisoformat(created_str) + timedelta(days=14):
        raise HTTPException(status_code=402, detail="14-day trial expired. Visit /upgrade.")
    if spend >= budget:
        raise HTTPException(status_code=402, detail=f"Max Budget Exceeded (${spend}/{budget}).")
    return {"token": token, "alias": alias, "tier": tier, "reqs": reqs, "spend": spend, "saved": saved, "budget": budget}

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

app = FastAPI(title="OptiMax Proxy Admin | Cut AI Coding Costs by 74%")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
LEMON_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
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
    return sqlite3.connect("optimax_litellm.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS litellm_keys (api_key TEXT PRIMARY KEY, key_alias TEXT, email TEXT, tier TEXT, created_at TEXT, requests INTEGER DEFAULT 0, spend_usd REAL DEFAULT 0.0, saved_usd REAL DEFAULT 0.0, max_budget_usd REAL DEFAULT 25.0)")
    now = datetime.utcnow().isoformat()
    starters = [
        ("optx_free_trial_user", "default-sandbox-key", "trial@user.com", "trial", now, 0, 0.0, 0.0, 15.0),
        ("optx_live_prod_99x1", "production-coding-bot", "prod@enterprise.io", "enterprise", now, 142, 4.18, 12.10, 500.0)
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
    model: Optional[str] = "auto"

async def verify_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.strip().removeprefix("Bearer ").strip()
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT key_alias, tier, created_at, requests, spend_usd, saved_usd, max_budget_usd FROM litellm_keys WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid Virtual Key.")
    alias, tier, created_str, reqs, spend, saved, budget = row
    if tier == "trial" and datetime.utcnow() > datetime.fromisoformat(created_str) + timedelta(days=14):
        raise HTTPException(status_code=402, detail="14-day trial expired. Visit /upgrade.")
    if spend >= budget:
        raise HTTPException(status_code=402, detail=f"Max Budget Exceeded (${spend}/{budget}).")
    return {"token": token, "alias": alias, "tier": tier, "reqs": reqs, "spend": spend, "saved": saved, "budget": budget}

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
