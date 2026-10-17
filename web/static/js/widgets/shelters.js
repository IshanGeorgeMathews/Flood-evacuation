// Shelters: map layer (open / closed by flood risk) + the three nearest to the chosen origin with capacity bars.
import { api } from '../core/api.js';
import { bus, state } from '../core/bus.js';
import { palette } from '../core/charts.js';
import { haversine } from '../core/map.js';
import { el, fmt, icon } from '../core/ui.js';

const L = window.L;

export function mount(panel, map) {
  const layer = L.layerGroup().addTo(map);
  const list = el('div', {}, el('div', { class: 'empty', text: 'Loading shelters…' }));
  panel.append(list);
  let fc = null;

  function drawLayer() {
    layer.clearLayers();
    if (!fc) return;
    const pal = palette();
    fc.features.forEach((f) => {
      const p = f.properties;
      const [lon, lat] = f.geometry.coordinates;
      const m = L.circleMarker([lat, lon], {
        renderer: map.renderer, radius: p.open ? 5 : 4, weight: 2, color: pal.surface,
        fillColor: p.open ? pal.good : pal.critical, fillOpacity: 0.95,
      });
      m.bindTooltip(`${p.name} — ${p.open ? 'open' : 'flood risk, closed'} · capacity ~${p.capacity}`);
      layer.addLayer(m);
    });
  }

  function renderList() {
    if (!fc) return;
    const o = state.origin;
    if (!o) {
      const open = fc.features.filter((f) => f.properties.open).length;
      list.replaceChildren(el('div', { class: 'empty', text: `${open} of ${fc.features.length} candidate shelters reachable. Pick a starting point to see the nearest.` }));
      return;
    }
    const near = fc.features.map((f) => ({ f, d: haversine(o, { lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0] }) }))
      .sort((a, b) => a.d - b.d).slice(0, 3);
    list.replaceChildren(...near.map(({ f, d }) => {
      const p = f.properties;
      const load = p.capacity ? Math.min(1, p.demand / p.capacity) : 0;
      const status = !p.open ? ['crit', 'x', 'At flood risk'] : load > 0.9 ? ['warn', 'alert', 'Near full'] : ['good', 'check', 'Open'];
      return el('div', { class: 'shelter' },
        el('div', { class: 'shelter-head' }, el('b', { text: p.name }), el('span', { class: 'muted', text: `${(d / 1000).toFixed(1)} km` })),
        el('div', { class: 'shelter-meta' },
          el('span', { class: `badge ${status[0]}` }, icon(status[1]), status[2]),
          el('span', { text: `${fmt.int(p.demand)} / ${fmt.int(p.capacity)} est. places` }),
          p.verified ? null : el('span', { class: 'badge', title: 'OSM candidate, not yet confirmed by DDMA', text: 'unverified' })),
        el('div', { class: `meter ${load > 0.9 ? 'crit' : load > 0.7 ? 'warn' : ''}`, role: 'meter', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(load * 100)), 'aria-label': 'Projected occupancy' },
          el('span', { style: `width:${Math.round(load * 100)}%` })),
        el('div', { class: 'shelter-meta', text: `${p.kind.replace('_', ' ')} · ${p.facilities}` }));
    }));
  }

  async function load() {
    try {
      fc = await api.shelters();
      drawLayer();
      renderList();
    } catch (err) {
      list.replaceChildren(el('div', { class: 'empty', text: `Shelters unavailable: ${err.message}` }));
    }
  }
  bus.on('route', renderList);
  bus.on('state:preset', load);
  bus.on('state:scenario', load);
  bus.on('state:simDate', load);
  bus.on('sse:refresh', load);
  bus.on('theme', drawLayer);
  bus.on('layer:shelters', (on) => (on ? map.addLayer(layer) : map.removeLayer(layer)));
  load();
}
