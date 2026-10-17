// Explain-this-road: tap a road to see its probability and the top SHAP reasons behind it.
import { api } from '../core/api.js';
import { bus, state } from '../core/bus.js';
import { palette } from '../core/charts.js';
import { el, fmt } from '../core/ui.js';

const L = window.L;
const NAMES = {
  elev: 'Elevation', hand: 'Height above drainage', slope: 'Slope', twi: 'Wetness index', dist_stream_m: 'Distance to stream',
  stream_order: 'Stream order', flow_acc_log: 'Upslope area', landcover_water: 'Water / wetland nearby',
  landcover_built: 'Built-up', landcover_tree: 'Tree cover', landcover_crop: 'Cropland', road_class_rank: 'Road class',
  is_bridge: 'Bridge', is_causeway: 'Causeway / bund', pop_density: 'Population', dist_gauge_km: 'Distance to gauge',
  rain_1d: 'Rain, 1 day', rain_3d: 'Rain, 3 days', rain_5d: 'Rain, 5 days', rain_7d: 'Rain, 7 days',
  rain_up_3d: 'Upstream rain, 3 days', rain_up_5d: 'Upstream rain, 5 days', gauge_near_rel: 'Nearest river vs danger',
  gauge_near_rel_3d: 'River peak (3 d) vs danger', gauge_max_rel: 'Highest river vs danger', days_since_onset: 'Days into monsoon',
  past_flood_freq: 'Flooded in past events',
};
const UNITS = {
  elev: 'm', hand: 'm', slope: '°', dist_stream_m: 'm', rain_1d: 'mm', rain_3d: 'mm', rain_5d: 'mm', rain_7d: 'mm',
  rain_up_3d: 'mm', rain_up_5d: 'mm', gauge_near_rel: 'm', gauge_near_rel_3d: 'm', gauge_max_rel: 'm', dist_gauge_km: 'km',
};

function valueText(feature, v) {
  if (v === null || v === undefined) return 'no data';
  if (feature.startsWith('landcover') || feature === 'past_flood_freq') return fmt.pct(v);
  if (feature === 'is_bridge' || feature === 'is_causeway') return v ? 'yes' : 'no';
  const u = UNITS[feature] || '';
  return `${Math.abs(v) >= 100 ? Math.round(v) : v.toFixed(1)}${u ? ` ${u}` : ''}`;
}

export function mount(map) {
  bus.on('road:click', async ({ eid, latlng }) => {
    if (state.replayDate) {
      L.popup().setLatLng(latlng).setContent('Road explanations are available for the live picture and what-if scenarios.').openOn(map);
      return;
    }
    const pop = L.popup({ maxWidth: 360 }).setLatLng(latlng).setContent('Explaining…').openOn(map);
    try {
      const d = await api.explain(eid);
      const pal = palette();
      const maxAbs = Math.max(0.01, ...d.top.map((t) => Math.abs(t.shap)));
      const rows = d.top.map((t) => {
        const w = (Math.abs(t.shap) / maxAbs) * 50;
        const up = t.shap > 0;
        return el('div', { class: 'why-row' },
          el('span', { title: valueText(t.feature, t.value) }, el('b', { text: NAMES[t.feature] || t.feature }), el('div', { class: 'muted', text: valueText(t.feature, t.value) })),
          el('div', { class: 'bar', role: 'img', 'aria-label': `${up ? 'raises' : 'lowers'} risk` },
            el('span', { style: `${up ? 'left:50%' : `left:${50 - w}%`};width:${w}%;background:${up ? pal.critical : pal.s1}` })),
          el('span', { class: 'num', style: 'text-align:right', text: `${up ? '+' : '−'}${Math.abs(t.shap).toFixed(2)}` }));
      });
      const r = d.road;
      const node = el('div', { class: 'explain' },
        el('h3', { text: r.name || (r.highway ? `${r.highway} road` : 'Road segment') }),
        el('div', { class: 'muted', text: `${r.highway || ''}${r.bridge ? ' · bridge' : ''}${r.causeway ? ' · causeway' : ''} · ${fmt.m(r.length_m)}` }),
        el('div', { class: 'p' }, fmt.pct(d.p), el('small', { class: 'muted', text: ' flood probability' })),
        el('div', { class: 'muted', text: `${d.date}${d.scenario_mm ? ` · what-if +${d.scenario_mm} mm` : ''} · bars: raises (right) / lowers (left) risk` }),
        el('div', { class: 'why' }, rows),
        el('div', { class: 'note', text: `${d.base_value_note}. Model inputs: HAND ${valueText('hand', r.values?.hand)}, 3-day rain ${valueText('rain_3d', r.values?.rain_3d)}, nearest river ${valueText('gauge_near_rel', r.values?.gauge_near_rel)}.` }));
      pop.setContent(node);
    } catch (err) {
      pop.setContent(`Explanation unavailable: ${err.message}`);
    }
  });
}
