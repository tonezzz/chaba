const assert = require('assert');
const Course = require('./course.js');

function test(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (e) {
    console.error(`FAIL ${name}: ${e.message}`);
    process.exitCode = 1;
  }
}

test('haversine equator degree', () => {
  const d = Course.haversine([0, 0], [0, 1]);
  assert(Math.abs(d - 111195) < 10, `expected ~111195, got ${d}`);
});

test('midpoint', () => {
  const m = Course.midpoint([0, 0], [2, 2]);
  assert.deepStrictEqual(m, [1, 1]);
});

test('resolveSide static keywords', () => {
  const center = { lat: 1, lon: 0.5 };
  const p1 = [0, 0], p2 = [0, 1];
  assert.strictEqual(Course.resolveSide(p1, p2, 'inner', null, null, center), 'left');
  assert.strictEqual(Course.resolveSide(p1, p2, 'outer', null, null, center), 'right');
  assert.strictEqual(Course.resolveSide(p1, p2, 'left', null, null, center), 'left');
  assert.strictEqual(Course.resolveSide(p1, p2, 'right', null, null, center), 'right');
});

test('resolveSide front/back role', () => {
  const center = { lat: 1, lon: 0.5 };
  const p1 = [0, 0], p2 = [0, 1];
  const roleSide = { x: 'right' };
  assert.strictEqual(Course.resolveSide(p1, p2, 'front', 'x', roleSide, center), 'right');
  assert.strictEqual(Course.resolveSide(p1, p2, 'back', 'x', roleSide, center), 'left');
});

test('resolvePoint marker', () => {
  const markers = [{ id: 'x', lat: 1, lon: 2 }];
  assert.deepStrictEqual(Course.resolvePoint(markers, {}, 'x'), [1, 2]);
});

test('resolvePoint line annotation midpoint', () => {
  const markers = [{ id: 'a', lat: 0, lon: 0 }, { id: 'b', lat: 2, lon: 2 }];
  const annotations = {
    my_line: { type: 'line', from: 'a', to: 'b' }
  };
  const p = Course.resolvePoint(markers, annotations, 'my_line');
  assert.deepStrictEqual(p, [1, 1]);
});

test('buildGuide with one leg', () => {
  const markers = [
    { id: 'a', lat: 0, lon: 1 },
    { id: 'b', lat: 0, lon: -1 },
    { id: 'c', lat: 1, lon: 0 }
  ];
  const course = {
    annotations: {
      start_line: { type: 'line', role: 'start', from: 'a', to: 'b' },
      finish_line: { type: 'line', role: 'finish', from: 'a', to: 'b' }
    },
    legs: [{ mark: 'c', rounding: 'port' }]
  };
  const g = Course.buildGuide(markers, course, 100);
  assert.strictEqual(g.legInfo.length, 1);
  assert.strictEqual(g.guidePts.length, 3);
  assert(g.total > 0, 'total distance should be positive');
});

test('buildRoundedGuide produces arced path', () => {
  const markers = [
    { id: 'a', lat: 0, lon: 1 },
    { id: 'b', lat: 0, lon: -1 },
    { id: 'c', lat: 1, lon: 0 }
  ];
  const course = {
    annotations: {
      start_line: { type: 'line', role: 'start', from: 'a', to: 'b' },
      finish_line: { type: 'line', role: 'finish', from: 'a', to: 'b' }
    },
    legs: [{ mark: 'c', rounding: 'port' }]
  };
  const g = Course.buildRoundedGuide(markers, course, 100);
  assert.strictEqual(g.legInfo.length, 1);
  assert(g.guidePts.length > 3, 'rounded guide should have more than 3 points');
  assert(g.total > 0, 'total distance should be positive');
});

test('roundBuoyArc points stay on the circle radius', () => {
  const arc = Course.roundBuoyArc([0, 0], [0, -0.02], [0.02, 0], 1000, 'starboard', 4);
  assert.strictEqual(arc.arcPoints.length, 5);
  for (const p of arc.arcPoints) {
    const d = Course.haversine([0, 0], p);
    assert(Math.abs(d - 1000) < 1, `point ${p} should be ~1000 m from center, got ${d}`);
  }
});

test('buildRoundedGuide derives legs from sections', () => {
  const markers = [
    { id: 'a', lat: 0, lon: 1 },
    { id: 'b', lat: 0, lon: -1 },
    { id: 'c', lat: 1, lon: 0 }
  ];
  const course = {
    annotations: {
      start_line: { type: 'line', role: 'start', from: 'a', to: 'b' },
      finish_line: { type: 'line', role: 'finish', from: 'a', to: 'b' },
      c_zone: { type: 'zone', mark: 'c', radius: 100 }
    },
    sections: {
      leg1: { type: 'arrow-area', from: 'start_line', to: 'c_zone' },
      round_c: { type: 'round-bouy', bouy: 'c_zone', rounding: 'port', text: 'Round C' },
      leg2: { type: 'arrow-area', from: 'c_zone', to: 'finish_line' }
    }
  };
  const g = Course.buildRoundedGuide(markers, course, 100);
  assert.strictEqual(g.legInfo.length, 1, 'should derive one leg from round-bouy section');
  assert.strictEqual(g.legInfo[0].label, 'Round C');
  assert(g.guidePts.length > 3, 'rounded guide should have more than 3 points');
  assert(g.total > 0, 'total distance should be positive');
});

if (process.exitCode) process.exit(process.exitCode);
console.log('done');
