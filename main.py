@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(content=UI_A + UI_B)

@app.get("/v1/admin/stats")
async def admin_stats():
    conn, _ = get_db()
    cur = conn.cursor()
    cur.execute("SELECT api_key, key_alias, tier, requests, spend_usd, saved_usd, max_budget_usd FROM litellm_keys")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    keys = [
        {"key": k_val[:12] + "...", "alias": alias, "tier": tier, "reqs": int(reqs), "spend": float(spend), "saved": float(saved), "budget": float(budget)}
        for k_val, alias, tier, reqs, spend, saved, budget in rows
    ]
    return {"keys": keys, "total_reqs": sum(k["reqs"] for k in keys), "total_saved": sum(k["spend"] for k in keys)}

@app.post("/start-trial", response_class=HTMLResponse)
async def start_trial(name: str = Form(...), email: str = Form(...)):
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT api_key FROM litellm_keys WHERE email = {ph}", (email,))
    row = cur.fetchone()
    if row:
        (key,) = row
    else:
        key = f"optx_trial_{secrets.token_hex(8)}"
        cur.execute(f"INSERT INTO litellm_keys VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})", (key, name, email, "trial", datetime.utcnow().isoformat(), 0, 0.0, 0.0, 15.0))
        conn.commit()
    cur.close()
    conn.close()
    return HTMLResponse(content=f"<body style='background:#090d16;color:#fff;font-family:sans-serif;text-align:center;padding:60px'><h2 style='color:#10b981'>🎉 You're In! 14-Day Trial Key Active</h2><p>Copy Key: <b style='color:#38bdf8'>{key}</b></p><a href='/' style='color:#38bdf8'>← Return to OptiMax Proxy Console</a></body>")

@app.get("/upgrade")
async def upgrade():
    return RedirectResponse(url=LEMON_URL, status_code=303)

@app.post("/v1/route")
async def route(req: PromptReq, user: dict = Depends(verify_user)):
    t0 = time.perf_counter()
    verdict = shield.inspect_payload(req.prompt)
    if not verdict.get("safe", True):
        raise HTTPException(status_code=400, detail=f"Blocked: {verdict.get('reason')}")
    ans, used_model, cached = await route_ai(req.prompt, req.model)
    lat = round((time.perf_counter() - t0) * 1000, 2)
    raw_cost = round(max(0.0005, (len(req.prompt) + len(ans)) * 0.000001), 6)
    actual_cost = 0.0 if cached else round(raw_cost * 0.257, 6)
    saved_call = round(raw_cost - actual_cost, 6)
    pct_cut = "100.0%" if cached else "74.3%"
    new_spend = round(user["spend"] + actual_cost, 6)
    new_saved = round(user["saved"] + saved_call, 6)
    conn, ph = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE litellm_keys SET requests = {ph}, spend_usd = {ph}, saved_usd = {ph} WHERE api_key = {ph}", (user["reqs"] + 1, new_spend, new_saved, user["token"]))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "coding_cost_cut": pct_cut, "saved_this_call_usd": saved_call, "total_saved_usd": new_saved, "model": used_model, "cached": cached, "latency_ms": lat, "response": ans}

@app.post("/webhook/lemonsqueezy")
async def webhook(request: Request):
    data = await request.json()
    if data.get("meta", {}).get("event_name") in ["order_created", "subscription_created"]:
        email = data.get("data", {}).get("attributes", {}).get("user_email")
        if email:
            conn, ph = get_db()
            cur = conn.cursor()
            cur.execute(f"UPDATE litellm_keys SET tier = 'enterprise', max_budget_usd = 5000.0 WHERE email = {ph}", (email,))
            conn.commit()
            cur.close()
            conn.close()
    return {"status": "ok"}

@app.post("/v1/chat/completions")
async def openai_dropin(req: dict, user: dict = Depends(verify_user)):
    msgs = req.get("messages", [])
    prompt = msgs[-1].get("content", "") if msgs else ""
    verdict = shield.inspect_payload(prompt)
    if not verdict.get("safe", True):
        raise HTTPException(status_code=400, detail=f"Blocked: {verdict.get('reason')}")
    ans, used_model, _ = await route_ai(prompt, req.get("model", "auto"))
    return {"id": f"chatcmpl-{secrets.token_hex(6)}", "object": "chat.completion", "created": int(time.time()), "model": used_model, "choices": [{"index": 0, "message": {"role": "assistant", "content": ans}, "finish_reason": "stop"}]}
