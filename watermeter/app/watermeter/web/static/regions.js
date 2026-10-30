// Regions page (C2). State = the regions JSON of api/regions; all URLs are relative (ingress).
// A line (volume, flow) is two groups, whole digits and decimals: `count` digits of width x height, `gap` apart.
// The table shows y from the image's bottom edge to the box's bottom edge; changing a height keeps that edge.
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

  // ---- items: marks ([x,y,w,h]) and groups ({x,y,width,height,count,gap}), as rows with a common accessor ------
  // rect(item) = [x, y, w, h] of the item's (first) box in reference pixels, y from the top.
  function items() {
    const out = [];
    state.marks.forEach((m, i) => m && out.push({ kind: 'mark', key: 'mark' + i, index: i, label: 'mark ' + (i + 1), mark: m }));
    for (const line of LINES) for (const g of GROUPS) {
      const group = state[line] && state[line][g];
      if (group) out.push({ kind: line, key: line + '.' + g, group, label: `${line} ${g === 'whole' ? 'digits' : 'decimals'}` });
    }
    return out;
  }
  const rect = item => item.mark ? item.mark : [item.group.x, item.group.y, item.group.width, item.group.height];
  function setRect(item, [x, y, w, h]) {
    if (item.mark) { item.mark.splice(0, 4, x, y, w, h); return; }
    Object.assign(item.group, { x, y, width: w, height: h });
  }
  const boxes = g => Array.from({ length: g.count }, (_, i) => [g.x + i * (g.width + g.gap), g.y, g.width, g.height]);

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
      for (const b of item.mark ? [item.mark] : boxes(item.group)) {
        const [x, y, w, h] = b.map(v => v * scale); ctx.strokeRect(x, y, w, h);
      }
      const [x, y] = rect(item).map(v => v * scale);
      ctx.font = '12px system-ui'; ctx.fillText(item.label, x, Math.max(y - 3, 10));
    }
    if (drag) {
      ctx.setLineDash([5, 4]); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5;
      ctx.strokeRect(drag.x0, drag.y0, drag.x1 - drag.x0, drag.y1 - drag.y0); ctx.setLineDash([]);
    }
  }

  // table columns: x, y (bottom-based), width (per digit), height, gap, digits / name
  function renderTable() {
    const t = $('boxes');
    t.innerHTML = '<tr><th></th><th>x</th><th>y (from bottom)</th><th>width</th><th>height</th><th>gap</th><th>digits / name</th></tr>';
    for (const item of items()) {
      const tr = document.createElement('tr');
      if (state.selected === item.key) tr.style.background = 'rgba(127,127,127,.18)';
      tr.innerHTML = '<td></td>' + '<td></td>'.repeat(6);
      tr.cells[0].textContent = item.label;
      tr.cells[0].style.cursor = 'pointer';
      tr.cells[0].onclick = () => { state.selected = item.key; draw(); renderTable(); };
      const field = (cell, get, set, min, width = '5em') => {
        const inp = document.createElement('input');
        inp.type = 'number'; inp.min = min; inp.style.width = width; inp.value = get();
        // `input` fires on every step while an arrow is held: redraw live, re-render the table only on `change`
        inp.oninput = () => { const v = Math.round(Number(inp.value)); if (Number.isFinite(v)) { set(Math.max(min, v)); state.selected = item.key; dirty = true; draw(); } };
        inp.onchange = () => { inp.value = get(); changed(); };
        inp.onfocus = () => { state.selected = item.key; draw(); };
        tr.cells[cell].appendChild(inp);
      };
      const H = state.ref.height;
      const r = () => rect(item);
      field(1, () => r()[0], v => { const [, y, w, h] = r(); setRect(item, [v, y, w, h]); }, 0);
      field(2, () => H - r()[1] - r()[3], v => { const [x, , w, h] = r(); setRect(item, [x, H - v - h, w, h]); }, 0);
      field(3, () => r()[2], v => { const [x, y, , h] = r(); setRect(item, [x, y, v, h]); }, 1);
      field(4, () => r()[3], v => { const [x, y, w, h] = r(); setRect(item, [x, y + h - v, w, v]); }, 1);   // bottom stays
      if (item.group) {
        field(5, () => item.group.gap, v => { item.group.gap = v; }, 0, '4em');
        field(6, () => item.group.count, v => { item.group.count = clamp(v, 1, 12); }, 1, '4em');
      } else {
        const name = document.createElement('input');
        name.value = state.names[item.index]; name.style.width = '7em';
        name.onchange = () => { state.names[item.index] = name.value.trim() || state.names[item.index]; dirty = true; };
        tr.cells[6].appendChild(name);
      }
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
      const count = clamp(Math.round(Number($('count').value)) || 1, 1, 12);
      const gap = state[line][g] ? state[line][g].gap : 0;   // a redrawn group keeps its gap
      state[line][g] = { x, y, width: Math.max(1, Math.round((w - gap * (count - 1)) / count)), height: h, count, gap };
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
  $('rotation').oninput = () => {   // live while an arrow is held
    const v = Math.round(Number($('rotation').value) * 10) / 10;
    if (Number.isFinite(v)) { state.rotation = clamp(v, -45, 45); dirty = true; draw(); }
  };
  $('rotation').onchange = () => { $('rotation').value = state.rotation.toFixed(1); changed(); };
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
