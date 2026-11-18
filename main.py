import time
import os
import sqlite3
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends, Request, Form
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
DB_FILE = "optimax_v2.db"
TRIAL_DAYS = 14

# ---> DATABASE INITIALIZATION (SQLite with 14-Day Trial Tracking)
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            api_key TEXT PRIMARY KEY,
            name TEXT,
            email TEXT UNIQUE,
            tier TEXT,
            created_at TEXT,
            usage_count INTEGER DEFAULT 0
        )
    """)
    now_iso = datetime.utcnow().isoformat()
    starter_users = [
        ("optx_live_dev_78x92", "Alpha Tech Ventures", "dev@alphatech.io", "premium", now_iso, 0),
        ("optx_live_scale_11a42", "Nexus AI Core", "admin@nexusai.io", "premium", now_iso, 0),
        ("optx_free_trial_user", "Standard Sandbox User", "trial@user.com", "trial", now_iso, 0)
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO users (api_key, name, email, tier, created_at, usage_count) VALUES (?, ?, ?, ?, ?, ?)",
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
        .card { background: #21262d; padding: 25px; border-radius: 6px; border: 1px solid #30363d; margin-top: 20px; }
        .btn-pay { display: inline-block; background: #238636; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-top: 10px; border: none; cursor: pointer; font-size: 15px; }
        .btn-pay:hover { background: #2ea043; }
        .btn-blue { background: #1f6feb; }
        .btn-blue:hover { background: #388bfd; }
        input { padding: 10px; border-radius: 6px; border: 1px solid #30363d; background: #0d1117; color: white; width: 35%; margin-right: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h1>Optimax AI Operational Router</h1>
            <span class="status-badge">● Multi-LLM & 14-Day Trial Active</span>
        </div>
        <p>Production routing gateway powered by persistent SQLite storage, CogniShield firewall, and live OpenAI/Gemini upstream clusters.</p>
        
        <div class="metric-box">
            <div class="metric">
                <div>Free Trial Period</div>
                <div class="metric-value">14 Days</div>
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

        <div class="card">
            <h3>Start Your Free 2-Week Trial</h3>
            <p>Generate an instant API key with full routing access for 14 days. No credit card required upfront.</p>
            <form action="/start-trial" method="post">
                <input type="text" name="name" placeholder="Company or Your Name" required>
                <input type="email" name="email" placeholder="Work Email Address" required>
                <button type="submit" class="btn-pay btn-blue">Get 14-Day Trial Key</button>
            </form>
        </div>

        <div class="card" style="text-align: center;">
            <h3>Enterprise Access & Interactive Testing</h3>
            <p>Test your API key live in our interactive playground or upgrade for uninterrupted enterprise clusters.</p>
            <a class="btn-pay btn-blue" href="/docs" style="margin-right: 10px;">Open API Playground</a>
            <a class="btn-pay" href="/upgrade">Upgrade Account ($49/mo)</a>
        </div>
    </div>
</body>
</html>
"""

async def verify_api_key_and_billing(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed credentials structure.")
    parts = authorization.split(" ")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Invalid Authorization header format. Use 'Bearer <API_KEY>'.")
    token = parts[1]
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name, tier, created_at, usage_count FROM users WHERE api_key = ?", (token,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=403, detail="Unauthorized client signature detected.")
    
    name, tier, created_at_str, usage_count = row
    
    # Enforce 14-Day (2-Week) Free Trial Expiration Check
    if tier == "trial":
        created_at = datetime.fromisoformat(created_at_str)
        expiration_date = created_at + timedelta(days=TRIAL_DAYS)
        if datetime.utcnow() > expiration_date:
            conn.close()
            raise HTTPException(
                status_code=402, 
                detail="Payment Required: Your 14-day free trial has expired. Please visit /upgrade to continue using Optimax."
            )
        
    new_usage = usage_count + 1
    cursor.execute("UPDATE users SET usage_count = ? WHERE api_key = ?", (new_usage, token))
    conn.commit()
    conn.close()
        
    return {"api_key": token, "name": name, "tier": tier, "usage_count": new_usage}

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    return HTMLResponse(content=DASHBOARD_HTML, status_code=200)

@app.post("/start-trial", response_class=HTMLResponse)
async def start_free_trial(name: str = Form(...), email: str = Form(...)):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT api_key, tier, created_at FROM users WHERE email = ?", (email,))
    existing = cursor.fetchone()
    
    if existing:
        api_key, tier, created_at = existing
        conn.close()
    else:
        api_key = f"optx_trial_{secrets.token_hex(8)}"
        created_at = datetime.utcnow().isoformat()
        cursor.execute(
            "INSERT INTO users (api_key, name, email, tier, created_at, usage_count) VALUES (?, ?, ?, ?, ?, ?)",
            (api_key, name, email, "trial", created_at, 0)
        )
        conn.commit()
        conn.close()

    return f"""
    <html>
    <body style="font-family: 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; padding: 50px; text-align: center;">
        <div style="max-width: 600px; margin: 0 auto; background: #161b22; padding: 30px; border-radius: 8px; border: 1px solid #30363d;">
            <h2 style="color: #3fb950;">Your 14-Day Free Trial is Active!</h2>
            <p>Copy your Bearer API Key below to test your router:</p>
            <div style="background: #0d1117; padding: 15px; border-radius: 6px; border: 1px solid #58a6ff; font-family: monospace; font-size: 16px; color: #58a6ff; margin: 20px 0;">
                {api_key}
            </div>
            <p style="font-size: 14px; color: #8b949e;">Trial valid for 14 days from {created_at[:10]}. Upgrade anytime using the same email ({email}) to unlock unlimited access automatically.</p>
            <div style="margin-top: 25px;">
                <a href="/docs" style="display: inline-block; background: #1f6feb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-right: 10px;">Test Key in API Playground →</a>
                <a href="/" style="display: inline-block; color: #58a6ff; text-decoration: none; padding: 12px;">← Back to Dashboard</a>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/upgrade")
async def redirect_to_checkout():
    return RedirectResponse(url=LEMON_CHECKOUT_URL, status_code=303)

@app.post("/webhook/lemonsqueezy")
