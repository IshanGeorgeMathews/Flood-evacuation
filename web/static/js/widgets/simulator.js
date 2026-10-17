// What-if rainfall simulator: add extra rain over 3 days; the model re-scores every road and routes re-draw.
import { api } from '../core/api.js';
import { bus, state } from '../core/bus.js';
import { renderKpis } from '../core/shell.js';
import { el, fmt, setLoading, toast } from '../core/ui.js';

export function mount(panel) {
  const value = el('span', { class: 'big num', text: '+0' });
  const slider = el('input', { type: 'range', min: '0', max: '300', step: '25', value: '0', 'aria-label': 'Extra rainfall over 3 days (mm)' });
  const quick = el('div', { class: 'btn-row' }, [0, 50, 100, 200].map((mm) => {
    const b = el('button', { class: 'btn', type: 'button', text: mm ? `+${mm} mm` : 'None' });
    b.addEventListener('click', () => { slider.value = String(mm); apply(); });
    return b;
  }));
  const out = el('div', { class: 'sim-out' });
  panel.append(
    el('div', { class: 'sim-value' }, el('span', { class: 'muted', text: 'Extra rain over 3 days' }), el('span', {}, value, el('small', { class: 'muted', text: ' mm' }))),
    slider, el('div', { class: 'sim-ticks' }, el('span', { text: '0' }), el('span', { text: '150' }), el('span', { text: '300 mm' })),
    quick, out,
    el('div', { class: 'field-hint', text: 'Adds rain evenly across the district and the upstream catchment on top of the selected day (live or historical); river levels stay as measured, so this is a lower bound.' }));

  slider.addEventListener('input', () => { value.textContent = `+${slider.value}`; });
  slider.addEventListener('change', apply);

  function cell(label, v) { return el('div', { class: 'cell' }, el('div', { class: 'l', text: label }), el('div', { class: 'v num', text: v })); }

  async function apply() {
    const mm = Number(slider.value);
    value.textContent = `+${mm}`;
    setLoading(panel, true);
    try {
      const r = await api.simulate(mm);
      bus.set('scenario', mm);
      renderKpis(r.kpis, mm ? r.baseline : null, state.simDate ? 'simulated day' : 'live');
      out.replaceChildren(
        cell('Roads at risk', `${fmt.km(r.kpis.roads_at_risk_km)} km`),
        cell('Change', `${r.delta.roads_at_risk_km >= 0 ? '+' : ''}${fmt.km(r.delta.roads_at_risk_km)} km`),
        cell('Newly at-risk segments', fmt.int(r.segments_newly_at_risk)),
        cell('Shelters reachable', fmt.int(r.kpis.shelters_open)));
    } catch (err) {
      toast(`Simulation failed: ${err.message}`);
    } finally {
      setLoading(panel, false);
    }
  }
  bus.on('state:preset', () => { if (state.scenario) apply(); });
  bus.on('state:simDate', () => { slider.value = '0'; value.textContent = '+0'; out.replaceChildren(); });
}
