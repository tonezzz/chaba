/* GEV tour player — data-driven flyover with ordered checkpoint reporting.
 *
 * Loaded by index.html ahead of the app bundle. Registers
 * window.__gevTourCmd(name, args, ctx), invoked by the bundle's tool
 * dispatcher for play_tour / stop_tour / tour_status, and window.__gevTour
 * for in-page inspection.
 *
 * Tour definitions live at /apps/gev/tours/<id>.json (see tours/index.json).
 * Format (docs/ssot/jobs/gev/2026-10-06-gev-tour-format.yml):
 *   { id, title, version, defaults: {dwellS, durationS, pitchDeg},
 *     stops: [ { id, label,
 *                lat, lon,                     // explicit camera-position stop
 *                locationId | query,           // OR a resolved-place stop
 *                camera: {heightM, headingDeg, pitchDeg, durationS, rangeM},
 *                dwellS, narration: {en, th} | "text",
 *                annotate: [...], clearAnnotations, persist } ] }
 *
 * Checkpoint contract: stops are visited strictly in order; when the camera
 * arrives at a stop the player appends {seq,id,label,at} to
 * __gevTour.status().checkpoints AND emits a 'checkpoint' tour_event frame
 * over the remote ws (hooked by index.html -> bridge /command/events). A
 * scenario verifies playback by asserting checkpoints arrive seq=0..N-1 in
 * order, then a tour_end event with state=done.
 */
(function () {
  'use strict';

  var TOUR_BASE = '/apps/gev/tours/';
  var MAX_EVENTS = 500;
  var DEFAULTS = { dwellS: 6, durationS: 4, pitchDeg: -28 };

  var st = {
    tour: null,          // parsed tour definition
    running: false,
    stopRequested: false,
    current: null,       // {seq, id, label, phase: leg|dwell}
    checkpoints: [],     // [{seq,id,label,at,arrived}] — append-on-arrival, ordered
    events: [],          // local ring buffer of every emitted event
    error: null,
    endState: null,      // done | stopped | error
    startedAt: 0,
    endedAt: 0,
    ctx: null,           // {viewer, run, ...} captured at play() time
    lang: 'en',
  };

  function num(v, dflt) {
    var n = Number(v);
    return Number.isFinite(n) ? n : dflt;
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // ---- events ---------------------------------------------------------------
  function emit(kind, extra) {
    var ev = Object.assign({
      kind: kind,
      tour: st.tour ? st.tour.id : null,
      seq: st.current ? st.current.seq : null,
      at: Date.now(),
    }, extra || {});
    st.events.push(ev);
    if (st.events.length > MAX_EVENTS) st.events.splice(0, st.events.length - MAX_EVENTS);
    try { console.log('[GEV-TOUR]', kind, JSON.stringify(ev)); } catch (e) {}
    try { if (window.__gevTourEmit) window.__gevTourEmit(ev); } catch (e) {}
    try { window.dispatchEvent(new CustomEvent('gev-tour', { detail: ev })); } catch (e) {}
    return ev;
  }

  function status(action) {
    return {
      ok: true,
      action: action || 'tour_status',
      state: st.running ? 'playing'
        : (st.endState || (st.error ? 'error' : 'idle')),
      tour: st.tour ? { id: st.tour.id, title: st.tour.title, stops: st.tour.stops.length } : null,
      current: st.current,
      checkpoints: st.checkpoints.slice(),
      events: st.events.slice(-50),
      error: st.error,
      startedAt: st.startedAt || null,
      endedAt: st.endedAt || null,
    };
  }

  // ---- tour loading -----------------------------------------------------------
  function tourUrl(tour) {
    if (/^https?:\/\//.test(tour) || tour.charAt(0) === '/') return tour;
    if (!/^[a-z0-9][a-z0-9-_]*$/i.test(tour)) {
      throw new Error('bad tour id: ' + tour);
    }
    return TOUR_BASE + tour + '.json';
  }

  function validate(tour) {
    if (!tour || typeof tour !== 'object') return 'tour is not an object';
    if (!Array.isArray(tour.stops) || !tour.stops.length) return 'tour has no stops';
    var seen = {};
    for (var i = 0; i < tour.stops.length; i++) {
      var s = tour.stops[i];
      if (!s || typeof s !== 'object') return 'stop ' + i + ' is not an object';
      if (!s.id) return 'stop ' + i + ' has no id';
      if (seen[s.id]) return 'duplicate stop id: ' + s.id;
      seen[s.id] = true;
      var hasCoords = Number.isFinite(Number(s.lat)) && Number.isFinite(Number(s.lon));
      if (!hasCoords && !s.locationId && !s.query) {
        return 'stop "' + s.id + '" needs lat/lon, locationId, or query';
      }
    }
    return null;
  }

  async function loadTour(args) {
    var ref = String((args && args.tour) || 'london-icons');
    var url;
    try { url = tourUrl(ref); } catch (e) { return { ok: false, action: 'play_tour', error: String(e && e.message || e) }; }
    var tour;
    try {
      var res = await fetch(url, { cache: 'no-cache' });
      if (!res.ok) return { ok: false, action: 'play_tour', tour: ref, error: 'fetch ' + url + ' -> HTTP ' + res.status };
      tour = await res.json();
    } catch (e) {
      return { ok: false, action: 'play_tour', tour: ref, error: 'load failed: ' + String(e && e.message || e) };
    }
    var bad = validate(tour);
    if (bad) return { ok: false, action: 'play_tour', tour: ref, error: 'invalid tour: ' + bad };
    if (!tour.id) tour.id = ref;
    return { ok: true, tour: tour };
  }

  // ---- camera -----------------------------------------------------------------
  // lat/lon stops fly the camera directly (position AT lat/lon/heightM,
  // oriented by headingDeg/pitchDeg — same semantics as the app's internal
  // scene helper). locationId/query stops go through fly_to_location so they
  // inherit the app's framing logic; waitForArrival makes the checkpoint
  // deterministic.
  function flyCamera(ctx, stop, durS) {
    var viewer = ctx && ctx.viewer;
    var cam = viewer && viewer.camera;
    if (!cam || typeof Cesium === 'undefined') return Promise.resolve(false);
    try { cam.cancelFlight(); } catch (e) {}
    var c = stop.camera || {};
    var h = num(c.heightM != null ? c.heightM : c.rangeM, 600);
    var heading = Cesium.Math.toRadians(num(c.headingDeg, 0));
    var pitch = Cesium.Math.toRadians(num(c.pitchDeg, DEFAULTS.pitchDeg));
    return new Promise(function (res) {
      var done = false;
      var finish = function (ok) { if (!done) { done = true; clearTimeout(timer); res(ok); } };
      var timer = setTimeout(function () { finish(true); }, Math.max(6, durS * 3) * 1000);
      try {
        cam.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(Number(stop.lon), Number(stop.lat), h),
          orientation: { heading: heading, pitch: pitch, roll: 0 },
          duration: durS,
          complete: function () { finish(true); },
          cancel: function () { finish(false); },
        });
      } catch (e) { finish(false); }
    });
  }

  async function goto(ctx, stop, tour) {
    var d = (tour && tour.defaults) || {};
    var durS = num((stop.camera || {}).durationS, num(d.durationS, DEFAULTS.durationS));
    if (Number.isFinite(Number(stop.lat)) && Number.isFinite(Number(stop.lon))) {
      return flyCamera(ctx, stop, durS);
    }
    if (!(ctx && typeof ctx.run === 'function')) return false;
    var a = { waitForArrival: true };
    if (stop.locationId) a.locationId = stop.locationId;
    if (stop.query) a.query = stop.query;
    if (stop.viewMode) a.viewMode = stop.viewMode;
    if (Number.isFinite(Number((stop.camera || {}).rangeM))) a.rangeM = Number(stop.camera.rangeM);
    try {
      var r = await ctx.run('fly_to_location', a, ctx.opts || {});
      return !!(r && r.ok === true);
    } catch (e) { return false; }
  }

  // ---- narration + annotation ---------------------------------------------------
  var capEl = null;
  function caption(text) {
    if (!capEl) {
      capEl = document.createElement('div');
      capEl.id = 'gev-tour-caption';
      capEl.style.cssText = 'position:fixed;left:50%;bottom:6%;transform:translateX(-50%);' +
        'max-width:70%;padding:10px 18px;background:rgba(8,12,20,.72);color:#eaf2ff;' +
        'font:16px/1.45 system-ui,sans-serif;border:1px solid rgba(140,180,255,.35);' +
        'border-radius:10px;z-index:9999;pointer-events:none;text-align:center;' +
        'opacity:0;transition:opacity .3s';
      (document.body || document.documentElement).appendChild(capEl);
    }
    if (text) { capEl.textContent = text; capEl.style.opacity = '1'; }
    else capEl.style.opacity = '0';
  }

  function narrationText(stop) {
    var n = stop.narration;
    if (!n) return null;
    if (typeof n === 'string') return n;
    return n[st.lang] || n.en || n[Object.keys(n)[0]] || null;
  }

  function narrate(stop, when) {
    var text = narrationText(stop);
    if (!text) return;
    emit('narration', { id: stop.id, when: when, text: text });
    caption(when === 'depart' ? null : text);
  }

  function annotate(ctx, stop) {
    if (!Array.isArray(stop.annotate) || !stop.annotate.length) return;
    if (!(ctx && typeof ctx.run === 'function')) return;
    // fire-and-forget — name resolution may geocode; never hold up the tour
    Promise.resolve(ctx.run('annotate_map', {
      annotations: stop.annotate,
      clearPrevious: !!stop.clearAnnotations,
      persist: !!stop.persist,
    }, ctx.opts || {})).catch(function () {});
  }

  // ---- playback -------------------------------------------------------------------
  async function runTour(ctx, tour, startAt) {
    for (var seq = startAt; seq < tour.stops.length; seq++) {
      if (st.stopRequested) break;
      var stop = tour.stops[seq];
      st.current = { seq: seq, id: stop.id, label: stop.label || stop.id, phase: 'leg' };
      emit('leg', { id: stop.id, label: st.current.label });
      var arrived = await goto(ctx, stop, tour);
      if (st.stopRequested) break;
      var cp = { seq: seq, id: stop.id, label: st.current.label, at: Date.now(), arrived: !!arrived };
      st.checkpoints.push(cp);
      st.current.phase = 'dwell';
      emit('checkpoint', { id: cp.id, label: cp.label, arrived: cp.arrived });
      narrate(stop, 'arrive');
      annotate(ctx, stop);
      var dwellMs = 1000 * num(stop.dwellS,
        num(tour.defaults && tour.defaults.dwellS, DEFAULTS.dwellS));
      var t0 = Date.now();
      while (Date.now() - t0 < dwellMs && !st.stopRequested) await sleep(200);
      if (st.stopRequested) break;
      narrate(stop, 'depart');
    }
    st.running = false;
    st.endedAt = Date.now();
    st.endState = st.error ? 'error' : (st.stopRequested ? 'stopped' : 'done');
    st.current = null;
    caption(null);
    emit('tour_end', { state: st.endState, visited: st.checkpoints.length, error: st.error });
  }

  async function start(ctx, args) {
    var loaded = await loadTour(args);
    if (!loaded.ok) return loaded;
    var tour = loaded.tour;
    // replace any in-flight tour: request stop, wait briefly for the loop to notice
    if (st.running) {
      st.stopRequested = true;
      try { ctx && ctx.viewer && ctx.viewer.camera.cancelFlight(); } catch (e) {}
      for (var i = 0; i < 60 && st.running; i++) await sleep(100);
    }
    st.tour = tour;
    st.ctx = ctx;
    st.lang = String(args.lang || 'en').toLowerCase();
    st.checkpoints = [];
    st.events = [];
    st.error = null;
    st.endState = null;
    st.current = null;
    st.startedAt = Date.now();
    st.endedAt = 0;
    st.stopRequested = false;
    st.running = true;
    var startAt = Math.max(0, Math.min(tour.stops.length - 1, num(args.startAt, 0) | 0));
    emit('tour_start', { title: tour.title, stops: tour.stops.length, startAt: startAt });
    var etaS = tour.stops.slice(startAt).reduce(function (acc, s) {
      return acc + num(s.dwellS, num(tour.defaults && tour.defaults.dwellS, DEFAULTS.dwellS)) +
        num(s.camera && s.camera.durationS, num(tour.defaults && tour.defaults.durationS, DEFAULTS.durationS));
    }, 0);
    // playback is detached — play_tour answers immediately; callers watch
    // tour_status or the tour_event stream for progress.
    runTour(ctx, tour, startAt).catch(function (e) {
      st.error = String(e && e.message || e);
      st.running = false;
      st.endState = 'error';
      st.endedAt = Date.now();
      st.current = null;
      caption(null);
      emit('tour_end', { state: 'error', error: st.error });
    });
    return {
      ok: true, action: 'play_tour',
      tour: { id: tour.id, title: tour.title, stops: tour.stops.length },
      startAt: startAt, etaS: Math.round(etaS),
      note: 'playback detached — poll tour_status or watch tour_event stream; checkpoints[] fills in order',
    };
  }

  function stopTour() {
    st.stopRequested = true;
    try { st.ctx && st.ctx.viewer && st.ctx.viewer.camera.cancelFlight(); } catch (e) {}
    caption(null);
    return status('stop_tour');
  }

  window.__gevTour = {
    status: function () { return status(); },
    stop: stopTour,
    events: function () { return st.events.slice(); },
  };

  window.__gevTourCmd = async function (name, args, ctx) {
    args = args && typeof args === 'object' ? args : {};
    if (name === 'play_tour') {
      try { return await start(ctx, args); }
      catch (e) { return { ok: false, action: 'play_tour', error: String(e && e.message || e) }; }
    }
    if (name === 'stop_tour') return stopTour();
    if (name === 'tour_status') return status();
    return { ok: false, action: name, error: 'unknown tour command' };
  };
})();
