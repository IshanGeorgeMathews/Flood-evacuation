// Caution slider: moves routing between "safest" and "fastest" by switching the cost preset (alpha, tau).
import { bus, state } from '../core/bus.js';
import { el } from '../core/ui.js';

const LABELS = { cautious: 'Cautious', balanced: 'Balanced', fast: 'Fast' };
const HELP_TEXT = {
  cautious: 'Longer, safer routes.',
  balanced: 'Recommended for residents.',
  fast: 'For responders who need to reach people quickly.',
};
let TAU = {};
bus.on('status', (s) => { if (s.presets) { TAU = s.presets; bus.emit('caution:refresh'); } });
const pct = (v) => `${Math.round(v * 100)}%`;
const help = (p) => (TAU[p] ? `Blocks roads with ≥ ${pct(TAU[p].tau)} flood probability (${pct(TAU[p].tau_bridge)} on bridges and causeways). ${HELP_TEXT[p] || ''}` : HELP_TEXT[p] || '');

export function mount(panel, presets) {
  const seg = el('div', { class: 'seg', role: 'group', 'aria-label': 'Caution level' });
  const helpEl = el('div', { class: 'field-hint' });
  presets.forEach((p) => {
    const b = el('button', { type: 'button', 'aria-pressed': String(p === state.preset), text: LABELS[p] || p });
    b.addEventListener('click', () => bus.set('preset', p));
    seg.append(b);
  });
  const sync = () => {
    [...seg.children].forEach((b, i) => b.setAttribute('aria-pressed', String(presets[i] === state.preset)));
    helpEl.textContent = help(state.preset);
  };
  bus.on('state:preset', sync);
  bus.on('caution:refresh', sync);
  sync();
  panel.append(seg, helpEl);
}
