// Values are Valhalla route costing models. Transit requires a provider with GTFS feeds.
export const ROUTE_MODES = Object.freeze({
  pedestrian: { costing: 'pedestrian', label: 'Walk', infrastructure: 'pedestrian' },
  bicycle: { costing: 'bicycle', label: 'Bicycle', infrastructure: 'pedestrian' },
  car: { costing: 'auto', label: 'Car', infrastructure: 'road' },
  motorcycle: { costing: 'motorcycle', label: 'Motorcycle', infrastructure: 'road' },
  scooter: { costing: 'motor_scooter', label: 'Scooter / moped', infrastructure: 'road' },
  transit: { costing: 'multimodal', label: 'Public transit', infrastructure: 'mixed' }
});

export function resolveRouteMode(value) {
  return Object.hasOwn(ROUTE_MODES, value) ? value : null;
}
