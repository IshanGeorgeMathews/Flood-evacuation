// Simulation lab: run the whole console (risk map, routes, shelters, gauges, rainfall, KPIs) on a real historical
// day — e.g. the 16 Aug 2018 peak — using that day's IMD rainfall and CWC river levels. What-if rain stacks on top.
import { bus, state } from '../core/bus.js';
import { el, toast } from '../core/ui.js';

const DEMO = { date: '2018-08-16', lat: 10.1076, lon: 76.3525, place: 'Aluva' };

export function mount(panel, badge) {
  const seg = el('div', { class: 'seg', role: 'group', 'aria-label': 'Conditions' });
  const liveBtn = el('button', { type: 'button', 'aria-pressed': 'true', text: 'Live today' });
  const histBtn = el('button', { type: 'button', 'aria-pressed': 'false', text: 'Historical day' });
  seg.append(liveBtn, histBtn);
  const pick = el('select', { 'aria-label': 'Historical flood day' });
  const date = el('input', { type: 'date', 'aria-label': 'Any date to simulate', style: 'width:100%;min-height:40px;border-radius:9px;border:1px solid var(--border-strong);background:var(--surface-2);color:var(--text-primary);padding:0 10px' });
  const hist = el('div', { style: 'display:grid;gap:8px', hidden: true }, pick, el('div', { class: 'field-hint', text: 'or any date:' }), date);
  const demo = el('button', { class: 'btn btn-primary', type: 'button', text: '▶ Run the 2018 flood demo' });
  panel.append(
    el('p', { class: 'field-hint', style: 'margin-top:0', text: 'Run the whole console on a real past day: that day’s IMD rainfall and CWC river levels drive the risk map, routes, shelters and KPIs. Add what-if rain below to stress-test it.' }),
    seg, hist, el('div', { class: 'btn-row', style: 'margin-top:8px' }, demo));

  bus.on('status', (s) => {
    if (!s.sim_days || pick.options.length) return;
    pick.append(el('option', { value: '', text: 'Choose a flood day…' }), ...s.sim_days.map((d) => el('option', { value: d.date, text: d.label })));
    if (s.sim_range) { date.min = s.sim_range[0]; date.max = s.sim_range[1]; }
  });

  function setMode(historical) {
    liveBtn.setAttribute('aria-pressed', String(!historical));
    histBtn.setAttribute('aria-pressed', String(historical));
    hist.hidden = !historical;
  }
  function choose(d) {
    if (!d) return;
    setMode(true);
    pick.value = [...pick.options].some((o) => o.value === d) ? d : '';
    date.value = d;
    bus.set('scenario', 0);
    bus.set('simDate', d);
  }
  liveBtn.addEventListener('click', () => { setMode(false); bus.set('scenario', 0); bus.set('simDate', null); });
  histBtn.addEventListener('click', () => { setMode(true); if (!state.simDate) choose(DEMO.date); });
  pick.addEventListener('change', () => choose(pick.value));
  date.addEventListener('change', () => choose(date.value));
  demo.addEventListener('click', () => {
    bus.emit('colour:set', 'rank');
    choose(DEMO.date);
    toast(`Simulating 16 Aug 2018 · routing from ${DEMO.place}`);
    bus.emit('demo:route', DEMO);
  });

  function renderBadge() {
    const parts = [];
    if (state.simDate) parts.push(`SIMULATION: ${new Date(state.simDate).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })} conditions`);
    if (state.scenario) parts.push(`WHAT-IF +${state.scenario} mm / 3 days`);
    badge.hidden = !parts.length;
    badge.textContent = parts.join(' · ');
  }
  bus.on('state:simDate', renderBadge);
  bus.on('state:scenario', renderBadge);
}
