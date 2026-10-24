"""When each file was taken, in the local time of the place it was taken."""
from datetime import datetime, timedelta, timezone

WEEKDAYS = '一二三四五六日'


def taken(meta: dict):
    """An aware datetime in the shot's own local time, or None when the file doesn't say.

    Photos keep the local time and its offset in separate EXIF fields; iPhone videos keep both in one tag. A photo
    with no offset is read as Malaysia time (UTC+8), which is also China's.
    """
    if meta.get('taken'):
        try:
            when = datetime.strptime(meta['taken'], '%Y:%m:%d %H:%M:%S')
        except ValueError:
            return None
        offset = meta.get('offset') or '+08:00'
        sign = -1 if offset[0] == '-' else 1
        zone = timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[4:6])))
        return when.replace(tzinfo=zone)
    if meta.get('created'):
        try:
            return datetime.strptime(meta['created'], '%Y-%m-%dT%H:%M:%S%z')
        except ValueError:
            return None
    return None


def day_label(day: str) -> str:
    """"2026-10-14" as "10月14日 周二"."""
    d = datetime.strptime(day, '%Y-%m-%d')
    return f'{d.month}月{d.day}日 周{WEEKDAYS[d.weekday()]}'
