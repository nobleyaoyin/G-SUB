// Display only; no professor-approved word or keyword thresholds are implied.
export function metadataCounts(value) {
  const text = typeof value === 'string' ? value : '';
  const trimmed = text.trim();
  return { characters: Array.from(text).length, words: trimmed ? trimmed.split(/\s+/u).length : 0 };
}
