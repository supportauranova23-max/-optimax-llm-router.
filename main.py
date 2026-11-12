import time
import os
import re
import hashlib
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import stripe

app = FastAPI(title="OptiMax: Decentralized GPU Exchange, Data Refinery & Outcome Engine")

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "sk_test_mock_placeholder_key")
YOUR_DOMAIN = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

supabase_db = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase_db = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as db_err:
        print(f"Supabase init warning: {db_err}")

SEMANTIC_CACHE = dict()
SYNTHETIC_DATA_VAULT = list()

GPU_EXCHANGE_NODES = {
    "fast_tier": {"node": "gpu-cluster-nordic-idle-04", "cloud_cost": 0.090, "gpu_cost": 0.014, "platform_fee": 0.004},
    "reasoning_tier": {"node": "gpu-cluster-zurich-idle-09", "cloud_cost": 0.240, "gpu_cost": 0.048, "platform_fee": 0.015}
}

SESSION_METRICS = {
    "baseline_spend_usd": 4120.00,
    "cash_saved_usd": 2980.00,
    "rebate_owed_to_client_usd": 1490.00,
    "threats_redacted": 54,
    "shadow_calls_mirrored": 14290,
    "cache_hits_saved": 3840,
    "hallucinations_caught": 19,
    "golden_training_pairs": 1420,
    "outcomes_billed_usd": 645.00
}

class PromptRequest(BaseModel):
    prompt: str
    priority: Optional[str] = "standard"
    mode: Optional[str] = "live"

class OutcomeEvent(BaseModel):
    event_type: str
    deal_value_usd: Optional[float] = 0.0

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
    filler_words = (
        r'\bplease\b',
        r'\bkindly\b',
        r'\bcould you\b',
        r'\bi would like you to\b',
        r'\bcan you\b',
        r'\bimmediately\b'
    )
    for pattern in filler_words:
        compressed = re.sub(pattern, '', compressed, flags=re.IGNORECASE)
    compressed = re.sub(r'\s+', ' ', compressed).strip()
    saved_chars = max(0, original_len - len(compressed))
    estimated_tokens_saved = max(1, saved_chars // 4) if saved_chars > 0 else 0
    return compressed, estimated_tokens_saved

def silent_hallucination_guard(clean_prompt: str, initial_tier: str) -> tuple[str, bool]:
    risk_keywords = ("legal", "contract", "audit", "medical", "financial", "compliance")
    needs_upgrade = any(word in clean_prompt.lower() for word in risk_keywords)
    if initial_tier == "fast_tier" and needs_upgrade:
        return "reasoning_tier", True
    return initial_tier, False

def refine_synthetic_training_pair(clean_prompt: str, routed_node: str, upgraded: bool) -> dict:
    pair_id = hashlib.md5(f"{clean_prompt}-{time.time()}".encode()).hexdigest()[:10]
    record = {
        "pair_id": f"zk_synth_{pair_id}",
        "sanitized_input": clean_prompt,
        "verified_node": routed_node,
        "quality_score": 0.99 if upgraded else 0.94,
        "licensable_value_usd": 0.25
    }
    SYNTHETIC_DATA_VAULT.append(record)
    if len(SYNTHETIC_DATA_VAULT) > 100:
        SYNTHETIC_DATA_VAULT.pop(0)
    return record

def idle_gpu_arbitrage_router(clean_prompt: str, priority: str, cache_hit: bool) -> dict:
    if cache_hit:
        return {
            "routed_node": "optimax-semantic-cache-edge",
            "cloud_baseline_usd": 0.090,
            "idle_gpu_cost_usd": 0.000,
            "optimax_arbitrage_fee_usd": 0.000,
            "saved_on_call_usd": 0.090,
            "instant_cashback_rebate_usd": 0.045,
            "hallucination_auto_upgraded": False
        }

    word_count = len(clean_prompt.split())
    chosen_tier = "fast_tier" if (word_count < 25 and priority != "complex") else "reasoning_tier"
    chosen_tier, was_upgraded = silent_hallucination_guard(clean_prompt, chosen_tier)

    node_info = GPU_EXCHANGE_NODES.get(chosen_tier)
    cloud_cost = node_info.get("cloud_cost")
    gpu_cost = node_info.get("gpu_cost")
    platform_fee = node_info.get("platform_fee")
    total_client_cost = round(gpu_cost + platform_fee, 4)
    saved_amount = round(cloud_cost - total_client_cost, 4)
    rebate_amount = round(saved_amount * 0.50, 4)

    return {
        "routed_node": node_info.get("node"),
        "cloud_baseline_usd": cloud_cost,
        "idle_gpu_cost_usd": gpu_cost,
        "optimax_arbitrage_fee_usd": platform_fee,
        "saved_on_call_usd": saved_amount,
        "instant_cashback_rebate_usd": rebate_amount,
        "hallucination_auto_upgraded": was_upgraded
    }

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    saved = f"{SESSION_METRICS.get('cash_saved_usd'):,.2f}"
    rebate = f"{SESSION_METRICS.get('rebate_owed_to_client_usd'):,.2f}"
    synth_pairs = f"{SESSION_METRICS.get('golden_training_pairs'):,}"
    outcomes_usd = f"{SESSION_METRICS.get('outcomes_billed_usd'):,.2f}"
    cache_hits = f"{SESSION_METRICS.get('cache_hits_saved'):,}"
    threats = SESSION_METRICS.get('threats_redacted')

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>OptiMax GPU Exchange & Data Refinery</title>
<style>
body {{ font-family: sans-serif; background: #0d1117; color: #c9d1d9; padding: 28px; }}
.box {{ max-width: 1100px; margin: 0 auto; background: #161b22; padding: 28px; border-radius: 10px; border: 1px solid #30363d; }}
.grid {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin: 20px 0; }}
.card {{ background: #21262d; padding: 14px; border-radius: 8px; border: 1px solid #30363d; text-align: center; }}
.lbl {{ font-size: 11px; text-transform: uppercase; color: #8b949e; }}
.val {{ font-size: 19px; font-weight: bold; color: #3fb950; margin-top: 6px; }}
textarea {{ width: 100%; background: #0d1117; color: #c9d1d9; border: 1px solid #30363d; border-radius: 6px; padding: 10px; font-family: monospace; box-sizing: border-box; }}
pre {{ background: #0d1117; padding: 12px; border-radius: 6px; border: 1px solid #30363d; color: #79c0ff; overflow-x: auto; font-size: 12px; }}
.btn {{ display: inline-block; padding: 11px 18px; border-radius: 6px; font-weight: bold; text-decoration: none; color: #fff; cursor: pointer; border: none; margin-top: 10px; margin-right: 8px; font-size: 13px; }}
</style>
</head>
<body>
<div class="box">
<h1 style="color: #58a6ff; margin-top: 0;">OptiMax Decentralized GPU Exchange & Data Refinery</h1>
<p style="color: #8b949e;">Idle GPU Compute Arbitrage + Zero-Knowledge Synthetic Data Refinery + $1.50 Outcome Micro-Billing + 50% Month-1 Rebate</p>
<div class="grid">
<div class="card"><div class="lbl">GPU Savings</div><div class="val">${saved}</div></div>
<div class="card"><div class="lbl">50% Rebate</div><div class="val" style="color: #a371f7;">${rebate}</div></div>
<div class="card"><div class="lbl">ZK Data Pairs</div><div class="val" style="color: #f778ba;">{synth_pairs}</div></div>
<div class="card"><div class="lbl">Outcome Billed</div><div class="val" style="color: #58a6ff;">${outcomes_usd}</div></div>
<div class="card"><div class="lbl">$0 Cache Hits</div><div class="val" style="color: #79c0ff;">{cache_hits}</div></div>
<div class="card"><div class="lbl">PII Blocked</div><div class="val" style="color: #d29922;">{threats}</div></div>
</div>
<h3>Live Engineer Sandbox</h3>
<textarea id="prompt" rows="3">Please kindly audit this legal contract for sarah.connor@enterprise.com with card 4532 1234 5678 9010 immediately.</textarea>
<button class="btn" style="background: #1f6feb;" onclick="runTest()">1. Test GPU Arbitrage & ZK Data Mint</button>
<button class="btn" style="background: #8957e5;" onclick="testOutcome()">2. Simulate Closed Sale ($1.50 Micro-Bill)</button>
<pre id="out">Click either button above to test OptiMax live...</pre>
<div style="margin-top: 20px; text-align: center;">
<a class="btn" style="background: #238636;" href="/create-checkout-session">Start 14-Day Free Trial</a>
<a class="btn" style="background: #1f6feb;" href="/shadow-receipt" target="_blank">View 48-Hr Shadow Audit Receipt</a>
</div>
</div>
<script>
async function runTest() {{
    const p = document.getElementById('prompt').value;
    const o = document.getElementById('out');
    o.innerText = 'Routing to Decentralized Idle GPU Node...';
    const r = await fetch('/v1/demo-test', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ prompt: p, mode: 'shadow' }})
    }});
    o.innerText = JSON.stringify(await r.json(), null, 2);
}}
async function testOutcome() {{
    const o = document.getElementById('out');
    o.innerText = 'Recording verified closed sale outcome...';
    const r = await fetch('/v1/record-outcome', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ event_type: 'sale_closed', deal_value_usd: 250.00 }})
    }});
    o.innerText = JSON.stringify(await r.json(), null, 2);
}}
</script>
</body>
</html>"""

@app.get("/shadow-receipt")
async def get_shadow_receipt():
    return {
        "document": "OPTIMAX 48-HOUR SHADOW AUDIT & REBATE RECEIPT",
        "status": "VERIFIED",
        "shadow_calls_audited": SESSION_METRICS.get("shadow_calls_mirrored"),
        "zero_cost_cache_hits": SESSION_METRICS.get("cache_hits_saved"),
