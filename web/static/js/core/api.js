// All HTTP calls go through here. Query values are encoded; failures surface as rejected promises.
import { state } from './bus.js';

async function request(path, opts = {}) {
  const res = await fetch(path, { headers: { Accept: 'application/json' }, ...opts });
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).error || msg; } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

function qs(params) {
  const u = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') u.set(k, v); });
  return u.toString();
}

const common = () => ({ preset: state.preset, scenario: state.scenario || undefined, date: state.simDate || undefined });
const when = () => ({ date: state.simDate || undefined });

export const api = {
  status: () => request('/api/status'),
  risk: (bbox, zoom) => request(`/api/risk?${qs({ bbox: bbox.join(','), zoom, scenario: state.scenario || undefined, colour: state.colour, ...when() })}`),
  route: (lat, lon) => request(`/api/route?${qs({ lat, lon, ...common() })}`),
  shelters: () => request(`/api/shelters?${qs(common())}`),
  gauges: () => request(`/api/gauges?${qs(when())}`),
  simulate: (mm) => request('/api/simulate', {
    method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ rain_mm_3d: mm, preset: state.preset, date: state.simDate || undefined }),
  }),
  explain: (eid) => request(`/api/explain/${encodeURIComponent(eid)}?${qs({ scenario: state.scenario || undefined, ...when() })}`),
  isochrone: (lat, lon, minutes = 15) => request(`/api/isochrone?${qs({ lat, lon, minutes, ...common() })}`),
  replaySummary: () => request('/api/replay'),
  replayDay: (date, bbox, zoom) => request(`/api/replay/${encodeURIComponent(date)}?${qs({ bbox: bbox && bbox.join(','), zoom, colour: state.colour })}`),
  stats: () => request(`/api/stats?${qs(common())}`),
  model: () => request('/api/model'),
  rainfall: () => request(`/api/rainfall?${qs(when())}`),
  dams: () => request('/api/dams'),
  alerts: () => request(`/api/alerts?${qs({ preset: state.preset })}`),
  taluks: () => request(`/api/responder/taluks?${qs(common())}`),
  exportUrl: (format) => `/api/export/routes?${qs({ preset: state.preset, format })}`,
};
