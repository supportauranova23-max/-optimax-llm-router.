import time
import os
import sqlite3
import hmac
import hashlib
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional

# ---> COGNISHIELD FIREWALL
from cognishield_layer import CogniShieldLayer

# ---> REAL AI PROVIDER SDKs
from openai import OpenAI
from google import genai

app = FastAPI(title="OptiMax: Intelligent AI API Cost Management Router")

# Load Keys & Checkout Links from Render Environment Variables
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
LEMON_CHECKOUT_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
LEMON_WEBHOOK_SECRET = os.environ.get("LEMON_WEBHOOK_SECRET", "")

# Initialize AI Clients
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

shield = CogniShieldLayer()
DB_FILE = "optimax.db"

# ---> DATABASE INITIALIZATION (SQLite)
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            api_key TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            tier TEXT,
            usage_count INTEGER DEFAULT 0
        )
    """)
    starter_users = [
        ("optx_live_dev_78x92", "Alpha Tech Ventures", "dev@alphatech.io", "premium", 0),
        ("optx_live_scale_11a42", "Nexus AI Core", "admin@nexusai.io", "premium", 0),
        ("optx_free_trial_user", "Standard Sandbox User", "trial@user.com", "free", 0)
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO users (api_key, name, email, tier, usage_count) VALUES (?, ?, ?, ?, ?)",
        starter_users
    )
    conn.commit()
    conn.close()

init_db()

class PromptRequest(BaseModel):
    prompt: str
    preferred_model: Optional[str] = "auto"

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OptiMax Admin & Billing Controls</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 40px; }
        .container { max-width: 900px; margin: 0 auto; background: #161b22; padding: 30px; border-radius: 8px; border: 1px solid #30363d; }
        h1 { color: #58a6ff; margin-top: 0; }
        .metric-box { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin: 25px 0; }
        .metric { background: #21262d; padding: 20px; border-radius: 6px; border: 1px solid #30363d; text-align: center; }
        .metric-value { font-size: 24px; font-weight: bold; color: #3fb950; margin-top: 5px; }
        .status-badge { display: inline-block; padding: 6px 12px; background: rgba(63, 185, 80, 0.15); color: #3fb950; border-radius: 20px; font-size: 14px; font-weight: 500; }
        .btn-pay { display: inline-block; background: #238636; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-top: 15px; }
        .btn-pay:hover { background: #2ea043; }
    </style>
</head>
<body>
    <div class="container">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h1>Optimax AI Operational Router</h1>
            <span class="status-badge">● Multi-LLM & DB Active</span>
        </div>
        <p>Production routing gateway powered by persistent SQLite storage, CogniShield firewall, and live OpenAI/Gemini upstream clusters.</p>
        
        <div class="metric-box">
            <div class="metric">
                <div>Database Engine</div>
                <div class="metric-value">SQLite Live</div>
            </div>
            <div class="metric">
                <div>Connected Models</div>
                <div class="metric-value">GPT-4o / Gemini</div>
            </div>
            <div class="metric">
                <div>Global Billing</div>
                <div class="metric-value" style="color: #58a6ff;">Lemon + Payoneer</div>
            </div>
        </div>

        <div style="background: #21262d; padding: 20px; border-radius: 6px; border: 1px solid #30363d; margin-top: 20px; text-align: center;">
            <h3>Upgrade to Optimax Enterprise Unlimited</h3>
            <p>Unlock endless sub-token proxy calls, high-throughput dedicated clusters, and advanced fallback routing redundancy.</p>
            <a class="btn-pay" href="/upgrade">Upgrade Account ($49/mo)</a>
        </div>
    </div>
</body>
</html>
"""

async def verify_api_key_and_billing(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed credentials structure.")
    token = authorization.split(" ")[1]
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name, tier, usage_count FROM users WHERE api_key = ?", (token,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=403, detail="Unauthorized client signature detected.")
    
    name, tier, usage_count = row
    
    if tier == "free" and usage_count >= 5:
        conn.close()
        raise HTTPException(
            status_code=402, 
            detail="Payment Required: Free tier request allocation (5/5) exhausted. Visit /upgrade to unlock unlimited access."
        )
        
    new_usage = usage_count + 1
    cursor.execute("UPDATE users SET usage_count = ? WHERE api_key = ?", (new_usage, token))
    conn.commit()
    conn.close()
        
    return {"api_key": token, "name": name, "tier": tier, "usage_count": new_usage}

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    return HTMLResponse(content=DASHBOARD_HTML, status_code=200)

@app.get("/upgrade")
async def redirect_to_checkout():
    return RedirectResponse(url=LEMON_CHECKOUT_URL, status_code=303)

@app.post("/webhook/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("X-Signature", "")
    
    if LEMON_WEBHOOK_SECRET:
        digest = hmac.new(LEMON_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature.")
            
    data = await request.json()
    event_name = data.get("meta", {}).get("event_name")
    customer_email = data.get("data", {}).get("attributes", {}).get("user_email")
    
    if event_name in ["order_created", "subscription_created"] and customer_email:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET tier = 'premium' WHERE email = ?", (customer_email,))
        conn.commit()
        conn.close()
        
    return {"status": "webhook_processed"}

@app.post("/v1/route")
async def optimize_and_route(request: PromptRequest, client_profile: dict = Depends(verify_api_key_and_billing)):
    start_time = time.time()
    
    shield_verdict = shield.inspect_payload(request.prompt)
    if not shield_verdict.get("safe", True):
        raise HTTPException(status_code=400, detail=f"Blocked by CogniShield: {shield_verdict.get('reason')}")
    
    word_count = len(request.prompt.split())
    target_provider = request.preferred_model
    if target_provider == "auto":
        target_provider = "gemini" if word_count < 15 else "openai"

    ai_response_text = ""
    model_used = ""

    try:
        if target_provider == "gemini":
            if not gemini_client:
                raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured on server.")
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=request.prompt
            )
            ai_response_text = response.text
            model_used = "gemini-2.5-flash"
            
        elif target_provider == "openai":
            if not openai_client:
                raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured on server.")
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": request.prompt}]
            )
            ai_response_text = response.choices[0].message.content
            model_used = "gpt-4o-mini"
        else:
            raise HTTPException(status_code=400, detail="Invalid preferred_model. Choose 'auto', 'openai', or 'gemini'.")
            
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream AI Provider Error: {str(e)}")

    execution_overhead = (time.time() - start_time) * 1000
    
    return {
        "status": "success",
        "tenant": client_profile["name"],
        "tier_status": client_profile["tier"],
        "requests_used": client_profile["usage_count"],
        "router_metrics": {
            "total_latency_ms": round(execution_overhead, 2),
            "routed_to_model": model_used
        },
        "response": ai_response_text
    }
