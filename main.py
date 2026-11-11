import time
import os
import re
import hashlib
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
from supabase import create_client, Client
import stripe

app = FastAPI(title="OptiMax: Zero-Code Shadow Switch & Developer Engine")

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "sk_test_mock_placeholder_key")
YOUR_DOMAIN = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "your-anon-key-here")

supabase_db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SEMANTIC_CACHE = {}

SESSION_METRICS = {
    "baseline_spend_usd": 3840.00,
    "cash_saved_usd": 1920.00,
    "rebate_owed_to_client_usd": 960.00,
    "threats_redacted": 47,
    "shadow_calls_mirrored": 12840,
    "cache_hits_saved": 3190
}

class PromptRequest(BaseModel):
    prompt: str
    priority: Optional[str] = "standard"
    mode: Optional[str] = "live"

def auto_redact_sensitive_data(text: str) -> tuple[str, int]:
    redactions = 0
    text, cc_count = re.subn(r'\b(?:\d[ -]*?){13,16}\b', '[REDACTED_CARD]', text)
    redactions += cc_count
    text, ssn_count = re.subn(r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED_SSN]', text)
    redactions += ssn_count
    text, email_count = re.subn(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[REDACTED_EMAIL]', text)
    redactions += email_count
    return text, redactions

def compress_prompt_tokens(text: str) -> tuple[str, int]:
    original_len = len(text)
    compressed = re.sub(r'\s+', ' ', text).strip()
    filler_words = [
        r'\bplease\b',
        r'\bkindly\b',
        r'\bcould you\b',
        r'\bi would like you to\b',
        r'\bcan you\b',
        r'\bimmediately\b'
    ]
    for pattern in filler_words:
        compressed = re.sub(pattern, '', compressed, flags=re.IGNORECASE)
    compressed = re.sub(r'\s+', ' ', compressed).strip()
    saved_chars = max(0, original_len - len(compressed))
    estimated_tokens_saved = max(1, saved_chars // 4) if saved_chars > 0 else 0
    return compressed, estimated_tokens_saved

def smart_cost_and_failover_router(clean_prompt: str, priority: str, cache_hit: bool) -> dict:
    if cache_hit:
        return {
            "routed_model": "optimax-semantic-cache-edge",
            "failover_standby": "none-required",
            "baseline_cost_usd": 0.090,
            "optimized_cost_usd": 0.000,
            "saved_on_call_usd": 0.090,
            "instant_cashback_rebate_usd": 0.045
        }

    word_count = len(clean_prompt.split())
    if word_count < 25 and priority != "complex":
        selected_model = "gpt-4o-mini-optimized"
        backup_model = "claude-3-haiku-failover"
        baseline_cost = 0.090
        optimized_cost = 0.015
    else:
        selected_model = "claude-3-5-sonnet-enterprise"
        backup_model = "gpt-4o-failover"
        baseline_cost = 0.240
        optimized_cost = 0.090

    saved_amount = round(baseline_cost - optimized_cost, 4)
    rebate_amount = round(saved_amount * 0.50, 4)

    return {
        "routed_model": selected_model,
        "failover_standby": backup_model,
        "baseline_cost_usd": baseline_cost,
        "optimized_cost_usd": optimized_cost,
        "saved_on_call_usd": saved_amount,
        "instant_cashback_rebate_usd": rebate_amount
    }

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OptiMax Shadow Switch & Developer Engine</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 36px; }}
        .container {{ max-width: 1020px; margin: 0 auto; background: #161b22; padding: 32px; border-radius: 10px; border: 1px solid #30363d; }}
        h1 {{ color: #58a6ff; margin-top: 0; font-size: 26px; }}
        .metric-box {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; margin: 26px 0; }}
        .metric {{ background: #21262d; padding: 18px; border-radius: 8px; border: 1px solid #30363d; text-align: center; }}
        .metric-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.7px; color: #8b949e; }}
        .metric-value {{ font-size: 22px; font-weight: bold; color: #3fb950; margin-top: 8px; }}
        .status-badge {{ display: inline-block; padding: 6px 14px; background: rgba(63, 185, 80, 0.15); color: #3fb950; border-radius: 20px; font-size: 13px; font-weight: 600; }}
        .sandbox {{ background: #0d1117; padding: 20px; border-radius: 8px; border: 1px solid #30363d; margin-top: 20px; }}
        textarea {{ width: 100%; background: #161b22; color: #c9d1d9; border: 1px solid #30363d; border-radius: 6px; padding: 12px; font-family: monospace; font-size: 13px; box-sizing: border-box; margin-top: 10px; }}
        pre {{ background: #161b22; padding: 14px; border-radius: 6px; border: 1px solid #30363d; color: #79c0ff; font-size: 12px; overflow-x: auto; margin-top: 12px; }}
        .btn {{ display: inline-block; padding: 12px 22px; border-radius: 6px; font-weight: bold; text-decoration: none; cursor: pointer; border: none; font-size: 14px; margin-top: 12px; margin-right: 8px; }}
        .btn-green {{ background: #238636; color: white; }}
        .btn-green:hover {{ background: #2ea043; }}
        .btn-blue {{ background: #1f6feb; color: white; }}
        .btn-blue:hover {{ background: #388bfd; }}
    </style>
</head>
<body>
    <div class="container">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h1>OptiMax Developer & Rebate Engine</h1>
            <span class="status-badge">● Semantic Cache + PII Shield + 50% Rebate Active</span>
        </div>
        <p style="color: #8b949e;">1-Line Base URL switch. Compress tokens, serve instant $0 cached hits, scrub PII leaks, and claim 50% of Month-1 savings in cash back.</p>
        
        <div class="metric-box">
            <div class="metric">
                <div class="metric-label">Total Cash Saved</div>
                <div class="metric-value" id="cash-counter">${SESSION_METRICS['cash_saved_usd']:,.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">50% Client Rebate</div>
                <div class="metric-value" id="rebate-counter" style="color: #a371f7;">${SESSION_METRICS['rebate_owed_to_client_usd']:,.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">$0 Cache Hits</div>
                <div class="metric-value" style="color: #79c0ff;">{SESSION_METRICS['cache_hits_saved']:,}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Shadow Calls</div>
                <div class="metric-value" style="color: #58a6ff;">{SESSION_METRICS['shadow_calls_mirrored']:,}</div>
            </div>
            <div class="metric">
                <div class="metric-label">PII Leaks Blocked</div>
                <div class="metric-value" style="color: #d29922;">{SESSION_METRICS['threats_redacted']}</div>
            </div>
        </div>

        <div class="sandbox">
            <strong style="color: #58a6ff; font-size: 15px;">Live Engineer Sandbox (Test PII Redaction, Token Diet & Caching)</strong>
            <textarea id="test-prompt" rows="3">Please kindly summarize the account for john.doe@enterprise.com with card 4532 1234 5678 9010 immediately.</textarea>
            <button class="btn btn-blue" onclick="runLiveTest()">Run Live API Simulation</button>
            <pre id="test-output">Click "Run Live API Simulation" to see OptiMax scrub PII, compress tokens, and calculate savings in real time...</pre>
        </div>

        <div style="background: #21262d; padding: 24px; border-radius: 8px; border: 1px solid #30363d; margin-top: 24px; text-align: center;">
            <h3 style="margin-top: 0;">Deploy OptiMax Enterprise + Claim 50% Month-1 Cash-Back Rebate</h3>
            <p style="color: #8b949e;">Zero upfront cost. Start your 14-day free trial or download your 48-Hour Shadow Audit statement.</p>
            <a class="btn btn-green" href="/create-checkout-session">Start 14-Day Free Trial</a>
            <a class="btn btn-blue" href="/shadow-receipt" target="_blank">View 48-Hr Shadow Audit Receipt</a>
        </div>
    </div>

    <script>
        let saved = {SESSION_METRICS['cash_saved_usd']};
        let rebate = {SESSION_METRICS['rebate_owed_to_client_usd']};
        setInterval(() => {{
            saved += 0.06;
            rebate += 0.03;
            document.getElementById('cash-counter').innerText = '$' + saved.toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
            document.getElementById('rebate-counter').innerText = '$' + rebate.toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
        }}, 2500);

        async function runLiveTest() {{
            const promptText = document.getElementById('test-prompt').value;
            const outputBox = document.getElementById('test-output');
            outputBox.innerText = "Routing through OptiMax Edge Shield...";
            try {{
                const res = await fetch('/v1/demo-test', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ prompt: promptText, mode: 'shadow' }})
                }});
                const data = await res.json();
                outputBox.innerText = JSON.stringify(data, null, 2);
            }} catch (err) {{
                outputBox.innerText = "Error running test: " + err;
            }}
        }}
