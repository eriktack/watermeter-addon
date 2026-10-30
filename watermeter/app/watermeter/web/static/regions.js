// Regions page (C2). State = the regions JSON of api/regions; all URLs are relative (ingress).
// A line (volume, flow) is two groups, whole digits and decimals: one box each, split into `count` equal digits.
(() => {
  const $ = id => document.getElementById(id);
  const COLORS = { mark: '#d1832a', volume: '#1a9f37', flow: '#2f81f7' };
  const LINES = ['volume', 'flow'], GROUPS = ['whole', 'decimals'];
  const DEFAULT_COUNT = { whole: 6, decimals: 3 };
  const state = { ref: null, rotation: 0, marks: [null, null], names: ['logo', 'text'], volume: null, flow: null, selected: null };
  const canvas = $('canvas'), ctx = canvas.getContext('2d');
  let image = null, scale = 1, drag = null, dirty = false;

  const json = async (url, opts) => {
    const r = await fetch(url, opts);
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || r.statusText);
    return body;
  };
  const say = (text, bad) => { $('status').textContent = text; $('status').className = bad ? 'bad' : 'muted'; };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const changed = () => { dirty = true; draw(); renderTable(); renderCrops(); };

  function split([x, y, w, h], count) {
    const edges = Array.from({ length: count + 1 }, (_, i) => x + Math.round(w * i / count));
    return Array.from({ length: count }, (_, i) => [edges[i], y, edges[i + 1] - edges[i], h]);
  }

  // ---- items: the marks and the groups, each with a box [x,y,w,h] in (turned) reference pixels ----------------
  function items() {
    const out = [];
    state.marks.forEach((m, i) => m && out.push({ kind: 'mark', key: 'mark' + i, index: i, label: 'mark ' + (i + 1), box: m }));
    for (const line of LINES) for (const g of GROUPS) {
      const group = state[line] && state[line][g];
      if (group) out.push({ kind: line, key: line + '.' + g, group, label: `${line} ${g === 'whole' ? 'digits' : 'decimals'}`, box: group.box });
    }
    return out;
  }

  function draw() {
    if (!image) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();   // turned about the centre as the server does (OpenCV: counterclockwise for positive degrees)
    ctx.translate(canvas.width / 2, canvas.height / 2); ctx.rotate(-state.rotation * Math.PI / 180);
    ctx.drawImage(image, -canvas.width / 2, -canvas.height / 2, canvas.width, canvas.height);
    ctx.restore();
    for (const item of items()) {
      ctx.strokeStyle = ctx.fillStyle = COLORS[item.kind];
      ctx.lineWidth = state.selected === item.key ? 3 : 1.5;
      const boxes = item.kind === 'mark' ? [item.box] : split(item.box, item.group.count);
      for (const b of boxes) { const [x, y, w, h] = b.map(v => v * scale); ctx.strokeRect(x, y, w, h); }
      const [x, y] = item.box.map(v => v * scale);
      ctx.font = '12px system-ui'; ctx.fillText(item.label, x, Math.max(y - 3, 10));
    }
    if (drag) {
      ctx.setLineDash([5, 4]); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5;
      ctx.strokeRect(drag.x0, drag.y0, drag.x1 - drag.x0, drag.y1 - drag.y0); ctx.setLineDash([]);
    }
  }

  function renderTable() {
    const t = $('boxes');
    t.innerHTML = '<tr><th></th><th>x</th><th>y</th><th>width</th><th>height</th><th>digits / name</th></tr>';
    for (const item of items()) {
      const tr = document.createElement('tr');
      if (state.selected === item.key) tr.style.background = 'rgba(127,127,127,.18)';
      tr.innerHTML = '<td></td>' + [0, 1, 2, 3].map(i => `<td><input type="number" data-i="${i}" style="width:5em"></td>`).join('') + '<td></td>';
      tr.cells[0].textContent = item.label;
      tr.cells[0].style.cursor = 'pointer';
      tr.cells[0].onclick = () => { state.selected = item.key; draw(); renderTable(); };
      tr.querySelectorAll('input').forEach(inp => {
        const i = Number(inp.dataset.i);
        inp.value = item.box[i];
        inp.onchange = () => { item.box[i] = Math.max(i < 2 ? 0 : 1, Math.round(Number(inp.value)) || 0); state.selected = item.key; changed(); };
        inp.onfocus = () => { state.selected = item.key; draw(); };
      });
      const extra = document.createElement('input');
      if (item.kind === 'mark') {
        extra.value = state.names[item.index]; extra.style.width = '7em';
        extra.onchange = () => { state.names[item.index] = extra.value.trim() || state.names[item.index]; dirty = true; };
      } else {
        extra.type = 'number'; extra.min = 1; extra.max = 12; extra.value = item.group.count; extra.style.width = '4em';
        extra.onchange = () => { item.group.count = clamp(Math.round(Number(extra.value)) || 1, 1, 12); changed(); };
      }
      tr.cells[5].appendChild(extra);
      t.appendChild(tr);
    }
  }

  function finishDrag(d) {
    const x = clamp(Math.round(Math.min(d.x0, d.x1) / scale), 0, state.ref.width), y = clamp(Math.round(Math.min(d.y0, d.y1) / scale), 0, state.ref.height);
    const w = clamp(Math.round(Math.abs(d.x1 - d.x0) / scale), 0, state.ref.width - x), h = clamp(Math.round(Math.abs(d.y1 - d.y0) / scale), 0, state.ref.height - y);
    if (w < 4 || h < 4) return;
    const mode = $('mode').value;
    if (mode.startsWith('mark')) state.marks[Number(mode.slice(4))] = [x, y, w, h];
    else {
      const [line, g] = mode.split('.');
      state[line] = state[line] || { whole: null, decimals: null };
      state[line][g] = { box: [x, y, w, h], count: clamp(Math.round(Number($('count').value)) || 1, 1, 12) };
    }
    state.selected = mode;
    changed();
  }

  function pos(e) {
    const r = canvas.getBoundingClientRect();
    return { x: clamp((e.clientX - r.left) * canvas.width / r.width, 0, canvas.width), y: clamp((e.clientY - r.top) * canvas.height / r.height, 0, canvas.height) };
  }
  canvas.addEventListener('pointerdown', e => { const p = pos(e); drag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', e => { if (!drag) return; const p = pos(e); drag.x1 = p.x; drag.y1 = p.y; draw(); });
  canvas.addEventListener('pointerup', () => { const d = drag; drag = null; if (d) finishDrag(d); draw(); });

  // ---- crop preview --------------------------------------------------------------------------------------
  function renderCrops() {
    const box = $('crops'); box.innerHTML = '';
    if (dirty) { box.innerHTML = '<p class="muted">Save the regions to see the crops.</p>'; return; }
    const t = Date.now(), source = $('source').value;
    for (const line of LINES) {
      if (!state[line] || !state[line].whole) continue;
      const count = state[line].whole.count + (state[line].decimals ? state[line].decimals.count : 0);
      const row = document.createElement('div'); row.style.cssText = 'display:flex;gap:6px;margin:6px 0;align-items:flex-end';
      for (let i = 0; i < count; i++) {
        const img = document.createElement('img');
        img.src = `api/crop/${line}/${i}.png?source=${source}&t=${t}`; img.alt = line + ' ' + (i + 1);
        img.style.cssText = 'height:64px;width:auto;border:1px solid var(--line)';
        img.onerror = () => { img.alt = 'n/a'; };
        row.appendChild(img);
      }
      box.appendChild(row);
    }
    if (source === 'latest') alignment();
  }

  async function alignment() {
    try {
      const a = await json('api/alignment');
      $('alignment').textContent = !a.available ? 'No camera image or no saved regions yet.' :
        (a.ok ? 'Aligned' : 'Alignment failed') + ' – ' + Object.entries(a.scores).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(', ') +
        ` (needs ${a.min_score}); shift ${a.shift.map(v => v.toFixed(1)).join(', ')} px, rotation ${a.rotation_deg.toFixed(2)}°`;
    } catch (e) { $('alignment').textContent = e.message; }
  }

  // ---- loading and saving --------------------------------------------------------------------------------
  function loadImage() {
    return new Promise((resolve, reject) => {
      const img = new Image(); img.onload = () => resolve(img); img.onerror = () => reject(new Error('no reference image'));
      img.src = 'api/reference.jpg?t=' + Date.now();
    });
  }

  function syncCount() {   // the digits field shows the count of the group about to be drawn
    const mode = $('mode').value;
    if (mode.startsWith('mark')) return;
    const [line, g] = mode.split('.');
    const group = state[line] && state[line][g];
    $('count').value = group ? group.count : DEFAULT_COUNT[g];
  }

  async function load() {
    const info = await json('api/regions');
    $('no-reference').hidden = !!info.reference; $('editor').hidden = !info.reference;
    if (!info.reference) return;
    image = await loadImage();
    state.ref = info.reference;
    canvas.width = Math.min(image.naturalWidth, 1000); scale = canvas.width / image.naturalWidth;
    canvas.height = Math.round(image.naturalHeight * scale);
    canvas.style.cssText = 'max-width:100%;height:auto;touch-action:none;cursor:crosshair;border:1px solid var(--line)';
    const r = info.regions;
    if (r && r.reference_width === info.reference.width && r.reference_height === info.reference.height) {
      state.marks = [0, 1].map(i => r.marks[i] ? r.marks[i].box : null);
      state.names = [0, 1].map(i => r.marks[i] ? r.marks[i].name : ['logo', 'text'][i]);
      state.volume = r.volume; state.flow = r.flow; state.rotation = r.rotation_deg || 0;
    } else { state.marks = [null, null]; state.volume = null; state.flow = null; state.rotation = 0; }
    $('rotation').value = state.rotation.toFixed(1);
    dirty = false; state.selected = null;
    syncCount(); draw(); renderTable(); renderCrops();
  }

  async function save() {
    const marks = state.marks.map((box, i) => box && { name: state.names[i], box }).filter(Boolean);
    const line = l => l ? { whole: l.whole, decimals: l.decimals } : null;
    if (!state.volume || !state.volume.whole) { say('Draw the volume digits first.', true); return; }
    if (state.flow && !state.flow.whole) { say('Draw the flow digits too, or remove its decimals.', true); return; }
    try {
      await json('api/regions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        reference_width: state.ref.width, reference_height: state.ref.height, rotation_deg: state.rotation,
        marks, volume: line(state.volume), flow: line(state.flow) }) });
      dirty = false; say('Saved.'); renderCrops();
    } catch (e) { say(e.message, true); }
  }

  $('save').onclick = save;
  $('source').onchange = renderCrops;
  $('mode').onchange = syncCount;
  $('rotation').onchange = () => {
    state.rotation = clamp(Math.round(Number($('rotation').value) * 10) / 10 || 0, -45, 45);
    $('rotation').value = state.rotation.toFixed(1); changed();
  };
  $('remove-group').onclick = () => {
    const mode = $('mode').value;
    if (mode.startsWith('mark')) state.marks[Number(mode.slice(4))] = null;
    else {
      const [line, g] = mode.split('.');
      if (state[line]) state[line][g] = null;
      if (state[line] && !state[line].whole && !state[line].decimals) state[line] = null;
    }
    changed();
  };
  $('use-latest').onclick = async () => {
    if (state.volume && !confirm('A new reference image makes the saved boxes invalid. Continue?')) return;
    try { await json('api/reference/latest', { method: 'POST' }); await load(); say('Reference updated.'); }
    catch (e) { alert(e.message); }
  };
  $('upload').onchange = async e => {
    const file = e.target.files[0]; if (!file) return;
    try { await json('api/reference', { method: 'POST', body: await file.arrayBuffer() }); await load(); say('Reference updated.'); }
    catch (err) { alert(err.message); }
  };

  load().catch(e => { $('no-reference').hidden = false; $('no-reference').textContent = e.message; });
})();
