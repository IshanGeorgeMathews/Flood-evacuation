// Safest vs fastest comparison card (+ share). Keys mirror the map: blue = safest, grey = fastest.
import { bus } from '../core/bus.js';
import { palette } from '../core/charts.js';
import { el, fmt, icon, toast } from '../core/ui.js';

export function mount(panel) {
  const body = el('div', {}, el('div', { class: 'empty', text: 'Pick a starting point to compare routes.' }));
  panel.append(body);

  function col(r, title, color, dashed) {
    if (!r) return el('div', { class: 'route-col' }, el('h3', {}, title), el('div', { class: 'empty', text: 'No route' }));
    return el('div', { class: 'route-col' },
      el('h3', {}, el('span', { class: 'key-line', style: `border-color:${color};${dashed ? 'border-top-style:dotted' : ''}` }), title),
      el('div', { class: 'big' }, fmt.min(r.eta_s), el('small', { class: 'muted', text: ' min' })),
      el('div', { class: 'row' }, 'Distance', el('b', { text: fmt.m(r.dist_m) })),
      el('div', { class: 'row' }, 'On risky roads', el('b', { text: fmt.m(r.exposure_m) })),
      el('div', { class: 'row' }, 'Worst stretch', el('b', { text: fmt.pct(r.max_p) })));
  }

  function share(res) {
    const s = res.routes.find((r) => r.kind === 'safest');
    if (!s || !s.shelter) return null;
    const gmaps = `https://www.google.com/maps/dir/?api=1&origin=${res.origin.lat},${res.origin.lon}&destination=${s.shelter.lat},${s.shelter.lon}&travelmode=driving`;
    const app = `${location.origin}/?lat=${res.origin.lat.toFixed(5)}&lon=${res.origin.lon.toFixed(5)}`;
    const text = `Flood evacuation route to ${s.shelter.name} (${fmt.min(s.eta_s)} min, ${fmt.m(s.dist_m)}). Live risk-aware route: ${app} — Directions: ${gmaps}. Follow official KSDMA orders.`;
    const wa = el('a', { class: 'btn', href: `https://wa.me/?text=${encodeURIComponent(text)}`, target: '_blank', rel: 'noopener' }, icon('share'), 'WhatsApp');
    const sms = el('a', { class: 'btn', href: `sms:?&body=${encodeURIComponent(text)}` }, icon('share'), 'SMS');
    const copy = el('button', { class: 'btn', type: 'button' }, 'Copy link');
    copy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(app); toast('Link copied'); } catch (e) { toast(app, 6000); }
    });
    return el('div', { class: 'btn-row', style: 'margin-top:10px' }, wa, sms, copy);
  }

  bus.on('route', ({ res }) => {
    const pal = palette();
    const safest = res.routes.find((r) => r.kind === 'safest');
    const fastest = res.routes.find((r) => r.kind === 'fastest');
    const alt = res.routes.find((r) => r.kind === 'alternative');
    const parts = [el('div', { class: 'compare' }, col(safest, 'Safest', pal.s1), col(fastest, 'Fastest (no risk)', pal.muted))];
    if (safest && safest.shelter) {
      parts.push(el('div', { class: 'dest' }, icon('home'), el('div', {},
        el('b', { text: safest.shelter.name }),
        el('div', { class: 'muted', text: `Capacity est. ${fmt.int(safest.shelter.capacity)} · avoids ${safest.blocked_avoided || 0} blocked section(s)` }))));
    }
    if (alt) parts.push(el('div', { class: 'field-hint', text: `Alternative (dotted): ${fmt.min(alt.eta_s)} min, ${fmt.m(alt.exposure_m)} on risky roads.` }));
    if (res.warnings.length) {
      parts.push(el('ul', { class: 'warn-list' }, res.warnings.map((w) => el('li', {}, icon('alert'), el('span', { text: w })))));
    }
    const sh = share(res);
    if (sh) parts.push(sh);
    body.replaceChildren(...parts);
  });
}
