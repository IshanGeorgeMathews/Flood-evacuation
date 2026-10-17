// Evacuation console: map-first view with routing and conditions docks.
import { api } from '../core/api.js';
import { bus, state } from '../core/bus.js';
import { createMap } from '../core/map.js';
import { initShell, renderKpis } from '../core/shell.js';
import * as caution from '../widgets/caution.js';
import * as conditions from '../widgets/conditions.js';
import * as explain from '../widgets/explain.js';
import * as gauges from '../widgets/gauges.js';
import * as health from '../widgets/health.js';
import * as rainfall from '../widgets/rainfall.js';
import * as replay from '../widgets/replay.js';
import * as reroute from '../widgets/reroute.js';
import * as riskmap from '../widgets/riskmap.js';
import * as routecard from '../widgets/routecard.js';
import * as routefinder from '../widgets/routefinder.js';
import * as shelters from '../widgets/shelters.js';
import * as simulator from '../widgets/simulator.js';

const $ = (id) => document.getElementById(id);

initShell();
const map = createMap($('map'));
map.on('click', (e) => bus.emit('map:click', e.latlng));

health.mount($('w-health'));
riskmap.mount(map, $('w-layers'), $('w-legend'));
caution.mount($('w-caution'), document.body.dataset.presets.split(','));
routefinder.mount($('w-routefinder'), map);
routecard.mount($('w-routecard'));
shelters.mount($('w-shelters'), map);
gauges.mount($('w-gauges'), map);
rainfall.mount($('w-rainfall'));
simulator.mount($('w-simulator'));
conditions.mount($('w-conditions'), $('w-scenario-badge'));
replay.mount($('w-replay'));
explain.mount(map);
reroute.mount($('w-reroute'));

bus.on('status', (s) => { if (s.presets) bus.emit('presets:tau', Object.fromEntries(Object.entries(s.presets).map(([k, v]) => [k, v.tau]))); });

async function kpis() {
  if (state.scenario) return; // the simulator owns the KPI strip while a what-if is active
  try { renderKpis((await api.stats()).kpis); } catch (err) { /* strip keeps its last values */ }
}
bus.on('state:preset', kpis);
bus.on('state:scenario', (mm) => { if (!mm) kpis(); });
bus.on('state:simDate', kpis);
bus.on('sse:refresh', kpis);
kpis();

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
