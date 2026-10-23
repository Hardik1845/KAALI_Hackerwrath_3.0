import { formatDuration } from './time-format.js';

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const safeText = value => String(value ?? '');

const state = {
  view: 'dashboard', map: null, routeOrigin: null, routeDestination: null, currentLocation: null,
  travelMode: 'pedestrian',
  routeOptions: [], modeTimes: {}, selectedRoute: null, destinationLabel: '', navigation: false, watchId: null,
  routeRequestId: 0,
  lastRerouteAt: 0, lastRerouteLocation: null, reportLayer: null, routeLayer: null, serviceLayer: null,
  reportPollTimer: null, checkinTimer: null, checkinDeadline: null, cameraStream: null, cameraArmed: false,
  isCapturing: false, referenceFile: null, referenceHash: null, contacts: loadJson('saheli.contacts', []),
  emergencyNumber: localStorage.getItem('saheli.emergency') || '112', selectedContact: null,
  reportLocation: null, reportMode: 'community', demoReportCount: 0, pickingReportLocation: false,
  includeLocation: false, twilioConfigured: null, twilioStatusUnavailable: false
};

function loadJson(key, fallback) {
  try { const value = JSON.parse(localStorage.getItem(key)); return Array.isArray(value) ? value : fallback; }
  catch { return fallback; }
}

function toast(message, type = 'info', action = null) {
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.textContent = message;
  if (action) {
    const button = document.createElement('button'); button.textContent = action.label;
    button.addEventListener('click', () => { action.run(); node.remove(); }); node.append(button);
  }
  $('#toast-region').append(node);
  setTimeout(() => node.remove(), action ? 10000 : 5200);
}

async function api(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { ...(options.body ? { 'content-type': 'application/json' } : {}), ...options.headers } });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.blob();
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status}).`);
  return payload;
}

function openDialog(id) { const dialog = document.getElementById(id); if (dialog && !dialog.open) dialog.showModal(); }
function closeDialog(id) { const dialog = document.getElementById(id); if (dialog?.open) dialog.close(); }

function setView(name) {
  state.view = name;
  $$('.view').forEach(view => view.classList.toggle('active', view.id === `view-${name}`));
  $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === name));
  const labels = { dashboard: 'Safety map', protection: 'Image protection', evidence: 'Evidence & check-in', contacts: 'Trusted circle' };
  $('#crumb-title').textContent = labels[name] || labels.dashboard;
  $('#sidebar').classList.remove('open'); $('#scrim').classList.remove('open');
  if (name === 'dashboard') setTimeout(() => state.map?.invalidateSize(), 100);
  if (name === 'evidence') renderEvidence();
}

function setCurrentLocation(position, updateOrigin = false) {
  state.currentLocation = {
    lat: position.coords.latitude, lon: position.coords.longitude, accuracy: position.coords.accuracy,
    speed: Number.isFinite(position.coords.speed) ? position.coords.speed : 0,
    timestamp: new Date(position.timestamp || Date.now()).toISOString()
  };
  if (updateOrigin) {
    clearRouteResults('Starting point changed. Compare routes again when ready.');
    state.routeOrigin = { lat: state.currentLocation.lat, lon: state.currentLocation.lon, label: 'Current location' };
    $('#origin-input').value = 'Current location';
    if (state.routeDestination) requestRoutes({ origin: state.routeOrigin, destination: state.routeDestination, mode: state.travelMode });
  }
  updateLocationUI();
  if (state.map) {
    const point = [state.currentLocation.lat, state.currentLocation.lon];
    if (!state.userMarker) state.userMarker = L.marker(point, { icon: L.divIcon({ className: 'user-pin', iconSize: [15, 15], iconAnchor: [7.5, 7.5] }), zIndexOffset: 900 }).addTo(state.map);
    else state.userMarker.setLatLng(point);
  }
}

function updateLocationUI() {
  const located = Boolean(state.currentLocation);
  $('#map-caption').textContent = located ? 'Current position stays on this device' : 'Choose a location to get started';
  $('#map-overlay-label').textContent = located ? `Location · ±${Math.round((state.currentLocation.accuracy || 0) / 10) * 10} m` : 'No location shared';
  if (located && state.map && state.map.getZoom() < 12) state.map.setView([state.currentLocation.lat, state.currentLocation.lon], 15);
}

function locate({ updateOrigin = false, center = true } = {}) {
  if (!navigator.geolocation) { toast('This browser does not support location sharing.', 'error'); return Promise.reject(new Error('Geolocation unavailable.')); }
  return new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(position => {
    setCurrentLocation(position, updateOrigin);
    if (center && state.map) state.map.setView([position.coords.latitude, position.coords.longitude], 16);
    resolve(state.currentLocation);
  }, error => {
    const messages = { 1: 'Location permission was declined.', 2: 'Your location is currently unavailable.', 3: 'Location request timed out.' };
    const failure = new Error(messages[error.code] || 'Location could not be read.'); toast(failure.message, 'error'); reject(failure);
  }, { enableHighAccuracy: true, timeout: 14_000, maximumAge: 15_000 }));
}

function initMap() {
  if (!window.L) { toast('The map library did not load. Check your internet connection and refresh.', 'error'); return; }
  state.map = L.map('map', { zoomControl: false, preferCanvas: true, minZoom: 2 }).setView([17, 0], 2);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>' }).addTo(state.map);
  L.control.zoom({ position: 'bottomright' }).addTo(state.map);
  state.reportLayer = L.layerGroup().addTo(state.map);
  state.routeLayer = L.layerGroup().addTo(state.map);
  state.serviceLayer = L.layerGroup().addTo(state.map);
  state.map.on('click', event => {
    const point = { lat: event.latlng.lat, lon: event.latlng.lng };
    if (state.pickingReportLocation) {
      state.pickingReportLocation = false;
      state.reportLocation = point;
      state.lastMapPoint = point;
      L.popup().setLatLng(event.latlng).setContent('Report location selected').openOn(state.map);
      openReportDialog({ demo: state.reportMode === 'demo', preserveLocation: true });
      return;
    }
    state.lastMapPoint = point;
    const target = state.activeWaypoint || (!state.routeOrigin ? 'origin' : 'destination');
    clearRouteResults(`${target === 'origin' ? 'Starting point' : 'Destination'} changed. Compare routes again when ready.`);
    if (target === 'origin') { state.routeOrigin = point; $('#origin-input').value = `${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`; }
    else { state.routeDestination = point; state.destinationLabel = 'Map pin'; $('#destination-input').value = `${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`; }
    if (state.routeOrigin && state.routeDestination) requestRoutes({ origin: state.routeOrigin, destination: state.routeDestination, mode: state.travelMode });
    const popup = document.createElement('div'); popup.textContent = `Set as ${target === 'origin' ? 'starting point' : 'destination'}`;
    L.popup().setLatLng(event.latlng).setContent(popup).openOn(state.map);
  });
  state.map.on('moveend', refreshReports);
  state.map.on('moveend', drawRouteMarkers);
  refreshReports();
}

const reportLabels = {
  harassment: 'Harassment reported', following: 'Someone may be followed', poor_lighting: 'Poorly lit area',
  unsafe_path: 'Unsafe path or blocked route', help_available: 'Help offered here', other: 'Other concern'
};

function seriousCategory(category) { return ['harassment', 'following', 'unsafe_path'].includes(category); }

function updateDemoControls() {
  const clear = $('#clear-demo-reports');
  if (clear) clear.disabled = state.demoReportCount < 1;
  const add = $('#add-demo-report');
  if (add) add.setAttribute('aria-label', `Add practice report${state.demoReportCount ? `; ${state.demoReportCount} currently active` : ''}`);
}

function reportIcon(report) {
  const serious = ['harassment', 'following', 'unsafe_path'].includes(report.category);
  const caution = ['poor_lighting', 'other'].includes(report.category);
  return L.divIcon({ className: `report-pin${serious ? ' severe-report-pin' : caution ? ' caution-report-pin' : ''}${Number(report.is_demo) === 1 ? ' demo-report-pin' : ''}`, iconSize: [13, 13], iconAnchor: [6.5, 6.5] });
}
function serviceIcon() { return L.divIcon({ className: 'service-pin', html: '+', iconSize: [25, 25], iconAnchor: [12.5, 12.5] }); }

function currentBounds() {
  if (!state.map) return null;
  const box = state.map.getBounds();
  if (box.getNorth() - box.getSouth() > 1.02 || box.getEast() - box.getWest() > 1.02) return null;
  return `${box.getSouth()},${box.getWest()},${box.getNorth()},${box.getEast()}`;
}

let reportFetchAt = 0;
async function refreshReports() {
  const bbox = currentBounds(); if (!bbox) return;
  if (Date.now() - reportFetchAt < 1200) { clearTimeout(state.reportRefreshTimer); state.reportRefreshTimer = setTimeout(refreshReports, 1300); return; }
  reportFetchAt = Date.now();
  try {
    const result = await api(`/api/reports?bbox=${encodeURIComponent(bbox)}`);
    state.mapReports = result.reports || [];
    state.demoReportCount = Number(result.demoCount) || 0;
    updateDemoControls();
    drawReports();
  } catch (error) { console.warn('Community notes unavailable:', error.message); }
}

function popupFor(title, note, createdAt, report) {
  const box = document.createElement('div'), strong = document.createElement('strong'), text = document.createElement('small');
  strong.textContent = title;
  const relative = createdAt ? new Date(createdAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '';
  const source = Number(report?.is_demo) === 1 ? `Practice-only synthetic report${report.reporter ? ` · ${report.reporter}` : ''} · not real` : 'Community-submitted · not verified';
  text.textContent = [note, relative, source].filter(Boolean).join(' · ');
  box.append(strong, text); return box;
}

function drawReports() {
  if (!state.reportLayer || !state.mapReports) return;
  state.reportLayer.clearLayers();
  for (const report of state.mapReports) {
    const marker = L.marker([report.lat, report.lon], { icon: reportIcon(report) });
    marker.bindPopup(popupFor(reportLabels[report.category] || 'Community report', report.note, report.created_at, report));
    marker.addTo(state.reportLayer);
  }
}

function drawRouteMarkers() {
  if (!state.map || !state.selectedRoute) return;
  // Route layers are redrawn separately; this hook keeps map-bound report refresh distinct.
}

function drawSelectedRoute() {
  if (!state.routeLayer) return;
  state.routeLayer.clearLayers();
  if (!state.selectedRoute) return;
  const chosen = state.selectedRoute;
  for (const route of state.routeOptions) {
    if (route.id === chosen.id) continue;
    L.polyline(route.points.map(point => [point.lat, point.lon]), { color: '#9ea99f', weight: 3, opacity: .57, dashArray: '5 7', lineCap: 'round' }).addTo(state.routeLayer);
  }
  const pathLine = L.polyline(chosen.points.map(point => [point.lat, point.lon]), { color: chosen.seriousCount ? '#b95b50' : '#62816e', weight: 5, opacity: .94, lineCap: 'round', lineJoin: 'round', className: `leaflet-routing-line${chosen.seriousCount ? ' unsafe-line' : ''}` }).addTo(state.routeLayer);
  for (const segment of chosen.segments || []) {
    if (segment.reportStatus === 'concern_report_found') {
      L.polyline(segment.points.map(point => [point.lat, point.lon]), { color: '#c47a57', weight: 7, opacity: .9, lineCap: 'round', lineJoin: 'round' })
        .bindPopup(`${segment.recentConcernCount} recent community concern report${segment.recentConcernCount === 1 ? '' : 's'} mapped near this route section. Reports are unverified.`)
        .addTo(state.routeLayer);
    } else if (segment.reportStatus === 'unavailable') {
      L.polyline(segment.points.map(point => [point.lat, point.lon]), { color: '#888f89', weight: 6, opacity: .8, dashArray: '3 7', lineCap: 'round' }).addTo(state.routeLayer);
    }
  }
  state.map.fitBounds(pathLine.getBounds().pad(.15), { maxZoom: 16 });
  if (state.routeOrigin) L.circleMarker([state.routeOrigin.lat, state.routeOrigin.lon], { radius: 5, color: '#fff', weight: 2, fillColor: '#6a8a72', fillOpacity: 1 }).addTo(state.routeLayer);
  if (state.routeDestination) L.circleMarker([state.routeDestination.lat, state.routeDestination.lon], { radius: 6, color: '#fff', weight: 2, fillColor: '#d47560', fillOpacity: 1 }).addTo(state.routeLayer);
  $('#map-caption').textContent = `${formatDistance(chosen.lengthKm)} ${chosen.travelModeLabel || modeLabel(state.travelMode)} · ${formatDuration(chosen.summary.time)}`;
  $('#map-overlay-label').textContent = `${chosen.travelModeLabel || modeLabel(state.travelMode)} routes compared with recent notes`;
}

function modeLabel(mode) { return ({ pedestrian: 'Walk', bicycle: 'Bicycle', car: 'Car', motorcycle: 'Motorcycle', scooter: 'Scooter / moped', transit: 'Public transit' })[mode] || 'Walk'; }

function formatDistance(km) { return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`; }

function parseCoordinate(value) {
  const match = String(value).trim().match(/^(-?\d{1,2}(?:\.\d+)?)[,\s]+(-?\d{1,3}(?:\.\d+)?)$/);
  if (!match) return null;
  const lat = Number(match[1]), lon = Number(match[2]);
  return lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180 ? { lat, lon, label: 'Map pin' } : null;
}

let previousGeocodeAt = 0;
async function geocode(text) {
  const wait = Math.max(0, 1150 - (Date.now() - previousGeocodeAt)); if (wait) await sleep(wait);
  previousGeocodeAt = Date.now();
  const data = await api(`/api/geocode?q=${encodeURIComponent(text)}`);
  if (!data.length) throw new Error(`No place found for “${text}”. Try a nearby street or full address.`);
  const result = data[0];
  return { lat: Number(result.lat), lon: Number(result.lon), label: result.display_name, importance: result.importance };
}

function routeStatus(message, busy = false) {
  $('#route-result').hidden = false; $('#route-list').hidden = true;
  const box = $('#route-result'); box.replaceChildren();
  if (busy) { const spin = document.createElement('span'); spin.className = 'spinner'; const text = document.createElement('span'); text.textContent = message; box.append(spin, text); box.style.flexDirection = 'row'; box.style.gap = '9px'; }
  else { const title = document.createElement('b'); title.textContent = message; const sub = document.createElement('p'); sub.textContent = 'You can adjust your start or destination and try again.'; box.append(title, sub); box.style.flexDirection = 'column'; box.style.gap = '0'; }
}

function clearRouteResults(message = 'Choose a starting point and destination to compare routes.') {
  state.routeRequestId++;
  state.routeOptions = [];
  state.modeTimes = {};
  state.selectedRoute = null;
  state.lastReportSignature = null;
  state.routeLayer?.clearLayers();
  const list = $('#route-list');
  if (list) { list.replaceChildren(); list.hidden = true; }
  const result = $('#route-result');
  if (result) {
    result.hidden = false;
    result.style.display = '';
    result.style.flexDirection = 'column';
    result.style.gap = '0';
    result.replaceChildren();
    const title = document.createElement('b'); title.textContent = message;
    const detail = document.createElement('p'); detail.textContent = 'Previous route comparisons were cleared because the trip settings changed.';
    result.append(title, detail);
  }
  $('#map-caption').textContent = 'Choose a location to plan a route';
  $('#map-overlay-label').textContent = 'No route selected';
}

async function requestRoutes({ origin, destination, quiet = false, mode = state.travelMode } = {}) {
  state.travelMode = mode;
  const requestId = ++state.routeRequestId;
  if (!quiet) routeStatus(`Finding current ${modeLabel(mode).toLowerCase()} routes…`, true);
  state.routeOrigin = origin; state.routeDestination = destination;
  if (state.navigation) { $('#origin-input').value = 'Current location'; state.originInputValue = 'Current location'; }
  try {
    const result = await api('/api/route', { method: 'POST', body: JSON.stringify({ origin, destination, mode }) });
    if (requestId !== state.routeRequestId) return null;
    if (result.mode !== mode || !result.modeTimes || !Object.keys(result.modeTimes).length) {
      throw new Error('The routing server did not return mode-specific times. Restart the app server, then refresh this page.');
    }
    state.routeOptions = result.options || [];
    state.modeTimes = result.modeTimes || {};
    state.selectedRoute = state.routeOptions.find(route => route.recommended) || state.routeOptions[0] || null;
    renderRouteOptions(); drawSelectedRoute();
    if (!quiet) toast(`Compared ${state.routeOptions.length} ${modeLabel(mode).toLowerCase()} route${state.routeOptions.length === 1 ? '' : 's'} with recent local notes.`);
    state.lastRerouteAt = Date.now();
    state.lastRerouteLocation = { lat: origin.lat, lon: origin.lon };
    return state.selectedRoute;
  } catch (error) {
    if (requestId !== state.routeRequestId) return null;
    if (!quiet) routeStatus(error.message);
    else toast(`Route refresh failed: ${error.message}`, 'error');
    return null;
  }
}

function renderRouteOptions() {
  const result = $('#route-result'), list = $('#route-list');
  result.hidden = true; list.hidden = false; list.replaceChildren();
  if (!state.routeOptions.length) { routeStatus(`No ${modeLabel(state.travelMode).toLowerCase()} options were returned.`); return; }
  const timePanel = document.createElement('section'); timePanel.className = 'mode-time-comparison';
  timePanel.setAttribute('aria-label', 'Estimated travel times by mode');
  const timeHeading = document.createElement('b'); timeHeading.textContent = 'Estimated time by travel mode';
  const timeNote = document.createElement('small'); timeNote.textContent = 'Provider estimates; each mode may use a different route. Road-speed data may be incomplete, and actual travel times vary.';
  const timeGrid = document.createElement('div'); timeGrid.className = 'mode-time-grid';
  for (const [mode, estimate] of Object.entries(state.modeTimes)) {
    const cell = document.createElement('div'); cell.className = `mode-time-cell ${mode === state.travelMode ? 'active' : ''}`;
    const label = document.createElement('span'); label.textContent = modeLabel(mode);
    const value = document.createElement('b');
    value.textContent = estimate?.available && Number.isFinite(estimate.durationSeconds) ? formatDuration(estimate.durationSeconds) : 'Unavailable';
    const distance = document.createElement('small');
    distance.textContent = estimate?.available && Number.isFinite(estimate.distanceKm) ? formatDistance(estimate.distanceKm) : 'No estimate';
    cell.append(label, value, distance); timeGrid.append(cell);
  }
  timePanel.append(timeHeading, timeNote, timeGrid); list.append(timePanel);
  for (const [index, route] of state.routeOptions.entries()) {
    const option = document.createElement('button');
    option.type = 'button'; option.className = `route-option ${route.id === state.selectedRoute?.id ? 'selected' : ''}${route.seriousCount ? ' unsafe' : route.cautionCount ? ' caution' : ''}`;
    const head = document.createElement('div'); head.className = 'route-option-head';
    const title = document.createElement('b'); title.textContent = `Route ${String.fromCharCode(65 + index)}`;
    const badge = document.createElement('span'); badge.className = `route-badge${route.seriousCount ? ' critical' : route.cautionCount ? ' caution' : route.recentConcernCount ? ' concern' : ''}`;
    badge.textContent = route.seriousCount
      ? route.recommended ? 'Recommended · serious reports remain' : `${route.seriousCount} serious report${route.seriousCount === 1 ? '' : 's'}`
      : route.recommended ? 'Recommended' : route.confidence === 'insufficient' ? 'Evidence limited' : route.cautionCount ? `${route.cautionCount} caution report${route.cautionCount === 1 ? '' : 's'}` : 'No reports found';
    head.append(title, badge);
    const meta = document.createElement('div'); meta.className = 'route-option-meta';
    const detour = Number.isFinite(route.detourKm) ? ` · +${formatDistance(route.detourKm)} (${Math.round(route.detourPercent || 0)}% detour)` : '';
    meta.textContent = `${formatDistance(route.lengthKm)} · ${Number.isFinite(route.summary?.time) ? formatDuration(route.summary.time) : 'Time unavailable'}${detour}`;
    const desc = document.createElement('div'); desc.className = 'route-option-desc';
    desc.className += route.seriousCount ? ' critical' : route.cautionCount ? ' caution' : '';
    const reasonText = (route.riskReasons || []).map(reason => `${reason.label} (${reason.count})`).join(' · ');
    desc.textContent = route.reportsAvailable === false ? 'Community report data is unavailable.'
      : route.seriousCount ? `${reasonText}. Serious concerns are mapped nearby; reports are unverified.`
        : route.cautionCount ? `${reasonText}. Consider this as a caution, not a safety guarantee.`
          : route.recentConcernCount ? `${route.recentConcernCount} recent community concern report${route.recentConcernCount === 1 ? '' : 's'} nearby (within about 160 m).`
            : 'No recent reports found in this server’s data; this does not mean the route is safe.';
    const riskPills = document.createElement('div'); riskPills.className = 'route-risk-reasons';
    for (const reason of (route.riskReasons || []).slice(0, 3)) {
      const pill = document.createElement('span');
      pill.className = seriousCategory(reason.category) ? '' : 'caution-pill';
      pill.textContent = `${reason.label} · ${reason.count}`;
      riskPills.append(pill);
      if (reason.demoCount) {
        const demo = document.createElement('span'); demo.className = 'demo-risk';
        demo.textContent = `Practice data${reason.demoReporters?.length ? ` · ${reason.demoReporters.join(', ')}` : ''}`;
        riskPills.append(demo);
      }
    }
    const mapSignals = document.createElement('div'); mapSignals.className = 'route-option-meta';
    const lighting = route.lighting || {};
    mapSignals.textContent = `${route.infrastructureCoverage == null ? 'Infrastructure coverage unavailable' : `Infrastructure data near ${Math.round(route.infrastructureCoverage * 100)}% of sampled locations`}. ${lighting.mapped ? `${Math.round((lighting.coverage || 0) * 100)}% of samples have a lighting tag (${lighting.lit} yes, ${lighting.unlit} no).` : 'Lighting is unknown; missing tags do not mean dark.'}`;
    const walkway = document.createElement('div'); walkway.className = 'route-option-meta';
    walkway.textContent = ['pedestrian', 'bicycle'].includes(route.travelMode || state.travelMode)
      ? route.pedestrian?.known ? `Sidewalk tag coverage ${Math.round((route.pedestrian.coverage || 0) * 100)}%; mapped sidewalk/pedestrian way near ${Math.round((route.pedestrian.positiveShare || 0) * 100)}% of known samples.` : 'Sidewalk information is unavailable; missing tags do not establish that sidewalks are absent.'
      : `Mapped road context for ${route.travelModeLabel || modeLabel(state.travelMode)} travel; this data does not indicate current traffic or closures.`;
    const assessment = document.createElement('div'); assessment.className = 'route-option-meta';
    assessment.textContent = route.assessmentStatus === 'relative_comparison' && route.relativeRiskScore != null
      ? `Relative comparison index ${route.relativeRiskScore}/100 · Evidence ${route.confidence || 'limited'} (index is not a probability)`
      : `No reliable route-to-route safety comparison · Evidence ${route.confidence || 'insufficient'}`;
    const explanation = document.createElement('div'); explanation.className = 'route-option-desc';
    explanation.textContent = route.explanation || 'Insufficient evidence to compare these alternatives confidently.';
    const maneuvers = document.createElement('div'); maneuvers.className = 'route-option-directions';
    (route.maneuvers || []).slice(0, 3).forEach(maneuver => { const row = document.createElement('div'); row.className = 'maneuver'; const icon = document.createElement('i'); icon.textContent = '↗'; const line = document.createElement('span'); line.textContent = maneuver.instruction; row.append(icon, line); maneuvers.append(row); });
    option.setAttribute('aria-pressed', String(route.id === state.selectedRoute?.id));
    option.setAttribute('aria-label', `${title.textContent}${route.recommended ? ', recommended' : ''}, ${meta.textContent}`);
    option.append(head, meta, desc);
    if (riskPills.childElementCount) option.append(riskPills);
    option.append(mapSignals, walkway, assessment, explanation, maneuvers);
    option.addEventListener('click', () => {
      state.selectedRoute = route; renderRouteOptions(); drawSelectedRoute();
    });
    list.append(option);
  }
  const start = document.createElement('button'); start.type = 'button'; start.className = 'primary-button navigation-action'; start.textContent = state.navigation ? 'End journey guidance' : 'Start journey guidance';
  start.addEventListener('click', toggleNavigation); list.append(start);
  const caveat = $('#route-result'); caveat.replaceChildren(); caveat.style.display = 'none';
}

async function onRouteSubmit(event) {
  event.preventDefault();
  clearRouteResults('Updating routes…');
  routeStatus('Resolving locations and finding updated routes…', true);
  try {
    const originText = $('#origin-input').value.trim(), destinationText = $('#destination-input').value.trim();
    if (!originText || !destinationText) throw new Error('Add a starting point and destination first.');
    const coordinateOrigin = parseCoordinate(originText), coordinateDest = parseCoordinate(destinationText);
    const origin = state.routeOrigin && originText === state.originInputValue ? state.routeOrigin : coordinateOrigin || await geocode(originText);
    $('#origin-input').value = originText === 'Current location' ? originText : origin.label || `${origin.lat.toFixed(5)}, ${origin.lon.toFixed(5)}`;
    state.originInputValue = $('#origin-input').value;
    const destination = state.routeDestination && destinationText === state.destinationInputValue ? state.routeDestination : coordinateDest || await geocode(destinationText);
    state.routeOrigin = origin; state.routeDestination = destination; state.destinationLabel = destination.label || destinationText;
    $('#destination-input').value = destinationText === state.destinationInputValue ? destinationText : destination.label || destinationText;
    state.destinationInputValue = $('#destination-input').value;
    await requestRoutes({ origin, destination, mode: $('#travel-mode').value });
  } catch (error) { routeStatus(error.message); toast(error.message, 'error'); }
}

function onLocationInput(which) {
  clearRouteResults(`${which === 'origin' ? 'Starting point' : 'Destination'} changed. Compare routes again when ready.`);
  state.activeWaypoint = which;
  if (which === 'origin') { state.routeOrigin = null; state.originInputValue = null; }
  else { state.routeDestination = null; state.destinationInputValue = null; }
}

function distanceToSegment(p, a, b) {
  const scale = Math.cos(p.lat * Math.PI / 180), px = p.lon * scale, py = p.lat;
  const ax = a.lon * scale, ay = a.lat, bx = b.lon * scale, by = b.lat;
  const dx = bx - ax, dy = by - ay;
  const denom = dx * dx + dy * dy;
  const t = denom ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / denom)) : 0;
  const latDiff = (py - (ay + t * dy)) * 111_320;
  const lonDiff = (px - (ax + t * dx)) * 111_320;
  return Math.hypot(latDiff, lonDiff);
}

function distanceFromRoute(point, route) {
  let closest = Infinity;
  for (let i = 0; i < route.points.length - 1; i++) closest = Math.min(closest, distanceToSegment(point, route.points[i], route.points[i + 1]));
  return closest;
}

async function startJourneyGuidance() {
  if (!navigator.geolocation) { toast('Location is needed for live route guidance.', 'error'); return; }
  try {
    const position = await locate({ updateOrigin: false, center: false });
    state.navigation = true; state.routeOrigin = { lat: position.lat, lon: position.lon, label: 'Current location' };
    $('#origin-input').value = 'Current location'; state.originInputValue = 'Current location';
    $('#map-overlay-label').textContent = 'Live route guidance is on';
    state.watchId = navigator.geolocation.watchPosition(onNavigationLocation, error => toast(error.code === 1 ? 'Location permission is needed to keep guidance updated.' : 'Location updates are temporarily unavailable.', 'error'), { enableHighAccuracy: true, maximumAge: 8_000, timeout: 20_000 });
    const action = $('.navigation-action'); if (action) action.textContent = 'End journey guidance';
    toast('Journey guidance is on. Keep Kaali open while you walk.');
    state.reportPollTimer = setInterval(pollRouteNotes, 45_000);
  } catch {}
}

function endJourneyGuidance() {
  state.navigation = false;
  if (state.watchId !== null) navigator.geolocation.clearWatch(state.watchId);
  state.watchId = null; clearInterval(state.reportPollTimer); state.reportPollTimer = null;
  const action = $('.navigation-action'); if (action) action.textContent = 'Start journey guidance';
  $('#map-overlay-label').textContent = 'Journey guidance is off';
  toast('Journey guidance stopped.');
}

function toggleNavigation() { state.navigation ? endJourneyGuidance() : startJourneyGuidance(); }

let navPosition = null;
async function onNavigationLocation(position) {
  navPosition = { lat: position.coords.latitude, lon: position.coords.longitude, accuracy: position.coords.accuracy };
  setCurrentLocation(position, false);
  if (!state.selectedRoute || !state.routeDestination) return;
  const offRoute = distanceFromRoute(navPosition, state.selectedRoute) > Math.max(100, position.coords.accuracy || 0);
  const moved = state.lastRerouteLocation ? distanceMeters(state.lastRerouteLocation, navPosition) > 115 : true;
  if ((offRoute || moved) && Date.now() - state.lastRerouteAt > 35_000) {
    const oldId = state.selectedRoute.id;
    const route = await requestRoutes({ origin: navPosition, destination: state.routeDestination, quiet: true });
    if (route) {
      if (route.id !== oldId) toast('Route refreshed with your latest position and recent community notes.');
      renderRouteOptions();
    }
  }
}

async function pollRouteNotes() {
  if (!state.navigation || !state.selectedRoute) return;
  const box = state.selectedRoute.points.reduce((bounds, point) => ({
    south: Math.min(bounds.south, point.lat), west: Math.min(bounds.west, point.lon),
    north: Math.max(bounds.north, point.lat), east: Math.max(bounds.east, point.lon)
  }), { south: 90, west: 180, north: -90, east: -180 });
  box.south = Math.max(-90, box.south - .002); box.west = Math.max(-180, box.west - .002);
  box.north = Math.min(90, box.north + .002); box.east = Math.min(180, box.east + .002);
  if (box.north - box.south > 1 || box.east - box.west > 1) return;
  try {
    const data = await api(`/api/reports?bbox=${encodeURIComponent([box.south, box.west, box.north, box.east].join(','))}`);
    const routeNotes = (data.reports || []).filter(report => state.selectedRoute.points.some(point => distanceMeters(point, report) <= 160));
    const signature = routeNotes.map(r => r.id).sort().join('|');
    if (state.lastReportSignature && signature !== state.lastReportSignature) {
      toast('A community note changed along your journey. Refreshing your route options.');
      if (navPosition) await requestRoutes({ origin: navPosition, destination: state.routeDestination, quiet: true });
    }
    state.lastReportSignature = signature;
  } catch (error) { console.info('Route notes could not be refreshed:', error.message); }
}

async function loadNearbyServices() {
  if (!state.map) return;
  if (!state.currentLocation && state.map.getZoom() < 9) { toast('Use your location or zoom the map to a town before looking up nearby services.'); return; }
  const center = state.currentLocation || { lat: state.map.getCenter().lat, lon: state.map.getCenter().lng };
  const button = $('#nearby-services'), old = button.textContent; button.disabled = true; button.textContent = 'Loading…';
  try {
    const data = await api('/api/services', { method: 'POST', body: JSON.stringify({ lat: center.lat, lon: center.lon }) }); state.serviceLayer.clearLayers();
    for (const item of data.elements || []) {
      const lat = item.lat ?? item.center?.lat, lon = item.lon ?? item.center?.lon;
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      const category = item.tags?.amenity || 'service';
      const names = { police: 'Police station', hospital: 'Hospital', fire_station: 'Fire station', pharmacy: 'Pharmacy', shelter: 'Shelter listing' };
      const title = item.tags?.name || names[category] || 'Nearby service';
      const marker = L.marker([lat, lon], { icon: serviceIcon() });
      marker.bindPopup(popupFor(title, `${names[category] || category} · map listing only; hours and availability are not confirmed`, null));
      marker.addTo(state.serviceLayer);
    }
    const count = state.serviceLayer.getLayers().length;
    if (!count) toast('No listed support services were found in this area. OpenStreetMap coverage varies.');
    else toast(`Showing ${count} nearby OpenStreetMap listing${count === 1 ? '' : 's'}. Hours and availability are not confirmed.`);
  } catch (error) { toast(`Nearby listings unavailable: ${error.message}`, 'error'); }
  finally { button.disabled = false; button.innerHTML = '<span>⌖</span> Nearby support'; if (old === 'Loading…') button.setAttribute('aria-label', 'Nearby support'); }
}

function startCheckinTimer(minutes) {
  state.checkinDeadline = Date.now() + minutes * 60_000;
  localStorage.setItem('saheli.checkin', String(state.checkinDeadline));
  $('#checkin-title').textContent = 'Check-in timer is running';
  $('#checkin-description').textContent = 'Keep Kaali open. When time is up, you’ll get a reminder to check in.';
  $('#timer-row').hidden = true; $('#checkin-done').hidden = false;
  tickCheckin(); clearInterval(state.checkinTimer); state.checkinTimer = setInterval(tickCheckin, 1000);
}

function stopCheckinTimer(overdue = false) {
  clearInterval(state.checkinTimer); state.checkinTimer = null; state.checkinDeadline = null;
  localStorage.removeItem('saheli.checkin');
  $('#checkin-title').textContent = overdue ? 'Your check-in time has passed' : 'A gentle reminder to check in';
  $('#checkin-description').textContent = overdue ? 'If you need someone, use SOS to alert your trusted contact or call local emergency services.' : 'Set a timer for the trip. If it passes, Kaali will remind you to contact someone.';
  $('#timer-row').hidden = false; $('#checkin-done').hidden = true;
  if (overdue) toast('Your check-in timer ended.', 'error', { label: 'Need help?', run: triggerSOS });
}

function tickCheckin() {
  if (!state.checkinDeadline) return;
  const remaining = Math.max(0, state.checkinDeadline - Date.now());
  if (!remaining) { stopCheckinTimer(true); return; }
  const minutes = Math.floor(remaining / 60_000), seconds = Math.floor((remaining % 60_000) / 1000);
  $('#checkin-title').textContent = `Check in within ${minutes}:${String(seconds).padStart(2, '0')}`;
  $('#checkin-description').textContent = 'When the timer ends, Kaali will remind you to reach someone. It will not send an alert on its own.';
}

function openSOS() {
  state.includeLocation = false;
  state.twilioConfigured = null;
  state.twilioStatusUnavailable = false;
  updateSosLocation(false);
  const select = $('#sos-recipient'); select.replaceChildren();
  for (const item of state.contacts) {
    const option = document.createElement('option'); option.value = item.id; option.textContent = `${item.name} · ${item.phone}`; select.append(option);
  }
  const contact = state.contacts[0]; state.selectedContact = contact || null;
  $('#recipient-wrap').hidden = state.contacts.length < 2;
  $('#sos-call-label').textContent = `Emergency number: ${state.emergencyNumber}`;
  renderSosContactPreview();
  openDialog('sos-dialog');
  api('/api/health').then(health => {
    state.twilioStatusUnavailable = health.sosService === false;
    state.twilioConfigured = state.twilioStatusUnavailable ? null : Boolean(health.twilio);
    if ($('#sos-dialog').open) renderSosContactPreview();
  }).catch(() => {
    state.twilioConfigured = null;
    state.twilioStatusUnavailable = true;
    if ($('#sos-dialog').open) renderSosContactPreview();
  });
  if (state.cameraArmed) takePhotoBurst().catch(error => toast(`Camera capture did not complete: ${error.message}`, 'error'));
}

function renderSosContactPreview() {
  const preview = $('#sos-contact-preview'); preview.replaceChildren();
  const contact = state.selectedContact;
  const message = document.createElement('span');
  message.textContent = contact ? `Your alert will be addressed to ${contact.name} (${contact.phone}).` : 'Add a trusted contact to send an SOS by text.';
  const delivery = document.createElement('small');
  delivery.textContent = state.twilioConfigured === true
    ? 'Direct SMS through Twilio is ready.'
    : state.twilioConfigured === false
      ? 'Twilio is not configured; the SMS app will open for you to send the message.'
      : state.twilioStatusUnavailable
        ? 'SMS service status is unavailable; Kaali will show the sending result after you tap alert.'
        : 'Checking SMS delivery…';
  preview.append(message, delivery);
  const button = $('#sos-send');
  button.disabled = false;
  button.textContent = contact ? `Alert ${contact.name}` : 'Add a trusted contact';
}

function updateSosLocation(include) {
  const location = $('#sos-location'); location.replaceChildren();
  const icon = document.createElement('span'); icon.className = 'location-mini'; icon.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>';
  const copy = document.createElement('span'); copy.style.flex = '1'; const title = document.createElement('b'), small = document.createElement('small');
  const action = document.createElement('button');
  if (include && state.currentLocation) {
    state.includeLocation = true; title.textContent = 'Map link will be added';
    small.textContent = `${state.currentLocation.lat.toFixed(4)}, ${state.currentLocation.lon.toFixed(4)}`;
    action.textContent = 'Remove'; action.addEventListener('click', () => updateSosLocation(false));
  } else {
    state.includeLocation = false; title.textContent = 'Location not shared'; small.textContent = 'Add location to create the live radar link required by SOS dispatch.';
    action.textContent = 'Add location'; action.addEventListener('click', async () => {
      try { if (!state.currentLocation) await locate({ center: false }); updateSosLocation(true); } catch {}
    });
  }
  copy.append(title, small); location.append(icon, copy, action);
}

function buildSosMessage() {
  const lines = ['I need help. Please call me as soon as you can.'];
  if (state.includeLocation && state.currentLocation) lines.push(`My location: https://maps.google.com/?q=${state.currentLocation.lat},${state.currentLocation.lon}`);
  lines.push('Sent using Kaali Safety.');
  return lines.join('\n');
}

async function sendSos() {
  const contact = state.selectedContact || state.contacts[0];
  if (!contact) { closeDialog('sos-dialog'); setView('contacts'); toast('Add a trusted contact before sending an SOS.'); return; }
  if (!state.includeLocation || !state.currentLocation) { toast('Add your location before sending this SOS so the live tracking link can be created.', 'error'); return; }
  const message = buildSosMessage(), button = $('#sos-send'); button.disabled = true;
  try {
    let userId = localStorage.getItem('kaali.sos-user-id');
    if (!userId) { userId = crypto.randomUUID(); localStorage.setItem('kaali.sos-user-id', userId); }
    const point = state.currentLocation;
    const location = { lat: point.lat, lng: point.lon, accuracy: point.accuracy || 0, speed: point.speed || 0, timestamp: point.timestamp || new Date().toISOString() };
    const result = await api('/api/sos', { method: 'POST', body: JSON.stringify({
      user_id: userId,
      user_name: 'Kaali user',
      location,
      trigger_type: 'manual',
      contacts: [{ name: contact.name, phone: contact.phone, relation: 'Trusted contact', priority: 1 }],
      passphrase: '',
      message
    }) });
    if (result.sent) {
      closeDialog('sos-dialog');
      const recipients = Array.isArray(result.sms_sent_to) ? result.sms_sent_to.length : 1;
      const message = `SOS activated. Alert sent to ${recipients} trusted contact${recipients === 1 ? '' : 's'}.`;
      const trackingUrl = result.trackingUrl || result.tracking_url;
      const action = trackingUrl ? { label: 'Open live radar', run: () => window.open(trackingUrl, '_blank', 'noopener,noreferrer') } : null;
      toast(message, 'info', action);
    }
    else {
      const phone = contact.phone.replace(/[^+\d]/g, '');
      const composer = `sms:${phone}?body=${encodeURIComponent(message)}`;
      window.location.href = composer; closeDialog('sos-dialog'); toast('Your messaging app is opening. Review and tap Send to alert your contact.');
    }
  } catch (error) { toast(error.message, 'error'); }
  finally { button.disabled = false; }
}

function callEmergency() {
  const number = state.emergencyNumber.replace(/[^+\d]/g, '');
  if (!number) { setView('contacts'); toast('Set your local emergency number first.'); return; }
  window.location.href = `tel:${number}`;
}

function saveContacts() { localStorage.setItem('saheli.contacts', JSON.stringify(state.contacts)); }

function renderContacts() {
  const container = $('#saved-contacts'); container.replaceChildren();
  if (!state.contacts.length) { const empty = document.createElement('div'); empty.className = 'contact-empty'; empty.textContent = 'No trusted person saved yet. Add someone you trust to reach quickly.'; container.append(empty); return; }
  for (const [index, contact] of state.contacts.entries()) {
    const row = document.createElement('div'); row.className = 'contact-row';
    const avatar = document.createElement('span'); avatar.className = 'contact-avatar'; avatar.textContent = contact.name.trim().charAt(0).toUpperCase() || '•';
    const details = document.createElement('div'), name = document.createElement('b'), phone = document.createElement('small');
    name.textContent = contact.name; phone.textContent = contact.phone; details.append(name, phone);
    const remove = document.createElement('button'); remove.className = 'remove-contact'; remove.setAttribute('aria-label', `Remove ${contact.name}`); remove.textContent = '×';
    remove.addEventListener('click', () => { state.contacts.splice(index, 1); saveContacts(); renderContacts(); toast('Trusted contact removed.'); });
    row.append(avatar, details, remove); container.append(row);
  }
}

function updateEmergencyNumber(value) {
  state.emergencyNumber = value.trim() || '112';
  localStorage.setItem('saheli.emergency', state.emergencyNumber);
  $('#emergency-number').value = state.emergencyNumber;
  $('#sos-call-label').textContent = `Emergency number: ${state.emergencyNumber}`;
}

function openReportDialog({ demo = false, preserveLocation = false } = {}) {
  state.pickingReportLocation = false;
  state.reportMode = demo ? 'demo' : 'community';
  if (!preserveLocation) state.reportLocation = state.lastMapPoint || state.currentLocation || null;
  $('#demo-reporter-wrap').hidden = !demo;
  $('#report-eyebrow').textContent = demo ? 'PRACTICE MODE · SYNTHETIC DATA' : 'A NOTE FOR THE COMMUNITY';
  $('#report-title').textContent = demo ? 'Add a practice incident' : 'Share what you noticed';
  $('#report-description').textContent = demo
    ? 'This synthetic report is clearly labeled and only exists to demonstrate how reports affect route comparisons.'
    : 'Notes are anonymous, unverified and automatically rounded to around 100 metres.';
  $('#report-submit').textContent = demo ? 'Add practice report' : 'Post anonymous note';
  $('#report-position').replaceChildren();
  const text = document.createElement('span');
  text.textContent = state.reportLocation ? `${state.reportLocation.lat.toFixed(3)}, ${state.reportLocation.lon.toFixed(3)} · approximate` : 'Choose a spot on the map, or use your current location.';
  const use = document.createElement('button'); use.type = 'button'; use.className = 'text-button'; use.style.marginLeft = '7px'; use.textContent = state.currentLocation ? 'Use my location' : 'Share my location';
  use.addEventListener('click', async () => { try { if (!state.currentLocation) await locate({ center: false }); state.reportLocation = state.currentLocation; text.textContent = `${state.currentLocation.lat.toFixed(3)}, ${state.currentLocation.lon.toFixed(3)} · approximate`; } catch {} });
  const choose = document.createElement('button'); choose.type = 'button'; choose.className = 'text-button'; choose.style.marginLeft = '7px'; choose.textContent = 'Choose on map';
  choose.addEventListener('click', () => {
    state.pickingReportLocation = true;
    closeDialog('report-dialog');
    toast('Tap the map to place this report.');
  });
  $('#report-position').append(text, choose, use); openDialog('report-dialog');
}

async function postReport(event) {
  event.preventDefault();
  if (!state.reportLocation) { toast('Choose a place on the map or share your location first.', 'error'); return; }
  const button = $('#report-form button[type="submit"]'); button.disabled = true;
  try {
    const demo = state.reportMode === 'demo';
    const reporter = $('#demo-reporter').value;
    const result = await api('/api/reports', { method: 'POST', body: JSON.stringify({ lat: state.reportLocation.lat, lon: state.reportLocation.lon, category: $('#report-category').value, note: $('#report-note').value, demo, reporter }) });
    closeDialog('report-dialog'); $('#report-note').value = ''; state.lastMapPoint = null;
    state.demoReportCount = Number(result.demoCount) || state.demoReportCount;
    updateDemoControls();
    if (state.map && currentBounds()) { const latlng = [result.report.lat, result.report.lon]; if (!state.map.getBounds().contains(latlng)) state.map.panTo(latlng); }
    reportFetchAt = 0; await refreshReports();
    if (state.routeOrigin && state.routeDestination) await requestRoutes({ origin: state.routeOrigin, destination: state.routeDestination, mode: state.travelMode });
    toast(demo ? `Practice report from ${reporter} added. It is synthetic and will affect route comparisons until cleared.` : 'Your anonymous note was added. Its location was rounded to about 100 metres.');
  } catch (error) { toast(error.message, 'error'); }
  finally { button.disabled = false; }
}

async function clearDemoReports() {
  const button = $('#clear-demo-reports'); button.disabled = true;
  try {
    const result = await api('/api/demo-reports', { method: 'DELETE' });
    state.demoReportCount = Number(result.demoCount) || 0;
    updateDemoControls();
    reportFetchAt = 0; await refreshReports();
    if (state.routeOrigin && state.routeDestination) await requestRoutes({ origin: state.routeOrigin, destination: state.routeDestination, mode: state.travelMode });
    toast(`${Number(result.deleted) || 0} practice report${Number(result.deleted) === 1 ? '' : 's'} cleared. Routes were refreshed.`);
  } catch (error) { toast(error.message, 'error'); }
  finally { updateDemoControls(); }
}

function setImagePreview(file, image, container) {
  const url = URL.createObjectURL(file); image.src = url; image.hidden = false;
  $('.drop-content', container).hidden = true;
}

function validateImage(file, maxMB = 15) {
  const types = ['image/jpeg', 'image/png', 'image/webp', 'image/avif'];
  if (!types.includes(file.type)) throw new Error('Choose a JPG, PNG, WebP or AVIF image.');
  if (file.size > maxMB * 1024 * 1024) throw new Error(`Choose an image smaller than ${maxMB} MB.`);
}

function validateDeepfakeImage(file, maxMB = 15) {
  if (!['image/jpeg', 'image/png', 'image/webp', 'image/bmp'].includes(file.type)) throw new Error('Choose a JPEG, PNG, WebP or BMP image.');
  if (file.size > maxMB * 1024 * 1024) throw new Error(`Choose an image smaller than ${maxMB} MB.`);
}

async function analyzeDeepfake() {
  if (!state.deepfakeFile) return;
  const progress = $('#model-progress'), status = $('#model-status'), resultBox = $('#deepfake-result'), button = $('#deepfake-run');
  progress.hidden = false; resultBox.hidden = true; button.disabled = true;
  try {
    status.textContent = 'Checking local DeepDefend service…';
    const health = await fetch('/api/deepfake/health');
    const healthInfo = await health.json().catch(() => ({}));
    if (!health.ok || !healthInfo.pretrained_weights) throw new Error(healthInfo.error || 'Start the local DeepDefend service before analyzing an image.');
    status.textContent = 'Analyzing on this computer’s CPU…';
    const form = new FormData(); form.append('image', state.deepfakeFile, state.deepfakeFile.name);
    const response = await fetch('/api/deepfake', { method: 'POST', body: form });
    const output = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(output.error || 'Deepfake analysis failed.');
    const titleText = ({ AUTHENTIC: 'Fewer manipulation artifacts detected', SUSPICIOUS: 'Some manipulation artifacts detected', LIKELY_DEEPFAKE: 'Elevated manipulation artifacts detected', CONFIRMED_DEEPFAKE: 'Strong manipulation artifacts detected' })[output.verdict] || 'Analysis complete';
    resultBox.className = `analysis-result ${output.verdict === 'AUTHENTIC' ? '' : 'result-warn'}`; resultBox.replaceChildren();
    const title = document.createElement('b'); title.textContent = titleText;
    const summary = document.createElement('small'); summary.textContent = `${output.verdict || 'Unknown'} · artifact score ${output.manipulation_score ?? '—'}/100 · ${output.faces_detected ?? 0} face(s) detected`;
    const streams = document.createElement('small'); streams.textContent = `MesoNet spatial ${output.spatial_score ?? '—'} · DCT frequency ${output.frequency_score ?? '—'} · ELA ${output.ela_score ?? '—'} (scores are uncalibrated signals)`;
    const notes = document.createElement('small'); notes.textContent = `${output.forensic_notes || ''} ${output.faces_detected === 0 ? 'No face was detected; the engine analyzed the full image, so facial conclusions are limited.' : ''} ${output.score_notice || 'This result is not proof of authenticity or manipulation.'}`;
    resultBox.append(title, summary, streams, notes);
    if (output.heatmap_base64) { const heatmap = document.createElement('img'); heatmap.src = output.heatmap_base64; heatmap.alt = 'Visualization of image analysis artifacts'; heatmap.className = 'deepfake-heatmap'; resultBox.append(heatmap); }
    resultBox.hidden = false;
  } catch (error) {
    toast(`DeepDefend could not run: ${error.message}`, 'error');
    status.textContent = 'Local service unavailable. Start DeepDefend and try again.';
  } finally { progress.hidden = true; button.disabled = false; }
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b), mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

async function perceptualHash(imageSource) {
  let bitmap;
  try { bitmap = imageSource instanceof Blob ? await createImageBitmap(imageSource) : await createImageBitmap(imageSource); }
  catch { throw new Error('This image could not be decoded by your browser.'); }
  const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 32;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(bitmap, 0, 0, 32, 32); bitmap.close?.();
  const { data } = context.getImageData(0, 0, 32, 32);
  const gray = new Float64Array(1024);
  for (let index = 0; index < 1024; index++) gray[index] = .299 * data[index * 4] + .587 * data[index * 4 + 1] + .114 * data[index * 4 + 2];
  const coefficients = [];
  for (let u = 0; u < 8; u++) for (let v = 0; v < 8; v++) {
    let sum = 0;
    for (let x = 0; x < 32; x++) for (let y = 0; y < 32; y++) {
      sum += gray[x * 32 + y] * Math.cos(((2 * x + 1) * u * Math.PI) / 64) * Math.cos(((2 * y + 1) * v * Math.PI) / 64);
    }
    coefficients.push(sum);
  }
  const cut = median(coefficients.slice(1));
  let bits = 0n;
  coefficients.forEach((value, index) => { if (index > 0 && value > cut) bits |= 1n << BigInt(index); });
  return bits.toString(16).padStart(16, '0');
}

function setReferenceFile(file) {
  try { validateImage(file); } catch (error) { toast(error.message, 'error'); return; }
  state.referenceFile = file; state.referenceHash = null;
  $('#hash-file-label').textContent = `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MB`;
  $('#hash-scan').disabled = false;
}

function extractImageSource(url) {
  return `/api/hash/image?url=${encodeURIComponent(url)}`;
}

async function scanWebsite() {
  const site = $('#scan-site').value.trim();
  if (!state.referenceFile) { toast('Choose a reference image first.', 'error'); return; }
  if (!site) { toast('Enter a public web page to scan.', 'error'); return; }
  try { new URL(site); } catch { toast('Enter a full website address, including https://.', 'error'); return; }
  const progress = $('#hash-progress'), status = $('#hash-status'), resultBox = $('#hash-results'), button = $('#hash-scan');
  progress.hidden = false; resultBox.hidden = true; button.disabled = true;
  try {
    status.textContent = 'Creating a reference fingerprint in your browser…';
    state.referenceHash ||= await perceptualHash(state.referenceFile);
    status.textContent = 'Scanning up to eight pages on the selected website…';
    const crawl = await api('/api/hash/crawl', { method: 'POST', body: JSON.stringify({ url: site }) });
    const assets = crawl.assets || [];
    if (!assets.length) throw new Error('No same-site images could be found. The page may block automated requests or use a separate image host.');
    const indexed = [], concurrency = 3; let cursor = 0, completed = 0, errors = 0;
    async function worker() {
      while (cursor < assets.length) {
        const asset = assets[cursor++];
        try {
          const blob = await api(extractImageSource(asset.url));
          const hash = await perceptualHash(blob);
          indexed.push({ url: asset.url, hash });
        } catch { errors++; }
        completed++;
        status.textContent = `Comparing images on ${crawl.scope} · ${completed} of ${assets.length}`;
      }
    }
    await Promise.all(Array.from({ length: Math.min(concurrency, assets.length) }, worker));
    const results = await api('/api/hash/search', { method: 'POST', body: JSON.stringify({ targetHash: state.referenceHash, images: indexed }) });
    resultBox.replaceChildren();
    const title = document.createElement('strong'); title.textContent = results.matches.length ? `${results.matches.length} visually similar image${results.matches.length === 1 ? '' : 's'} found` : 'No close matches found'; resultBox.append(title);
    const summary = document.createElement('p'); summary.textContent = `Checked ${completed} image${completed === 1 ? '' : 's'} across ${crawl.pagesScanned} same-site page${crawl.pagesScanned === 1 ? '' : 's'} on ${crawl.scope}. ${errors ? `${errors} image${errors === 1 ? '' : 's'} could not be analyzed. ` : ''}The local index contains ${results.compared} image fingerprint${results.compared === 1 ? '' : 's'}.`; resultBox.append(summary);
    for (const match of results.matches) {
      const row = document.createElement('div'); row.className = 'match-item';
      const link = document.createElement('a'); link.href = match.url; link.target = '_blank'; link.rel = 'noreferrer'; link.textContent = match.url;
      const detail = document.createElement('small'); detail.textContent = `Perceptual distance ${match.distance}/64 · ${new Date(match.created_at).toLocaleDateString()}`;
      row.append(link, detail); resultBox.append(row);
    }
    resultBox.hidden = false;
    $('#hash-clear').hidden = results.compared === 0;
    if (crawl.capped) toast('The scan reached its page or image limit. This is a focused website check, not a full-web search.');
    else toast(`Checked ${completed} images from ${crawl.scope}.`);
  } catch (error) { toast(error.message, 'error'); status.textContent = 'Scan stopped. You can correct the website address and try again.'; }
  finally { progress.hidden = true; button.disabled = false; }
}

async function clearHashIndex() {
  if (!window.confirm('Clear all image fingerprints and source links saved by this Kaali server? This cannot be undone.')) return;
  try {
    await api('/api/hash/index', { method: 'DELETE' });
    $('#hash-results').hidden = true; $('#hash-clear').hidden = true; state.referenceHash = null;
    toast('The local image fingerprint index has been cleared.');
  } catch (error) { toast(error.message, 'error'); }
}

function openCaptureDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('saheli-private-evidence', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('captures', { keyPath: 'id', autoIncrement: true });
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error || new Error('Private evidence storage is unavailable.'));
  });
}

async function saveCapture(blob) {
  const database = await openCaptureDb();
  try { return await new Promise((resolve, reject) => { const request = database.transaction('captures', 'readwrite').objectStore('captures').add({ blob, createdAt: new Date().toISOString() }); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); }); }
  finally { database.close(); }
}

async function listCaptures() {
  const database = await openCaptureDb();
  try { return await new Promise((resolve, reject) => { const request = database.transaction('captures', 'readonly').objectStore('captures').getAll(); request.onsuccess = () => resolve(request.result || []); request.onerror = () => reject(request.error); }); }
  finally { database.close(); }
}

async function removeAllCaptures() {
  const database = await openCaptureDb();
  try { await new Promise((resolve, reject) => { const request = database.transaction('captures', 'readwrite').objectStore('captures').clear(); request.onsuccess = resolve; request.onerror = () => reject(request.error); }); }
  finally { database.close(); }
  await renderEvidence(); toast('All local captures were deleted.');
}

async function renderEvidence() {
  const gallery = $('#evidence-gallery'); if (!gallery) return;
  try {
    const captures = await listCaptures();
    for (const url of state.evidenceUrls || []) URL.revokeObjectURL(url);
    state.evidenceUrls = []; gallery.replaceChildren(); $('#delete-captures').hidden = !captures.length;
    if (!captures.length) {
      const empty = document.createElement('div'); empty.className = 'gallery-empty';
      for (const [tag, value] of [['span', '✳'], ['b', 'No captures saved'], ['small', 'A photo burst appears here after an SOS while capture is armed.']]) { const item = document.createElement(tag); item.textContent = value; empty.append(item); }
      gallery.append(empty); return;
    }
    for (const capture of captures.slice(-12).reverse()) {
      const thumb = document.createElement('div'); thumb.className = 'capture-thumb';
      const image = document.createElement('img'); image.alt = 'Private camera capture'; image.src = URL.createObjectURL(capture.blob); state.evidenceUrls.push(image.src);
      const link = document.createElement('a'); link.href = image.src; link.download = `kaali-capture-${new Date(capture.createdAt).toISOString().replaceAll(':', '-')}.jpg`; link.textContent = new Date(capture.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      thumb.append(image, link); gallery.append(thumb);
    }
  } catch (error) { toast(`Local capture storage is unavailable: ${error.message}`, 'error'); }
}

async function turnCameraOn() {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access needs a secure browser connection (HTTPS or localhost).');
  const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: 'user' }, width: { ideal: 1280 }, height: { ideal: 720 } } });
  state.cameraStream = stream; state.cameraArmed = true;
  const video = $('#camera-video'); video.srcObject = stream; video.hidden = false;
  $('#camera-placeholder').hidden = true; $('#camera-live-label').hidden = false;
  $('#camera-state').innerHTML = '<span class="status-dot green"></span>CAMERA ARMED';
  $('#camera-toggle').hidden = true; $('#camera-stop').hidden = false;
  $('#camera-stop').textContent = 'Turn camera off · disarm capture ×';
  toast('Camera is armed. Five photos save locally if you trigger SOS.');
}

function turnCameraOff() {
  if (state.cameraStream) state.cameraStream.getTracks().forEach(track => track.stop());
  state.cameraStream = null; state.cameraArmed = false;
  const video = $('#camera-video'); if (video) { video.srcObject = null; video.hidden = true; }
  $('#camera-placeholder').hidden = false; $('#camera-live-label').hidden = true;
  $('#camera-state').innerHTML = '<span class="status-dot"></span>CAMERA OFF';
  $('#camera-toggle').hidden = false; $('#camera-stop').hidden = true;
}

function canvasSnapshot(video) {
  return new Promise((resolve, reject) => {
    if (!video.videoWidth || !video.videoHeight) { reject(new Error('The camera is still starting.')); return; }
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 1440 / video.videoWidth); canvas.width = Math.round(video.videoWidth * scale); canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not capture a camera frame.')), 'image/jpeg', .84);
  });
}

async function takePhotoBurst() {
  if (!state.cameraArmed || state.isCapturing) return;
  state.isCapturing = true;
  const notice = $('#burst-notice'); notice.hidden = false; notice.textContent = 'SOS capture started · saving five photos on this device…';
  const video = $('#camera-video');
  try {
    for (let index = 0; index < 5; index++) {
      if (!state.cameraArmed || !state.cameraStream) break;
      const blob = await canvasSnapshot(video); await saveCapture(blob);
      notice.textContent = `SOS capture · ${index + 1} of 5 photos saved locally…`;
      if (index < 4) await sleep(320);
    }
    await renderEvidence(); notice.textContent = 'Capture complete · photos saved on this device only.';
  } finally { state.isCapturing = false; }
}

function bindEvents() {
  $$('.nav-item').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
  $$('[data-view="contacts"]').forEach(button => button.addEventListener('click', () => setView('contacts')));
  $('#route-form').addEventListener('submit', onRouteSubmit);
  $('#travel-mode').addEventListener('change', async event => {
    const mode = event.target.value;
    state.travelMode = mode;
    $('#route-mode-label').textContent = modeLabel(mode);
    clearRouteResults(`Travel mode changed to ${modeLabel(mode)}. Updating routes…`);
    if (state.routeOrigin && state.routeDestination) await requestRoutes({ origin: state.routeOrigin, destination: state.routeDestination, mode });
  });
  $('#origin-input').addEventListener('focus', () => { state.activeWaypoint = 'origin'; });
  $('#destination-input').addEventListener('focus', () => { state.activeWaypoint = 'destination'; });
  $('#origin-input').addEventListener('input', () => onLocationInput('origin'));
  $('#destination-input').addEventListener('input', () => onLocationInput('destination'));
  $('#origin-here').addEventListener('click', async () => { try { await locate({ updateOrigin: true }); state.originInputValue = 'Current location'; } catch {} });
  $('#map-locate').addEventListener('click', async () => { try { await locate({ updateOrigin: true }); state.originInputValue = 'Current location'; } catch {} });
  $('#nearby-services').addEventListener('click', loadNearbyServices);
  $('#map-report').addEventListener('click', () => openReportDialog());
  $('#community-report').addEventListener('click', () => openReportDialog());
  $('#add-demo-report').addEventListener('click', () => openReportDialog({ demo: true }));
  $('#clear-demo-reports').addEventListener('click', clearDemoReports);
  $('#report-form').addEventListener('submit', postReport);
  $('#sos-sidebar').addEventListener('click', openSOS);
  $('#sos-send').addEventListener('click', sendSos);
  $('#sos-copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(buildSosMessage()); toast('SOS message copied to this device’s clipboard.'); }
    catch { toast('Clipboard access is unavailable in this browser.', 'error'); }
  });
  $('#sos-recipient').addEventListener('change', event => {
    state.selectedContact = state.contacts.find(contact => contact.id === event.target.value) || state.contacts[0] || null;
    renderSosContactPreview();
  });
  $('#sos-call').addEventListener('click', callEmergency);
  $('#sos-locate').addEventListener('click', () => state.currentLocation ? updateSosLocation(true) : locate({ center: false }).then(() => updateSosLocation(true)).catch(() => {}));
  $('#call-emergency').addEventListener('click', callEmergency);
  $('#emergency-number').addEventListener('change', event => updateEmergencyNumber(event.target.value));
  $('#contact-form').addEventListener('submit', event => {
    event.preventDefault();
    const name = $('#contact-name').value.trim();
    const rawPhone = $('#contact-phone').value.trim().replace(/[\s().-]/g, '');
    const digits = rawPhone.replace(/\D/g, '');
    const phone = /^[6-9]\d{9}$/.test(digits) ? `+91${digits}`
      : digits.length === 12 && digits.startsWith('91') ? `+${digits}`
        : rawPhone;
    if (!name) { toast('Add a name for your trusted contact.', 'error'); return; }
    if (!/^\+[1-9]\d{7,14}$/.test(phone)) { toast('Enter a 10-digit Indian mobile number, or an international number with its country code.', 'error'); return; }
    if (state.contacts.some(contact => contact.phone === phone)) { toast('That number is already in your trusted circle.', 'error'); return; }
    if (state.contacts.length >= 3) { toast('You can keep up to three trusted contacts on this device.', 'error'); return; }
    state.contacts.push({ id: crypto.randomUUID(), name, phone }); saveContacts(); renderContacts(); event.target.reset(); toast(`${name} was added to your trusted circle.`);
  });
  $$('.timer-row button[data-minutes]').forEach(button => button.addEventListener('click', () => {
    $$('.timer-row button[data-minutes]').forEach(item => item.classList.remove('selected')); button.classList.add('selected'); state.selectedTimer = Number(button.dataset.minutes);
  }));
  $('#timer-start').addEventListener('click', () => startCheckinTimer(state.selectedTimer || 30));
  $('#checkin-done').addEventListener('click', () => stopCheckinTimer(false));
  $('#privacy-info').addEventListener('click', () => openDialog('privacy-dialog'));
  ['privacy-info-footer', 'privacy-info-protection', 'privacy-info-evidence', 'privacy-info-contacts'].forEach(id => document.getElementById(id)?.addEventListener('click', () => openDialog('privacy-dialog')));
  $$('[data-close]').forEach(button => button.addEventListener('click', () => closeDialog(button.dataset.close)));
  $$('.modal').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); }));
  $('#mobile-menu').addEventListener('click', () => { $('#sidebar').classList.add('open'); $('#scrim').classList.add('open'); });
  $('#scrim').addEventListener('click', () => { $('#sidebar').classList.remove('open'); $('#scrim').classList.remove('open'); });
  $('#deepfake-browse').addEventListener('click', event => { event.preventDefault(); $('#deepfake-file').click(); });
  $('#deepfake-file').addEventListener('change', event => {
    const file = event.target.files[0]; if (!file) return;
    try { validateDeepfakeImage(file); } catch (error) { toast(error.message, 'error'); return; }
    state.deepfakeFile = file; setImagePreview(file, $('#deepfake-preview'), $('#deepfake-drop')); $('#deepfake-run').disabled = false; $('#deepfake-result').hidden = true;
  });
  $('#deepfake-drop').addEventListener('click', event => { if (event.target.closest('button')) return; $('#deepfake-file').click(); });
  $('#deepfake-drop').addEventListener('dragover', event => { event.preventDefault(); $('#deepfake-drop').classList.add('dragging'); });
  $('#deepfake-drop').addEventListener('dragleave', () => $('#deepfake-drop').classList.remove('dragging'));
  $('#deepfake-drop').addEventListener('drop', event => { event.preventDefault(); $('#deepfake-drop').classList.remove('dragging'); const file = event.dataTransfer.files[0]; if (!file) return; try { validateDeepfakeImage(file); } catch (error) { toast(error.message, 'error'); return; } state.deepfakeFile = file; setImagePreview(file, $('#deepfake-preview'), $('#deepfake-drop')); $('#deepfake-run').disabled = false; $('#deepfake-result').hidden = true; });
  $('#deepfake-run').addEventListener('click', analyzeDeepfake);
  $('#hash-file').addEventListener('change', event => { const file = event.target.files[0]; if (file) setReferenceFile(file); });
  $('#hash-scan').addEventListener('click', scanWebsite);
  $('#hash-clear').addEventListener('click', clearHashIndex);
  $('#camera-toggle').addEventListener('click', async () => { try { await turnCameraOn(); } catch (error) { toast(`Camera could not be armed: ${error.message}`, 'error'); } });
  $('#camera-stop').addEventListener('click', turnCameraOff);
  $('#delete-captures').addEventListener('click', removeAllCaptures);
  window.addEventListener('pagehide', () => { if (!state.navigation && state.cameraStream) turnCameraOff(); });
}

async function initialize() {
  const now = new Date();
  $('#today-label').textContent = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' }).format(now);
  $('#journey-clock').textContent = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(now);
  bindEvents(); initMap(); renderContacts(); updateEmergencyNumber(state.emergencyNumber); renderEvidence();
  try { await api('/api/health'); $('#connection-status').textContent = 'Kaali is ready'; }
  catch { $('#connection-status').textContent = 'Local server unavailable'; $('.connection').classList.add('offline'); }
  const savedDeadline = Number(localStorage.getItem('saheli.checkin'));
  if (Number.isFinite(savedDeadline) && savedDeadline > 0) { if (savedDeadline <= Date.now()) stopCheckinTimer(true); else startCheckinTimer(Math.ceil((savedDeadline - Date.now()) / 60_000)); state.checkinDeadline = savedDeadline; tickCheckin(); }
  window.addEventListener('resize', () => state.map?.invalidateSize());
  state.reportRefreshInterval = setInterval(() => { if (state.view === 'dashboard') refreshReports(); }, 45_000);
}

initialize();
