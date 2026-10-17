// Reroute alert: when new risk (live refresh or a what-if) changes the safest route, say so loudly.
import { bus } from '../core/bus.js';
import { el, fmt } from '../core/ui.js';

export function mount(banner) {
  bus.on('route', ({ res, prev }) => {
    if (!prev) return;
    const a = prev.routes.find((r) => r.kind === 'safest');
    const b = res.routes.find((r) => r.kind === 'safest');
    if (!a && !b) return;
    let msg = null;
    if (a && !b) msg = 'Roads ahead are now above the risk threshold — no safe route to a shelter. Move to high ground.';
    else if (a && b && (a.shelter?.id !== b.shelter?.id || Math.abs(a.dist_m - b.dist_m) / Math.max(a.dist_m, 1) > 0.03)) {
      msg = `Risk changed on your route — rerouted to ${b.shelter.name} (${fmt.min(b.eta_s)} min, ${fmt.m(b.dist_m)}).`;
    }
    if (!msg) return;
    const close = el('button', { type: 'button', text: 'Dismiss' });
    close.addEventListener('click', () => { banner.hidden = true; });
    banner.replaceChildren(el('span', { text: '⚠' }), el('span', { text: msg }), close);
    banner.hidden = false;
    clearTimeout(banner._t);
    banner._t = setTimeout(() => { banner.hidden = true; }, 15000);
  });
}
