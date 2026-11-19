export const PAGE_SIZE = 10;
export const UNKNOWN_STATUS = '__unavailable__';
export const statusValue = item => typeof item.status === 'string' && item.status.trim() ? item.status : UNKNOWN_STATUS;
export const statusLabel = value => value === UNKNOWN_STATUS ? 'Status unavailable' : value.replaceAll('_', ' ');

export function prepareManuscriptList(items, search, filter, sortBy, direction) {
  // The endpoint is the authorization boundary; deduplication only prevents repeated display/counts.
  const unique = [...new Map(items.map(item => [item.manuscript_id, item])).values()];
  const counts = new Map();
  for (const item of unique) counts.set(statusValue(item), (counts.get(statusValue(item)) || 0) + 1);
  const query = search.trim().toLocaleLowerCase();
  const filtered = unique.filter(item => (!filter || statusValue(item) === filter) && `${item.title || ''} ${item.manuscript_id}`.toLocaleLowerCase().includes(query));
  const compare = (a,b) => {
    const key = item => sortBy === 'title' ? (item.title || '').trim() : sortBy === 'status' ? statusValue(item) : sortBy === 'created_at' ? Date.parse(item.created_at) : item.manuscript_id;
    const x = key(a), y = key(b);
    const missing = value => sortBy === 'created_at' ? !Number.isFinite(value) : sortBy === 'status' ? value === UNKNOWN_STATUS : sortBy === 'title' ? !value : !Number.isFinite(value);
    if (missing(x) !== missing(y)) return missing(x) ? 1 : -1;
    let result = 0;
    if (!missing(x)) result = typeof x === 'string' ? x.localeCompare(y, 'en', {sensitivity:'base', numeric:true}) : x - y;
    return (direction === 'desc' ? -result : result) || a.manuscript_id - b.manuscript_id;
  };
  return {unique, counts, filtered:filtered.sort(compare)};
}
