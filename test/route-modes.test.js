import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveRouteMode, ROUTE_MODES } from '../route-modes.js';

test('maps supported travel choices to Valhalla costing profiles', () => {
  assert.equal(ROUTE_MODES.pedestrian.costing, 'pedestrian');
  assert.equal(ROUTE_MODES.bicycle.costing, 'bicycle');
  assert.equal(ROUTE_MODES.car.costing, 'auto');
  assert.equal(ROUTE_MODES.motorcycle.costing, 'motorcycle');
  assert.equal(ROUTE_MODES.scooter.costing, 'motor_scooter');
  assert.equal(ROUTE_MODES.transit.costing, 'multimodal');
});

test('rejects unknown route modes', () => {
  assert.equal(resolveRouteMode('flying'), null);
  assert.equal(resolveRouteMode('car'), 'car');
});
