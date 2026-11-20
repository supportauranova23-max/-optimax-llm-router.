document.addEventListener('DOMContentLoaded', () => {
  let ROLE = 'me', PRESET = 'max_savings', CUR_IDE = 'cursor';
  const getKey = () => (document.getElementById('key')?.value || 'optx_free_trial_user').trim();

  function renderIDE() {
    const box = document.getElementById('ideBox');
    if (!box) return;
    const k = getKey(), u = 'https://onrender.com';
    const cfg = {
      cursor: `{\n  "openai.apiKey": "${k}",\n  "openai.baseUrl": "${u}"\n}`,
      cline: `{\n  "apiProvider": "openai",\n  "openAiBaseUrl": "${u}",\n  "openAiApiKey": "${k}"\n}`,
      windsurf: `{\n  "windsurf.customApiUrl": "${u}",\n  "windsurf.apiKey": "${k}"\n}`,
      python: `from openai import OpenAI\n\nclient = OpenAI(\n    api_key="${k}",\n    base_url="${u}"\n)`
    };
    box.textContent = cfg[CUR_IDE] || cfg.cursor;
  }

  async function switchRole(r) {
    try {
      const res = await fetch(r === 'org' ? '/api/dashboard/org' : '/api/dashboard/me', {
        headers: { 'Authorization': 'Bearer ' + getKey() }
      });
      const d = await res.json();
      if (res.status === 403 && d.upgrade_required) {
        const m = document.getElementById('upModal');
        if (m) m.style.display = 'flex';
        return;
      }
      ROLE = r;
      document.getElementById('sw-me')?.classList.toggle('active', r === 'me');
      document.getElementById('sw-org')?.classList.toggle('active', r === 'org');
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      set('k1-lbl', r === 'me' ? 'Personal Savings' : 'Org Savings');
      set('k1-val', '$' + (r === 'me' ? (d.saved_usd || 0) : (d.org_saved_usd || 0)));
      set('k2-lbl', r === 'me' ? 'Tokens Routed' : 'Active IoT Devices');
      set('k2-val', r === 'me' ? (d.tokens_routed || 0) : (d.active_iot_devices || 0));
      set('k3-lbl', r === 'me' ? 'PII Masked' : 'Rogue Loops Blocked');
      set('k3-val', r === 'me' ? (d.pii_masked || 0) : (d.rogue_loops_blocked || 0));
      const feed = document.getElementById('logFeed');
      if (feed) feed.innerHTML = (d.logs || []).map(l => `<div style="padding:8px;border-bottom:1px solid #1e293b"><b>[${l.device_id}]</b> ${l.model} • ${l.tokens} tok • ${l.latency}ms • <span style="color:#00f5d4">Saved $${l.saved}</span></div>`).join('') || 'No traces yet.';
    } catch (e) { console.error('[OptiMax]', e); }
  }

  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const act = btn.dataset.action;

    if (act === 'tab') {
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
      document.getElementById(btn.dataset.target)?.classList.add('active');
      btn.classList.add('active');
    } else if (act === 'preset') {
      PRESET = btn.dataset.preset;
      document.querySelectorAll('.pre-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    } else if (act === 'ide') {
      CUR_IDE = btn.dataset.ide;
      renderIDE();
    } else if (act === 'copy-ide') {
      const box = document.getElementById('ideBox');
      if (box) navigator.clipboard.writeText(box.textContent);
      btn.textContent = '✓ Copied!';
      setTimeout(() => btn.textContent = '📋 Copy Config', 1500);
    } else if (act === 'copy-trial') {
      const td = document.getElementById('trialDisplay');
      if (td) navigator.clipboard.writeText(td.value);
      btn.textContent = '✓ Copied!';
      setTimeout(() => btn.textContent = '📋 Copy Key', 1500);
    } else if (act === 'role') {
      await switchRole(btn.dataset.role);
    } else if (act === 'close-modal') {
      const m = document.getElementById('upModal');
      if (m) m.style.display = 'none';
    } else if (act === 'gen-iot') {
      const box = document.getElementById('iotKeyBox');
      if (box) box.textContent = 'Generating IoT Key...';
      const r = await fetch('/api/keys/iot', { method: 'POST', headers: { 'Authorization': 'Bearer ' + getKey() } });
      const d = await r.json();
      if (box) box.textContent = r.ok ? ('New IoT Key: ' + d.api_key) : JSON.stringify(d);
    } else if (act === 'run-route') {
      const out = document.getElementById('out'), prm = document.getElementById('prm');
      if (out) out.textContent = 'Routing (' + PRESET + ')...';
      const r = await fetch('/v1/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + getKey() },
        body: JSON.stringify({ prompt: prm ? prm.value : '', preset: PRESET })
      });
      const d = await r.json();
      if (out) out.textContent = JSON.stringify(d, null, 2);
      await switchRole(ROLE);
    }
  });

  renderIDE();
  switchRole('me');
});
