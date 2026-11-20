import time, os, re, json, asyncio, httpx, sqlite3, hashlib, secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict
from cognishield_layer import CogniShieldLayer
from edge_gateway import check_device_rate_limit, get_edge_cache, set_edge_cache, ROGUE_LOOPS_BLOCKED

try:
    import psycopg2
except ImportError:
    psycopg2 = None

app = FastAPI(title="OptiMax Quantum Enterprise & Edge Gateway")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LEMON_URL = os.environ.get("LEMON_CHECKOUT_URL", "https://lemonsqueezy.com")
RAW_DB = os.environ.get("DATABASE_URL", "").strip().removeprefix("psql ").strip().strip("'\"")

USE_PG = bool(RAW_DB.startswith("postgres") and psycopg2)
shield = CogniShieldLayer()
http = httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=5.0), limits=httpx.Limits(max_keepalive_connections=50, max_connections=200))

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OptiMax Quantum | AI & Edge Gateway</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:sans-serif;background:#030712;color:#f1f5f9;display:flex;min-height:100vh;position:relative}
.glow-bg{position:fixed;inset:0;background:radial-gradient(circle at 15% 15%,rgba(56,189,248,0.12),transparent 40%);pointer-events:none !important;z-index:0}
.side,.main,.modal{position:relative;z-index:5}
button,.btn,.pre,.nav button,.sw button,a{position:relative;z-index:10;cursor:pointer !important}
.side{width:230px;background:#0a0f1c;border-right:1px solid #1e293b;padding:18px 12px;display:flex;flex-direction:column;justify-content:space-between}
.nav button{display:block;width:100%;background:none;border:none;color:#94a3b8;padding:10px;border-radius:8px;text-align:left;font-size:13.5px;font-weight:600;margin-top:4px}
.nav button.active,.nav button:hover{background:#1e293b;color:#38bdf8}
.main{flex:1;padding:20px;max-width:1050px;margin:0 auto;width:100%}
.bar{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;background:#0a0f1c;border:1px solid #1e293b;padding:10px 14px;border-radius:10px;margin-bottom:16px}
.sw button{background:#030712;border:1px solid #334155;color:#94a3b8;padding:6px 12px;border-radius:16px;font-size:12px;font-weight:700}
.sw button.active{background:#00f5d4;color:#022c22;border-color:#00f5d4}
.kpis,.presets{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}
.kpi,.pre{background:#0f172a;border:1px solid #1e293b;padding:12px;border-radius:10px}
.pre{text-align:left;color:#cbd5e1;font-size:12px}.pre.active{border-color:#00f5d4;background:rgba(0,245,212,0.1);color:#fff}
.panel{display:none;background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:18px}.panel.active{display:block}
input,textarea{width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#030712;color:#fff;margin:6px 0 10px;font-size:13px}
.btn{background:#0284c7;color:#fff;border:none;padding:9px 15px;border-radius:8px;font-weight:700;text-decoration:none;display:inline-block;font-size:12.5px}
.cta{background:#00f5d4;color:#022c22;font-weight:800}
pre{background:#020617;border:1px solid #1e293b;padding:12px;border-radius:8px;color:#00f5d4;white-space:pre-wrap;font-size:12px;margin:8px 0}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.85);align-items:center;justify-content:center;z-index:50;padding:16px}
.mbox{background:#0f172a;border:1px solid #00f5d4;border-radius:12px;padding:22px;max-width:420px;width:100%;text-align:center}
@media(max-width:768px){body{flex-direction:column}.side{width:100%}.nav{display:flex;overflow-x:auto}.kpis,.presets{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="glow-bg"></div>
<div class="side">
  <div>
    <b style="color:#00f5d4;font-size:16px">⚡ OPTIMAX QUANTUM</b>
    <div class="nav">
      <button data-act="tab" data-t="play" class="active">⚡ Neural Playground</button>
      <button data-act="tab" data-t="ide">🔌 Connect IDE</button>
      <button data-act="tab" data-t="iot">📡 Edge & IoT Fleet</button>
      <button data-act="tab" data-t="logs">📊 Route Trace Log</button>
      <button data-act="tab" data-t="keys">🔑 14-Day Trial Key</button>
    </div>
  </div>
  <a href="/upgrade" target="_blank" class="btn cta" style="text-align:center">Upgrade Enterprise</a>
</div>
<div class="main">
  <div class="bar">
    <span style="color:#00f5d4;font-size:12px;font-weight:700">🛡️ Zero-Data-Retention: ACTIVE</span>
    <div class="sw">
      <button id="sw-me" data-act="role" data-r="me" class="active">Personal View</button>
      <button id="sw-org" data-act="role" data-r="org">Team Admin</button>
    </div>
    <input id="key" value="optx_free_trial_user" style="width:200px;margin:0;padding:6px 10px;font-size:12px">
  </div>
  <div class="kpis">
    <div class="kpi"><small id="l1">Personal Savings</small><div id="v1" style="font-size:20px;font-weight:800;color:#00f5d4">$0.00</div></div>
    <div class="kpi"><small id="l2">Tokens Routed</small><div id="v2" style="font-size:20px;font-weight:800;color:#38bdf8">0</div></div>
    <div class="kpi"><small id="l3">PII Masked</small><div id="v3" style="font-size:20px;font-weight:800">0</div></div>
  </div>
  <div id="play" class="panel active">
    <div class="presets">
      <button data-act="mode" data-m="max_savings" class="pre active"><b>💰 Max Savings (74% Off)</b><br><small>Fast low-cost models</small></button>
      <button data-act="mode" data-m="balanced" class="pre"><b>⚖️ Balanced Quality</b><br><small>Frontier plan + fast exec</small></button>
      <button data-act="mode" data-m="strict_privacy" class="pre"><b>🔒 Strict Privacy</b><br><small>Zero-retention + PII mask</small></button>
    </div>
    <textarea id="prm" rows="3" placeholder="Enter code or prompt..."></textarea>
    <button data-act="route" class="btn">Execute Neural Route →</button>
    <pre id="out">// Ready...</pre>
  </div>
  <div id="ide" class="panel">
    <h3 style="margin-top:0">🔌 Connect IDE</h3>
    <div style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap">
      <button data-act="ide" data-i="cursor" class="btn">Cursor</button>
      <button data-act="ide" data-i="cline" class="btn">Cline</button>
      <button data-act="ide" data-i="windsurf" class="btn">Windsurf</button>
      <button data-act="ide" data-i="python" class="btn">Python SDK</button>
    </div>
    <pre id="ideBox" style="color:#38bdf8"></pre>
    <button data-act="copy-ide" class="btn cta">📋 Copy Config</button>
  </div>
  <div id="iot" class="panel">
    <h3 style="margin-top:0">📡 Edge & IoT Fleet</h3>
    <button data-act="iot" class="btn cta">+ Generate IoT Device Key</button>
    <pre id="iotBox" style="color:#38bdf8">// Demo fleet key: optx_live_prod_99x1</pre>
  </div>
  <div id="logs" class="panel"><h3 style="margin-top:0">📊 Route Trace Log</h3><div id="logBox">No traces yet.</div></div>
  <div id="keys" class="panel">
    <h3 style="margin-top:0">🔑 14-Day Trial Key</h3>
    <div style="display:flex;gap:8px;margin-bottom:10px">
      <input id="trialBox" value="optx_free_trial_user" readonly style="margin:0">
      <button data-act="copy-key" class="btn">📋 Copy Key</button>
    </div>
    <form action="/start-trial" method="post">
      <input name="name" placeholder="Name or Team" required>
      <input name="email" type="email" placeholder="Work Email" required>
      <button type="submit" class="btn cta">Generate New Trial Key →</button>
    </form>
  </div>
</div>
<div id="upModal" class="modal"><div class="mbox">
  <h3 style="color:#00f5d4;margin-top:0">🔒 Team Admin Locked</h3>
  <p style="font-size:13px">Upgrade via Lemon Squeezy to unlock Team Admin & IoT Fleet view.</p>
  <a href="/upgrade" target="_blank" class="btn cta">Upgrade Now →</a>
  <button data-act="close" class="btn" style="background:#334155">Close</button>
</div></div>
<script>
document.addEventListener('DOMContentLoaded',()=>{
  let ROLE='me',MODE='max_savings',IDE='cursor';
  const kVal=()=>document.getElementById('key')?.value.trim()||'optx_free_trial_user';
  function showIDE(t){IDE=t;const k=kVal(),u='https://onrender.com c={cursor:`{\n  "openai.apiKey": "${k}",\n  "openai.baseUrl": "${u}"\n}`,cline:`{\n  "apiProvider": "openai",\n  "openAiBaseUrl": "${u}",\n  "openAiApiKey": "${k}"\n}`,windsurf:`{\n  "windsurf.customApiUrl": "${u}",\n  "windsurf.apiKey": "${k}"\n}`,python:`from openai import OpenAI\nclient = OpenAI(api_key="${k}", base_url="${u}")`};const b=document.getElementById('ideBox');if(b)b.textContent=c[IDE]}
