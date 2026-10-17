// Tiny event bus + shared state. Widgets never call each other directly.
const listeners = new Map();

export const state = {
  preset: document.body.dataset.defaultPreset || 'balanced',
  scenario: 0,          // what-if 3-day rainfall added (mm)
  simDate: null,        // 'YYYY-MM-DD' to run on a historical day's real rain + river levels (null = live)
  replayDate: null,     // 'YYYY-MM-DD' while the 2018 replay is active
  colour: 'probability', // map colouring: 'probability' (calibrated) or 'rank' (relative, top 5% of roads)
  origin: null,         // {lat, lon} of the last route request
  route: null,          // last /api/route response
};

export const bus = {
  on(event, fn) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(fn);
    return () => listeners.get(event).delete(fn);
  },
  emit(event, payload) {
    (listeners.get(event) || []).forEach((fn) => {
      try { fn(payload); } catch (err) { console.error(`[bus] ${event}`, err); }
    });
  },
  set(key, value) {
    if (state[key] === value) return;
    state[key] = value;
    bus.emit(`state:${key}`, value);
  },
};
