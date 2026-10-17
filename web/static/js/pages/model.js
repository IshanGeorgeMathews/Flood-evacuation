// Model lab: every number comes from models/<version>/metrics.json — held-out event scores, calibration,
// drivers, spatial-CV folds and the Sentinel-1 events the labels were built from.
import { api } from '../core/api.js';
import { chart, legend, onTheme, palette, tableToggle } from '../core/charts.js';
import { initShell, renderKpis } from '../core/shell.js';
import { el, fmt, icon } from '../core/ui.js';

const $ = (id) => document.getElementById(id);
initShell();

const MODELS = [
  { key: 'logreg', label: 'Logistic regression (baseline)', slot: 's1' },
  { key: 'random_forest', label: 'Random Forest', slot: 's2' },
  { key: 'xgboost', label: 'XGBoost', slot: 's3' },
];
const FEATURE_NAMES = {
  elev: 'Elevation', hand: 'Height above drainage (HAND)', slope: 'Slope', twi: 'Topographic wetness', dist_stream_m: 'Distance to stream',
  stream_order: 'Stream order', flow_acc_log: 'Upslope area', landcover_water: 'Water / wetland nearby', landcover_built: 'Built-up',
  landcover_tree: 'Tree cover', landcover_crop: 'Cropland', road_class_rank: 'Road class', is_bridge: 'Bridge', is_causeway: 'Causeway / bund',
  pop_density: 'Population', dist_gauge_km: 'Distance to gauge', rain_1d: 'Rain, 1 day', rain_3d: 'Rain, 3 days', rain_5d: 'Rain, 5 days',
  rain_7d: 'Rain, 7 days', rain_up_3d: 'Upstream rain, 3 days', rain_up_5d: 'Upstream rain, 5 days', gauge_near_rel: 'Nearest river vs danger',
  gauge_near_rel_3d: 'River 3-day peak vs danger', gauge_max_rel: 'Highest river vs danger', days_since_onset: 'Days into monsoon',
  past_flood_freq: 'Flooded in earlier events',
};
let m = null;

function stat(label, value, sub) {
  return el('div', { class: 'stat' }, el('div', { class: 'l', text: label }), el('div', { class: 'v', text: value }), sub ? el('div', { class: 's', text: sub }) : null);
}

function drawGate() {
  const g = m.gate;
  const best = m.models[g.best_model];
  const base = m.models.logreg;
  const lift = best.pr_auc / Math.max(base.pr_auc, 1e-9);
  $('w-gate').querySelectorAll('.gate').forEach((n) => n.remove());
  $('w-gate').append(el('div', { class: 'gate' },
    el('div', {},
      el('div', { class: `gate-badge ${g.passed ? 'pass' : 'fail'}` }, icon(g.passed ? 'check' : 'x'), g.passed ? 'Gate passed' : 'Gate failed'),
      el('div', { class: 'field-hint', text: `Held-out event ${m.holdout_event}: never used for training, tuning or calibration.` })),
    el('div', { class: 'stat' }, el('div', { class: 'l', text: `PR-AUC, ${MODELS.find((x) => x.key === g.best_model).label}` }),
      el('div', { class: 'hero', text: best.pr_auc.toFixed(3) }), el('div', { class: 's', text: `${lift.toFixed(1)}× the baseline (${base.pr_auc.toFixed(3)}) · prevalence ${fmt.pct(best.prevalence, 2)}` })),
    stat(`Recall at ${fmt.pct(best.fpr_target)} false alarms`, fmt.pct(best.recall_at_fpr, 1), 'flooded roads caught'),
    stat('ROC-AUC', best.roc_auc.toFixed(3), `baseline ${base.roc_auc.toFixed(3)}`),
    stat('Brier score', best.brier.toFixed(4), `${fmt.int(best.n)} held-out segment-days`)));
}

function drawPR() {
  const pal = palette();
  const host = $('w-pr');
  let box = host.querySelector('.chart-box');
  if (!box) {
    host.append(el('div', { class: 'lg' }), box = el('div', { class: 'chart-box h260' }), el('div', { class: 'tt' }));
  }
  host.querySelector('.lg').replaceChildren(legend(MODELS.map((x) => ({ label: `${x.label} · ${m.models[x.key].pr_auc.toFixed(3)}`, color: pal[x.slot], line: true }))));
  chart(box, {
    type: 'line',
    ariaLabel: 'Precision-recall curves on the held-out event',
    data: { datasets: MODELS.map((x) => ({ label: x.label, data: m.models[x.key].pr_curve.map((p) => ({ x: p.recall, y: p.precision })), borderColor: pal[x.slot], parsing: false })) },
    options: {
      interaction: { mode: 'nearest', intersect: false },
      plugins: { tooltip: { callbacks: { label: (it) => ` ${it.dataset.label}: precision ${fmt.pct(it.parsed.y, 1)} at recall ${fmt.pct(it.parsed.x, 1)}` } } },
      scales: { x: { type: 'linear', min: 0, max: 1, title: { display: true, text: 'Recall' } }, y: { min: 0, max: 1, title: { display: true, text: 'Precision' } } },
    },
  });
  const tt = host.querySelector('.tt');
  tt.replaceChildren();
  tableToggle(tt, [{ key: 'label', label: 'Model' }, { key: 'pr', label: 'PR-AUC', right: true }, { key: 'roc', label: 'ROC-AUC', right: true },
    { key: 'rec', label: 'Recall @FPR', right: true }, { key: 'brier', label: 'Brier', right: true }, { key: 'cv', label: 'Spatial-CV PR-AUC', right: true }],
  MODELS.map((x) => { const r = m.models[x.key]; return { label: x.label, pr: r.pr_auc.toFixed(3), roc: r.roc_auc.toFixed(3), rec: fmt.pct(r.recall_at_fpr, 1), brier: r.brier.toFixed(4), cv: r.spatial_cv_pr_auc_mean.toFixed(3) }; }));
}

function drawReliability() {
  const pal = palette();
  const host = $('w-reliability');
  let box = host.querySelector('.chart-box');
  if (!box) host.append(el('div', { class: 'lg' }), box = el('div', { class: 'chart-box h260' }), el('div', { class: 'field-hint', text: 'Points on the diagonal mean a predicted 30% really floods 30% of the time — needed because probabilities set routing costs.' }), el('div', { class: 'tt' }));
  const relRows = MODELS.flatMap((x) => m.models[x.key].reliability.map((b) => ({ model: x.label, ...b })));
  const relTable = host.querySelector('.tt');
  relTable.replaceChildren();
  tableToggle(relTable, [{ key: 'model', label: 'Model' }, { key: 'bin', label: 'Bin' },
    { key: 'mean_pred', label: 'Predicted', right: true, fmt: (v) => fmt.pct(v, 1) }, { key: 'observed', label: 'Observed', right: true, fmt: (v) => fmt.pct(v, 1) },
    { key: 'n', label: 'n', right: true, fmt: fmt.int }], relRows);
  host.querySelector('.lg').replaceChildren(legend([...MODELS.map((x) => ({ label: x.label, color: pal[x.slot], line: true })), { label: 'Perfect calibration', color: pal.muted, line: true }]));
  chart(box, {
    type: 'line',
    ariaLabel: 'Reliability curves',
    data: { datasets: [
      { label: 'Perfect calibration', data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], borderColor: pal.axis, borderWidth: 1, parsing: false, pointRadius: 0 },
      ...MODELS.map((x) => ({ label: x.label, data: m.models[x.key].reliability.map((b) => ({ x: b.mean_pred, y: b.observed, n: b.n })), borderColor: pal[x.slot], backgroundColor: pal[x.slot], pointRadius: 4, pointBorderColor: pal.surface, pointBorderWidth: 2, parsing: false }))] },
    options: {
      interaction: { mode: 'nearest', intersect: false },
      plugins: { tooltip: { callbacks: { label: (it) => ` ${it.dataset.label}: predicted ${fmt.pct(it.parsed.x, 1)} → observed ${fmt.pct(it.parsed.y, 1)}${it.raw.n ? ` (n=${fmt.int(it.raw.n)})` : ''}` } } },
      scales: { x: { type: 'linear', min: 0, max: 1, title: { display: true, text: 'Mean predicted probability' } }, y: { min: 0, max: 1, title: { display: true, text: 'Observed flood frequency' } } },
    },
  });
}

function drawImportance() {
  const pal = palette();
  const host = $('w-importance');
  let box = host.querySelector('.chart-box');
  if (!box) host.append(box = el('div', { class: 'chart-box', style: 'height:360px' }), el('div', { class: 'tt' }));
  const top = m.importance.slice(0, 14);
  chart(box, {
    type: 'bar',
    ariaLabel: 'Mean absolute SHAP value by feature',
    data: { labels: top.map((f) => FEATURE_NAMES[f.feature] || f.feature), datasets: [{ data: top.map((f) => f.mean_abs_shap), backgroundColor: pal.s1 }] },
    options: {
      indexAxis: 'y',
      elements: { bar: { borderRadius: { topRight: 4, bottomRight: 4, topLeft: 0, bottomLeft: 0 } } },
      plugins: { tooltip: { displayColors: false, callbacks: { label: (it) => `mean |SHAP| ${it.parsed.x.toFixed(3)}` } } },
      scales: { x: { beginAtZero: true, title: { display: true, text: 'Mean |SHAP| (log-odds)' } }, y: { grid: { display: false } } },
    },
  });
  const tt = host.querySelector('.tt');
  tt.replaceChildren();
  tableToggle(tt, [{ key: 'feature', label: 'Feature', fmt: (v) => FEATURE_NAMES[v] || v }, { key: 'mean_abs_shap', label: 'Mean |SHAP|', right: true, fmt: (v) => v.toFixed(4) }], m.importance);
}

function drawFolds() {
  const pal = palette();
  const host = $('w-folds');
  let box = host.querySelector('.chart-box');
  if (!box) host.append(el('div', { class: 'lg' }), box = el('div', { class: 'chart-box h260' }), el('div', { class: 'field-hint' }), el('div', { class: 'tt' }));
  host.querySelector('.lg').replaceChildren(legend(MODELS.map((x) => ({ label: x.label, color: pal[x.slot] }))));
  const n = Math.max(...MODELS.map((x) => m.models[x.key].spatial_cv_pr_auc_folds.length));
  const foldTable = host.querySelector('.tt');
  foldTable.replaceChildren();
  tableToggle(foldTable, [{ key: 'fold', label: 'Fold' }, ...MODELS.map((x) => ({ key: x.key, label: x.label, right: true, fmt: (v) => (v === undefined ? '–' : v.toFixed(3)) }))],
    Array.from({ length: n }, (_, i) => Object.fromEntries([['fold', `Fold ${i + 1}`], ...MODELS.map((x) => [x.key, m.models[x.key].spatial_cv_pr_auc_folds[i]])])));
  chart(box, {
    type: 'bar',
    ariaLabel: 'PR-AUC per spatial cross-validation fold',
    data: { labels: Array.from({ length: n }, (_, i) => `Fold ${i + 1}`), datasets: MODELS.map((x) => ({ label: x.label, data: m.models[x.key].spatial_cv_pr_auc_folds, backgroundColor: pal[x.slot] })) },
    options: {
      datasets: { bar: { categoryPercentage: 0.7, barPercentage: 0.9 } },
      plugins: { tooltip: { callbacks: { label: (it) => ` ${it.dataset.label}: ${it.parsed.y.toFixed(3)}` } } },
      scales: { y: { beginAtZero: true, title: { display: true, text: 'PR-AUC (sample-weighted)' } }, x: { grid: { display: false } } },
    },
  });
  host.querySelector('.field-hint').textContent = `${m.development.folds} folds of ${m.development.block_km} km blocks (${m.development.spatial_blocks} blocks); whole blocks never straddle train and test.`;
}

function drawEvents() {
  const host = $('w-events');
  host.querySelectorAll('.ev').forEach((n) => n.remove());
  const held = new Set(m.holdout_dates);
  host.append(el('div', { class: 'ev', style: 'max-height:330px;overflow:auto' }, el('table', { class: 'data' },
    el('thead', {}, el('tr', {}, el('th', { text: 'Date' }), el('th', { class: 'r', text: 'Segments observed' }), el('th', { class: 'r', text: 'Flooded' }), el('th', { text: 'Use' }))),
    el('tbody', {}, m.events.map((e) => el('tr', {}, el('td', { text: e.date }), el('td', { class: 'r', text: fmt.int(e.observed) }),
      el('td', { class: 'r', text: fmt.pct(e.flooded_share, 2) }), el('td', {}, el('span', { class: `badge ${held.has(e.date) ? 'warn' : ''}`, text: held.has(e.date) ? 'held-out test' : 'training' }))))))),
  el('div', { class: 'ev field-hint', text: m.label_rule }));
}

function drawCard() {
  const host = $('w-card');
  host.querySelectorAll('.card-text').forEach((n) => n.remove());
  host.append(el('div', { class: 'card-text' },
    el('div', { text: `Version ${m.version}, trained ${m.trained_at.replace('T', ' ')}. Production model: ${m.production.kind}, refitted on all ${m.events.length} Sentinel-1 dates.` }),
    el('h4', { text: 'Data' }),
    el('ul', {}, el('li', { text: 'Labels: Sentinel-1 VV change detection + Otsu threshold (Google Earth Engine), JRC permanent water and steep slopes masked.' }),
      el('li', { text: 'Rainfall: IMD 0.25° daily gridded rainfall (imdlib); river levels: CWC hourly gauges; terrain: Copernicus GLO-30 DEM.' }),
      el('li', { text: 'Roads: OpenStreetMap drive network split into ~100 m segments.' })),
    el('h4', { text: 'Known blind spots' }),
    el('ul', {}, el('li', { text: 'Radar misses water under tree canopy and between buildings; satellite passes can miss the flood peak.' }),
      el('li', { text: 'IMD grids are ~27 km and daily — local cloudbursts are not resolved.' }),
      el('li', { text: 'Only four CWC gauges serve the district; dam releases are not a direct input.' }))));
}

function drawAll() { if (!m) return; drawGate(); drawPR(); drawReliability(); drawImportance(); drawFolds(); drawEvents(); drawCard(); }
onTheme(drawAll);
api.model().then((d) => { m = d; drawAll(); }).catch((err) => $('w-gate').append(el('div', { class: 'empty', text: `Model metrics unavailable: ${err.message}` })));
api.stats().then((s) => renderKpis(s.kpis)).catch(() => {});
