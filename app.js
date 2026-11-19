function tab(id, b) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav button').forEach(x => x.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  if (b) b.classList.add('active');
}

function setDemo(t) {
  document.getElementById('prm').value = t;
  runAI();
}

function copyTxt(t, b) {
  navigator.clipboard.writeText(t);
  const old = b.textContent;
  b.textContent = '✓ Copied!';
  setTimeout(() => b.textContent = old, 1500);
}

let ALL_M = [];
fetch('/v1/models').then(r => r.json()).then(d => {
  ALL_M = d.data || [];
  filterM();
});

function filterM() {
  const q = (document.getElementById('mSearch').value || '').toLowerCase();
  document.getElementById('mList').innerHTML = ALL_M
    .filter(m => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q))
    .map(m => `<div style='padding:10px;border-bottom:1px solid #1e293b;display:flex;justify-content:space-between;align-items:center'><span><b>${m.name}</b> <small style='color:#94a3b8'>(${m.in_price})</small></span><button class='btn' style='padding:5px 12px;font-size:12px' onclick="pickM('${m.id}')">Test →</button></div>`)
    .join('');
}

function pickM(id) {
  const s = document.getElementById('mod');
  if (![...s.options].some(o => o.value === id)) s.add(new Option(id, id));
  s.value = id;
  tab('test', document.getElementById('b-test'));
}

async function runAI() {
  const o = document.getElementById('out');
  o.style.color = '#38bdf8';
  o.textContent = 'Running PII X-Ray & Neural Route...';
  try {
    const r = await fetch('/v1/route', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + document.getElementById('key').value.trim()
      },
      body: JSON.stringify({
        prompt: document.getElementById('prm').value,
        model: document.getElementById('mod').value
      })
    });
    const d = await r.json();
    o.style.color = r.ok ? '#00f5d4' : '#f87171';
    o.textContent = JSON.stringify(d, null, 2);
  } catch (e) {
    o.style.color = '#f87171';
    o.textContent = e.toString();
  }
}
