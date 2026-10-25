// Regions page (C2). State = the regions JSON of api/regions; all URLs are relative (ingress).
(() => {
  const $ = id => document.getElementById(id);
  const COLORS = { mark: '#d1832a', volume: '#1a9f37', flow: '#2f81f7' };
  const state = { ref: null, marks: [null, null], names: ['logo', 'text'], volume: null, flow: null, selected: null };
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

  // ---- boxes: [{group, key, label, box:[x,y,w,h]}] in reference pixels -------------------------------------
  function allBoxes() {
    const out = [];
    state.marks.forEach((m, i) => m && out.push({ group: 'mark', index: i, label: 'mark ' + (i + 1), box: m }));
    if (state.volume) state.volume.digits.forEach((b, i) => out.push({ group: 'volume', index: i, label: 'volume ' + (i + 1), box: b }));
    if (state.flow) state.flow.digits.forEach((b, i) => out.push({ group: 'flow', index: i, label: 'flow ' + (i + 1), box: b }));
    return out;
  }
  const same = (a, b) => a && b && a.group === b.group && a.index === b.index;

  function draw() {
    if (!image) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    for (const item of allBoxes()) {
      const [x, y, w, h] = item.box.map(v => v * scale);
      ctx.lineWidth = same(item, state.selected) ? 3 : 1.5;
      ctx.strokeStyle = COLORS[item.group];
      ctx.strokeRect(x, y, w, h);
      if (item.group !== 'mark' && (item.index === 0 || same(item, state.selected))) {
        ctx.fillStyle = COLORS[item.group]; ctx.font = '12px system-ui';
        ctx.fillText(item.group + ' ' + (item.index + 1), x, Math.max(y - 3, 10));
      }
      if (item.group !== 'mark' && state[item.group].digits.length - item.index === state[item.group].decimals) {
        ctx.fillStyle = COLORS[item.group]; ctx.fillRect(x - 2, y + h - 3, 4, 4);   // the decimal point sits before this digit
      }
    }
    if (drag) {
      ctx.setLineDash([5, 4]); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5;
      ctx.strokeRect(drag.x0, drag.y0, drag.x1 - drag.x0, drag.y1 - drag.y0); ctx.setLineDash([]);
    }
  }

  function renderTable() {
    const t = $('boxes');
    t.innerHTML = '<tr><th>Box</th><th>x</th><th>y</th><th>width</th><th>height</th><th>name</th></tr>';
    for (const item of allBoxes()) {
      const tr = document.createElement('tr');
      if (same(item, state.selected)) tr.style.background = 'rgba(127,127,127,.18)';
      tr.innerHTML = '<td></td>' + [0, 1, 2, 3].map(i => `<td><input type="number" data-i="${i}" style="width:5em"></td>`).join('') + '<td></td>';
      tr.cells[0].textContent = item.label;
      tr.cells[0].style.cursor = 'pointer';
      tr.cells[0].onclick = () => { state.selected = item; draw(); renderTable(); };
      tr.querySelectorAll('input').forEach(inp => {
        inp.value = item.box[inp.dataset.i];
        inp.onchange = () => { item.box[inp.dataset.i] = Math.round(Number(inp.value)); dirty = true; draw(); };
        inp.onfocus = () => { state.selected = item; draw(); };
      });
      if (item.group === 'mark') {
        const name = document.createElement('input');
        name.value = state.names[item.index]; name.style.width = '7em';
        name.onchange = () => { state.names[item.index] = name.value.trim() || state.names[item.index]; dirty = true; };
        tr.cells[5].appendChild(name);
      }
      t.appendChild(tr);
    }
  }

  function split(x, y, w, h, count) {
    const edges = Array.from({ length: count + 1 }, (_, i) => x + Math.round(w * i / count));
    return Array.from({ length: count }, (_, i) => [edges[i], y, edges[i + 1] - edges[i], h]);
  }

  function finishDrag(d) {
    const x = clamp(Math.round(Math.min(d.x0, d.x1) / scale), 0, state.ref.width), y = clamp(Math.round(Math.min(d.y0, d.y1) / scale), 0, state.ref.height);
    const w = clamp(Math.round(Math.abs(d.x1 - d.x0) / scale), 0, state.ref.width - x), h = clamp(Math.round(Math.abs(d.y1 - d.y0) / scale), 0, state.ref.height - y);
    if (w < 4 || h < 4) return;
    const mode = $('mode').value;
    if (mode.startsWith('mark')) state.marks[Number(mode.slice(4))] = [x, y, w, h];
    else {
      const count = clamp(Math.round(Number($('count').value)) || 1, 1, 12);
      const decimals = clamp(Math.round(Number($('decimals').value)) || 0, 0, count);
      state[mode] = { digits: split(x, y, w, h, count), decimals };
    }
    dirty = true; state.selected = null; draw(); renderTable(); renderCrops();
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
    for (const g of ['volume', 'flow']) {
      if (!state[g]) continue;
      const row = document.createElement('div'); row.style.cssText = 'display:flex;gap:6px;margin:6px 0;align-items:flex-end';
      state[g].digits.forEach((_, i) => {
        const img = document.createElement('img');
        img.src = `api/crop/${g}/${i}.png?source=${source}&t=${t}`; img.alt = g + ' ' + (i + 1);
        img.style.cssText = 'height:64px;width:auto;border:1px solid var(--line)';
        img.onerror = () => { img.alt = 'n/a'; };
        row.appendChild(img);
      });
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
      state.volume = r.volume; state.flow = r.flow;
    } else { state.marks = [null, null]; state.volume = null; state.flow = null; }
    dirty = false; state.selected = null;
    if (state.volume) { $('count').value = state.volume.digits.length; $('decimals').value = state.volume.decimals; }
    draw(); renderTable(); renderCrops();
  }

  async function save() {
    const marks = state.marks.map((box, i) => box && { name: state.names[i], box }).filter(Boolean);
    if (!state.volume) { say('Draw the volume line first.', true); return; }
    try {
      await json('api/regions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        reference_width: state.ref.width, reference_height: state.ref.height, marks, volume: state.volume, flow: state.flow }) });
      dirty = false; say('Saved.'); renderCrops();
    } catch (e) { say(e.message, true); }
  }

  $('save').onclick = save;
  $('source').onchange = renderCrops;
  $('mode').onchange = () => {
    const g = $('mode').value;
    if (state[g] && state[g].digits) { $('count').value = state[g].digits.length; $('decimals').value = state[g].decimals; }
  };
  $('remove-flow').onclick = () => { state.flow = null; dirty = true; draw(); renderTable(); renderCrops(); };
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
