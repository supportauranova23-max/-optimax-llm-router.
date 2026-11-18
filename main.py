import time, os, re, json, httpx, sqlite3, hmac, hashlib, secrets
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

app = FastAPI(title="OptiMax Edge Gateway")

KEYS = {
    "openai": os.environ.get("OPENAI_API_KEY", ""),
    "gemini": os.environ.get("GEMINI_API_KEY", ""),
}
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
LEMON_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
LEMON_SECRET = os.environ.get("LEMON_WEBHOOK_SECRET", "")
RAW_DB = os.environ.get("DATABASE_URL", "").strip().removeprefix("psql ").strip().strip("'\"")

USE_PG = bool(RAW_DB.startswith("postgres") and psycopg2)
shield = CogniShieldLayer()
http_pool = httpx.AsyncClient(timeout=25.0)
LOCAL_CACHE: Dict[str, str] = {}
LOCAL_LOOPS: Dict[str, List[float]] = {}

def get_db():
    if USE_PG:
        try:
            return psycopg2.connect(RAW_DB), "%s"
        except Exception:
            pass
    return sqlite3.connect("optimax_live.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users_live (api_key TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, tier TEXT, created_at TEXT, usage_count INTEGER DEFAULT 0, saved_usd REAL DEFAULT 0.0)")
    now = datetime.utcnow().isoformat()
    sql = "INSERT INTO users_live VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING" if ph == "%s" else "INSERT OR IGNORE INTO users_live VALUES (?,?,?,?,?,?,?)"
    cur.execute(sql, ("optx_free_trial_user", "Sandbox User", "trial@user.com", "trial", now, 0, 0.0))
    conn.commit()
    cur.close()
    conn.close()

init_db()

class PromptRequest(BaseModel):
    prompt: str
    preferred_model: Optional[str] = "auto"
    stream: Optional[bool] = False

async def redis_cmd(*args):
    if UPSTASH_URL and UPSTASH_TOKEN:
        try:
            r = await http_pool.post(UPSTASH_URL, headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, json=list(args), timeout=2.0)
            if r.status_code == 200:
                return r.json().get("result")
        except Exception:
            pass
    return None

async def check_loop(token: str, prompt: str):
    h = hashlib.md5(prompt.strip().lower().encode()).hexdigest()
    key = f"loop:{token}:{h}"
    cnt = await redis_cmd("INCR", key)
    if cnt is not None:
        if cnt == 1:
            await redis_cmd("EXPIRE", key, 15)
        if cnt >= 4:
            raise HTTPException(status_code=429, detail="Circuit Breaker: Loop detected.")
        return
    now = time.time()
    hits = [t for t in LOCAL_LOOPS.get(key, []) if now - t < 15.0]
    if len(hits) >= 3:
        raise HTTPException(status_code=429, detail="Circuit Breaker: Loop detected (4x in 15s).")
    hits.append(now)
    LOCAL_LOOPS[key] = hits

def scan_and_redact(text: str):
    if re.search(r"(sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z-_]{35})", text):
        raise HTTPException(status_code=400, detail="Blocked: Secret API key leak.")
    verdict = shield.inspect_payload(text)
    if not verdict.get("safe", True):
        raise HTTPException(status_code=400, detail=f"CogniShield Block: {verdict.get('reason')}")
    vault = {}
    for i, m in enumerate(re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)):
        tok = f"[EMAIL_{i}]"
        vault[tok] = m
        text = text.replace(m, tok, 1)
    return " ".join(text.split()), vault

def restore(text: str, vault: Dict[str, str]):
    for k, v in vault.items():
        text = text.replace(k, v)
    return text

async def upstream_stream(prompt: str, pref: str, vault: Dict[str, str], c_key: str):
    cached = await redis_cmd("GET", f"cache:{c_key}") or LOCAL_CACHE.get(c_key)
    if cached:
        for w in restore(cached, vault).split(" "):
            yield f"data: {json.dumps({'choices': [{'delta': {'content': w + ' '}}]})}\n\n"
        yield "data: [DONE]\n\n"
        return
    primary = pref if pref in ["openai", "gemini"] else ("gemini" if len(prompt.split()) < 20 else "openai")
    collected = []
    if primary == "gemini" and KEYS["gemini"]:
        url = f"https://googleapis.com{KEYS['gemini']}"
        async with http_pool.stream("POST", url, json={"contents": [{"parts": [{"text": prompt}]}]}) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    try:
                        txt = json.loads(line[6:])["candidates"][0]["content"]["parts"][0]["text"]
                        collected.append(txt)
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': restore(txt, vault)}}]})}\n\n"
                    except Exception:
                        pass
    elif KEYS["openai"]:
        url = "https://openai.com"
        async with http_pool.stream("POST", url, headers={"Authorization": f"Bearer {KEYS['openai']}"}, json={"model": "gpt-4o-mini", "stream": True, "messages": [{"role": "user", "content": prompt}]}) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        txt = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                        if txt:
                            collected.append(txt)
                            yield f"data: {json.dumps({'choices': [{'delta': {'content': restore(txt, vault)}}]})}\n\n"
                    except Exception:
                        pass
    if collected:
        full_txt = "".join(collected)
        LOCAL_CACHE[c_key] = full_txt
        await redis_cmd("SETEX", f"cache:{c_key}", 86400, full_txt)
    yield "data: [DONE]\n\n"

async def verify_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.strip().removeprefix("Bearer ").strip()
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT name, tier, created_at, usage_count, saved_usd FROM users_live WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid API Key.")
    name, tier, created_str, usage, saved = row
    if tier == "trial" and datetime.utcnow() > datetime.fromisoformat(created_str) + timedelta(days=14):
        raise HTTPException(status_code=402, detail="14-day trial expired. Visit /upgrade.")
    return {"token": token, "name": name, "tier": tier, "usage": usage, "saved": saved}

HTML_PAGE = (
    "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>OptiMax Edge AI Gateway</title><style>"
    "body{font-family:sans-serif;background:#0d1117;color:#c9d1d9;padding:20px}"
    ".box{max-width:850px;margin:auto;background:#161b22;padding:25px;border-radius:10px;border:1px solid #30363d}"
    "h1{color:#58a6ff;margin-top:0}.card{background:#21262d;padding:18px;border-radius:8px;margin-top:15px}"
    "input,select,textarea{padding:10px;border-radius:6px;border:1px solid #30363d;background:#0d1117;color:#fff;margin-bottom:8px}"
    ".btn{background:#1f6feb;color:#fff;padding:10px 18px;border:none;border-radius:6px;font-weight:bold;cursor:pointer;text-decoration:none;display:inline-block}"
    ".green{background:#238636}pre{background:#0d1117;padding:14px;border-radius:6px;color:#3fb950;white-space:pre-wrap;min-height:60px}"
    "</style></head><body><div class='box'><h1>OptiMax Edge AI Gateway</h1>"
    "<div class='card'><h3>1. Start 14-Day Free Trial</h3><form action='/start-trial' method='post'>"
    "<input name='name' placeholder='Name' required> <input name='email' type='email' placeholder='Email' required> "
    "<button class='btn'>Get Trial Key</button></form></div>"
    "<div class='card'><h3>2. Live Streaming Playground</h3>"
    "<input id='key' value='optx_free_trial_user' style='width:55%'> "
    "<select id='mod' style='width:38%'><option value='auto'>Auto Route</option><option value='gemini'>Gemini 2.5 Flash</option><option value='openai'>GPT-4o Mini</option></select>"
    "<textarea id='prm' rows='2' placeholder='Ask anything...' style='width:96%'></textarea>"
    "<button onclick='go()' class='btn'>Stream Live Response</button><pre id='out'>Ready...</pre></div>"
    "<div class='card' style='text-align:center'><a href='/upgrade' class='btn green'>Upgrade ($49/mo)</a></div></div>"
    "<script>async function go(){const out=document.getElementById('out');out.textContent='';"
    "const r=await fetch('/v1/route',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+document.getElementById('key').value},"
    "body:JSON.stringify({prompt:document.getElementById('prm').value,preferred_model:document.getElementById('mod').value,stream:true})});"
    "if(!r.ok){out.textContent=await r.text();return}const rd=r.body.getReader();const dc=new TextDecoder();let b='';"
    "while(true){const{done,value}=await rd.read();if(done)break;b+=dc.decode(value,{stream:true});const ls=b.split('\\n\\n');b=ls.pop();"
    "for(const l of ls){if(l.startsWith('data: ')&&l!=='data: [DONE]'){try{out.textContent+=JSON.parse(l.slice(6)).choices[0].delta.content||''}catch(e){}}}}}</script></body></html>"
)

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(content=HTML_PAGE)

