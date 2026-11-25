import {recordedTimestamp} from './recordedTimestamp';

const roles = {AUTHOR:'Author', REVIEWER:'Reviewer', EDITOR:'Editor', FORMATTER:'Formatter', EIC:'EIC'};
export function recordedRole(value) {
  return typeof value === 'string' ? (roles[value] || value) : '';
}
// Normalize only a known server-generated template; preserve names and free text.
export function recordedMessage(value) {
  if (typeof value !== 'string') return value;
  return value.replace(/^(AUTHOR|REVIEWER|EDITOR|FORMATTER|EIC)(?= reviewed final editing submission #\d+:)/, role => roles[role]);
}
export function readableRecordedDate(value) {
  if (typeof value !== 'string') return '';
  const text = value.trim().replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:)/, '$1T$2');
  if (recordedTimestamp(text) === 'Unavailable') return '';
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(text);
  const date = new Date(zoned ? text : `${text}Z`);
  if (Number.isNaN(date.valueOf())) return '';
  const options = {year:'numeric',month:'long',day:'numeric',hour:'numeric',minute:'2-digit', ...(zoned ? {} : {timeZone:'UTC'})};
  return new Intl.DateTimeFormat(undefined, options).format(date) + (zoned ? '' : ' (timezone not recorded)');
}
