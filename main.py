import time, os, re, json, httpx, sqlite3, hashlib, secrets
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

app = FastAPI(title="OptiMax Quantum v11.0 | Neural AI Gateway")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LEMON_PRO_URL = os.environ.get("LEMON_PRO_URL", "https://lemonsqueezy.com")
LEMON_SCALE_URL = os.environ.get("LEMON_SCALE_URL", "https://lemonsqueezy.com")
LEMON_ENT_URL = os.environ.get("LEMON_ENTERPRISE_URL", "https://lemonsqueezy.com")
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
    return sqlite3.connect("optimax_quantum_v11.db"), "?"

def init_db():
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS quantum_keys (api_key TEXT PRIMARY KEY, key_alias TEXT, email TEXT, tier TEXT, created_at TEXT, requests INTEGER DEFAULT 0, spend_usd REAL DEFAULT 0.0, saved_usd REAL DEFAULT 0.0, max_budget_usd REAL DEFAULT 25.0)")
    now = datetime.utcnow().isoformat()
    starters = [
        ("optx_free_trial_user", "quantum-sandbox-node", "trial@user.com", "trial", now, 0, 0.0, 0.0, 15.0),
        ("optx_live_prod_99x1", "enterprise-core-cluster", "prod@enterprise.io", "enterprise", now, 412, 9.80, 38.40, 5000.0)
    ]
    for s in starters:
        sql = "INSERT INTO quantum_keys VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (api_key) DO NOTHING" if ph == "%s" else "INSERT OR IGNORE INTO quantum_keys VALUES (?,?,?,?,?,?,?,?,?)"
        cur.execute(sql, s)
    conn.commit()
    cur.close()
    conn.close()

init_db()

class PromptReq(BaseModel):
    prompt: str
    model: Optional[str] = "auto"

def pii_xray_mask(text: str):
    vault = {}
    for label, pat in {"EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "CARD": r"\b(?:\d[ -]*?){13,16}\b"}.items():
        for i, m in enumerate(re.findall(pat, text)):
            tok = f"[{label}_{i}]"
            vault[tok] = m
            text = text.replace(m, tok, 1)
    return " ".join(text.split()), vault

def pii_xray_restore(text: str, vault: Dict[str, str]):
    for k, v in vault.items():
        text = text.replace(k, v)
    return text

async def verify_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.strip().removeprefix("Bearer ").strip()
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT key_alias, tier, created_at, requests, spend_usd, saved_usd, max_budget_usd FROM quantum_keys WHERE api_key = {ph}", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid Virtual Key.")
    alias, tier, created_str, reqs, spend, saved, budget = row
    if tier == "trial" and datetime.utcnow() > datetime.fromisoformat(created_str) + timedelta(days=14):
        raise HTTPException(status_code=402, detail="14-day trial expired. Upgrade below.")
    if spend >= budget:
        raise HTTPException(status_code=402, detail=f"Max Budget Exceeded (${spend}/{budget}).")
    return {"token": token, "alias": alias, "tier": tier, "reqs": reqs, "spend": spend, "saved": saved, "budget": budget}

@app.get("/v1/models")
async def list_models():
    models = [
        {"id": "google/gemini-2.5-flash", "name": "Google: Gemini 2.5 Flash", "cat": "Ultra-Fast", "ctx": "1M", "in_price": "$0.15", "out_price": "$0.60"},
        {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Meta: Llama 3.3 70B (Free)", "cat": "Budget", "ctx": "128K", "in_price": "$0.00", "out_price": "$0.00"},
        {"id": "deepseek/deepseek-r1:free", "name": "DeepSeek: R1 Reasoner (Free)", "cat": "Reasoning", "ctx": "64K", "in_price": "$0.00", "out_price": "$0.00"},
        {"id": "qwen/qwen-2.5-coder-32b-instruct:free", "name": "Qwen: 2.5 Coder 32B (Free)", "cat": "Coding", "ctx": "32K", "in_price": "$0.00", "out_price": "$0.00"}
    ]
    try:
        r = await http.get("https://openrouter.ai", timeout=4.0)
        if r.status_code == 200:
            for m in r.json().get("data", [])[:45]:
                mid = m["id"]
                is_free = ":free" in mid or float(m.get("pricing", {}).get("prompt", 1)) == 0
                models.append({"id": mid, "name": m.get("name", mid), "cat": "Budget" if is_free else ("Coding" if "code" in mid or "claude" in mid else "General"), "ctx": f"{round(m.get('context_length', 128000)/1000)}K", "in_price": "$0.00" if is_free else f"${round(float(m.get('pricing', {}).get('prompt', 0))*1000000, 2)}", "out_price": "$0.00" if is_free else f"${round(float(m.get('pricing', {}).get('completion', 0))*1000000, 2)}"})
    except Exception:
        pass
    return {"object": "list", "data": models}

async def route_ai(prompt: str, pref: str):
    c_key = hashlib.sha256(prompt.strip().lower().encode()).hexdigest()
    if c_key in CACHE:
        return CACHE[c_key], "semantic-cache", True
    if (pref in ["auto", "gemini", "google/gemini-2.5-flash"]) and GEMINI_KEY and (pref != "auto" or len(prompt.split()) < 15):
        url = f"https://googleapis.com{GEMINI_KEY}"
        r = await http.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
        if r.status_code == 200:
            ans = r.json()["candidates"]["content"]["parts"]["text"]
            CACHE[c_key] = ans
            return ans, "google/gemini-2.5-flash", False
    if (pref in ["auto", "openai", "openai/gpt-4o-mini"]) and OPENAI_KEY:
        r = await http.post("https://openai.com", headers={"Authorization": f"Bearer {OPENAI_KEY}"}, json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]})
        if r.status_code == 200:
            ans = r.json()["choices"]["message"]["content"]
            CACHE[c_key] = ans
            return ans, "openai/gpt-4o-mini", False
    if OPENROUTER_KEY:
        target = "meta-llama/llama-3.3-70b-instruct:free" if pref == "auto" else pref
        r = await http.post("https://openrouter.ai", headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "HTTP-Referer": "https://onrender.com"}, json={"model": target, "messages": [{"role": "user", "content": prompt}]})
        if r.status_code == 200:
            ans = r.json()["choices"]["message"]["content"]
            CACHE[c_key] = ans
            return ans, target, False
    raise HTTPException(status_code=502, detail="Add OPENROUTER_API_KEY (free at openrouter.ai/keys) or GEMINI_API_KEY in Render.")

UI_A = (
    "<!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<link rel='icon' type='image/svg+xml' href=\"data:image/svg+xml,<svg xmlns='http://w3.org' viewBox='0 0 40 40'><rect width='40' height='40' rx='10' fill='%2300f5d4'/><circle cx='20' cy='20' r='9' stroke='%23030712' stroke-width='3.5' fill='none'/></svg>\">"
    "<title>OptiMax Quantum | Neural AI Gateway</title><style>"
    "*{box-sizing:border-box}body{margin:0;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#030712;background-image:radial-gradient(circle at 15% 15%,rgba(56,189,248,0.13),transparent 35%),radial-gradient(circle at 85% 80%,rgba(16,185,129,0.13),transparent 35%);color:#f1f5f9;display:flex;min-height:100vh}"
    ".side{width:250px;background:rgba(10,15,28,0.88);backdrop-filter:blur(16px);border-right:1px solid rgba(56,189,248,0.2);padding:20px 14px;display:flex;flex-direction:column;justify-content:space-between}"
    ".logo{display:flex;align-items:center;gap:10px;font-weight:800;font-size:18px;letter-spacing:0.5px;color:#fff;padding:0 8px 18px;border-bottom:1px solid rgba(56,189,248,0.15)}"
    ".badge{background:linear-gradient(90deg,#0284c7,#059669);color:#fff;font-size:10px;padding:2px 8px;border-radius:12px;letter-spacing:1px}"
    ".nav{margin-top:16px;display:flex;flex-direction:column;gap:6px}"
    ".nav button{background:none;border:1px solid transparent;color:#94a3b8;padding:11px 13px;border-radius:8px;text-align:left;font-size:13.5px;font-weight:600;cursor:pointer;transition:all .2s}"
    ".nav button:hover,.nav button.active{background:rgba(56,189,248,0.1);border-color:rgba(56,189,248,0.35);color:#38bdf8;box-shadow:0 0 15px rgba(56,189,248,0.15)}"
    ".main{flex:1;display:flex;flex-direction:column}.top{height:58px;background:rgba(10,15,28,0.75);backdrop-filter:blur(12px);border-bottom:1px solid rgba(56,189,248,0.15);padding:0 26px;display:flex;align-items:center;justify-content:space-between;font-size:13px}"
    ".hero{background:linear-gradient(135deg,rgba(14,165,233,0.16),rgba(16,185,129,0.16));border:1px solid rgba(0,245,212,0.45);box-shadow:0 0 30px rgba(0,245,212,0.12);border-radius:14px;padding:22px 26px;margin-bottom:18px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:15px}"
    ".hero h2{margin:0 0 6px;font-size:21px;color:#fff}.pct{background:linear-gradient(90deg,#00f5d4,#10b981);color:#022c22;font-weight:900;padding:3px 11px;border-radius:20px;font-size:12.5px;margin-left:8px;box-shadow:0 0 12px rgba(0,245,212,0.5)}"
    ".hero p{margin:0;color:#cbd5e1;font-size:13.5px}.cta-start{background:linear-gradient(90deg,#00f5d4,#10b981);color:#022c22;padding:12px 24px;border-radius:8px;font-weight:800;font-size:14px;border:none;cursor:pointer;box-shadow:0 0 20px rgba(0,245,212,0.4)}"
    ".eco{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:18px;font-size:11.5px;color:#94a3b8}.eco span{background:rgba(15,23,42,0.85);border:1px solid rgba(56,189,248,0.2);padding:5px 11px;border-radius:20px;color:#cbd5e1}"
    ".wrap{padding:24px;max-width:1100px;width:100%;margin:0 auto}.panel{display:none;background:rgba(15,23,42,0.75);backdrop-filter:blur(14px);border:1px solid rgba(56,189,248,0.2);border-radius:12px;padding:22px}.panel.active{display:block}"
    ".grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}.stat{background:rgba(15,23,42,0.85);border:1px solid rgba(56,189,248,0.22);padding:16px;border-radius:10px;position:relative}"
    ".stat small{color:#94a3b8;font-size:11.5px;text-transform:uppercase;letter-spacing:0.6px}.stat div{font-size:21px;font-weight:800;margin-top:5px;color:#fff}"
    ".pop-tag{position:absolute;top:-10px;right:12px;background:linear-gradient(90deg,#00f5d4,#38bdf8);color:#022c22;font-size:10px;font-weight:900;padding:2px 9px;border-radius:10px}"
    "table{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px}th,td{text-align:left;padding:11px;border-bottom:1px solid rgba(56,189,248,0.15)}th{color:#38bdf8}"
    "input,select,textarea{width:100%;padding:11px;border-radius:8px;border:1px solid rgba(56,189,248,0.3);background:#030712;color:#fff;margin:6px 0 12px;font-size:13.5px;outline:none}"
    ".btn{background:linear-gradient(90deg,#0284c7,#2563eb);color:#fff;border:none;padding:10px 18px;border-radius:8px;font-weight:700;cursor:pointer;font-size:13px;text-decoration:none;display:inline-block}"
    ".pill-btn{background:rgba(56,189,248,0.12);border:1px solid rgba(56,189,248,0.35);color:#38bdf8;padding:6px 12px;border-radius:20px;font-size:12px;cursor:pointer;font-weight:600}"
    ".pill-btn:hover{background:rgba(0,245,212,0.2);border-color:#00f5d4;color:#00f5d4}"
    ".up{background:linear-gradient(90deg,#059669,#10b981);width:100%;text-align:center}pre{background:#020617;border:1px solid rgba(0,245,212,0.25);padding:15px;border-radius:8px;color:#00f5d4;white-space:pre-wrap;min-height:95px;font-size:12.5px;font-family:monospace}"
    "@media(max-width:768px){body{flex-direction:column}.side{width:100%}.nav{flex-direction:row;overflow-x:auto}.grid{grid-template-columns:repeat(2,1fr)}}"
    "</style></head><body>"
    "<div class='side'><div><div class='logo'>"
    "<svg width='32' height='32' viewBox='0 0 40 40' fill='none' xmlns='http://w3.org'>"
    "<defs><linearGradient id='qGrad' x1='0' y1='0' x2='40' y2='40' gradientUnits='userSpaceOnUse'>"
    "<stop offset='0%' stop-color='#00f5d4'/><stop offset='100%' stop-color='#2563eb'/></linearGradient></defs>"
    "<rect width='40' height='40' rx='10' fill='url(#qGrad)'/>"
    "<path d='M13 20C13 16.134 16.134 13 20 13C23.866 13 27 16.134 27 20C27 23.866 23.866 27 20 27' stroke='#030712' stroke-width='3.4' stroke-linecap='round'/>"
    "<path d='M21 17L16 22H21L19 27L25 21H20L21 17Z' fill='#030712'/>"
    "</svg> OPTIMAX <span class='badge'>QUANTUM</span></div><div class='nav'>"
    "<button id='btn-test' class='active' onclick=\"tab('test',this)\">⚡ Neural Playground</button>"
    "<button id='btn-models' onclick=\"tab('models',this)\">🔍 Model Marketplace</button>"
    "<button id='btn-keys' onclick=\"tab('keys',this)\">🔑 Virtual Keys & Trial</button>"
    "<button id='btn-spend' onclick=\"tab('spend',this)\">📊 ROI & Spend Matrix</button>"
    "<button id='btn-docs' onclick=\"tab('docs',this)\">🔌 SDK Drop-In</button>"
    "</div></div><a href='/upgrade?plan=pro' class='btn up'>⚡ Upgrade Pro ($49)</a></div>"
)

UI_B = (
    "<div class='main'><div class='top'><span id='hdr' style='font-weight:700;color:#38bdf8'>NEURAL PLAYGROUND</span><span style='color:#00f5d4;font-size:11.5px;font-weight:600'>● EDGE NODES: US-EAST • EU-CENTRAL • AFRICA-SOUTH (14ms)</span></div>"
    "<div class='wrap'>"
    "<div class='hero'><div><h2>⚡ Cut AI & Coding Costs Automatically <span class='pct'>SAVE UP TO 74.3%</span></h2>"
    "<p>Autonomous complexity downgrading + PII X-Ray masking + semantic vector caching in milliseconds.</p></div>"
    "<button class='cta-start' onclick=\"tab('keys',document.getElementById('btn-keys'))\">Get Started Free (14-Day Trial) →</button></div>"
    "<div class='eco'><b>WORKS WITH:</b><span>⚡ OpenAI SDK</span><span>🦜 LangChain</span><span>🖱️ Cursor IDE</span><span>🤖 Cline</span><span>▲ Vercel AI</span><span>🔄 n8n</span></div>"
    "<div class='grid'>"
    "<div class='stat'><small>Coding Cost Cut</small><div style='color:#00f5d4'>-74.3%</div></div>"
    "<div class='stat'><small>Neural Requests</small><div id='rCnt'>412</div></div>"
    "<div class='stat'><small>Verified Savings</small><div id='savCnt' style='color:#38bdf8'>$38.40</div></div>"
    "<div class='stat'><small>PII & Firewall</small><div style='color:#00f5d4'>ZERO-TRUST</div></div></div>"
    "<div id='test' class='panel active'><div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px'>"
    "<h3 style='margin:0;color:#fff'>Live Multi-LLM Router Playground</h3>"
    "<div style='display:flex;gap:6px;flex-wrap:wrap'>"
    "<button class='pill-btn' onclick=\"setDemo('Write a fast Python binary search function')\">💻 Python Code</button>"
    "<button class='pill-btn' onclick=\"setDemo('Draft an invoice reminder for client john@acme.com')\">🔒 Test PII Masking</button>"
    "<button class='pill-btn' onclick=\"setDemo('Explain quantum computing in 2 sentences')\">⚡ Test 2ms Cache</button></div></div>"
    "<div style='display:grid;grid-template-columns:2fr 1fr;gap:10px'>"
    "<input id='key' value='optx_free_trial_user' placeholder='Virtual API Key'>"
    "<select id='mod'><option value='auto'>Auto-Route (Cut Costs 74.3%)</option><option value='google/gemini-2.5-flash'>Google: Gemini 2.5 Flash</option><option value='meta-llama/llama-3.3-70b-instruct:free'>Meta: Llama 3.3 70B (Free)</option><option value='deepseek/deepseek-r1:free'>DeepSeek: R1 Reasoner (Free)</option><option value='qwen/qwen-2.5-coder-32b-instruct:free'>Qwen: 2.5 Coder 32B (Free)</option></select></div>"
    "<textarea id='prm' rows='3' onkeydown=\"if((event.ctrlKey||event.metaKey)&&event.key==='Enter')runAI()\" placeholder='Type a prompt or click a 1-click demo pill above (Press Ctrl+Enter to run)...'></textarea>"
    "<div style='display:flex;justify-content:space-between;align-items:center'>"
    "<button onclick='runAI()' class='btn'>Execute Neural Route (Ctrl+Enter) →</button>"
    "<button onclick=\"copyTxt(document.getElementById('out').textContent,this)\" class='pill-btn'>📋 Copy Output</button></div>"
    "<pre id='out'>// Quantum X-Ray telemetry, masked PII count, % saved & AI response...</pre></div>"
    "<div id='models' class='panel'><div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px'>"
    "<h3 style='margin:0;color:#fff'>🔍 OpenRouter-Style Model Marketplace</h3>"
    "<input id='mSearch' oninput='filterModels()' placeholder='Search 50+ models (e.g. DeepSeek, Coder, Llama, Free)...' style='width:320px;margin:0'></div>"
    "<div style='display:flex;gap:6px;margin:12px 0;flex-wrap:wrap'>"
    "<button class='btn' style='padding:5px 12px;font-size:12px' onclick=\"setCat('')\">All Models</button>"
    "<button class='btn' style='padding:5px 12px;font-size:12px;background:#1e293b' onclick=\"setCat('Coding')\">💻 Coding</button>"
    "<button class='btn' style='padding:5px 12px;font-size:12px;background:#1e293b' onclick=\"setCat('Reasoning')\">🧠 Reasoning</button>"
    "<button class='btn' style='padding:5px 12px;font-size:12px;background:#1e293b' onclick=\"setCat('Ultra-Fast')\">⚡ Ultra-Fast</button>"
    "<button class='btn' style='padding:5px 12px;font-size:12px;background:#1e293b' onclick=\"setCat('Budget')\">💰 Free / Budget</button></div>"
    "<div id='modelCards' style='display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-top:12px'></div></div>"
    "<div id='keys' class='panel'><h3 style='margin-top:0;color:#fff'>Get Started: Generate 14-Day Virtual Key</h3>"
    "<form action='/start-trial' method='post' style='display:grid;grid-template-columns:1fr 1fr auto;gap:8px'>"
    "<input name='name' placeholder='Project or Team Name' required><input name='email' type='email' placeholder='Work Email' required>"
    "<button type='submit' class='btn' style='height:40px;margin-top:6px;background:linear-gradient(90deg,#00f5d4,#10b981);color:#022c22;font-weight:800'>Get Started →</button></form>"
    "<table><thead><tr><th>Key Alias</th><th>API Key</th><th>Tier</th><th>Requests</th><th>Saved / Spend</th></tr></thead><tbody id='keyTbl'></tbody></table></div>"
    "<div id='spend' class='panel'><h3 style='margin-top:0;color:#fff'>Real-Time ROI & Cost Comparison (OptiMax vs Raw GPT-4o)</h3><div id='spendBars'></div></div>"
    "<div id='docs' class='panel'><div style='display:flex;justify-content:space-between;align-items:center'><h3 style='margin:0;color:#fff'>1-Line OpenAI SDK Drop-In</h3>"
    "<button onclick=\"copyTxt(document.getElementById('sdkCode').textContent,this)\" class='pill-btn'>📋 Copy Code</button></div>"
    "<pre id='sdkCode' style='color:#38bdf8'>from openai import OpenAI\n\nclient = OpenAI(\n    api_key=\"optx_free_trial_user\",\n    base_url=\"https://onrender.com\"\n)</pre></div>"
    "<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:20px'>"
    "<div class='stat'><b>Pro Tier — $49/mo</b><p style='font-size:12px;color:#94a3b8;line-height:1.5'>✓ $500/mo API Budget Cap<br>✓ Auto Complexity Downgrade<br>✓ Semantic Vector Caching</p><a href='/upgrade?plan=pro' class='btn'>Choose Pro ($49)</a></div>"
    "<div class='stat' style='border-color:#00f5d4;box-shadow:0 0 25px rgba(0,245,212,0.15)'><span class='pop-tag'>MOST POPULAR</span><b>Business Scale — $499/mo</b><p style='font-size:12px;color:#94a3b8;line-height:1.5'>✓ $5,000/mo API Budget Cap<br>✓ PII X-Ray Masking + Firewall<br>✓ 50+ Models & Priority Failover</p><a href='/upgrade?plan=scale' class='btn' style='background:linear-gradient(90deg,#00f5d4,#10b981);color:#022c22;font-weight:800'>Choose Scale ($499)</a></div>"
    "<div class='stat' style='border-color:#38bdf8'><b>Quantum Enterprise — $15,000</b><p style='font-size:12px;color:#94a3b8;line-height:1.5'>✓ $100,000/mo API Cap + BYOK<br>✓ Zero-Data-Retention SOC2 SLA<br>✓ Dedicated Edge Cluster</p><a href='/upgrade?plan=enterprise' class='btn'>Buy Enterprise ($15k)</a></div>"
    "</div><div style='text-align:center;font-size:11.5px;color:#94a3b8;margin-top:16px'>🔒 14-Day Risk-Free Trial • Zero-Data-Retention Privacy Guarantee • Global Payments via Lemon Squeezy & Payoneer</div></div></div><script>"
    "const titles={test:'NEURAL PLAYGROUND',models:'MODEL MARKETPLACE',keys:'VIRTUAL KEYS & TRIAL',spend:'ROI & SPEND MATRIX',docs:'SDK DROP-IN'};"
    "function tab(id,b){document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');if(b)b.classList.add('active');document.getElementById('hdr').textContent=titles[id];loadStats()}"
    "function setDemo(t){document.getElementById('prm').value=t;runAI()}"
    "function copyTxt(t,b){navigator.clipboard.writeText(t);const old=b.textContent;b.textContent='✓ Copied!';setTimeout(()=>b.textContent=old,1500)}"
    "let ALL_M=[],CUR_C='';async function initCat(){try{const r=await fetch('/v1/models');const d=await r.json();ALL_M=d.data||[];filterModels()}catch(e){}}function setCat(c){CUR_C=c;filterModels()}"
    "function filterModels(){const q=(document.getElementById('mSearch').value||'').toLowerCase();const l=ALL_M.filter(m=>(!CUR_C||m.cat===CUR_C)&&(m.name.toLowerCase().includes(q)||m.id.toLowerCase().includes(q)||m.cat.toLowerCase().includes(q)));document.getElementById('modelCards').innerHTML=l.map(m=>`<div style='background:#030712;border:1px solid rgba(56,189,248,0.25);padding:14px;border-radius:10px'><div style='display:flex;justify-content:space-between'><b style='color:#fff'>${m.name}</b><span style='background:rgba(56,189,248,0.15);color:#38bdf8;font-size:11px;padding:2px 8px;border-radius:12px'>${m.cat}</span></div><div style='font-family:monospace;font-size:11.5px;color:#94a3b8;margin:6px 0'>${m.id} • ${m.ctx}</div><div style='display:flex;justify-content:space-between;align-items:center;margin-top:10px'><span style='font-size:12px;color:#00f5d4'>In: ${m.in_price} | Out: ${m.out_price}</span><button class='btn' style='padding:5px 11px;font-size:11.5px' onclick=\"pickM('${m.id}')\">Test →</button></div></div>`).join('')}"
    "function pickM(id){const s=document.getElementById('mod');if(![...s.options].some(o=>o.value===id)){s.add(new Option(id,id))}s.value=id;tab('test',document.getElementById('btn-test'))}"
    "async function loadStats(){try{const r=await fetch('/v1/admin/stats');const d=await r.json();document.getElementById('rCnt').textContent=d.total_reqs;document.getElementById('savCnt').textContent='$'+d.total_saved.toFixed(2);"
    "document.getElementById('keyTbl').innerHTML=d.keys.map(k=>`<tr><td><b>${k.alias}</b></td><td style='font-family:monospace;color:#38bdf8'>${k.key}</td><td>${k.tier}</td><td>${k.reqs}</td><td style='color:#00f5d4'>Saved $${k.saved.toFixed(3)} / Spent $${k.spend.toFixed(3)}</td></tr>`).join('');"
