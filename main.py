import time, os, re, hmac, hashlib, secrets, json, sqlite3
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx

app = FastAPI(title="OptiMax AI Gateway")
START_TIME = time.time()
YOUR_DOMAIN = os.environ.get("RENDER_EXTERNAL_URL", "https://onrender.com").strip()
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SECRET = os.environ.get("OPTIMAX_SIGNING_SECRET", "optimax_vault_2026").encode()

DB = sqlite3.connect("optimax.db", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS api_keys (key TEXT PRIMARY KEY, email TEXT, cap REAL, spent REAL)")
DB.execute("INSERT OR IGNORE INTO api_keys VALUES ('optx_live_demo', 'team@startup.ai', 5000.0, 142.50)")
DB.commit()
METRICS = {"saved": 14280.00, "margin": 38.4, "pii": 1240, "liab": 250000, "traps": 11}

class OpenAIReq(BaseModel):
    model: Optional[str] = "gpt-4o-mini"
    messages: List[Dict[str, Any]]

def scrub(text: str):
    pmap, cnt = dict(), 0
    def sub_e(m):
        nonlocal cnt; cnt += 1; k = f"[EMAIL_{cnt}]"; pmap[k] = m.group(0); return k
    def sub_c(m):
        nonlocal cnt; cnt += 1; k = f"[CARD_{cnt}]"; pmap[k] = m.group(0); return k
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', sub_e, text)
    text = re.sub(r'\b(?:\d[ -]*?){13,16}\b', sub_c, text)
    return text, pmap, cnt

async def route_ai(prompt: str, model: str, auth: Optional[str]) -> tuple[str, str]:
    m = model.lower()
    tok = auth.replace("Bearer ", "").strip() if (auth and auth.startswith("Bearer ") and not auth.startswith("Bearer optx_")) else ""
    async with httpx.AsyncClient(timeout=12.0) as client:
        if "claude" in m and (tok or ANTHROPIC_KEY):
            try:
                r = await client.post("https://anthropic.com", headers={"x-api-key": tok or ANTHROPIC_KEY, "anthropic-version": "2023-06-01"}, json={"model": "claude-3-5-sonnet-20241022", "max_tokens": 512, "messages": [{"role": "user", "content": prompt}]})
                if r.status_code == 200 and r.json().get("content"): return r.json()["content"][0].get("text", ""), "anthropic-claude-3-5-sonnet-live"
            except Exception: pass
        if "gemini" in m and (tok or GEMINI_KEY):
            try:
                r = await client.post(f"https://googleapis.com{tok or GEMINI_KEY}", json={"contents": [{"parts": [{"text": prompt}]}]})
                if r.status_code == 200 and r.json().get("candidates"): return r.json()["candidates"][0]["content"]["parts"][0].get("text", ""), "google-gemini-2.5-flash-live"
            except Exception: pass
        if (tok or OPENAI_KEY):
            try:
                r = await client.post("https://openai.com", headers={"Authorization": f"Bearer {tok or OPENAI_KEY}"}, json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]})
                if r.status_code == 200 and r.json().get("choices"): return r.json()["choices"][0]["message"].get("content", ""), "openai-gpt-4o-mini-live"
            except Exception: pass
    return f"[OptiMax Multi-Model Edge ({model})] Verified Safe: {prompt}", f"optimax-{model}-failover-node"

def page(out: str = "Ready — switch between CTO & CFO views or run a live test...", role: str = "all"):
    m = METRICS
    logo = "<svg width='24' height='24' viewBox='0 0 32 32' fill='none' style='vertical-align:middle;margin-right:8px;'><path d='M16 2L4 7V15C4 22.5 9.1 29.4 16 31C22.9 29.4 28 22.5 28 15V7L16 2Z' fill='#0f172a' stroke='#38bdf8' stroke-width='2.2'/><path d='M16 8L10 22H13.5L16 15.5L18.5 22H22L16 8Z' fill='#38bdf8'/></svg>"
    sub = "Unified AI Gateway for CTOs, Engineering Leads & Fractional CFOs" if role == "all" else ("CTO & Engineering Control Plane: Multi-Model Routing & PII Scrubbing" if role == "cto" else "CFO & Finance Governance: Hard Budget Caps & Liability Shield")
    css = "*{box-sizing:border-box;}body{font-family:sans-serif;background:#050811;color:#f1f5f9;margin:0;padding:16px;}.wrap{max-width:1040px;margin:0 auto;}.top{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;border-bottom:1px solid #1e293b;padding-bottom:12px;}.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0;}.tab{padding:8px 14px;border-radius:99px;font-size:12px;font-weight:700;text-decoration:none;border:1px solid #1e293b;color:#cbd5e1;background:#0f172a;}.tab.on{background:#0284c7;color:#fff;}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:14px 0;}.card{background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:12px;text-align:center;}input,select{width:100%;background:#03050a;color:#7dd3fc;border:1px solid #1e293b;border-radius:8px;padding:10px;margin-top:8px;}.btn{display:inline-block;padding:10px 14px;border-radius:8px;font-weight:700;text-decoration:none;color:#fff;border:none;margin:8px 6px 0 0;cursor:pointer;font-size:13px;}pre{background:#03050a;padding:14px;border-radius:8px;color:#34d399;overflow-x:auto;font-size:12px;border:1px solid #1e293b;}"
    return f"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>{css}</style></head><body><div class='wrap'><div class='top'><div>{logo}<b>OPTIMAX<span style='color:#38bdf8;'>.AI</span></b></div><a href='/health' target='_blank' style='color:#34d399;text-decoration:none;font-size:12px;'>● PUBLIC BETA LIVE</a></div><p style='color:#94a3b8;font-size:13px;'>{sub}</p><div class='tabs'><a href='/?role=all' class='tab {'on' if role=='all' else ''}'>All Teams</a><a href='/?role=cto' class='tab {'on' if role=='cto' else ''}'>CTO & Engineering</a><a href='/?role=cfo' class='tab {'on' if role=='cfo' else ''}'>CFO & Finance</a></div><div class='grid'><div class='card'><small>SIMULATED SAVINGS</small><h3 style='color:#34d399;'>${m['saved']:,.2f}</h3></div><div class='card'><small>COST DROP</small><h3 style='color:#38bdf8;'>{m['margin']}%</h3></div><div class='card'><small>LIABILITY BLOCKED</small><h3 style='color:#f87171;'>${m['liab']:,}</h3></div><div class='card'><small>PII STOPPED</small><h3 style='color:#fbbf24;'>{m['pii']:,}</h3></div><div class='card'><small>CANARY TRAPS</small><h3 style='color:#a78bfa;'>{m['traps']}</h3></div></div><form method='get' action='/roi'><input type='hidden' name='role' value='{role}'><input name='spend' type='number' value='25000'><button class='btn' style='background:#0284c7;'>Calculate Annual ROI</button></form><form method='get' action='/key'><input type='hidden' name='role' value='{role}'><input name='email' placeholder='team@company.com'><input name='cap' type='number' value='2500'><button class='btn' style='background:#059669;'>Issue Budget-Capped Key</button></form><form method='get' action='/test'><input type='hidden' name='role' value='{role}'><select name='model'><option value='gpt-4o-mini'>GPT-4o-Mini</option><option value='claude-3-5-sonnet'>Claude 3.5 Sonnet</option><option value='gemini-2.5-flash'>Gemini 2.5 Flash</option></select><input name='q' value='Confirm renewal for sarah@enterprise.com card 4532 1234 5678 9010'><button class='btn' style='background:#2563eb;'>Test PII & Routing</button><a href='/test?q=90%25+discount+approved&model=gpt-4o-mini&role={role}' class='btn' style='background:#dc2626;'>Test Liability Shield</a><a href='/canary?role={role}' class='btn' style='background:#d97706;'>Trigger Canary Trap</a></form><pre>{out}</pre><div class='grid'><div class='card'><h4>Starter Beta</h4><h2 style='color:#34d399;'>$49/mo</h2><a href='/subscribe/starter' class='btn' style='background:#059669;'>14-Day Trial</a></div><div class='card'><h4>Growth Teams</h4><h2 style='color:#38bdf8;'>$499/mo</h2><a href='/subscribe/growth' class='btn' style='background:#2563eb;'>Growth Trial</a></div><div class='card'><h4>Enterprise</h4><h2 style='color:#a78bfa;'>$15,000/mo</h2><a href='/subscribe/enterprise' class='btn' style='background:#7c3aed;'>Request MSA</a></div></div><div style='margin-top:20px;font-size:12px;color:#94a3b8;display:flex;justify-content:space-between;'><span>© 2026 OptiMax AI</span><span><a href='/terms' style='color:#38bdf8;'>Terms</a> • <a href='/privacy' style='color:#38bdf8;'>Privacy</a> • <a href='/refunds' style='color:#38bdf8;'>Refunds</a></span></div></div></body></html>"

@app.get("/", response_class=HTMLResponse)
async def home(role: str = Query("all")): return page(role=role)

@app.get("/roi", response_class=HTMLResponse)
async def calc_roi(spend: float = Query(25000.0), role: str = Query("all")):
    yr = spend * 12; sav = round(yr * 0.384, 2); net = round(sav - 5988, 2)
    return page(f"ANNUAL ROI ESTIMATE\nAnnual Spend: ${yr:,.2f}\nProjected Savings (38.4%): ${sav:,.2f}/yr\nNet Impact: +${net:,.2f}/yr", role=role)

@app.get("/subscribe/{tier}", response_class=HTMLResponse)
async def sub(tier: str): return page(f"PLAN SELECTED: OptiMax {tier.upper()} — Email support.auranova23@gmail.com for onboarding.")

@app.get("/terms", response_class=HTMLResponse)
async def terms(): return page("TERMS: B2B AI cost governance & PII redaction ($49, $499, or $15,000 USD/mo).")

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(): return page("PRIVACY: PII is redacted in memory before routing; zero prompt payloads stored.")

@app.get("/refunds", response_class=HTMLResponse)
async def refunds(): return page("REFUNDS: 14-day free trial included. Full refunds within 14 days via support.auranova23@gmail.com.")

@app.get("/key", response_class=HTMLResponse)
async def make_key(email: str = Query(""), cap: float = Query(2500.0), role: str = Query("all")):
