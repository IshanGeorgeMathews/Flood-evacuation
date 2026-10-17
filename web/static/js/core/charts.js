// Chart.js theming + helpers following the data-viz spec: 2px lines, <=24px bars with 4px rounded data-ends,
// hairline solid grids, legend for >=2 series, tooltip on every chart, a table-view twin for every chart.
import { bus } from './bus.js';
import { cssVar, el } from './ui.js';

const Chart = window.Chart;
const registry = new Set();

export const palette = () => ({
  s1: cssVar('--series-1'), s2: cssVar('--series-2'), s3: cssVar('--series-3'),
  s1wash: cssVar('--series-1-wash'),
  good: cssVar('--good'), warning: cssVar('--warning'), serious: cssVar('--serious'), critical: cssVar('--critical'),
  none: cssVar('--risk-none'), text: cssVar('--text-primary'), text2: cssVar('--text-secondary'),
  muted: cssVar('--text-muted'), grid: cssVar('--grid'), axis: cssVar('--axis'), surface: cssVar('--surface-1'),
});

// Flood-risk state classes (status scale; always shown with a text label in legends and popups)
// Boundaries come from configs/routing.yaml (risk_classes) via the page's data attributes
const B = (document.body.dataset.riskClasses || '0.05,0.1,0.2').split(',').map(Number);
const pc = (v) => `${Math.round(v * 100)}%`;
export const RISK_CLASSES = [
  { max: B[0], key: 'none', label: `Low (< ${pc(B[0])})` },
  { max: B[1], key: 'warning', label: `Watch (${pc(B[0])}–${pc(B[1])})` },
  { max: B[2], key: 'serious', label: `High (${pc(B[1])}–${pc(B[2])})` },
  { max: 1.01, key: 'critical', label: `Severe (≥ ${pc(B[2])})` },
];
export const RISKY_P = Number(document.body.dataset.riskyP || 0.2);

export function riskClass(p) {
  return RISK_CLASSES.findIndex((c) => p < c.max);
}

export function riskColor(p, pal = palette()) {
  return pal[RISK_CLASSES[Math.max(0, riskClass(p))].key];
}

function applyDefaults() {
  const p = palette();
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 11.5;
  Chart.defaults.color = p.muted;
  Chart.defaults.borderColor = p.grid;
  Chart.defaults.animation.duration = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 500;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.plugins.legend.display = false; // we render our own HTML legends (text tokens + swatches)
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: p.surface, titleColor: p.text2, bodyColor: p.text, borderColor: p.axis, borderWidth: 1,
    padding: 10, cornerRadius: 8, displayColors: true, boxWidth: 14, boxHeight: 2, usePointStyle: false,
    titleFont: { weight: '600' }, bodyFont: { weight: '700' },
  });
  Chart.defaults.elements.line.borderWidth = 2;
  Chart.defaults.elements.line.borderCapStyle = 'round';
  Chart.defaults.elements.line.borderJoinStyle = 'round';
  Chart.defaults.elements.point.radius = 0;
  Chart.defaults.elements.point.hoverRadius = 5;
  Chart.defaults.elements.point.hitRadius = 14;
  Chart.defaults.elements.bar.borderRadius = { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 };
  Chart.defaults.elements.bar.borderSkipped = 'start';
  Chart.defaults.datasets.bar.maxBarThickness = 24;
  Chart.defaults.scale.grid.color = p.grid;
  Chart.defaults.scale.grid.lineWidth = 1;
  Chart.defaults.scale.border.color = p.axis;
  Chart.defaults.scale.ticks.color = p.muted;
}
applyDefaults();

// Re-theme every registered chart when the theme flips
bus.on('theme', () => {
  applyDefaults();
  registry.forEach((fn) => fn());
});

export function onTheme(fn) {
  registry.add(fn);
  return fn;
}

/** Create (or replace) a chart inside `box`. */
export function chart(box, config) {
  if (box._chart) box._chart.destroy();
  const canvas = box.querySelector('canvas') || box.appendChild(el('canvas', { role: 'img' }));
  if (config.ariaLabel) canvas.setAttribute('aria-label', config.ariaLabel);
  box._chart = new Chart(canvas, config);
  return box._chart;
}

/** HTML legend: rect keys for bars/areas, line keys for lines. Text stays in text tokens. */
export function legend(items) {
  return el('div', { class: 'chart-legend' }, items.map((it) =>
    el('span', {}, el('i', { class: it.line ? 'line' : '', style: it.line ? `border-color:${it.color}` : `background:${it.color}` }),
      it.label)));
}

/** "Show table" toggle that renders the same numbers as an accessible table (the chart's table-view twin). */
export function tableToggle(host, columns, rows) {
  const wrap = el('div', { class: 'table-wrap', hidden: true });
  const btn = el('button', { class: 'table-toggle', type: 'button', 'aria-expanded': 'false', text: 'Show table' });
  const render = () => {
    const head = el('tr', {}, columns.map((c) => el('th', { class: c.right ? 'r' : '', text: c.label })));
    const body = rows.map((r) => el('tr', {}, columns.map((c) => el('td', { class: c.right ? 'r' : '', text: c.fmt ? c.fmt(r[c.key], r) : r[c.key] }))));
    wrap.replaceChildren(el('table', { class: 'data' }, el('thead', {}, head), el('tbody', {}, body)));
  };
  btn.addEventListener('click', () => {
    const open = wrap.hidden;
    if (open) render();
    wrap.hidden = !open;
    btn.setAttribute('aria-expanded', String(open));
    btn.textContent = open ? 'Hide table' : 'Show table';
  });
  host.append(btn, wrap);
}

/** Horizontal reference line plugin (warning / danger levels). Labelled in text ink, never data colour. */
export const refLines = {
  id: 'refLines',
  afterDatasetsDraw(c, _args, opts) {
    const lines = opts && opts.lines;
    if (!lines || !lines.length) return;
    const { ctx, chartArea, scales } = c;
    const p = palette();
    lines.forEach((l) => {
      const y = scales.y.getPixelForValue(l.value);
      if (y < chartArea.top - 1 || y > chartArea.bottom + 1) return;
      ctx.save();
      ctx.strokeStyle = l.color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(chartArea.left, y);
      ctx.lineTo(chartArea.right, y);
      ctx.stroke();
      ctx.fillStyle = p.text2;
      ctx.font = '600 10px system-ui, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(l.label, chartArea.right - 2, y - 3);
      ctx.restore();
    });
  },
};
