import test from 'node:test';
import assert from 'node:assert/strict';
import { evaluateRoutes } from '../route-model.js';

const route = (id, lengthKm, patch = {}) => ({ id, lengthKm, points: [{ lat: 0, lon: 0 }], recentConcernCount: 0, lighting: { lit: 0, unlit: 0, mapped: 0 }, infrastructureCoverage: 0, ...patch });

test('calculates detours from shortest valid route', () => {
  const [a,b] = evaluateRoutes([route('a', 2), route('b', 2.2)], { reportsAvailable: true });
  assert.equal(a.detourKm, 0); assert.equal(a.detourPercent, 0);
  assert.ok(Math.abs(b.detourKm - .2) < 1e-9); assert.equal(Math.round(b.detourPercent), 10);
});
test('ignores zero, missing and malformed length candidates', () => {
  assert.deepEqual(evaluateRoutes([route('zero', 0), route('bad', NaN), { id: 'shape' }]), []);
});
test('normalizes reports by route distance and does not penalize length alone', () => {
  const [short, long] = evaluateRoutes([route('s', 1), route('l', 2)], { reportsAvailable: true });
  assert.equal(short.relativeRiskScore, 0); assert.ok(long.relativeRiskScore > 0); // difference is detour only
  const both = evaluateRoutes([route('s', 1, { recentConcernCount: 2 }), route('l', 1.2, { recentConcernCount: 2.4 })], { reportsAvailable: true });
  assert.equal(both[0].relativeRiskScore - both[1].relativeRiskScore, -20); // equal report exposure; only detour
});
test('missing lighting stays unknown and missing reports stay distinct from zero', () => {
  const [r] = evaluateRoutes([route('a', 1)], { reportsAvailable: false });
  assert.equal(r.relativeRiskScore, null);
  assert.ok(r.reasons.some(x => x.code === 'lighting_unknown'));
  assert.ok(r.reasons.some(x => x.code === 'reports_unavailable'));
  const [empty] = evaluateRoutes([route('a', 1)], { reportsAvailable: true });
  assert.equal(empty.recentConcernCount, 0); assert.equal(empty.relativeRiskScore, 0);
});
test('does not recommend when evidence is insufficient or outside detour limit', () => {
  const none = evaluateRoutes([route('a', 1)], { reportsAvailable: true });
  assert.equal(none[0].recommended, false);
  const tooLong = evaluateRoutes([route('a', 1, { lighting: { mapped: 1, lit: 1, unlit: 0 } }), route('b', 1.5)], { reportsAvailable: true });
  assert.equal(tooLong.find(r => r.id === 'b').recommendationEligible, false);
  assert.equal(tooLong.find(r => r.recommended).id, 'a');
  const unknownAlternative = evaluateRoutes([
    route('mapped', 1, { lighting: { mapped: 1, lit: 1, unlit: 0 } }),
    route('unknown', 1.1)
  ], { reportsAvailable: true });
  assert.equal(unknownAlternative.every(r => !r.recommended), true);
  assert.equal(unknownAlternative.every(r => r.assessmentStatus === 'insufficient_evidence'), true);
});
