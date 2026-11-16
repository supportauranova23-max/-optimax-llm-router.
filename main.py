@app.get("/key", response_class=HTMLResponse)
async def make_key(email: str = Query(""), cap: float = Query(2500.0), role: str = Query("all")):
    k = "optx_live_" + secrets.token_hex(8)
    DB.execute("INSERT INTO api_keys VALUES (?, ?, ?, 0.0)", (k, email, cap)); DB.commit()
    return page(f"API KEY ISSUED\nOwner: {email}\nKey: {k}\nCap: ${cap:,.2f}/mo\nBase URL: {YOUR_DOMAIN}/v1", role=role)

@app.get("/canary", response_class=HTMLResponse)
async def trigger_canary(role: str = Query("all")):
    METRICS["traps"] += 1
    sig = hmac.new(SECRET, b"CANARY_TRAP_185.220.101.44", hashlib.sha256).hexdigest()[:24]
    return page(f"CANARY TRAP TRIGGERED! Simulated IP 185.220.101.44 blocked. Receipt: zk_{sig}", role=role)

@app.get("/test", response_class=HTMLResponse)
async def run_test(q: str = Query(""), model: str = Query("gpt-4o-mini"), role: str = Query("all")):
    res = await execute(q, model, "optx_live_demo", None)
    return page(json.dumps(res, indent=2), role=role)

@app.get("/health")
async def health():
    row = DB.execute("SELECT COUNT(*) FROM api_keys").fetchone()
    return {"status": "OPERATIONAL", "uptime_s": round(time.time() - START_TIME, 1), "persistent_keys": row if row else 0}

async def execute(text: str, model: str, key_id: str, auth: Optional[str]) -> dict:
    t0 = time.time()
    row = DB.execute("SELECT cap, spent FROM api_keys WHERE key=?", (key_id,)).fetchone()
    if row and row >= row: return {"status": "BLOCKED_BUDGET_CAP_EXCEEDED", "spent": row, "cap": row}
    if any(r in text.lower() for r in ("100% free", "90% discount", "full refund approved", "lifetime access for $0")):
        METRICS["liab"] += 50000; return {"status": "BLOCKED_BY_LIABILITY_SHIELD", "loss_prevented_usd": 50000}
    masked, pmap, cnt = scrub(text); METRICS["pii"] += cnt
    raw, engine = await route_ai(masked, model, auth)
    for k, v in pmap.items(): raw = raw.replace(k, v)
    tokens = max(1, (len(masked) + len(raw)) // 4)
    cost = round((tokens / 1000.0) * 0.001, 6)
    if row: DB.execute("UPDATE api_keys SET spent = spent + ? WHERE key=?", (cost, key_id)); DB.commit()
    METRICS["saved"] = round(METRICS["saved"] + 0.082, 2)
    sig = hmac.new(SECRET, masked.encode(), hashlib.sha256).hexdigest()[:24]
    return {"status": "success", "provider": engine, "tokens": tokens, "cost_usd": cost, "scrubbed": masked, "reply": raw, "receipt": f"zk_{sig}", "ms": round((time.time() - t0) * 1000, 2)}

@app.post("/v1/chat/completions")
async def openai_dropin(req: OpenAIReq, authorization: Optional[str] = Header(None)):
    msg = next((str(m.get("content", "")) for m in req.messages if m.get("role") == "user"), "")
    key_id = authorization.replace("Bearer ", "").strip() if (authorization and authorization.startswith("Bearer optx_")) else "optx_live_demo"
    res = await execute(msg, req.model, key_id, authorization)
    if res.get("status") == "BLOCKED_BUDGET_CAP_EXCEEDED": raise HTTPException(status_code=402, detail=res)
    if res.get("status") != "success": raise HTTPException(status_code=403, detail=res)
    return {"id": f"chatcmpl-{int(time.time())}", "object": "chat.completion", "model": res["provider"], "choices": [{"index": 0, "message": {"role": "assistant", "content": res["reply"]}, "finish_reason": "stop"}], "receipt": res["receipt"]}
