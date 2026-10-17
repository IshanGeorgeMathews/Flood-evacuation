// Responder ops: district-wide picture for officials — taluk choropleth, shelter load, network risk profile,
// dam releases, riskiest roads, field-team export and the 2018 replay proof.
import { api } from '../core/api.js';
import { bus, state } from '../core/bus.js';
import { chart, legend, onTheme, palette, RISK_CLASSES, tableToggle } from '../core/charts.js';
import { createMap } from '../core/map.js';
import { initShell, renderKpis } from '../core/shell.js';
import { cssVar, el, fmt, icon } from '../core/ui.js';

const L = window.L;
const $ = (id) => document.getElementById(id);
initShell();

// ---------------------------------------------------------------- filter row (scopes everything below)
const filters = $('w-filters');
const presetSel = el('select', { 'aria-label': 'Caution level', style: 'width:auto' },
  document.body.dataset.presets.split(',').map((p) => el('option', { value: p, text: `Caution: ${p}`, selected: p === state.preset || null })));
const scenSel = el('select', { 'aria-label': 'Rainfall scenario', style: 'width:auto' },
  [0, 50, 100, 200].map((mm) => el('option', { value: String(mm), text: mm ? `What-if: +${mm} mm / 3 days` : 'Live conditions' })));
const daySel = el('select', { 'aria-label': 'Conditions', style: 'width:auto' }, el('option', { value: '', text: 'Live today' }));
bus.on('status', (s) => { if (s.sim_days && daySel.options.length === 1) daySel.append(...s.sim_days.map((d) => el('option', { value: d.date, text: `Simulate ${d.label}` }))); });
daySel.addEventListener('change', () => bus.set('simDate', daySel.value || null));
presetSel.addEventListener('change', () => bus.set('preset', presetSel.value));
scenSel.addEventListener('change', () => bus.set('scenario', Number(scenSel.value)));
filters.append(daySel, presetSel, scenSel, el('span', { class: 'muted', id: 'scope-note' }));

// ---------------------------------------------------------------- taluk choropleth (sequential blue, one hue)
const SEQ = { light: ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'], dark: ['#184f95', '#256abf', '#3987e5', '#6da7ec', '#b7d3f6'] };
const talukPanel = $('w-taluks');
const mapBox = el('div', { class: 'mini-map', style: 'border-radius:10px;overflow:hidden' });
const talukLegend = el('div', { class: 'chart-legend' });
const talukTable = el('div');
talukPanel.append(talukLegend, mapBox, talukTable);
const tmap = createMap(mapBox, { zoom: 10 });
const tlayer = L.layerGroup().addTo(tmap);
let taluks = null;

function seqColors() { return SEQ[document.documentElement.dataset.theme === 'light' ? 'light' : 'dark']; }

function drawTaluks() {
  if (!taluks) return;
  tlayer.clearLayers();
  const vals = taluks.features.map((f) => f.properties.people_exposed);
  const max = Math.max(1, ...vals);
  const steps = seqColors();
  const color = (v) => steps[Math.min(steps.length - 1, Math.floor((v / max) * steps.length))];
  const gj = L.geoJSON(taluks, {
    style: (f) => ({ color: cssVar('--surface-1'), weight: 2, fillColor: color(f.properties.people_exposed), fillOpacity: 0.8 }),
    onEachFeature: (f, lyr) => {
      const p = f.properties;
      lyr.bindTooltip(`<b>${escapeHtml(p.name)}</b><br>${fmt.compact(p.people_exposed)} residents along at-risk roads<br>${fmt.km(p.km_at_risk)} of ${fmt.int(p.km_total)} km road at risk<br>${p.shelters_open}/${p.shelters} shelters reachable`, { sticky: true });
    },
  });
  tlayer.addLayer(gj);
  if (!drawTaluks.fitted && gj.getBounds().isValid()) { tmap.fitBounds(gj.getBounds(), { padding: [10, 10] }); drawTaluks.fitted = true; }
  talukLegend.replaceChildren(el('span', { text: 'Residents along at-risk roads:' }),
    ...steps.map((c, i) => el('span', {}, el('i', { style: `background:${c}` }), `≥ ${fmt.int(Math.ceil((max * i) / steps.length))}`)));
  talukTable.replaceChildren();
  tableToggle(talukTable, [
    { key: 'name', label: 'Taluk' }, { key: 'people_exposed', label: 'Residents exposed', right: true, fmt: fmt.int },
    { key: 'km_at_risk', label: 'Road at risk (km)', right: true, fmt: (v) => fmt.km(v) },
    { key: 'share_at_risk', label: 'Share', right: true, fmt: (v) => fmt.pct(v, 1) },
    { key: 'shelters_open', label: 'Shelters open', right: true }], taluks.features.map((f) => f.properties));
}

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

// ---------------------------------------------------------------- shelter load by taluk (demand vs capacity)
const loadPanel = $('w-shelterload');
const loadBox = el('div', { class: 'chart-box h260' });
const loadLegend = el('div');
const loadTable = el('div');
loadPanel.append(loadLegend, loadBox, loadTable);
function drawLoad() {
  if (!taluks) return;
  const pal = palette();
  const rows = taluks.features.map((f) => f.properties).sort((a, b) => b.capacity - a.capacity);
  loadLegend.replaceChildren(legend([{ label: 'Projected demand', color: pal.s1 }, { label: 'Estimated capacity', color: pal.s2 }]));
  chart(loadBox, {
    type: 'bar',
    ariaLabel: 'Projected shelter demand and estimated capacity by taluk',
    data: { labels: rows.map((r) => r.name), datasets: [
      { label: 'Projected demand', data: rows.map((r) => r.demand), backgroundColor: pal.s1 },
      { label: 'Estimated capacity', data: rows.map((r) => r.capacity), backgroundColor: pal.s2 }] },
    options: {
      indexAxis: 'y',
      elements: { bar: { borderRadius: { topRight: 4, bottomRight: 4, topLeft: 0, bottomLeft: 0 } } },
      plugins: { tooltip: { callbacks: { label: (it) => ` ${it.dataset.label}: ${fmt.int(it.parsed.x)} people` } } },
      scales: { x: { beginAtZero: true, ticks: { callback: (v) => fmt.compact(v) } }, y: { grid: { display: false } } },
    },
  });
  loadTable.replaceChildren();
  tableToggle(loadTable, [{ key: 'name', label: 'Taluk' }, { key: 'demand', label: 'Demand', right: true, fmt: fmt.int },
    { key: 'capacity', label: 'Capacity', right: true, fmt: fmt.int }, { key: 'shelters', label: 'Shelters', right: true }], rows);
}

// ---------------------------------------------------------------- network risk histogram + by class + top roads
const histPanel = $('w-histogram');
const histBox = el('div', { class: 'chart-box h220' });
const histLegend = el('div');
const histTable = el('div');
histPanel.append(histLegend, histBox, histTable);
const classPanel = $('w-byclass');
const classBox = el('div', { class: 'chart-box h220' });
const classTable = el('div');
classPanel.append(classBox, classTable);
const topPanel = $('w-toproads');
const topBody = el('div');
topPanel.append(topBody);
let stats = null;

function drawStats() {
  if (!stats) return;
  const pal = palette();
  const h = stats.histogram;
  const colorFor = (b) => pal[RISK_CLASSES.find((c) => b.from < c.max).key];
  histLegend.replaceChildren(legend(RISK_CLASSES.map((c) => ({ label: c.label, color: pal[c.key] }))));
  chart(histBox, {
    type: 'bar',
    ariaLabel: 'Kilometres of road by predicted flood probability',
    data: { labels: h.map((b) => `${Math.round(b.from * 100)}–${Math.round(b.to * 100)}%`), datasets: [{ data: h.map((b) => b.km), backgroundColor: h.map(colorFor) }] },
    options: {
      plugins: { tooltip: { displayColors: false, callbacks: { label: (it) => `${fmt.km(it.parsed.y)} km of road` } } },
      scales: { y: { type: 'logarithmic', title: { display: true, text: 'km (log scale)' }, ticks: { callback: (v) => ([1, 10, 100, 1000, 10000].includes(v) ? fmt.compact(v) : '') } }, x: { grid: { display: false } } },
    },
  });
  histTable.replaceChildren();
  tableToggle(histTable, [{ key: 'from', label: 'From', fmt: (v) => fmt.pct(v) }, { key: 'to', label: 'To', fmt: (v) => fmt.pct(v) }, { key: 'km', label: 'km', right: true, fmt: (v) => fmt.km(v) }], h);

  const bc = stats.by_class;
  if (!bc.length) {
    classBox.replaceChildren(el('div', { class: 'empty', text: 'No road at or above the at-risk probability right now.' }));
  } else {
    chart(classBox, {
      type: 'bar',
      ariaLabel: 'At-risk road length by road class',
      data: { labels: bc.map((r) => r.highway.replace('_', ' ')), datasets: [{ data: bc.map((r) => r.km), backgroundColor: pal.s1 }] },
      options: {
        indexAxis: 'y',
        elements: { bar: { borderRadius: { topRight: 4, bottomRight: 4, topLeft: 0, bottomLeft: 0 } } },
        plugins: { tooltip: { displayColors: false, callbacks: { label: (it) => `${fmt.km(it.parsed.x, 2)} km at risk` } } },
        scales: { x: { beginAtZero: true, title: { display: true, text: 'km at risk' } }, y: { grid: { display: false } } },
      },
    });
  }
  classTable.replaceChildren();
  tableToggle(classTable, [{ key: 'highway', label: 'Road class' }, { key: 'km', label: 'km at risk', right: true, fmt: (v) => fmt.km(v, 2) }], bc);

  topBody.replaceChildren(el('table', { class: 'data' },
    el('thead', {}, el('tr', {}, el('th', { text: '#' }), el('th', { text: 'Road' }), el('th', { text: 'Class' }), el('th', { class: 'r', text: 'Flood probability' }), el('th', { text: 'State' }))),
    el('tbody', {}, stats.top_segments.map((r, i) => {
      const c = RISK_CLASSES.find((k) => r.p < k.max);
      return el('tr', {}, el('td', { text: String(i + 1) }), el('td', { text: r.name }), el('td', { text: r.highway }),
        el('td', { class: 'r', text: fmt.pct(r.p, 1) }),
        el('td', {}, el('span', { class: 'badge' }, el('span', { class: 'dot', style: `background:${pal[c.key]}` }), c.label.split(' (')[0])));
    }))));
  $('scope-note').textContent = `${state.simDate ? 'SIMULATION · ' : ''}Picture for ${stats.date}${stats.scenario_mm ? ` + ${stats.scenario_mm} mm what-if` : ''} · ${stats.mode === 'full' ? 'rain + river model' : 'terrain-only fallback'}`;
}

// ---------------------------------------------------------------- dam release timeline
const damPanel = $('w-dams');
const damBody = el('div');
damPanel.append(damBody);
async function drawDams() {
  try {
    const d = await api.dams();
    const pal = palette();
    const dams = [...new Set(d.releases.map((r) => r.dam))];
    const color = (dam) => [pal.s1, pal.s2, pal.s3][dams.indexOf(dam) % 3];
    damBody.replaceChildren(
      legend(dams.map((n) => ({ label: n, color: color(n) }))),
      el('div', {}, d.releases.map((r) => el('div', { class: 'shelter' },
        el('div', { class: 'shelter-head' }, el('span', {}, el('span', { class: 'dot', style: `background:${color(r.dam)};margin-right:6px` }), el('b', { text: r.event })),
          el('span', { class: 'muted', text: `${fmt.date(r.start)}${r.end ? ` → ${fmt.date(r.end)}` : ''}` })),
        el('div', { class: 'shelter-meta' }, el('span', { class: 'badge', text: r.confidence }), el('span', { text: r.note }))))),
      el('div', { class: 'field-hint', text: d.note }));
  } catch (err) { damBody.replaceChildren(el('div', { class: 'empty', text: `Dam data unavailable: ${err.message}` })); }
}

// ---------------------------------------------------------------- export
const exportPanel = $('w-export');
function drawExport() {
  exportPanel.querySelectorAll('.export-body').forEach((n) => n.remove());
  exportPanel.append(el('div', { class: 'export-body' },
    el('p', { class: 'card-text', text: 'Safest routes from every taluk centre and the hardest-hit 2018 towns to their best reachable shelter, for the selected caution level.' }),
    el('div', { class: 'btn-row' },
      el('a', { class: 'btn btn-primary', href: api.exportUrl('geojson'), download: '' }, icon('download'), 'GeoJSON'),
      el('a', { class: 'btn', href: api.exportUrl('csv'), download: '' }, icon('download'), 'CSV'))));
}

// ---------------------------------------------------------------- replay proof
const rpPanel = $('w-replaycmp');
const rpBox = el('div', { class: 'chart-box h220' });
const rpLegend = el('div');
const rpNote = el('div', { class: 'field-hint' });
const rpTable = el('div');
rpPanel.append(rpLegend, rpBox, rpNote, rpTable);
let replay = null;
function drawReplay() {
  if (!replay) return;
  const pal = palette();
  const c = replay.comparisons;
  if (!c.length) { rpBox.replaceChildren(el('div', { class: 'empty', text: 'No radar-observed day in the replay window.' })); return; }
  rpLegend.replaceChildren(legend([{ label: 'Safest route', color: pal.s1 }, { label: 'Fastest route', color: pal.s2 }]));
  chart(rpBox, {
    type: 'bar',
    ariaLabel: 'Share of route length on radar-flooded roads, safest vs fastest',
    data: { labels: c.map((x) => x.date), datasets: [
      { label: 'Safest route', data: c.map((x) => 100 * x.safest.flooded_share_of_length), backgroundColor: pal.s1 },
      { label: 'Fastest route', data: c.map((x) => 100 * x.fastest.flooded_share_of_length), backgroundColor: pal.s2 }] },
    options: {
      plugins: { tooltip: { callbacks: { label: (it) => ` ${it.dataset.label}: ${it.parsed.y.toFixed(2)}% of length on flooded roads` } } },
      scales: { y: { beginAtZero: true, title: { display: true, text: '% of route length on flooded roads' } }, x: { grid: { display: false } } },
    },
  });
  rpNote.textContent = `${replay.model}. Routes from ${c[0].origins} origins checked against Sentinel-1 flood maps.`;
  rpTable.replaceChildren();
  tableToggle(rpTable, [{ key: 'date', label: 'Date' },
    { key: 's', label: 'Safest %', right: true, fmt: (_v, r) => (100 * r.safest.flooded_share_of_length).toFixed(2) },
    { key: 'f', label: 'Fastest %', right: true, fmt: (_v, r) => (100 * r.fastest.flooded_share_of_length).toFixed(2) },
    { key: 'st', label: 'Safest touching flood', right: true, fmt: (_v, r) => r.safest.routes_touching_flood },
    { key: 'ft', label: 'Fastest touching flood', right: true, fmt: (_v, r) => r.fastest.routes_touching_flood }], c);
}

// ---------------------------------------------------------------- loading
async function loadAll() {
  [talukPanel, loadPanel, histPanel, classPanel, topPanel].forEach((p) => p.classList.add('loading'));
  try {
    const [t, s] = await Promise.all([api.taluks(), api.stats()]);
    taluks = t; stats = s;
    renderKpis(s.kpis);
    drawTaluks(); drawLoad(); drawStats();
  } catch (err) {
    topBody.replaceChildren(el('div', { class: 'empty', text: `Unavailable: ${err.message}` }));
  } finally {
    [talukPanel, loadPanel, histPanel, classPanel, topPanel].forEach((p) => p.classList.remove('loading'));
  }
}
bus.on('state:preset', () => { loadAll(); drawExport(); });
bus.on('state:scenario', loadAll);
bus.on('state:simDate', loadAll);
bus.on('sse:refresh', loadAll);
onTheme(() => { drawTaluks(); drawLoad(); drawStats(); drawReplay(); drawDams(); });
loadAll();
drawDams();
drawExport();
api.replaySummary().then((r) => { replay = r; drawReplay(); }).catch((err) => rpBox.replaceChildren(el('div', { class: 'empty', text: `Replay unavailable: ${err.message}` })));
