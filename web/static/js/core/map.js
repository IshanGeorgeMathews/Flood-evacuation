// Leaflet map with real basemaps (satellite imagery by default) and a shared canvas renderer.
const L = window.L;

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const ESRI_ATTR = 'Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community';
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

// Basemaps. Satellite is the default so the map looks like the real place; road and place labels sit on top.
// For production traffic use a licensed tile service (Esri / OSM tile policies limit heavy public use).
const BASEMAPS = {
  Satellite: () => L.layerGroup([
    L.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, { attribution: ESRI_ATTR, maxZoom: 19, maxNativeZoom: 18 }),
    L.tileLayer(`${ESRI}/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 19, maxNativeZoom: 18, opacity: 0.85 }),
    L.tileLayer(`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 19, maxNativeZoom: 18 }),
  ]),
  Streets: () => L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: OSM_ATTR, maxZoom: 19, className: 'tiles-street' }),
  Topographic: () => L.tileLayer(`${ESRI}/World_Topo_Map/MapServer/tile/{z}/{y}/{x}`, { attribution: 'Tiles &copy; Esri and contributors', maxZoom: 19, maxNativeZoom: 18 }),
};

function savedBasemap() {
  try { return localStorage.getItem('fe-basemap') || 'Satellite'; } catch (e) { return 'Satellite'; }
}

export function createMap(node, { center, zoom } = {}) {
  const body = document.body.dataset;
  const c = center || body.center.split(',').map(Number);
  const z = zoom || Number(body.zoom);
  const map = L.map(node, { preferCanvas: true, zoomControl: true, minZoom: 8, maxZoom: 19, attributionControl: true })
    .setView(c, z);
  map.renderer = L.canvas({ padding: 0.3, tolerance: 6 });
  const layers = Object.fromEntries(Object.entries(BASEMAPS).map(([name, make]) => [name, make()]));
  const start = layers[savedBasemap()] ? savedBasemap() : 'Satellite';
  layers[start].addTo(map);
  L.control.layers(layers, null, { position: 'topleft', collapsed: false }).addTo(map);
  map.on('baselayerchange', (e) => { try { localStorage.setItem('fe-basemap', e.name); } catch (err) { /* ignore */ } });
  return map;
}

export function bboxOf(map, pad = 0.15) {
  const b = map.getBounds().pad(pad);
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => Number(v.toFixed(4)));
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function haversine(a, b) {
  const R = 6371000;
  const toR = (d) => (d * Math.PI) / 180;
  const dLat = toR(b.lat - a.lat);
  const dLon = toR(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toR(a.lat)) * Math.cos(toR(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
