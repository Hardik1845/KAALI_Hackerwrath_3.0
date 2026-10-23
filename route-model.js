// Explainable relative concern model. Scores are comparison points, never harm probabilities.
export const MAX_DETOUR_RATIO = 1.3;

export function evaluateRoutes(routes, { reportsAvailable = true, maxDetourRatio = MAX_DETOUR_RATIO } = {}) {
  const valid = routes.filter(r => Number.isFinite(r.lengthKm) && r.lengthKm > 0 && Array.isArray(r.points) && r.points.length > 0);
  if (!valid.length) return [];
  const shortest = Math.min(...valid.map(r => r.lengthKm));
  const mapped = valid.map(route => {
    const detourKm = Math.max(0, route.lengthKm - shortest);
    const detourPercent = shortest > 0 ? detourKm / shortest * 100 : null;
    const reportExposure = Number.isFinite(route.reportExposurePerKm) ? route.reportExposurePerKm : route.recentConcernCount / Math.max(route.lengthKm, .1);
    const reportRate = reportsAvailable ? Math.min(1, reportExposure / 4) : null;
    const knownLighting = route.lighting?.lit + route.lighting?.unlit;
    const lightingConcern = knownLighting > 0 ? route.lighting.unlit / knownLighting : null;
    const canScore = reportsAvailable || lightingConcern !== null;
    // 50% normalized report exposure, 20% observed unlit tags, 30% detour.
    // Zero reports are neutral: they do not earn a safety bonus.
    const score = canScore ? (reportRate ?? 0) * 50 + (lightingConcern ?? 0) * 20 + (detourPercent ?? 0) / Math.max((maxDetourRatio - 1) * 100, 1) * 30 : null;
    const coverage = Number.isFinite(route.infrastructureCoverage) ? route.infrastructureCoverage : null;
    const reasons = [];
    if (reportsAvailable && route.recentConcernCount) reasons.push({ code: 'recent_reports', text: `${route.recentConcernCount} recent concern report${route.recentConcernCount === 1 ? '' : 's'} nearby.` });
    if (reportsAvailable && !route.recentConcernCount) reasons.push({ code: 'no_recent_reports', text: 'No recent concern reports were found in this server’s report data; this is not evidence of safety.' });
    if (detourPercent !== null && detourPercent > 0) reasons.push({ code: 'detour', text: `This route is ${detourPercent.toFixed(0)}% longer than the shortest candidate.` });
    if (coverage !== null && coverage < 1) reasons.push({ code: 'incomplete_infrastructure', text: 'Some sampled locations have no nearby mapped road infrastructure data.' });
    if (lightingConcern === null) reasons.push({ code: 'lighting_unknown', text: 'Lighting information is unavailable for some or all sampled locations; OSM tags do not confirm working lights.' });
    if (!reportsAvailable) reasons.push({ code: 'reports_unavailable', text: 'Community report data is unavailable, so report exposure could not be assessed.' });
    const confidence = !reportsAvailable && coverage === 0 ? 'insufficient' : coverage === null || coverage < .5 || !reportsAvailable ? 'limited' : coverage >= .8 && reportsAvailable ? 'moderate' : 'limited';
    const missingData = [];
    if (!reportsAvailable) missingData.push('reports_unavailable');
    if (lightingConcern === null) missingData.push('lighting_unknown');
    if (coverage === null || coverage < 1) missingData.push('incomplete_infrastructure_coverage');
    return { ...route, detourKm, detourPercent, relativeRiskScore: score === null ? null : Number(score.toFixed(2)), confidence, confidenceReasons: [!reportsAvailable ? 'reports_unavailable' : 'reports_recent_window_only', coverage === null || coverage < 1 ? 'incomplete_map_coverage' : 'map_tags_unverified'], reasons, missingData, reportSummary: { status: reportsAvailable ? 'available' : 'unavailable', recentConcernCount: route.recentConcernCount, supportCount: route.supportCount, windowHours: reportsAvailable ? 12 : null, verification: 'unverified' }, recommendationEligible: route.lengthKm <= shortest * maxDetourRatio, shortestKm: shortest };
  });
  const eligible = mapped.filter(r => r.recommendationEligible && r.relativeRiskScore !== null);
  const best = eligible.sort((a,b) => a.relativeRiskScore - b.relativeRiskScore || a.lengthKm - b.lengthKm)[0];
  // Every eligible option needs some route-specific positive evidence before we
  // can explain a comparison. An uncovered route cannot win by having unknowns.
  const adequate = eligible.length > 0 && eligible.every(r => reportsAvailable && ((r.lighting?.mapped || 0) > 0 || r.recentConcernCount > 0));
  return mapped.map(r => {
    const recommended = Boolean(best && adequate && r.id === best.id);
    const explanation = !best || !adequate
      ? 'There is insufficient evidence to compare the safety of these alternatives confidently.'
      : recommended
        ? `Recommended within the ${Math.round((maxDetourRatio - 1) * 100)}% detour limit. ${r.reasons.find(x => x.code === 'recent_reports')?.text || r.reasons.find(x => x.code === 'detour')?.text || 'This has the lowest calculated relative concern score among eligible routes.'}`
        : r.reasons.find(x => x.code === 'detour')?.text || 'This alternative has a higher calculated relative concern score; the comparison is not a safety guarantee.';
    return { ...r, recommended, selected: recommended, assessmentStatus: best && adequate ? 'relative_comparison' : 'insufficient_evidence', explanation };
  });
}
