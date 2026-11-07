import time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="OptiMax: Intelligent AI API Cost Management Router")

class PromptRequest(BaseModel):
    prompt: str

# Unified Enterprise Dashboard UI & Live Frontend Sandbox Engine
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OptiMax | Enterprise Gateway Command Center</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            background-color: #0B0914;
            color: #FFFFFF;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        .navbar {
            background-color: #161329;
            padding: 20px 40px;
            border-bottom: 1px solid #2D284E;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .logo {
            font-size: 24px;
            font-weight: 900;
            letter-spacing: 1px;
        }
        .logo-highlight { color: #FF007F; }
        .status-badge {
            background-color: #0C2626;
            color: #00F0FF;
            border: 1px solid #00F0FF;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
        }
        .container {
            max-width: 1200px;
            margin: 50px auto;
            padding: 0 20px;
        }
        .header {
            margin-bottom: 40px;
        }
        .header h1 {
            font-size: 36px;
            margin: 0 0 10px 0;
            font-weight: 800;
        }
        .header p {
            color: #999;
            margin: 0;
            font-size: 16px;
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 24px;
            margin-bottom: 40px;
        }
        .card {
            background-color: #161329;
            border: 1px solid #2D284E;
            border-radius: 12px;
            padding: 24px;
        }
        .card-title {
            color: #999;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }
        .card-value {
            font-size: 32px;
            font-weight: 800;
            color: #FFF;
        }
        .value-pink { color: #FF007F; }
        .value-cyan { color: #00F0FF; }
        
        /* Sandbox Interactive Workspace CSS */
        .sandbox-section {
            background-color: #161329;
            border: 1px solid #2D284E;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 40px;
        }
        .sandbox-title {
            font-size: 20px;
            font-weight: 800;
            margin-bottom: 8px;
        }
        .sandbox-subtitle {
            color: #999;
            font-size: 14px;
            margin-bottom: 20px;
        }
        .input-group {
            display: flex;
            gap: 15px;
            margin-bottom: 25px;
        }
        .text-input {
            flex: 1;
            background-color: #0B0914;
            border: 1px solid #2D284E;
            color: #FFF;
            padding: 15px;
            border-radius: 8px;
            font-size: 16px;
        }
        .text-input:focus {
            outline: none;
            border-color: #FF007F;
        }
        .action-btn {
            background-color: #FF007F;
            color: white;
            border: none;
            padding: 0 30px;
            border-radius: 8px;
            font-weight: 700;
            font-size: 15px;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .action-btn:hover { opacity: 0.9; }
        
        .output-display {
            background-color: #05040A;
            border: 1px solid #2D284E;
            border-radius: 8px;
            padding: 20px;
            display: none;
        }
        .output-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #2D284E;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }
        .output-tag {
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .tag-route { color: #00F0FF; }
        .tag-cost { color: #FF007F; }
        .code-payload {
            font-family: 'Courier New', Courier, monospace;
            color: #00F0FF;
            white-space: pre-wrap;
            margin: 0;
        }
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
            <p>Automated infrastructure cost management layer running on edge global nodes.</p>
        </div>

        <div class="metrics-grid">
            <div class="card">
                <div class="card-title">Compute Efficiency</div>
                <div class="card-value value-cyan">84.6%</div>
            </div>
            <div class="card">
                <div class="card-title">Infrastructure Costs Eliminated</div>
                <div class="card-value value-pink">$14,240</div>
            </div>
            <div class="card">
                <div class="card-title">Active Sharded Networks</div>
                <div class="card-value">2 Live Clusters</div>
            </div>
        </div>

        <!-- Live Sandbox Terminal Tool -->
        <div class="sandbox-section">
            <div class="sandbox-title">Interactive Gateway Sandbox</div>
            <div class="sandbox-subtitle">Simulate real user prompts to test matrix caching speed and cost saving decisions.</div>
            
            <div class="input-group">
                <input type="text" id="promptInput" class="text-input" placeholder="Type a prompt here (e.g., 'hello', or ask a long question)...">
                <button onclick="simulateRoute()" class="action-btn">ROUTE METRICS</button>
            </div>

            <div id="outputDisplay" class="output-display">
                <div class="output-header">
                    <span id="routeBadge" class="output-tag tag-route">ROUTED TO: PENDING</span>
                    <span id="costBadge" class="output-tag tag-cost">COST INCURRED: $0.00</span>
                </div>
                <pre id="jsonOutput" class="code-payload"></pre>
            </div>
        </div>
    </div>

    <script>
        async function simulateRoute() {
            const promptText = document.getElementById('promptInput').value;
            if(!promptText.trim()) return;
            
            const displayBlock = document.getElementById('outputDisplay');
            const routeBadge = document.getElementById('routeBadge');
            const costBadge = document.getElementById('costBadge');
            const jsonOutput = document.getElementById('jsonOutput');
            
            displayBlock.style.display = 'block';
            jsonOutput.innerText = "Processing computational shard vectors...";

            try {
                const response = await fetch('/v1/route', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ prompt: promptText })
                });
                const data = await response.json();
                
                routeBadge.innerText = "ROUTED TO: " + data.routed_to.toUpperCase();
                costBadge.innerText = "COST INCURRED: $" + data.cost_incurred_usd.toFixed(5);
                jsonOutput.innerText = JSON.stringify(data, null, 4);
            } catch (err) {
                jsonOutput.innerText = "Error tracking live API gateway parameters.";
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serves the interactive infrastructure dashboard screen."""
    return DASHBOARD_HTML

@app.post("/v1/route")
def route_prompt(request: PromptRequest):
    """Processes computational complexity parameters to optimize cloud costs."""
    start_time = time.time()
    clean_prompt = request.prompt.strip().lower()

    # Fixed Local Matrix Caching Layer
    semantic_cache = {
        "hello": "Hello! How can I optimize your compute budget today?",
        "what is your name": "I am the OptiMax AI Routing Engine.",
        "help": "Route your prompts to this endpoint to slash your infrastructure bills."
    }

    # Step 1: Hit Cache ($0 Overhead)
    if clean_prompt in semantic_cache:
        return {
            "response": semantic_cache[clean_prompt],
            "routed_to": "Local SaaS Cache Layer",
            "cost_saved_usd": 0.0350,
            "cost_incurred_usd": 0.0000,
            "latency_ms": (time.time() - start_time) * 1000
        }

    # Step 2: Short Conversational Input -> Route to Open-Source Nodes
    if len(clean_prompt.split()) <= 5:
        return {
            "response": f"[Lean Core Answer processed for: {request.prompt}]",
            "routed_to": "Meta Llama-3-Lean Cluster",
            "cost_saved_usd": 0.0345,
            "cost_incurred_usd": 0.00005,
            "latency_ms": (time.time() - start_time) * 1000
        }

    # Step 3: Complex Cognitive Logic -> Route to Heavy Premium Clusters
    return {
        "response": f"[Comprehensive Data Payload calculated for: {request.prompt}]",
        "routed_to": "Premium Array (OpenAI GPT-4o / Google Gemini Pro)",
