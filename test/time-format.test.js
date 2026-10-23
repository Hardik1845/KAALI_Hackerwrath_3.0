import test from 'node:test';
import assert from 'node:assert/strict';
import { formatDuration } from '../public/time-format.js';

test('formats routing-provider durations from seconds as minutes and hours', () => {
  assert.equal(formatDuration(60), '1 min');
  assert.equal(formatDuration(3600), '1 hr');
  assert.equal(formatDuration(3900), '1 hr 5 min');
});

test('does not turn missing or zero provider durations into a fake one-minute estimate', () => {
  assert.equal(formatDuration(null), 'Time unavailable');
  assert.equal(formatDuration(0), 'Time unavailable');
  assert.equal(formatDuration(NaN), 'Time unavailable');
});
