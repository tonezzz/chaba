function toRad(d) { return d * Math.PI / 180; }
function toDeg(r) { return r * 180 / Math.PI; }

function haversine([lat1, lon1], [lat2, lon2]) {
  const R = 6371000;
  const dLat = toRad(lat2 - lat1), dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function bearing([lat1, lon1], [lat2, lon2]) {
  const p1 = toRad(lat1), p2 = toRad(lat2), dLon = toRad(lon2 - lon1);
  const x = Math.sin(dLon) * Math.cos(p2);
  const y = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dLon);
  return (toDeg(Math.atan2(x, y)) + 360) % 360;
}

function midpoint([lat1, lon1], [lat2, lon2]) { return [(lat1 + lat2) / 2, (lon1 + lon2) / 2]; }

function pointAt([lat, lon], bearingDeg, distM) {
  const R = 6371000;
  const h = toRad(bearingDeg);
  const latR = toRad(lat);
  const newLat = Math.asin(Math.sin(latR) * Math.cos(distM / R) + Math.cos(latR) * Math.sin(distM / R) * Math.cos(h));
  const newLon = toRad(lon) + Math.atan2(Math.sin(h) * Math.sin(distM / R) * Math.cos(latR), Math.cos(distM / R) - Math.sin(latR) * Math.sin(newLat));
  return [toDeg(newLat), toDeg(newLon)];
}
function offsetPoint(center, headingDeg, distM, side) {
  const sign = side === 'right' ? 1 : -1;
  return pointAt(center, headingDeg + 90 * sign, distM);
}

function markerById(markers, id) {
  if (!id) return null;
  if (Array.isArray(markers)) return markers.find(m => m.id === id) || null;
  if (markers && typeof markers === 'object') return markers[id] || null;
  return null;
}
function coordsOf(markers, ref) {
  if (Array.isArray(ref)) return ref;
  if (ref && typeof ref === 'object' && 'lat' in ref && 'lon' in ref) return [ref.lat, ref.lon];
  const m = markerById(markers, ref);
  return m ? [m.lat, m.lon] : [0, 0];
}

function resolvePoint(markers, annotations, id) {
  const m = markerById(markers, id);
  if (m) return [m.lat, m.lon];
  const ann = annotations && annotations[id];
  if (ann && ann.type === 'line') return midpoint(coordsOf(markers, ann.from), coordsOf(markers, ann.to));
  if (ann && ann.type === 'zone') return coordsOf(markers, ann.mark);
  return [0, 0];
}

function lineEntry(course, role) {
  const anns = course.annotations || {};
  const ann = Object.values(anns).find(a => a.type === 'line' && a.role === role);
  if (ann) return ann;
  const legacy = role === 'start' ? course.start_line : role === 'finish' ? course.finish_line : course.beach_start_line;
  if (Array.isArray(legacy) && legacy.length === 2 && legacy[0] && 'lat' in legacy[0]) {
    return { from: legacy[0], to: legacy[1] };
  }
  const e = (legacy && legacy[0]) || {};
  return { from: e.m1 || e.marker, to: e.m2 || e.marker };
}

function deriveLegs(course) {
  if (course.legs && course.legs.length) return course.legs;
  const all = { ...(course.annotations || {}), ...(course.sections || {}) };
  const legs = [];
  for (const [key, s] of Object.entries(course.sections || {})) {
    if (s.type === 'round-bouy' || s.type === 'round-buoy') {
      const zoneKey = s.bouy || s.buoy || s.zone || s.mark;
      const zone = all[zoneKey];
      const markId = (zone && zone.mark) ? zone.mark : zoneKey;
      if (markId) legs.push({ key, mark: markId, rounding: s.rounding || 'starboard', label: s.text || key, section: s });
    }
  }
  return legs;
}

function buildGuide(markers, course, roundDist = 25) {
  const startEntry = lineEntry(course, 'start');
  const start1 = coordsOf(markers, startEntry.from);
  const start2 = coordsOf(markers, startEntry.to);
  const startMid = midpoint(start1, start2);

  const finishEntry = lineEntry(course, 'finish');
  const finish1 = coordsOf(markers, finishEntry.from);
  const finish2 = coordsOf(markers, finishEntry.to);
  const finishMid = midpoint(finish1, finish2);

  const legs = deriveLegs(course);
  const guidePts = [startMid];
  const legInfo = [];
  let from = startMid;
  let total = 0;

  for (const leg of legs) {
    const m = markerById(markers, leg.mark);
    if (!m) continue;
    const mark = [m.lat, m.lon];
    const h = bearing(from, mark);
    const side = (leg.rounding || '').toLowerCase() === 'port' ? 'right' : 'left';
    const pass = offsetPoint(mark, h, roundDist, side);
    const d1 = haversine(from, pass);
    total += d1;
    legInfo.push({ label: leg.label || `Round ${m.label || leg.mark}`, distance: d1, target: m });
    guidePts.push(pass);
    from = pass;
  }
  const dFinish = haversine(from, finishMid);
  total += dFinish;
  guidePts.push(finishMid);

  return { start1, start2, startMid, finish1, finish2, finishMid, guidePts, legInfo, total, startEntry, finishEntry };
}

function normalizeAngle(deg) {
  let a = deg % 360;
  if (a <= -180) a += 360;
  if (a > 180) a -= 360;
  return a;
}
function tangentPoint(external, center, r, side, p1, p2) {
  const d = haversine(center, external);
  if (d <= r) return pointAt(center, bearing(center, external), r);
  const base = bearing(center, external);
  const delta = toDeg(Math.acos(Math.min(1, r / d)));
  const c1 = pointAt(center, base + delta, r);
  const c2 = pointAt(center, base - delta, r);
  if (pointSide(p1, p2, c1) === side) return c1;
  if (pointSide(p1, p2, c2) === side) return c2;
  return c1;
}
function buildRoundedGuide(markers, course, roundDist = 25) {
  const startEntry = lineEntry(course, 'start');
  const start1 = coordsOf(markers, startEntry.from);
  const start2 = coordsOf(markers, startEntry.to);
  const startMid = midpoint(start1, start2);

  const finishEntry = lineEntry(course, 'finish');
  const finish1 = coordsOf(markers, finishEntry.from);
  const finish2 = coordsOf(markers, finishEntry.to);
  const finishMid = midpoint(finish1, finish2);

  const legs = deriveLegs(course);
  const guidePts = [startMid];
  const legInfo = [];
  const roundArcs = new Map();
  let total = 0;
  let from = startMid;

  function push(p) {
    total += haversine(guidePts[guidePts.length - 1], p);
    guidePts.push(p);
  }

  for (let i = 0; i < legs.length; i++) {
    const leg = legs[i];
    const markId = leg.mark || leg.target;
    if (!markId || markId === 'finish') continue;
    const m = markerById(markers, markId);
    if (!m) continue;
    const mark = [m.lat, m.lon];
    const nextId = (i + 1 < legs.length) ? (legs[i + 1].mark || legs[i + 1].target) : null;
    const nextTarget = (nextId === 'finish' || !nextId) ? finishMid : coordsOf(markers, nextId);
    const zoneKey = leg.section ? (leg.section.bouy || leg.section.buoy || leg.section.zone || leg.section.mark) : null;
    const zone = zoneKey ? (course.annotations || {})[zoneKey] : null;
    const r = (leg.section && (leg.section.rounding_radius || leg.section.radius)) || (zone && zone.radius) || roundDist;
    const startTotal = total;
    const section = leg.section || {};
    const arc = roundBuoyArc(mark, from, nextTarget, r, leg.rounding || 'starboard', 6, section.entry_angle, section.exit_angle, section.turn);
    roundArcs.set(leg.key, arc);
    for (const p of arc.arcPoints) push(p);
    legInfo.push({ key: leg.key, label: leg.label || `${m.name || m.label || markId} (${arc.side})`, distance: total - startTotal, target: m, endIdx: guidePts.length - 1 });
    from = arc.exit;
  }
  push(finishMid);
  return { start1, start2, startMid, finish1, finish2, finishMid, guidePts, legInfo, roundArcs, total, startEntry, finishEntry };
}

function roundBuoyArc(center, prev, next, radius, rounding, steps = 6, entryBearing = null, exitBearing = null, turn = null) {
  // Starboard rounding keeps the mark on the right side of the boat, so the center is on the right and the turn is clockwise.
  // Port rounding keeps the mark on the left side, so the center is on the left and the turn is counterclockwise.
  const side = (rounding || '').toLowerCase() === 'starboard' ? 'right' : 'left';
  let finalEntryB = entryBearing;
  let finalExitB = exitBearing;
  let desiredDelta = null;
  if (turn != null && !Number.isNaN(Number(turn))) {
    desiredDelta = Number(turn);
    if (finalEntryB != null && finalExitB == null) {
      finalExitB = finalEntryB + desiredDelta;
    } else if (finalExitB != null && finalEntryB == null) {
      finalEntryB = finalExitB - desiredDelta;
    }
  }
  const entry = finalEntryB != null
    ? pointAt(center, finalEntryB, radius)
    : tangentPoint(prev, center, radius, side, prev, center);
  let exit = finalExitB != null
    ? pointAt(center, finalExitB, radius)
    : tangentPoint(next, center, radius, side, center, next);
  const entryAngle = bearing(center, entry);
  let exitAngle;
  let delta;
  if (desiredDelta != null && (entryBearing != null || exitBearing != null)) {
    delta = desiredDelta;
    exitAngle = entryAngle + delta;
    if (entryBearing != null && exitBearing != null) {
      const providedExit = pointAt(center, finalExitB, radius);
      const providedExitAngle = bearing(center, providedExit);
      if (Math.abs(normalizeAngle(providedExitAngle - exitAngle)) > 1) {
        console.warn(`roundBuoyArc: turn ${turn}° conflicts with explicit entry ${entryBearing}°/exit ${exitBearing}° pair; using turn`);
      }
    }
  } else {
    exitAngle = bearing(center, exit);
    delta = normalizeAngle(exitAngle - entryAngle);
    // Starboard rounding should be a clockwise turn (negative delta),
    // port rounding should be counterclockwise (positive delta).
    if (side === 'right' && delta > 0) {
      delta -= 360;
    } else if (side === 'left' && delta < 0) {
      delta += 360;
    }
  }
  exit = pointAt(center, exitAngle, radius);
  const arcPoints = [entry];
  for (let j = 1; j < steps; j++) {
    arcPoints.push(pointAt(center, entryAngle + delta * (j / steps), radius));
  }
  arcPoints.push(exit);
  return { entry, exit, arcPoints, side, entryAngle, exitAngle, radius, center, turn: desiredDelta };
}

function pointSide(p1, p2, p) {
  const dx = p2[1] - p1[1], dy = p2[0] - p1[0];
  const dpx = p[1] - p1[1], dpy = p[0] - p1[0];
  const cross = dx * dpy - dy * dpx;
  return cross > 1e-15 ? 'left' : 'right';
}

function resolveSide(p1, p2, side, role, roleSide, center) {
  const s = (side || '').toLowerCase();
  if (s === 'right' || s === 'starboard' || s === 'bottom') return 'right';
  if (s === 'left' || s === 'port' || s === 'top') return 'left';
  const inner = () => pointSide(p1, p2, [center.lat, center.lon]);
  if (s === 'front') return (roleSide && roleSide[role]) || inner();
  if (s === 'back') {
    const front = (roleSide && roleSide[role]) || inner();
    return front === 'left' ? 'right' : 'left';
  }
  if (s === 'inner') return inner();
  if (s === 'outer') {
    const i = inner();
    return i === 'left' ? 'right' : 'left';
  }
  return 'left';
}

const Course = {
  toRad, toDeg, haversine, bearing, midpoint, offsetPoint, pointAt,
  markerById, coordsOf, resolvePoint, lineEntry, buildGuide, buildRoundedGuide,
  roundBuoyArc, pointSide, resolveSide
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = Course;
}
