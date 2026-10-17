// Page shell shared by every view: theme toggle, clock, freshness badge, alert ticker, KPI strip, SSE stream.
import { api } from './api.js';
import { bus, state } from './bus.js';
import { countUp, el, fmt, icon, toast } from './ui.js';

const RISKY = `${Math.round(Number(document.body.dataset.riskyP || 0.2) * 100)}%`;

const DEFAULT_ALERT_ICON = { danger: 'alert', warning: 'alert', info: 'info', ok: 'check' };

export function initTheme() {
  const btn = document.getElementById('theme-toggle');
  btn?.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('fe-theme', next); } catch (e) { /* storage unavailable */ }
    bus.emit('theme', next);
  });
}

export function initClock() {
  const c = document.getElementById('clock');
  if (!c) return;
  const tick = () => { c.textContent = new Date().toLocaleString('en-IN', { weekday: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' IST'; };
  tick();
  setInterval(tick, 1000);
}

export async function renderFreshness() {
  const host = document.getElementById('w-freshness');
  if (!host) return null;
  try {
    const s = await api.status();
    const pills = s.feeds.filter((f) => ['rainfall', 'gauges', 'model'].includes(f.name)).map((f) =>
      el('span', { class: `chip state-${f.state}`, title: `${f.source}${f.detail ? ` — ${f.detail}` : ''}` },
        el('span', { class: 'dot' }), `${f.name}`, el('span', { class: 'muted', text: f.name === 'model' ? s.model_version : fmt.ago(f.last_ok) })));
    host.replaceChildren(...pills);
    bus.emit('status', s);
    return s;
  } catch (err) {
    host.replaceChildren(el('span', { class: 'chip state-down' }, el('span', { class: 'dot' }), 'API offline'));
    return null;
  }
}

export async function renderAlerts() {
  const host = document.getElementById('w-alerts');
  if (!host) return;
  try {
    const { alerts } = await api.alerts();
    host.replaceChildren(...alerts.map((a) => el('div', { class: `alert lvl-${a.level}` },
      icon(DEFAULT_ALERT_ICON[a.level] || 'info'), el('span', { class: 't', text: a.title }), el('span', { class: 'd', text: a.detail || '' }))));
  } catch (err) {
    host.replaceChildren(el('div', { class: 'alert lvl-info' }, icon('info'), el('span', { class: 't', text: 'Alerts unavailable' })));
  }
}

const KPI_DEFS = [
  { key: 'roads_at_risk_km', label: 'Roads at risk', unit: 'km', icon: 'road', render: (v) => fmt.km(v, 1), sub: (k) => `of ${fmt.int(k.network_km)} km network, p ≥ ${RISKY}`, upBad: true },
  { key: 'roads_blocked_km', label: 'Roads blocked', unit: 'km', icon: 'block', render: (v) => fmt.km(v, 1), sub: () => `above ${state.preset} threshold`, upBad: true },
  { key: 'people_exposed', label: 'Residents along at-risk roads', icon: 'people', render: (v) => fmt.compact(v), sub: () => 'WorldPop 2020 estimate', upBad: true },
  { key: 'shelters_open', label: 'Shelters reachable', icon: 'home', render: (v) => fmt.int(v), sub: (k) => `of ${fmt.int(k.shelters_total)} candidates (OSM)` },
  { key: 'capacity_used_pct', label: 'Shelter demand vs capacity', unit: '%', icon: 'shield', render: (v) => v.toFixed(v < 10 ? 1 : 0), sub: (k) => `${fmt.compact(k.shelter_demand)} of ${fmt.compact(k.shelter_capacity)} places`, meter: true, upBad: true },
  { key: 'segments_at_risk', label: `Road segments ≥ ${RISKY}`, icon: 'alert', render: (v) => fmt.int(v), sub: (k) => `mean probability ${fmt.pct(k.mean_p, 1)}`, upBad: true },
];

export function renderKpis(kpis, baseline = null, baseLabel = 'live') {
  const host = document.getElementById('w-kpis');
  if (!host || !kpis) return;
  if (!host.children.length) {
    KPI_DEFS.forEach((d) => {
      host.append(el('div', { class: 'kpi', 'data-key': d.key },
        el('div', { class: 'kpi-label' }, icon(d.icon), d.label),
        el('div', { class: 'kpi-value' }, el('span', { class: 'v', text: '–' }), d.unit ? el('small', { text: d.unit }) : null),
        el('div', { class: 'kpi-sub' }),
        d.meter ? el('div', { class: 'meter', role: 'presentation' }, el('span', { style: 'width:0%' })) : null));
    });
  }
  KPI_DEFS.forEach((d) => {
    const card = host.querySelector(`[data-key="${d.key}"]`);
    countUp(card.querySelector('.v'), kpis[d.key] ?? 0, d.render);
    const sub = card.querySelector('.kpi-sub');
    sub.replaceChildren();
    if (baseline && typeof baseline[d.key] === 'number') {
      const delta = kpis[d.key] - baseline[d.key];
      if (Math.abs(delta) > 1e-6) {
        const up = delta > 0;
        sub.append(el('span', { class: `kpi-delta ${up === !!d.upBad ? 'up-bad' : 'down-good'}`, text: `${up ? '▲' : '▼'} ${d.render(Math.abs(delta))} vs ${baseLabel}` }), ' ');
      }
    }
    sub.append(d.sub(kpis));
    if (d.meter) {
      const v = Math.min(100, kpis[d.key] || 0);
      const m = card.querySelector('.meter');
      m.className = `meter ${v > 90 ? 'crit' : v > 70 ? 'warn' : ''}`;
      m.firstChild.style.width = `${v}%`;
    }
  });
}

export function initStream() {
  if (!window.EventSource) return;
  const es = new EventSource('/api/stream');
  es.addEventListener('refresh', (e) => {
    const data = JSON.parse(e.data);
    bus.emit('sse:refresh', data);
    toast(`Risk picture refreshed · ${data.live_date || ''}`);
  });
  es.onerror = () => { /* the browser retries automatically */ };
}

export function initShell() {
  initTheme();
  initClock();
  renderFreshness();
  renderAlerts();
  bus.on('sse:refresh', () => { renderFreshness(); renderAlerts(); });
  bus.on('state:preset', renderAlerts);
  // live push only where it matters (each open stream holds a server thread)
  if (document.body.classList.contains('page-console')) initStream();
  setInterval(renderFreshness, 60_000);
}
