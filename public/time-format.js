export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return 'Time unavailable';
  const minutes = Math.max(1, Math.round(seconds / 60));
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (!hours) return `${minutes} min`;
  return remainder ? `${hours} hr ${remainder} min` : `${hours} hr`;
}
