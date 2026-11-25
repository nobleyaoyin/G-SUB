// Do not infer a timezone or turn malformed legacy data into a recorded date.
export function recordedTimestamp(value) {
  if (typeof value !== 'string') return 'Unavailable';
  const text = value.trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$/i.exec(text);
  if (!match) return 'Unavailable';
  const [, year, month, day, hour, minute, second, zone] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), Number(second)));
  if (date.getUTCFullYear() !== Number(year) || date.getUTCMonth() + 1 !== Number(month) || date.getUTCDate() !== Number(day)
      || date.getUTCHours() !== Number(hour) || date.getUTCMinutes() !== Number(minute) || date.getUTCSeconds() !== Number(second)) return 'Unavailable';
  if (!zone) return `${text} (timezone not recorded)`;
  const parsed = new Date(text);
  return Number.isNaN(parsed.valueOf()) ? 'Unavailable' : text;
}
