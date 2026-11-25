// Preserve actionable errors and only replace a known internal schema fallback.
export function displayError(value) {
  if (typeof value !== 'string') return value;
  if (/^(?:[\w /-]+ )?schema unavailable(?: or incompatible)?\.?$/i.test(value.trim())) return 'This information is currently unavailable.';
  return value.replace(/\bschema unavailable(?: or incompatible)?\b/gi, 'information is unavailable');
}
