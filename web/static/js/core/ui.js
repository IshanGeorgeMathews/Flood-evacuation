// DOM + formatting helpers. Untrusted strings always go through textContent (never innerHTML).

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'style') node.setAttribute('style', v);
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

// Static, trusted SVG icon paths (no user data)
const ICONS = {
  alert: 'M12 2 1 21h22L12 2zm0 6 1 7h-2l1-7zm0 9.5a1.2 1.2 0 1 1 0 2.4 1.2 1.2 0 0 1 0-2.4z',
  check: 'M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z',
  info: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z',
  x: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm4.3 13-1.3 1.3L12 13.3 9 16.3 7.7 15l3-3-3-3L9 7.7l3 3 3-3L16.3 9l-3 3z',
  road: 'M11 2h2v4h-2zm0 7h2v4h-2zm0 7h2v6h-2zM4 22 8 2h2L6 22zm14 0L14 2h2l4 20z',
  people: 'M16 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm-8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm0 2c-2.3 0-7 1.2-7 3.5V19h14v-2.5C15 14.2 10.3 13 8 13zm8 0h-.9a4.8 4.8 0 0 1 1.9 3.5V19h6v-2.5c0-2.3-4.7-3.5-7-3.5z',
  home: 'M12 3 2 12h3v8h5v-6h4v6h5v-8h3z',
  block: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM4 12a8 8 0 0 1 12.9-6.3L5.7 16.9A8 8 0 0 1 4 12zm8 8a8 8 0 0 1-4.9-1.7L18.3 7.1A8 8 0 0 1 12 20z',
  bell: 'M12 22a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2zm6-6V11a6 6 0 0 0-5-5.9V4h-2v1.1A6 6 0 0 0 6 11v5l-2 2v1h16v-1z',
  pin: 'M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7zm0 9.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z',
  locate: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm9 3h-2.1A7 7 0 0 0 13 5.1V3h-2v2.1A7 7 0 0 0 5.1 11H3v2h2.1a7 7 0 0 0 5.9 5.9V21h2v-2.1a7 7 0 0 0 5.9-5.9H21z',
  share: 'M18 16a3 3 0 0 0-2.4 1.2l-6.7-3.4a3 3 0 0 0 0-1.6l6.7-3.4A3 3 0 1 0 15 7l-6.7 3.4a3 3 0 1 0 0 3.2L15 17a3 3 0 1 0 3-1z',
  download: 'M5 20h14v-2H5zm14-11h-4V3H9v6H5l7 7z',
  clock: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 11h-5v-2h3V6h2z',
  rain: 'M6 14a4 4 0 0 1-.6-8A6 6 0 0 1 17 6.3 4 4 0 0 1 18 14zm1 2-1.5 3 1.7.9 1.5-3zm5 0-1.5 3 1.7.9 1.5-3zm5 0-1.5 3 1.7.9 1.5-3z',
  wave: 'M2 15c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2v2c-2 0-2 2-4 2s-2-2-4-2-2 2-4 2-2-2-4-2-2 2-4 2zm0-6c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2v2c-2 0-2 2-4 2s-2-2-4-2-2 2-4 2-2-2-4-2-2 2-4 2z',
  shield: 'M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5z',
};

export function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', ICONS[name] || ICONS.info);
  p.setAttribute('fill', 'currentColor');
  svg.append(p);
  return svg;
}

export const fmt = {
  int: (v) => (v === null || v === undefined ? '–' : Math.round(v).toLocaleString('en-IN')),
  compact: (v) => {
    if (v === null || v === undefined) return '–';
    const a = Math.abs(v);
    if (a >= 1e7) return `${(v / 1e7).toFixed(1)} Cr`;
    if (a >= 1e5) return `${(v / 1e5).toFixed(1)} L`;
    if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return `${Math.round(v)}`;
  },
  km: (v, d = 1) => (v === null || v === undefined ? '–' : `${Number(v).toFixed(d)}`),
  pct: (v, d = 0) => (v === null || v === undefined ? '–' : `${(v * 100).toFixed(d)}%`),
  min: (s) => (s === null || s === undefined ? '–' : `${Math.max(1, Math.round(s / 60))}`),
  m: (v) => (v === null || v === undefined ? '–' : v >= 1000 ? `${(v / 1000).toFixed(1)} km` : `${Math.round(v)} m`),
  ago: (iso) => {
    if (!iso) return 'never';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 90) return 'just now';
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 172800) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} d ago`;
  },
  date: (iso) => (iso ? new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '–'),
};

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function toast(msg, ms = 3200) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

// Count-up for KPI values (respects reduced motion)
export function countUp(node, to, render, ms = 900) {
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const from = Number(node.dataset.v || 0);
  node.dataset.v = to;
  if (reduce || !isFinite(to)) { node.textContent = render(to); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / ms);
    const e = 1 - (1 - k) ** 3;
    node.textContent = render(from + (to - from) * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

export function setLoading(panel, on) {
  if (panel) panel.classList.toggle('loading', !!on);
}

export function errorNote(container, err) {
  container.replaceChildren(el('div', { class: 'empty', text: `Unavailable: ${err.message || err}` }));
}
