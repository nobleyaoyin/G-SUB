"""Safe, standards-compatible download names; never interpret storage paths."""
import re
import unicodedata
from urllib.parse import quote


def _safe_filename(name: str) -> bool:
    if not name or len(name) > 255 or name in ('.', '..') or name.endswith(('.', ' ')):
        return False
    if any(unicodedata.category(c) in ('Cc', 'Cs') or c in '/\\<>:"|?*' for c in name):
        return False
    base = name.split('.', 1)[0].rstrip(' ').upper()
    return not re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])', base)


def normalize_upload_filename(filename: str) -> str:
    """Canonicalize a single untrusted name; never turn it into a path."""
    if not isinstance(filename, str):
        raise ValueError('Invalid filename')
    if any(unicodedata.category(c) in ('Cc', 'Cs') for c in filename):
        raise ValueError('Invalid filename')
    name = unicodedata.normalize('NFC', filename.strip())
    if not _safe_filename(name):
        raise ValueError('Invalid filename')
    return name


def content_disposition(filename: str, fallback: str) -> str:
    """Emit an ASCII fallback and RFC 5987 UTF-8 name for safe metadata."""
    if not isinstance(filename, str) or not _safe_filename(filename):
        filename = fallback
    if not re.fullmatch(r'[A-Za-z0-9._-]+', fallback) or not _safe_filename(fallback):
        raise ValueError('Unsafe fallback filename')
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}'
