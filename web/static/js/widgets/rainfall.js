// District rainfall: last 10 days (observed / provisional) and the 3-day forecast — one measure, one axis.
import { api } from '../core/api.js';
import { bus } from '../core/bus.js';
import { chart, legend, onTheme, palette, tableToggle } from '../core/charts.js';
import { el, fmt } from '../core/ui.js';

export function mount(panel) {
  const head = el('div', { class: 'kv' });
  const box = el('div', { class: 'chart-box' });
  const foot = el('div', { class: 'field-hint' });
  const legendHost = el('div');
  const tableHost = el('div');
  panel.append(head, legendHost, box, foot, tableHost);
  let data = null;

  function render() {
    if (!data) return;
    const pal = palette();
    const rows = [...data.daily.map((d) => ({ ...d, kind: 'Observed' })), ...data.forecast.map((d) => ({ ...d, kind: 'Forecast' }))];
    head.replaceChildren(
      el('dt', { text: 'Upstream catchment, last 3 days' }), el('dd', { text: data.upstream_3d === null ? '–' : `${fmt.int(data.upstream_3d)} mm` }),
      el('dt', { text: 'Next 3 days (forecast)' }), el('dd', { text: `${fmt.int(data.forecast.reduce((a, b) => a + b.mm, 0))} mm` }));
    legendHost.replaceChildren(legend([{ label: 'Observed (district mean)', color: pal.s1 }, { label: 'Forecast', color: pal.s2 }]));
    chart(box, {
      type: 'bar',
      ariaLabel: 'Daily district-mean rainfall, observed and forecast',
      data: {
        labels: rows.map((r) => r.date.slice(5)),
        datasets: [{ data: rows.map((r) => r.mm), backgroundColor: rows.map((r) => (r.kind === 'Forecast' ? pal.s2 : pal.s1)) }],
      },
      options: {
        plugins: { tooltip: { displayColors: false, callbacks: { title: (it) => `${rows[it[0].dataIndex].kind} · ${rows[it[0].dataIndex].date}`, label: (it) => `${it.parsed.y.toFixed(1)} mm` } } },
        scales: { x: { grid: { display: false } }, y: { beginAtZero: true, title: { display: true, text: 'mm / day' } } },
      },
    });
    foot.textContent = `Source: ${data.source}${data.forecast_source ? ` · forecast: ${data.forecast_source}` : ''}`;
    tableHost.replaceChildren();
    tableToggle(tableHost, [{ key: 'date', label: 'Date' }, { key: 'kind', label: 'Type' }, { key: 'mm', label: 'mm', right: true }], rows);
  }

  async function load() {
    try { data = await api.rainfall(); render(); } catch (err) { box.replaceChildren(el('div', { class: 'empty', text: `Rainfall unavailable: ${err.message}` })); }
  }
  onTheme(render);
  bus.on('sse:refresh', load);
  bus.on('state:simDate', load);
  load();
}
