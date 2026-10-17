// River gauges: one small single-series line per CWC station against its warning and danger levels,
// plus station markers on the map. Status always carries an icon + label, never colour alone.
import { api } from '../core/api.js';
import { bus } from '../core/bus.js';
import { chart, onTheme, palette, refLines, tableToggle } from '../core/charts.js';
import { el, icon } from '../core/ui.js';

const L = window.L;
const STATUS = {
  'above danger': ['crit', 'alert'], 'above warning': ['warn', 'alert'], normal: ['good', 'check'], 'no data': ['', 'info'],
};

export function mount(panel, map) {
  const list = el('div', {}, el('div', { class: 'empty', text: 'Loading gauges…' }));
  panel.append(list);
  const layer = map ? L.layerGroup().addTo(map) : null;
  let data = null;

  function render() {
    if (!data) return;
    const pal = palette();
    list.replaceChildren();
    data.gauges.forEach((g) => {
      const [cls, ic] = STATUS[g.status] || STATUS['no data'];
      const box = el('div', { class: 'spark' });
      const trend = g.trend_3h === null || g.trend_3h === undefined ? '' : `${g.trend_3h >= 0 ? '▲' : '▼'} ${Math.abs(g.trend_3h).toFixed(2)} m / 3 h`;
      list.append(el('div', { class: 'gauge' },
        el('div', { class: 'gauge-head' },
          el('span', { class: 'name', text: `${g.name}` }),
          el('span', { class: 'lvl num', text: g.level === null ? '–' : `${g.level.toFixed(2)} m` })),
        el('div', { class: 'gauge-sub' },
          el('span', {}, el('span', { class: `badge ${cls}` }, icon(ic), g.status), ` ${g.river}`),
          el('span', { text: trend })),
        box));
      if (g.series.length) {
        const vals = g.series.map((s) => s.v);
        const lo = Math.min(...vals, g.warning) - 0.5;
        const hi = Math.max(...vals, g.danger) + 0.4;
        chart(box, {
          type: 'line',
          ariaLabel: `${g.name} water level, last 72 hours`,
          data: { labels: g.series.map((s) => s.t), datasets: [{ data: vals, borderColor: pal.s1, backgroundColor: pal.s1wash, fill: 'start', tension: 0.25 }] },
          options: {
            interaction: { mode: 'index', intersect: false },
            plugins: {
              refLines: { lines: [{ value: g.danger, color: pal.critical, label: `Danger ${g.danger.toFixed(1)}` }, { value: g.warning, color: pal.warning, label: `Warning ${g.warning.toFixed(1)}` }] },
              tooltip: { callbacks: { title: (it) => new Date(it[0].label).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }), label: (it) => ` ${it.parsed.y.toFixed(2)} m` } },
            },
            scales: { x: { display: false }, y: { display: false, min: lo, max: hi } },
          },
          plugins: [refLines],
        });
      } else {
        box.replaceChildren(el('div', { class: 'empty', text: 'No readings in the last 72 h' }));
      }
    });
    tableToggle(list, [
      { key: 'name', label: 'Station' }, { key: 'river', label: 'River' },
      { key: 'level', label: 'Level (m)', right: true, fmt: (v) => (v === null ? '–' : v.toFixed(2)) },
      { key: 'warning', label: 'Warning', right: true }, { key: 'danger', label: 'Danger', right: true },
      { key: 'hfl', label: 'Record (HFL)', right: true }], data.gauges);

    if (layer) {
      layer.clearLayers();
      data.gauges.forEach((g) => {
        if (g.lat === null) return;
        const color = g.status === 'above danger' ? pal.critical : g.status === 'above warning' ? pal.warning : pal.s1;
        const m = L.circleMarker([g.lat, g.lon], { radius: 8, weight: 3, color: pal.surface, fillColor: color, fillOpacity: 1, renderer: map.renderer });
        m.bindTooltip(`${g.name} (${g.river}) · ${g.level === null ? 'no data' : `${g.level.toFixed(2)} m`} · danger ${g.danger} m · ${g.status}`);
        layer.addLayer(m);
      });
    }
  }

  async function load() {
    try {
      data = await api.gauges();
      render();
    } catch (err) {
      list.replaceChildren(el('div', { class: 'empty', text: `Gauges unavailable: ${err.message}` }));
    }
  }
  onTheme(render);
  bus.on('sse:refresh', load);
  bus.on('state:simDate', load);
  if (layer) bus.on('layer:gauges', (on) => (on ? map.addLayer(layer) : map.removeLayer(layer)));
  load();
}

