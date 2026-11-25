// Original upload names are optional metadata, never inferred from storage IDs.
export function originalDocumentName(record) {
  const value = record?.original_filename;
  if (typeof value !== 'string') return null;
  if (/[\p{Cc}\p{Cs}]/u.test(value)) return null;
  const name = value.trim();
  const base = name.split('.')[0].trimEnd();
  if (!name || [...name].length > 255 || name === '.' || name === '..' || /[. ]$/.test(name) || /[\\/<>:"|?*]/.test(name) || /^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])$/i.test(base)) return null;
  return name;
}

export function documentExtension(record) {
  const value = typeof record?.file_format === 'string' ? record.file_format : record?.filename?.split('.').pop();
  const format = typeof value === 'string' ? value.toLowerCase().replace(/^\./, '') : '';
  return ['pdf', 'docx', 'doc', 'txt'].includes(format) ? format : null;
}

// Prefer the UTF-8 extended parameter once; never reinterpret already-decoded text.
export function downloadFilename(disposition) {
  if (typeof disposition !== 'string') return null;
  const extended = disposition.match(/(?:^|;)\s*filename\*\s*=\s*UTF-8''([^;]*)/i);
  let name;
  try {
    if (extended) name = decodeURIComponent(extended[1].trim());
    else name = disposition.match(/(?:^|;)\s*filename\s*=\s*(?:"([^"\r\n]*)"|([^;\s]+))/i)?.slice(1).find(Boolean);
  } catch { return null; }
  return originalDocumentName({original_filename:name});
}
