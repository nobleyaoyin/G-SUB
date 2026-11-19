"""Strict canonical UTC timestamps for future persistence boundaries."""
import re
from datetime import datetime, timezone


_ISO = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$')


def canonical_utc(value):
    """Return UTC ISO text with microseconds; reject naive/ambiguous values."""
    if isinstance(value, str):
        if not _ISO.fullmatch(value):
            raise ValueError('Expected timezone-aware ISO timestamp')
        try:
            value = datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith('Z') else value)
        except ValueError as error:
            raise ValueError('Invalid timestamp') from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone-aware timestamp required')
    try:
        return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    except (ValueError, OverflowError) as error:
        raise ValueError('Timestamp outside supported range') from error
