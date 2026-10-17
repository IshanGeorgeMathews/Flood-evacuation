// Data feeds & model: age, source and state of every input; the model version and prediction mode.
import { bus } from '../core/bus.js';
import { el, fmt, icon } from '../core/ui.js';

const STATE = { ok: ['good', 'check', 'Live'], provisional: ['warn', 'info', 'Provisional'], stale: ['warn', 'alert', 'Stale'], down: ['crit', 'x', 'Down'] };

export function mount(panel) {
  const body = el('div', {}, el('div', { class: 'empty', text: 'Checking feeds…' }));
  panel.append(body);
  bus.on('status', (s) => {
    const rows = s.feeds.map((f) => {
      const [cls, ic, label] = STATE[f.state] || STATE.down;
      return el('div', { class: 'shelter' },
        el('div', { class: 'shelter-head' }, el('b', { text: f.name[0].toUpperCase() + f.name.slice(1) }), el('span', { class: `badge ${cls}` }, icon(ic), label)),
        el('div', { class: 'shelter-meta', text: f.source }),
        el('div', { class: 'shelter-meta', text: `Data for ${f.data_date || '–'} · fetched ${fmt.ago(f.last_ok)}${f.detail ? ` · ${f.detail}` : ''}` }));
    });
    body.replaceChildren(
      el('dl', { class: 'kv' },
        el('dt', { text: 'Risk picture for' }), el('dd', { text: s.live_date }),
        el('dt', { text: 'Prediction mode' }), el('dd', { text: s.mode === 'full' ? 'Rain + river model' : 'Terrain-only fallback' }),
        el('dt', { text: 'Refresh cycle' }), el('dd', { text: `every ${s.refresh_minutes} min` }),
        el('dt', { text: 'Last refresh' }), el('dd', { text: fmt.ago(s.refreshed_at) })),
      ...rows);
  });
}
