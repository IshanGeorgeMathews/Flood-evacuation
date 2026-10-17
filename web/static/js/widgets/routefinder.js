// Route finder: tap the map, use GPS, pick a town or type coordinates. Draws safest / alternative / fastest
// routes and the 15-minute safe-reach isochrone. Re-routes automatically when risk changes.
import { api } from '../core/api.js';
import { bus, state } from '../core/bus.js';
import { palette } from '../core/charts.js';
import { el, icon, toast, setLoading } from '../core/ui.js';

const L = window.L;
const TOWNS = [
  ['Aluva', 10.1076, 76.3525], ['North Paravur', 10.146, 76.212], ['Angamaly', 10.196, 76.386],
  ['Perumbavoor', 10.115, 76.476], ['Kalady', 10.168, 76.438], ['Chendamangalam', 10.17, 76.233],
  ['Kochi (Ernakulam South)', 9.968, 76.289], ['Muvattupuzha', 9.979, 76.579], ['Kothamangalam', 10.06, 76.632],
  ['Piravom', 9.873, 76.49],
];

export function mount(panel, map) {
  const routeLayer = L.layerGroup().addTo(map);
  const isoLayer = L.layerGroup();
  let pin = null;
  let isoOn = false;

  const coord = el('input', { type: 'text', placeholder: 'lat, lon  (e.g. 10.1076, 76.3525)', 'aria-label': 'Coordinates' });
  const town = el('select', { 'aria-label': 'Choose a town' },
    el('option', { value: '', text: 'Jump to a town…' }), TOWNS.map(([n, la, lo]) => el('option', { value: `${la},${lo}`, text: n })));
  const go = el('button', { class: 'btn btn-primary', type: 'button' }, icon('pin'), 'Find safest route');
  const gps = el('button', { class: 'btn', type: 'button' }, icon('locate'), 'Use my location');
  const status = el('div', { class: 'field-hint', text: 'Or tap anywhere on the map. Routes go to the best reachable shelter.' });
  panel.append(el('div', { style: 'display:grid;gap:8px' }, town, coord, el('div', { class: 'btn-row' }, go, gps), status));

  town.addEventListener('change', () => {
    if (!town.value) return;
    const [la, lo] = town.value.split(',').map(Number);
    coord.value = `${la}, ${lo}`;
    request(la, lo, true);
  });
  go.addEventListener('click', () => {
    const m = coord.value.match(/(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)/);
    if (!m) { toast('Enter coordinates as “lat, lon”'); return; }
    request(Number(m[1]), Number(m[2]), true);
  });
  gps.addEventListener('click', () => {
    if (!navigator.geolocation) { toast('Location is not available in this browser'); return; }
    status.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(
      (pos) => request(pos.coords.latitude, pos.coords.longitude, true),
      () => { status.textContent = 'Location permission denied — tap the map instead.'; },
      { enableHighAccuracy: true, timeout: 10000 });
  });
  bus.on('map:click', (ll) => request(ll.lat, ll.lng, false));

  function drawRoutes(res) {
    const pal = palette();
    routeLayer.clearLayers();
    const order = { fastest: 0, alternative: 1, safest: 2 };
    [...res.routes].sort((a, b) => order[a.kind] - order[b.kind]).forEach((r) => {
      const latlngs = r.geometry.coordinates.map(([x, y]) => [y, x]);
      if (r.kind === 'safest') {
        routeLayer.addLayer(L.polyline(latlngs, { color: '#ffffff', weight: 9, opacity: 0.85, interactive: false }));
        routeLayer.addLayer(L.polyline(latlngs, { color: pal.s1, weight: 5, opacity: 1, interactive: false }));
      } else if (r.kind === 'alternative') {
        routeLayer.addLayer(L.polyline(latlngs, { color: pal.s1, weight: 4, opacity: 0.55, dashArray: '2 8', interactive: false }));
      } else {
        routeLayer.addLayer(L.polyline(latlngs, { color: pal.muted, weight: 3, opacity: 0.9, interactive: false }));
      }
      if (r.kind === 'safest' && r.shelter) {
        routeLayer.addLayer(L.marker([r.shelter.lat, r.shelter.lon], {
          icon: L.divIcon({ className: '', html: '<div class="pin" style="background:#fff;box-shadow:0 0 0 3px var(--series-1)"></div>', iconSize: [18, 18] }),
          title: r.shelter.name,
        }));
      }
    });
  }

  async function drawIsochrone() {
    isoLayer.clearLayers();
    if (!isoOn || !state.origin) return;
    try {
      const f = await api.isochrone(state.origin.lat, state.origin.lon, 15);
      if (f.geometry) {
        const pal = palette();
        isoLayer.addLayer(L.geoJSON(f, { style: { color: pal.s1, weight: 1.5, fillColor: pal.s1, fillOpacity: 0.1 }, interactive: false }));
      }
    } catch (err) { toast(`Isochrone unavailable: ${err.message}`); }
  }
  bus.on('layer:isochrone', (on) => {
    isoOn = on;
    if (on) { map.addLayer(isoLayer); drawIsochrone(); } else map.removeLayer(isoLayer);
  });

  async function request(lat, lon, fly) {
    state.origin = { lat, lon };
    if (pin) map.removeLayer(pin);
    pin = L.marker([lat, lon], { icon: L.divIcon({ className: '', html: '<div class="pin"></div>', iconSize: [18, 18] }), title: 'Start' }).addTo(map);
    if (fly) map.flyTo([lat, lon], Math.max(map.getZoom(), 13), { duration: 0.8 });
    status.textContent = 'Computing the safest route…';
    setLoading(panel, true);
    try {
      const res = await api.route(lat, lon);
      const prev = state.route;
      state.route = res;
      drawRoutes(res);
      bus.emit('route', { res, prev });
      const s = res.routes.find((r) => r.kind === 'safest');
      status.textContent = s ? `Route to ${s.shelter.name}` : (res.warnings[0] || 'No route found');
      drawIsochrone();
      history.replaceState(null, '', `?lat=${lat.toFixed(5)}&lon=${lon.toFixed(5)}`);
    } catch (err) {
      status.textContent = `Routing failed: ${err.message}`;
    } finally {
      setLoading(panel, false);
    }
  }

  // re-route when the risk picture changes (scenario, preset, live refresh)
  const rerun = () => { if (state.origin && !state.replayDate) request(state.origin.lat, state.origin.lon, false); };
  bus.on('state:preset', rerun);
  bus.on('state:scenario', rerun);
  bus.on('state:simDate', rerun);
  bus.on('demo:route', (d) => request(d.lat, d.lon, true));
  bus.on('sse:refresh', rerun);
  bus.on('theme', () => { if (state.route) drawRoutes(state.route); });

  // deep link (?lat=&lon=) from shared routes
  const q = new URLSearchParams(location.search);
  if (q.get('lat') && q.get('lon')) request(Number(q.get('lat')), Number(q.get('lon')), true);
  return { request };
}
