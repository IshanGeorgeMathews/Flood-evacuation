// Live risk map: road segments coloured by flood-risk state, with width growing with probability.
// Also hosts the replay layers (model prediction + radar-observed flooding) and the layer toggles.
import { api } from '../core/api.js';
import { bus, state } from '../core/bus.js';
import { palette, RISK_CLASSES } from '../core/charts.js';
import { bboxOf, debounce } from '../core/map.js';
import { el, toast } from '../core/ui.js';

const L = window.L;

export function mount(map, layersHost, legendHost) {
  const roads = L.layerGroup().addTo(map);
  const observed = L.layerGroup().addTo(map);
  let lastReq = 0;
  let presetTau = { cautious: 0.1, balanced: 0.2, fast: 0.4 };

  let lastMeta = null;
  const KEYS = ['none', 'warning', 'serious', 'critical'];

  function style(p, cls) {
    const pal = palette();
    const blocked = p > presetTau[state.preset];
    return {
      color: pal[KEYS[cls]],
      weight: cls === 0 ? 1.2 : blocked ? 5.5 : 2 + 1.2 * cls,
      opacity: cls === 0 ? 0.55 : 0.95,
      lineCap: 'round',
      renderer: map.renderer,
      bubblingMouseEvents: false, // a road tap explains the road; only empty-map taps start a route
    };
  }

  function draw(fc, target) {
    target.clearLayers();
    const layer = L.geoJSON(fc, {
      renderer: map.renderer,
      style: (f) => style(f.properties.p, Math.min(3, f.properties.c || 0)),
      onEachFeature: (f, lyr) => {
        lyr.on('click', (e) => {
          L.DomEvent.stopPropagation(e);
          bus.emit('road:click', { eid: f.properties.eid, p: f.properties.p, latlng: e.latlng });
        });
      },
    });
    target.addLayer(layer);
  }

  async function load() {
    const req = ++lastReq;
    const bbox = bboxOf(map);
    const zoom = map.getZoom();
    try {
      if (state.replayDate) {
        const d = await api.replayDay(state.replayDate, bbox, zoom);
        if (req !== lastReq) return;
        lastMeta = d.meta || null;
        draw(d, roads);
        renderLegend();
        observed.clearLayers();
        if (d.observed && d.observed.features.length && toggles.observed.checked) {
          observed.addLayer(L.geoJSON(d.observed, {
            renderer: map.renderer,
            style: { color: palette().s1, weight: 7, opacity: 0.45, lineCap: 'round' },
            interactive: false,
          }));
        }
        bus.emit('replay:day', d);
      } else {
        const fc = await api.risk(bbox, zoom);
        if (req !== lastReq) return;
        observed.clearLayers();
        lastMeta = fc.meta || null;
        draw(fc, roads);
        renderLegend();
      }
    } catch (err) {
      toast(`Risk layer unavailable: ${err.message}`);
    }
  }

  // ---- layer toggles
  const toggles = {};
  function toggle(key, label, checked, onChange) {
    const input = el('input', { type: 'checkbox', checked: checked || null });
    input.checked = !!checked;
    input.addEventListener('change', () => onChange(input.checked));
    toggles[key] = input;
    layersHost.append(el('label', {}, input, label));
  }
  toggle('roads', 'Road flood risk', true, (on) => (on ? map.addLayer(roads) : map.removeLayer(roads)));
  toggle('shelters', 'Shelters', true, (on) => bus.emit('layer:shelters', on));
  toggle('gauges', 'River gauges', true, (on) => bus.emit('layer:gauges', on));
  toggle('observed', 'Radar flood (replay)', true, (on) => (on ? map.addLayer(observed) : map.removeLayer(observed)));
  toggle('iso', '15-min safe reach', false, (on) => bus.emit('layer:isochrone', on));
  toggle('rank', 'Colour by relative risk', false, (on) => { state.colour = on ? 'rank' : 'probability'; load(); });
  bus.on('colour:set', (c) => { toggles.rank.checked = c === 'rank'; state.colour = c; load(); });

  // ---- legend (status scale, always labelled)
  function renderLegend() {
    const pal = palette();
    const rank = state.colour === 'rank';
    const pc = (v) => (v < 0.01 ? `${(v * 100).toFixed(2)}%` : `${Math.round(v * 100)}%`);
    const rb = lastMeta && lastMeta.rank_bounds;
    const labels = rank
      ? ['Rest of network', `Top 5% of roads${rb ? ` (p ≥ ${pc(rb[0])})` : ''}`, `Top 2%${rb ? ` (p ≥ ${pc(rb[1])})` : ''}`, `Top 0.5%${rb ? ` (p ≥ ${pc(rb[2])})` : ''}`]
      : RISK_CLASSES.map((c) => c.label);
    const when = state.replayDate || state.simDate;
    const title = `${rank ? 'Relative flood risk' : 'Road flood probability'}${when ? ` · ${when}` : ''}`;
    legendHost.replaceChildren(...[
      el('div', { class: 'legend-title', text: title }),
      ...RISK_CLASSES.map((c, i) => ({ c, label: labels[i], h: [2, 3, 5, 6][i] })).reverse().map(({ c, label, h }) => el('div', { class: 'legend-row' },
        el('span', { class: 'legend-swatch', style: `background:${pal[c.key]};height:${h}px` }), label)),
      state.replayDate ? el('div', { class: 'legend-row' },
        el('span', { class: 'legend-swatch', style: `background:${pal.s1};opacity:.5;height:7px` }), 'Radar-observed flooding') : null,
      el('div', { class: 'legend-row muted', text: 'Thick = above route-block threshold' })].filter(Boolean));
  }
  renderLegend();

  const reload = debounce(load, 250);
  map.on('moveend', reload);
  bus.on('state:scenario', () => { load(); });
  bus.on('state:simDate', () => { load(); renderLegend(); });
  bus.on('state:preset', () => { load(); renderLegend(); });
  bus.on('state:replayDate', () => { load(); renderLegend(); });
  bus.on('theme', () => { load(); renderLegend(); });
  bus.on('sse:refresh', () => { if (!state.replayDate) load(); });
  bus.on('presets:tau', (t) => { presetTau = t; });
  load();
  return { reload: load };
}
