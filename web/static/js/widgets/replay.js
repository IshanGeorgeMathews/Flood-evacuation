// August 2018 replay: scrub day by day through the flood; the map shows the held-out model's prediction and,
// on Sentinel-1 days, the radar-observed flooding beside it.
import { api } from '../core/api.js';
import { bus, state } from '../core/bus.js';
import { el, fmt, toast } from '../core/ui.js';

export function mount(bar) {
  const btn = el('button', { class: 'btn', type: 'button', 'aria-pressed': 'false', text: '▶ 2018 replay' });
  const play = el('button', { class: 'btn', type: 'button', text: 'Play', hidden: true });
  const slider = el('input', { type: 'range', min: '0', max: '0', step: '1', value: '0', 'aria-label': 'Replay day', hidden: true });
  const date = el('span', { class: 'rp-date', hidden: true });
  const stat = el('span', { class: 'rp-stat', text: 'Replay the August 2018 Kerala flood with the held-out model' });
  bar.append(el('span', { class: 'rp-title', text: 'Flood replay' }), btn, play, date, slider, stat);
  let summary = null;
  let timer = null;

  async function ensure() {
    if (summary) return summary;
    summary = await api.replaySummary();
    slider.max = String(summary.days.length - 1);
    const peak = summary.days.findIndex((d) => d.date === '2018-08-16');
    slider.value = String(peak >= 0 ? peak : 0);
    return summary;
  }

  function setDay() {
    const d = summary.days[Number(slider.value)];
    date.textContent = d.date;
    bus.set('replayDate', d.date);
  }

  btn.addEventListener('click', async () => {
    const on = btn.getAttribute('aria-pressed') !== 'true';
    if (on) {
      try { await ensure(); } catch (err) { toast(`Replay unavailable: ${err.message}`); return; }
      btn.setAttribute('aria-pressed', 'true');
      btn.textContent = '■ Exit replay';
      [play, slider, date].forEach((n) => { n.hidden = false; });
      setDay();
    } else {
      stop();
      btn.setAttribute('aria-pressed', 'false');
      btn.textContent = '▶ 2018 replay';
      [play, slider, date].forEach((n) => { n.hidden = true; });
      bus.set('replayDate', null);
      stat.textContent = 'Back to the live risk picture';
    }
  });
  slider.addEventListener('input', setDay);

  function stop() { clearInterval(timer); timer = null; play.textContent = 'Play'; }
  play.addEventListener('click', () => {
    if (timer) { stop(); return; }
    play.textContent = 'Pause';
    timer = setInterval(() => {
      const n = Number(slider.value) + 1;
      if (n > Number(slider.max)) { stop(); return; }
      slider.value = String(n);
      setDay();
    }, 1600);
  });

  bus.on('replay:day', (d) => {
    const s = d.stats || {};
    const parts = [`${fmt.km(s.roads_at_risk_km)} km at risk`, `upstream 3-day rain ${fmt.int(s.rain_up_3d)} mm`];
    if (s.gauge_max_rel !== null && s.gauge_max_rel !== undefined) parts.push(`max gauge ${s.gauge_max_rel >= 0 ? '+' : ''}${s.gauge_max_rel.toFixed(2)} m vs danger`);
    if (d.comparison) {
      parts.push(`radar check: safest ${fmt.pct(d.comparison.safest.flooded_share_of_length, 1)} vs fastest ${fmt.pct(d.comparison.fastest.flooded_share_of_length, 1)} of route on flooded roads`);
    }
    stat.textContent = parts.join(' · ');
  });
  return { stop };
}
