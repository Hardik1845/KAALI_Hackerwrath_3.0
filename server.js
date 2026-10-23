import { createServer } from 'node:http';
import { DatabaseSync } from 'node:sqlite';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { isIP } from 'node:net';
import { lookup } from 'node:dns/promises';
import { createHash, randomUUID } from 'node:crypto';
import { evaluateRoutes } from './route-model.js';
import { resolveRouteMode, ROUTE_MODES } from './route-modes.js';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(ROOT, 'public');
const DATA = path.join(ROOT, '.data');
try { process.loadEnvFile(path.join(ROOT, '.env')); } catch (error) { if (error.code !== 'ENOENT') throw error; }
await mkdir(DATA, { recursive: true });
const db = new DatabaseSync(path.join(DATA, 'saheli.sqlite'));
db.exec(`
  PRAGMA journal_mode = WAL;
  CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL, category TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0, reporter TEXT NOT NULL DEFAULT ''
  );
  CREATE INDEX IF NOT EXISTS reports_created ON reports(created_at);

`);
const reportColumns = new Set(db.prepare('PRAGMA table_info(reports)').all().map(column => column.name));
if (!reportColumns.has('is_demo')) db.exec('ALTER TABLE reports ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0');
if (!reportColumns.has('reporter')) db.exec("ALTER TABLE reports ADD COLUMN reporter TEXT NOT NULL DEFAULT ''");
db.prepare('DELETE FROM reports WHERE is_demo = 0 AND created_at < ?').run(new Date(Date.now() - 30 * 24 * 3600_000).toISOString());

const PORT = Number(process.env.PORT || 4173);
const HOST = process.env.HOST || '127.0.0.1';
const SOS_SERVICE_URL = String(process.env.SOS_SERVICE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '');
const SOS_SERVICE_API_KEY = String(process.env.SOS_SERVICE_API_KEY || '').trim();
const DEEPFAKE_SERVICE_URL = String(process.env.DEEPFAKE_SERVICE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const HASH_SHIELD_SERVICE_URL = String(process.env.HASH_SHIELD_SERVICE_URL || 'http://127.0.0.1:8002').replace(/\/$/, '');
const HASH_SHIELD_API_KEY = String(process.env.HASH_SHIELD_API_KEY || '').trim();
const MAX_JSON = 1_200_000;
const MAX_DEEPFAKE_UPLOAD = 15 * 1024 * 1024 + 1024 * 1024;
const MAX_HASH_SHIELD_UPLOAD = 10 * 1024 * 1024;
const categories = new Set(['harassment', 'following', 'poor_lighting', 'unsafe_path', 'help_available', 'other']);
const demoReporters = new Set(Array.from({ length: 10 }, (_, index) => `Demo user ${String.fromCharCode(65 + index)}`));
const seriousCategories = new Set(['harassment', 'following', 'unsafe_path']);
const reportLabels = {
  harassment: 'Harassment reported', following: 'Someone may be followed', poor_lighting: 'Poorly lit area',
  unsafe_path: 'Unsafe path or blocked route', help_available: 'Help offered here', other: 'Other concern'
};
const mime = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.webmanifest': 'application/manifest+json'
};
let lastGeocode = 0;

function send(res, status, value, headers = {}) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...headers });
  res.end(JSON.stringify(value));
}

async function readJson(req, limit = MAX_JSON) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw Object.assign(new Error('Request is too large.'), { status: 413 });
    chunks.push(chunk);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'); }
  catch { throw Object.assign(new Error('Request body must be valid JSON.'), { status: 400 }); }
}

async function readBuffer(req, limit) {
  const chunks = []; let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw Object.assign(new Error('Image upload is too large (15 MB maximum).'), { status: 413 });
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function validCoord(lat, lon) {
  return Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
}

function normalizeContactPhone(value) {
  const raw = String(value || '').trim().replace(/[\s().-]/g, '');
  const digits = raw.replace(/\D/g, '');
  if (/^[6-9]\d{9}$/.test(digits)) return `+91${digits}`;
  if (digits.length === 12 && digits.startsWith('91') && /^[6-9]\d{9}$/.test(digits.slice(2))) return `+${digits}`;
  if (/^\+[1-9]\d{7,14}$/.test(raw)) return raw;
  return raw;
}

function distanceMeters(a, b) {
  const rad = n => n * Math.PI / 180;
  const dLat = rad(b.lat - a.lat), dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 6_371_000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function decodePolyline(encoded, precision = 6) {
  let index = 0, lat = 0, lon = 0;
  const coordinates = [];
  const factor = 10 ** precision;
  while (index < encoded.length) {
    let result = 0, shift = 0, byte;
    do { byte = encoded.charCodeAt(index++) - 63; result |= (byte & 0x1f) << shift; shift += 5; } while (byte >= 0x20 && index < encoded.length);
    lat += result & 1 ? ~(result >> 1) : result >> 1;
    result = 0; shift = 0;
    do { byte = encoded.charCodeAt(index++) - 63; result |= (byte & 0x1f) << shift; shift += 5; } while (byte >= 0x20 && index < encoded.length);
    lon += result & 1 ? ~(result >> 1) : result >> 1;
    coordinates.push({ lat: lat / factor, lon: lon / factor });
  }
  return coordinates;
}

function bboxFor(points, margin = 0.004) {
  const lats = points.map(p => p.lat), lons = points.map(p => p.lon);
  return {
    south: Math.max(-90, Math.min(...lats) - margin), west: Math.max(-180, Math.min(...lons) - margin),
    north: Math.min(90, Math.max(...lats) + margin), east: Math.min(180, Math.max(...lons) + margin)
  };
}

function getReportsInBox(box, hours = 24, limit = 300) {
  const since = new Date(Date.now() - hours * 3600_000).toISOString();
  return db.prepare(`SELECT id, lat, lon, category, note, created_at, is_demo, reporter FROM reports
    WHERE (created_at >= ? OR is_demo = 1) AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
    ORDER BY created_at DESC LIMIT ?`).all(since, box.south, box.north, box.west, box.east, limit);
}

function countDemoReports() {
  return Number(db.prepare('SELECT COUNT(*) AS count FROM reports WHERE is_demo = 1').get().count) || 0;
}

function sampleRoute(points, count = 18) {
  if (points.length <= count) return points;
  const distances = [0];
  let total = 0;
  for (let i = 1; i < points.length; i++) { total += distanceMeters(points[i - 1], points[i]); distances.push(total); }
  if (total < 1) return [points[0]];
  const samples = [];
  for (let target = 0; target <= total && samples.length < count; target += total / (count - 1)) {
    let i = 1;
    while (i < distances.length && distances[i] < target) i++;
    const start = points[Math.max(0, i - 1)], end = points[Math.min(i, points.length - 1)];
    const span = distances[i] - distances[Math.max(0, i - 1)];
    const ratio = span ? (target - distances[Math.max(0, i - 1)]) / span : 0;
    samples.push({ lat: start.lat + (end.lat - start.lat) * ratio, lon: start.lon + (end.lon - start.lon) * ratio });
  }
  return samples;
}

function metersToSegment(point, a, b) {
  const scale = Math.cos(point.lat * Math.PI / 180);
  const px = point.lon * scale, py = point.lat, ax = a.lon * scale, ay = a.lat, bx = b.lon * scale, by = b.lat;
  const dx = bx - ax, dy = by - ay, denom = dx * dx + dy * dy;
  const t = denom ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / denom)) : 0;
  return Math.hypot((py - ay - t * dy) * 111_320, (px - ax - t * dx) * 111_320);
}

function reportWeight(report, now = Date.now()) {
  if (Number(report.is_demo) === 1) return 1;
  const relevance = { harassment: 1, following: 1, unsafe_path: 0.85, poor_lighting: 0.7, other: 0.55 }[report.category] || 0;
  const ageHours = Math.max(0, (now - Date.parse(report.created_at)) / 3_600_000);
  return relevance * Math.max(0, 1 - ageHours / 12);
}

function routeReportSegments(points, reports, available) {
  const count = Math.min(6, Math.max(1, points.length - 1));
  const segments = [];
  for (let index = 0; index < count; index++) {
    const start = Math.floor(index * (points.length - 1) / count);
    const end = Math.floor((index + 1) * (points.length - 1) / count);
    segments.push({ points: points.slice(start, Math.max(start + 2, end + 1)), recentConcernCount: 0, weightedConcern: 0, reportStatus: available ? 'no_report_found' : 'unavailable' });
  }
  for (const report of reports) {
    let nearestIndex = -1, nearestDistance = 160;
    for (let i = 0; i < points.length; i++) {
      const distance = distanceMeters(points[i], report);
      if (distance < nearestDistance) { nearestDistance = distance; nearestIndex = i; }
    }
    if (nearestIndex < 0 || report.category === 'help_available') continue;
    const segmentIndex = Math.min(count - 1, Math.floor(nearestIndex / Math.max(1, points.length - 1) * count));
    segments[segmentIndex].recentConcernCount++;
    segments[segmentIndex].weightedConcern += reportWeight(report);
    segments[segmentIndex].reportStatus = 'concern_report_found';
  }
  return segments;
}

async function addMappedRoadSignals(routes) {
  const samplesByRoute = routes.map(route => sampleRoute(route.points));
  const samples = samplesByRoute.flat();
  if (!samples.length || samples.length > 60) { routes.forEach(r => { r.mapDataAvailable = false; }); return; }
  const query = `[out:json][timeout:18];(${samples.map(point => `way["highway"](around:65,${point.lat.toFixed(5)},${point.lon.toFixed(5)});`).join('')});out geom tags;`;
  try {
    const response = await fetch('https://overpass.kumi.systems/api/interpreter', {
      method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded;charset=UTF-8', 'user-agent': 'KaaliSafety/1.0 (user-requested route context lookup)' },
      body: new URLSearchParams({ data: query }), signal: AbortSignal.timeout(19_000)
    });
    if (!response.ok) { routes.forEach(r => { r.mapDataAvailable = false; }); return; }
    const data = await response.json();
    const roadSegments = [];
    for (const way of data.elements || []) {
      if (!Array.isArray(way.geometry) || way.geometry.length < 2 || way.geometry.length > 1500) continue;
      const tags = way.tags || {};
      for (let i = 1; i < way.geometry.length; i++) roadSegments.push({ a: way.geometry[i - 1], b: way.geometry[i], tags });
    }
    routes.forEach((route, index) => {
      let lit = 0, unlit = 0, sidewalk = 0, mapped = 0, sidewalkKnown = 0;
      for (const point of samplesByRoute[index]) {
        let nearest = null, nearestDistance = 65;
        for (const segment of roadSegments) {
          const distance = metersToSegment(point, segment.a, segment.b);
          if (distance < nearestDistance) { nearest = segment; nearestDistance = distance; }
        }
        if (!nearest) continue;
        mapped++;
        const tags = nearest.tags;
        if (/^(yes|automatic|24\/7|sunset-to-sunrise)$/i.test(tags.lit || '')) lit++;
        else if (/^no$/i.test(tags.lit || '')) unlit++;
        if (typeof tags.sidewalk === 'string') sidewalkKnown++;
        if (/^(yes|both|left|right)$/i.test(tags.sidewalk || '') || ['footway', 'pedestrian', 'living_street'].includes(tags.highway)) sidewalk++;
      }
      const total = samplesByRoute[index].length;
      route.lighting = { mapped: lit + unlit, lit, unlit, coverage: total ? (lit + unlit) / total : 0, litShare: (lit + unlit) ? lit / (lit + unlit) : null };
      route.pedestrian = { mappedPositive: sidewalk, known: sidewalkKnown, coverage: total ? sidewalkKnown / total : 0, positiveShare: sidewalkKnown ? sidewalk / sidewalkKnown : null };
      route.infrastructureCoverage = total ? mapped / total : null;
      route.mapDataAvailable = true;
    });
  } catch {
    routes.forEach(r => { r.mapDataAvailable = false; });
    // A public map-data endpoint can be unavailable; routing still works and the UI reports the missing context.
  }
}

function routeOptionsFor(route) {
  const encoded = route?.trip?.legs?.[0]?.shape;
  const summary = route?.trip?.summary;
  if (typeof encoded !== 'string' || !encoded || !summary || !Number.isFinite(Number(summary.length)) || Number(summary.length) <= 0 || !Number.isFinite(Number(summary.time)) || Number(summary.time) < 0) return null;
  let points;
  try { points = decodePolyline(encoded); } catch { return null; }
  if (!points.length || points.some(p => !validCoord(p.lat, p.lon))) return null;
  const box = bboxFor(points, 0.003);
  let reports = [], reportsAvailable = true;
  try { reports = getReportsInBox(box, 12, 300); } catch { reportsAvailable = false; }
  const nearby = reports.filter(report => points.some((point, index) => {
    if (index % 2 !== 0 && index !== points.length - 1) return false;
    return distanceMeters({ lat: point.lat, lon: point.lon }, { lat: report.lat, lon: report.lon }) <= 160;
  }));
  const uniq = [...new Map(nearby.map(item => [item.id, item])).values()];
  const concernReports = uniq.filter(r => r.category !== 'help_available');
  const segments = routeReportSegments(points, concernReports, reportsAvailable);
  const weightedConcern = concernReports.reduce((total, report) => total + reportWeight(report), 0);
  const concernCounts = new Map();
  for (const report of concernReports) concernCounts.set(report.category, (concernCounts.get(report.category) || 0) + 1);
  const seriousCount = concernReports.filter(report => seriousCategories.has(report.category)).length;
  const cautionCount = concernReports.length - seriousCount;
  const riskReasons = [...concernCounts].map(([category, count]) => {
    const matching = concernReports.filter(report => report.category === category);
    return {
      category, label: reportLabels[category] || 'Other concern', count,
      demoCount: matching.filter(report => Number(report.is_demo) === 1).length,
      demoReporters: [...new Set(matching.filter(report => Number(report.is_demo) === 1).map(report => report.reporter).filter(Boolean))]
    };
  });
  const lengthKm = Number(summary.length);
  return {
    id: createHash('sha256').update(encoded).digest('hex').slice(0, 16), points, segments, summary: route.trip.summary, maneuvers: route.trip.legs[0].maneuvers || [],
    reports: uniq, reportsAvailable, recentConcernCount: concernReports.length, seriousCount, cautionCount, riskReasons,
    weightedConcern, reportExposurePerKm: lengthKm > 0 ? weightedConcern / lengthKm : null,
    supportCount: uniq.filter(r => r.category === 'help_available').length,
    lighting: { mapped: 0, lit: 0, unlit: 0, coverage: null, litShare: null }, pedestrian: { mappedPositive: 0, known: 0, coverage: null, positiveShare: null }, infrastructureCoverage: null, mapDataAvailable: false
  };
}

async function getModeTime(origin, destination, mode) {
  try {
    const response = await fetch('https://valhalla1.openstreetmap.de/route', {
      method: 'POST', headers: { 'content-type': 'application/json', 'X-Client-Id': 'kaali-safety-local' },
      body: JSON.stringify({ locations: [origin, destination], costing: ROUTE_MODES[mode].costing, units: 'kilometers', language: 'en-IN', directions_type: 'instructions' }),
      signal: AbortSignal.timeout(20_000)
    });
    if (!response.ok) return { available: false, distanceKm: null, durationSeconds: null };
    const payload = await response.json();
    const summary = payload?.trip?.summary;
    if (!summary || !Number.isFinite(Number(summary.length)) || Number(summary.length) <= 0 || !Number.isFinite(Number(summary.time)) || Number(summary.time) <= 0) return { available: false, distanceKm: null, durationSeconds: null };
    return { available: true, distanceKm: Number(summary.length), durationSeconds: Number(summary.time) };
  } catch { return { available: false, distanceKm: null, durationSeconds: null }; }
}

async function handleApi(req, res, url) {
  if (url.pathname.startsWith('/api/hashshield/v1/')) {
    const upstreamPath = `/v1/${url.pathname.slice('/api/hashshield/v1/'.length)}`;
    const allowedPath = /^\/v1\/(?:scan|hash|vault|match|jobs\/due|cases(?:\/[A-Za-z0-9_-]+(?:\/(?:lookup|notices|sent|check|resolve))?)?)$/.test(upstreamPath);
    if (!allowedPath || !['GET', 'POST'].includes(req.method)) return send(res, 404, { error: 'Hash Shield API route not found.' });
    if (!HASH_SHIELD_API_KEY) return send(res, 503, { error: 'Hash Shield API key is not configured. Set HASH_SHIELD_API_KEY in the project .env file.' });
    try {
      let body;
      const headers = { 'X-API-Key': HASH_SHIELD_API_KEY };
      if (req.method === 'POST') {
        const type = String(req.headers['content-type'] || '');
        if (!type.toLowerCase().startsWith('application/json') && !type.toLowerCase().startsWith('multipart/form-data;')) return send(res, 415, { error: 'Hash Shield requests must use JSON or multipart form data.' });
        headers['content-type'] = type;
        body = await readBuffer(req, MAX_HASH_SHIELD_UPLOAD + 100_000);
      }
      const upstream = await fetch(`${HASH_SHIELD_SERVICE_URL}${upstreamPath}${url.search}`, {
        method: req.method, headers, ...(body ? { body } : {}), signal: AbortSignal.timeout(120_000)
      });
      const result = await upstream.text();
      return res.writeHead(upstream.status, {
        'content-type': upstream.headers.get('content-type') || 'application/json; charset=utf-8',
        'cache-control': 'no-store', 'x-content-type-options': 'nosniff'
      }).end(result);
    } catch (error) {
      const status = error.status || (error.name === 'TimeoutError' ? 504 : 503);
      return send(res, status, { error: status === 504 ? 'Hash Shield request timed out.' : error.status ? error.message : 'Hash Shield is unavailable. Start it on port 8002.' });
    }
  }
  if (req.method === 'GET' && url.pathname === '/api/hash/web-search/health') {
    try {
      const response = await fetch(`${HASH_SHIELD_SERVICE_URL}/health`, { signal: AbortSignal.timeout(2500) });
      const service = await response.json();
      return send(res, response.ok ? 200 : 503, { ...service, ok: response.ok });
    } catch { return send(res, 503, { ok: false, error: 'Hash Shield is unavailable. Start it on port 8002.' }); }
  }
  if (req.method === 'POST' && url.pathname === '/api/hash/web-search') {
    if (!HASH_SHIELD_API_KEY) return send(res, 503, { error: 'Hash Shield API key is not configured. Set HASH_SHIELD_API_KEY in the project .env file.' });
    const contentType = String(req.headers['content-type'] || '').toLowerCase();
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(contentType)) return send(res, 415, { error: 'Choose a JPEG, PNG or WebP image for web search.' });
    const isMinor = url.searchParams.get('is_minor') === 'true';
    const intimate = url.searchParams.get('intimate') === 'true';
    if (!intimate && url.searchParams.get('web_consent') !== 'true') return send(res, 400, { error: 'Confirm that you want this non-intimate image sent to the configured web search provider.' });
    try {
      const bytes = await readBuffer(req, MAX_HASH_SHIELD_UPLOAD);
      if (!bytes.length) return send(res, 400, { error: 'The selected image is empty.' });
      const rawName = String(req.headers['x-image-name'] || 'reference-image').slice(0, 180);
      const filename = rawName.replace(/[\\/\r\n"\0]/g, '_') || 'reference-image';
      const form = new FormData();
      form.append('file', new Blob([bytes], { type: contentType }), filename);
      form.append('consent', 'true');
      form.append('intimate', String(intimate));
      form.append('is_minor', String(isMinor));
      const response = await fetch(`${HASH_SHIELD_SERVICE_URL}/v1/scan`, {
        method: 'POST', headers: { 'X-API-Key': HASH_SHIELD_API_KEY }, body: form,
        signal: AbortSignal.timeout(90_000)
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) return send(res, response.status, { error: result.detail || result.error || 'Hash Shield web search failed.' });
      return send(res, 200, result);
    } catch (error) {
      const status = error.status || (error.name === 'TimeoutError' ? 504 : 503);
      return send(res, status, { error: status === 504 ? 'Web image search timed out. Try again with a smaller image.' : error.status ? error.message : 'Hash Shield is unavailable. Start it on port 8002.' });
    }
  }
  if (req.method === 'GET' && url.pathname === '/api/deepfake/health') {
    try {
      const response = await fetch(`${DEEPFAKE_SERVICE_URL}/health`, { signal: AbortSignal.timeout(2500) });
      const service = await response.json();
      return send(res, response.ok ? 200 : 503, { ...service, ok: response.ok });
    } catch { return send(res, 503, { ok: false, error: 'Local DeepDefend service is unavailable. Start it on port 8000.' }); }
  }
  if (req.method === 'POST' && url.pathname === '/api/deepfake') {
    const contentType = String(req.headers['content-type'] || '');
    if (!contentType.toLowerCase().startsWith('multipart/form-data;') || !/boundary=/i.test(contentType)) return send(res, 400, { error: 'Upload an image using multipart form data.' });
    try {
      const body = await readBuffer(req, MAX_DEEPFAKE_UPLOAD);
      const response = await fetch(`${DEEPFAKE_SERVICE_URL}/api/v1/detect/deepfake`, {
        method: 'POST', headers: { 'content-type': contentType }, body, signal: AbortSignal.timeout(120_000)
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) return send(res, response.status, { error: result.detail || result.error || 'Deepfake analysis failed.' });
      return send(res, 200, result);
    } catch (error) {
      const status = error.status || (error.name === 'TimeoutError' ? 504 : 503);
      return send(res, status, { error: status === 504 ? 'Local analysis timed out. Try a smaller image.' : error.status ? error.message : 'Local DeepDefend service is unavailable. Start it on port 8000.' });
    }
  }
  if (req.method === 'GET' && url.pathname === '/api/health') {
    try {
      const response = await fetch(`${SOS_SERVICE_URL}/health`, {
        headers: { 'X-API-Key': SOS_SERVICE_API_KEY }, signal: AbortSignal.timeout(2_000)
      });
      const service = await response.json();
      return send(res, 200, { ok: true, database: 'sqlite', sosService: response.ok, twilio: Boolean(service.twilio) });
    } catch {
      return send(res, 200, { ok: true, database: 'sqlite', sosService: false, twilio: false });
    }
  }
  if (req.method === 'GET' && url.pathname === '/api/geocode') {
    const query = (url.searchParams.get('q') || '').trim();
    if (query.length < 3 || query.length > 160) return send(res, 400, { error: 'Enter a place name or full address (at least 3 characters).' });
    if (Date.now() - lastGeocode < 1100) return send(res, 429, { error: 'Please wait a moment before searching another place.' });
    lastGeocode = Date.now();
    try {
      const endpoint = new URL('https://nominatim.openstreetmap.org/search');
      endpoint.search = new URLSearchParams({ q: query, format: 'jsonv2', limit: '5', addressdetails: '1' });
      const response = await fetch(endpoint, { headers: { 'user-agent': 'KaaliSafety/1.0 (open-source personal-safety web app)', 'accept-language': 'en' }, signal: AbortSignal.timeout(12_000) });
      if (!response.ok) throw new Error(`Geocoding returned ${response.status}.`);
      return send(res, 200, await response.json());
    } catch (error) { return send(res, 502, { error: error.message || 'Place search is unavailable right now.' }); }
  }
  if (req.method === 'POST' && url.pathname === '/api/route') {
    const body = await readJson(req, 40_000);
    const { origin, destination } = body;
    const travelMode = resolveRouteMode(String(body.mode || 'pedestrian'));
    if (!travelMode) return send(res, 400, { error: 'Choose a supported travel mode.' });
    if (!validCoord(Number(origin?.lat), Number(origin?.lon)) || !validCoord(Number(destination?.lat), Number(destination?.lon))) return send(res, 400, { error: 'Choose valid start and destination points first.' });
    try {
      const response = await fetch('https://valhalla1.openstreetmap.de/route', {
        method: 'POST', headers: { 'content-type': 'application/json', 'X-Client-Id': 'kaali-safety-local' },
        body: JSON.stringify({ locations: [{ lat: Number(origin.lat), lon: Number(origin.lon) }, { lat: Number(destination.lat), lon: Number(destination.lon) }], costing: ROUTE_MODES[travelMode].costing, units: 'kilometers', language: 'en-IN', directions_type: 'instructions', alternates: 2 }),
        signal: AbortSignal.timeout(20_000)
      });
      let payload;
      try { payload = await response.json(); } catch { return send(res, 502, { error: 'The walking route provider returned an invalid response.' }); }
      if (!response.ok) return send(res, 502, { error: payload.error || payload.status_message || `${ROUTE_MODES[travelMode].label} routes are unavailable right now.` });
      if (!payload || typeof payload !== 'object' || !payload.trip) return send(res, 502, { error: 'The walking route provider returned an invalid response.' });
      const candidates = [payload, ...(Array.isArray(payload.alternates) ? payload.alternates : [])].map(routeOptionsFor).filter(Boolean);
      if (!candidates.length) return send(res, 404, { error: payload.trip?.status_message || 'No walking route was found between those points.' });
      const routeLocations = [{ lat: Number(origin.lat), lon: Number(origin.lon) }, { lat: Number(destination.lat), lon: Number(destination.lon) }];
      const comparisonModes = ['pedestrian', 'bicycle', 'car'];
      const modeTimesEntries = await Promise.all(comparisonModes.map(async mode => [mode, mode === travelMode
        ? { available: true, distanceKm: Number(candidates[0].summary.length), durationSeconds: Number(candidates[0].summary.time) }
        : await getModeTime(routeLocations[0], routeLocations[1], mode)]));
      const modeTimes = Object.fromEntries(modeTimesEntries);
      if (!comparisonModes.includes(travelMode)) modeTimes[travelMode] = { available: true, distanceKm: Number(candidates[0].summary.length), durationSeconds: Number(candidates[0].summary.time) };
      await addMappedRoadSignals(candidates);
      const options = candidates.map(route => ({
        ...route,
        travelMode,
        travelModeLabel: ROUTE_MODES[travelMode].label,
        summary: { ...route.summary, length: Number(route.summary.length), time: Number(route.summary.time) },
        lengthKm: Number(route.summary.length),
        label: route.recentConcernCount ? `${route.recentConcernCount} recent reports nearby` : 'No recent reports mapped nearby'
      }));
      const reportsAvailable = options.every(r => r.reportsAvailable);
      const evaluated = evaluateRoutes(options, { reportsAvailable });
      evaluated.sort((a, b) => Number(b.recommended) - Number(a.recommended) || (a.relativeRiskScore ?? Infinity) - (b.relativeRiskScore ?? Infinity) || a.lengthKm - b.lengthKm);
      const modeRoute = evaluated.find(route => route.recommended) || evaluated[0];
      modeTimes[travelMode] = modeRoute
        ? { available: true, distanceKm: modeRoute.lengthKm, durationSeconds: modeRoute.summary.time }
        : { available: false, distanceKm: null, durationSeconds: null };
      return send(res, 200, { options: evaluated, mode: travelMode, modeLabel: ROUTE_MODES[travelMode].label, modeTimes, status: evaluated.some(r => r.recommended) ? 'compared' : 'insufficient_evidence', source: 'OpenStreetMap + Valhalla', checkedAt: new Date().toISOString() });
    } catch (error) { return send(res, 502, { error: error.name === 'TimeoutError' ? 'The route provider took too long to respond. Try again shortly.' : error.message || 'Routes are unavailable right now.' }); }
  }
  if (req.method === 'POST' && url.pathname === '/api/services') {
    const body = await readJson(req, 8_000);
    const lat = Number(body.lat), lon = Number(body.lon);
    if (!validCoord(lat, lon)) return send(res, 400, { error: 'Choose a valid map location first.' });
    const south = Math.max(-90, lat - .018), west = Math.max(-180, lon - .018);
    const north = Math.min(90, lat + .018), east = Math.min(180, lon + .018);
    const query = `[out:json][timeout:18];(nwr["amenity"~"^(police|hospital|fire_station|pharmacy|shelter)$"](${south},${west},${north},${east}););out center tags;`;
    try {
      const response = await fetch('https://overpass.kumi.systems/api/interpreter', {
        method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded;charset=UTF-8', 'user-agent': 'KaaliSafety/1.0 (user-requested nearby support lookup)' },
        body: new URLSearchParams({ data: query }), signal: AbortSignal.timeout(22_000)
      });
      if (!response.ok) return send(res, 502, { error: `OpenStreetMap search returned ${response.status}.` });
      return send(res, 200, await response.json());
    } catch (error) { return send(res, 502, { error: error.message || 'Nearby OpenStreetMap listings are unavailable.' }); }
  }
  if (req.method === 'GET' && url.pathname === '/api/reports') {
    const parts = (url.searchParams.get('bbox') || '').split(',').map(Number);
    if (parts.length !== 4 || !parts.every(Number.isFinite)) return send(res, 400, { error: 'A valid south,west,north,east bounding box is required.' });
    const [south, west, north, east] = parts;
    if (!validCoord(south, west) || !validCoord(north, east) || south > north || west > east || north - south > 1 || east - west > 1) return send(res, 400, { error: 'Please request reports for an area under roughly 100 km wide.' });
    return send(res, 200, { reports: getReportsInBox({ south, west, north, east }, 24, 300), demoCount: countDemoReports(), updatedAt: new Date().toISOString() });
  }
  if (req.method === 'POST' && url.pathname === '/api/reports') {
    const body = await readJson(req, 8_000);
    const lat = Number(body.lat), lon = Number(body.lon), category = String(body.category || ''), note = String(body.note || '').trim().slice(0, 160);
    if (!validCoord(lat, lon) || !categories.has(category)) return send(res, 400, { error: 'Choose a report type and a valid location.' });
    const isDemo = body.demo === true;
    const reporter = isDemo ? String(body.reporter || '') : '';
    if (isDemo && !demoReporters.has(reporter)) return send(res, 400, { error: 'Choose one of the practice reporter profiles.' });
    const roundedLat = Math.round(lat * 1000) / 1000, roundedLon = Math.round(lon * 1000) / 1000;
    const id = randomUUID(), createdAt = new Date().toISOString();
    db.prepare('INSERT INTO reports(id, lat, lon, category, note, created_at, is_demo, reporter) VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(id, roundedLat, roundedLon, category, note, createdAt, isDemo ? 1 : 0, reporter);
    return send(res, 201, { report: { id, lat: roundedLat, lon: roundedLon, category, note, created_at: createdAt, is_demo: isDemo ? 1 : 0, reporter }, demoCount: countDemoReports(), privacy: isDemo ? 'Practice-only report; synthetic reporter profile.' : 'Report location rounded to about 100 m.' });
  }
  if (req.method === 'DELETE' && url.pathname === '/api/demo-reports') {
    const result = db.prepare('DELETE FROM reports WHERE is_demo = 1').run();
    return send(res, 200, { deleted: Number(result.changes) || 0, demoCount: countDemoReports() });
  }
  if (req.method === 'POST' && url.pathname === '/api/sos') {
    const body = await readJson(req, 12_000);
    const contacts = (Array.isArray(body.contacts) ? body.contacts : []).slice(0, 5).map(contact => ({
      name: String(contact?.name || 'Trusted contact').trim().slice(0, 100),
      phone: normalizeContactPhone(contact?.phone),
      relation: String(contact?.relation || 'Trusted contact').slice(0, 60),
      priority: Math.max(1, Math.min(5, Number(contact?.priority) || 1)),
    }));
    const location = body.location && typeof body.location === 'object' ? {
      lat: Number(body.location.lat), lng: Number(body.location.lng),
      accuracy: Math.max(0, Number(body.location.accuracy) || 0),
      speed: Math.max(0, Number(body.location.speed) || 0),
      timestamp: String(body.location.timestamp || new Date().toISOString()).slice(0, 40),
    } : null;
    if (!contacts.length || contacts.some(contact => !/^\+?[1-9]\d{7,14}$/.test(contact.phone))) {
      return send(res, 400, { error: 'Add a trusted contact with a valid international phone number.' });
    }
    if (!location || !validCoord(location.lat, location.lng)) {
      return send(res, 400, { error: 'Add a valid current location before starting live SOS tracking.' });
    }
    try {
      const servicePayload = {
        user_id: String(body.user_id || 'kaali-local-user').slice(0, 100),
        user_name: String(body.user_name || 'User').slice(0, 100),
        location: body.location || null,
        trigger_type: String(body.trigger_type || 'manual'),
        contacts,
        passphrase: String(body.passphrase || '').slice(0, 200),
      };
      const response = await fetch(`${SOS_SERVICE_URL}/api/v1/sos/trigger`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'X-API-Key': SOS_SERVICE_API_KEY },
        body: JSON.stringify(servicePayload),
        signal: AbortSignal.timeout(15_000),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = result.detail;
        const error = typeof detail === 'string' ? detail
          : Array.isArray(detail) ? detail.map(item => item?.msg).filter(Boolean).join('; ')
            : detail?.error || 'The SOS dispatch service could not process this alert.';
        return send(res, response.status, { error, providerCode: detail?.providerCode || null });
      }
      const recipients = Array.isArray(result.sms_sent_to) ? result.sms_sent_to : [];
      return send(res, 200, {
        ...result,
        sent: recipients.length > 0,
        method: 'fastapi',
        status: result.status || 'active',
        trackingUrl: result.tracking_url || null,
      });
    } catch {
      return send(res, 503, { error: 'Kaali could not reach its SOS service. You can still use Copy SOS message or call local emergency services.' });
    }
  }
  return send(res, 404, { error: 'API route not found.' });
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
    if (url.pathname.startsWith('/api/')) return await handleApi(req, res, url);
    if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405, { error: 'Method not allowed.' });
    const requestPath = decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname);
    const file = path.resolve(PUBLIC, `.${requestPath}`);
    if (!file.startsWith(PUBLIC + path.sep)) return send(res, 403, { error: 'Forbidden.' });
    let content;
    try { content = await readFile(file); }
    catch { content = await readFile(path.join(PUBLIC, 'index.html')); }
    res.writeHead(200, { 'content-type': mime[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff', 'referrer-policy': 'strict-origin-when-cross-origin' });
    if (req.method === 'HEAD') return res.end();
    return res.end(content);
  } catch (error) {
    if (res.headersSent) return res.destroy();
    return send(res, Number(error.status) || 500, { error: error.message || 'Unexpected server error.' });
  }
});

server.listen(PORT, HOST, () => console.log(`Kaali Safety is available at http://${HOST}:${PORT}`));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { db.close(); server.close(() => process.exit(0)); });
