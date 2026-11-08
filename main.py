import time
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

# ---> INTEGRATE COGNISHIELD COGNITIVE INFRASTRUCTURE MIDDLEWARE
from cognishield_layer import CogniShieldLayer

app = FastAPI(title="OptiMax: Intelligent AI API Cost Management Router")

# Initialize the cognitive firewall engine
shield = CogniShieldLayer()

# Live Commercial Database of Authorized Enterprise API Keys
VALID_API_KEYS = {
    "optx_live_dev_78x92": "Alpha Tech Ventures (Dev Tier)",
    "optx_live_scale_11a42": "Nexus AI Core (Scale Tier)",
    "optx_live_enterprise_99z00": "Global Finance Shard (Enterprise Tier)"
}

class PromptRequest(BaseModel):
    prompt: str

# Dependency gate to protect algorithmic shards from unauthorized token burn
def verify_api_key(x_optimax_key: Optional[str] = Header(None)):
    if x_optimax_key not in VALID_API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid or unauthorized OptiMax API Key header credentials.")
    return VALID_API_KEYS[x_optimax_key]

# CORE ROUTER API GATEWAY ENDPOINT WITH ACTIVE COGNITIVE FIREWALLING
@app.post("/v1/route")
async def route_llm_request(payload: PromptRequest, client_org: str = Depends(verify_api_key)):
    start_time = time.time()
    
    # 1. RUN PAYLOAD STREAM THROUGH COGNISHIELD LAYER BEFORE WASTING LLM REVENUE
    assessment = shield.analyze_stream(payload.prompt)
    
    if assessment["recommended_route"] == "shield_block_payload":
        return {
            "status": "Shielded",
            "org": client_org,
            "shield_score": assessment["risk_score"],
            "selected_model": "None (Intercepted)",
            "latency_ms": round((time.time() - start_time) * 1000, 2),
            "response": "[⚠️ CogniShield High-Risk Intercept]: This data payload contains high algorithmic manipulation risk patterns or financial scam signatures."
        }
        
    # 2. STANDARD RUNTIME REVENUE-SAVING CALCULATOR LOGIC
    # Heuristic algorithm selects the ideal cheap vs expensive engine route
    prompt_len = len(payload.prompt)
    if prompt_len < 100:
        selected_model = "meta-llama/llama-3-8b-instruct"
        route_decision = "Lite Compute Tier"
        estimated_cost_saved = 0.0015
    else:
        selected_model = "openai/gpt-4o-mini"
        route_decision = "Premium Cognitive Tier"
        estimated_cost_saved = 0.0084

    return {
        "status": "Success",
        "org": client_org,
        "selected_model": selected_model,
        "route_allocation": route_decision,
        "cost_saved_usd": estimated_cost_saved,
        "latency_ms": round((time.time() - start_time) * 1000, 2),
        "response": f"Processed via optimized path on {selected_model}"
    }

# Unified B2B E-Commerce Storefront, Pricing Layout, and Interactive Sandbox Studio
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OptiMax | Enterprise Gateway Command Center</title>
    <style>
        body { margin: 0; padding: 0; background-color: #0B0914; color: #FFFFFF; font-family: 'Segoe UI', sans-serif; }
        .navbar { background-color: #161329; padding: 20px 40px; border-bottom: 1px solid #2D284E; display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 24px; font-weight: 900; letter-spacing: 1px; }
        .logo-highlight { color: #FF007F; }
        .status-badge { background-color: #0C2626; color: #00F0FF; border: 1px solid #00F0FF; padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 700; text-transform: uppercase; }
        .container { max-width: 1200px; margin: 50px auto; padding: 0 20px; }
        .header { margin-bottom: 40px; }
        .header h1 { font-size: 36px; margin: 0 0 10px 0; font-weight: 800; }
        .header p { color: #999; margin: 0; font-size: 16px; }
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; margin-bottom: 40px; }
        .card { background-color: #161329; border: 1px solid #2D284E; border-radius: 12px; padding: 24px; }
        .card-title { color: #999; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; }
        .card-value { font-size: 32px; font-weight: 800; color: #FFF; }
        .value-pink { color: #FF007F; }
        .value-cyan { color: #00F0FF; }
        
        .pricing-section { margin-bottom: 50px; }
        .pricing-title { font-size: 24px; font-weight: 800; margin-bottom: 20px; border-left: 4px solid #FF007F; padding-left: 15px; }
        .pricing-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px; }
        .price-card { background-color: #161329; border: 1px solid #2D284E; border-radius: 12px; padding: 30px; text-align: center; position: relative; }
        .price-card.featured { border-color: #FF007F; box-shadow: 0 0 15px rgba(255, 0, 127, 0.2); }
        .price-tier { font-size: 14px; text-transform: uppercase; color: #999; font-weight: 700; letter-spacing: 1px; }
        .price-amt { font-size: 42px; font-weight: 800; margin: 15px 0; color: #FFF; }
        .price-amt span { font-size: 16px; color: #999; }
        .price-features { list-style: none; padding: 0; margin: 20px 0; text-align: left; color: #CCC; font-size: 14px; }
        .price-features li { margin-bottom: 10px; }
        .price-features li::before { content: "✓ "; color: #00F0FF; margin-right: 8px; font-weight: bold; }
        .buy-btn { display: block; width: 100%; padding: 14px 0; background-color: #2D284E; color: white; border: none; border-radius: 6px; font-weight: 700; text-decoration: none; cursor: pointer; font-size: 14px; transition: opacity 0.2s; }
        .buy-btn.pink-btn { background-color: #FF007F; }
        .buy-btn:hover { opacity: 0.9; }

        .sandbox-section { background-color: #161329; border: 1px solid #2D284E; border-radius: 12px; padding: 30px; margin-bottom: 40px; }
        .sandbox-title { font-size: 20px; font-weight: 800; margin-bottom: 8px; }
        .sandbox-subtitle { color: #999; font-size: 14px; margin-bottom: 20px; }
        .input-group { display: grid; grid-template-columns: 1fr auto; gap: 15px; margin-bottom: 15px; }
        .key-group { display: flex; gap: 15px; margin-bottom: 15px; }
        .text-input { background-color: #0B0914; border: 1px solid #2D284E; color: #FFF; padding: 15px; border-radius: 8px; font-size: 16px; width: 100%; box-sizing: border-box; }
        .text-input:focus { outline: none; border-color: #FF007F; }
        .action-btn { background-color: #FF007F; color: white; border: none; padding: 0 30px; border-radius: 8px; font-weight: 700; font-size: 15px; cursor: pointer; }
        .output-display { background-color: #05040A; border: 1px solid #2D284E; border-radius: 8px; padding: 20px; display: none; }
        .output-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #2D284E; padding-bottom: 10px; margin-bottom: 15px; }
        .output-tag { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; }
        .tag-route { color: #00F0FF; }
        .tag-cost { color: #FF007F; }
        .code-payload { font-family: 'Courier New', monospace; color: #00F0FF; white-space: pre-wrap; margin: 0; }
        .webhook-log-box { margin-top: 20px; background-color: #05040A; border: 1px dashed #2D284E; padding: 15px; border-radius: 6px; font-size: 12px; font-family: monospace; color: #999; text-align: left; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="logo">OPTI<span class="logo-highlight">MAX</span></div>
        <div class="status-badge">⚡ Engine Online</div>
    </div>
    <div class="container">
        <div class="header">
            <h1>Platform Workspace</h1>
            <p>Automated infrastructure cost management layer running on edge global nodes with integrated CogniShield.</p>
        </div>
        <div class="metrics-grid">
            <div class="card"><div class="card-title">Compute Efficiency</div><div class="card-value value-cyan">94.2%</div></div>
            <div class="card"><div class="card-title">Infrastructure Costs Eliminated</div><div class="card-value value-pink">$14,240</div></div>
            <div class="card"><div class="card-title">Active Sharded Networks</div><div class="card-value">CogniShield Layer Active</div></div>
        </div>

        <div class="pricing-section">
            <div class="pricing-title">Commercial API Subscription Plans</div>
            <div class="pricing-grid">
                <div class="price-card">
                    <div class="price-tier">Startup Tier</div>
                    <div class="price-amt">$49<span>/mo</span></div>
                    <ul class="price-features">
                        <li>Up to 5 Million Monthly Requests</li>
                        <li>Automated Local Matrix Caching</li>
                        <li>Standard Meta Llama Core Sharding</li>
                    </ul>
                    <button class="buy-btn">Subscribe Startup</button>
                </div>
                <div class="price-card featured">
                    <div class="price-tier" style="color:#FF007F;">Scale Optimization Tier</div>
                    <div class="price-amt">$249<span>/mo</span></div>
                    <ul class="price-features">
                        <li>Up to 50 Million Requests / Mo</li>
                        <li>Advanced Semantic Vector Cache</li>
                        <li>Full Premium Array Routing (GPT-4o)</li>
                        <li>Dedicated Infrastructure SLA Support</li>
                    </ul>
                    <button class="buy-btn pink-btn">Subscribe Scale Tier</button>
                </div>
            </div>
