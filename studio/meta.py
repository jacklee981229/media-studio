"""What a photo or video says about itself: size, camera, when it was taken, where. Reads only; never decodes pixels."""
import json
import re
import subprocess
from pathlib import Path

import pillow_heif
from PIL import ExifTags, Image

from . import config

# pillow-heif turns an iPhone HEIC upright as it opens it and sets its EXIF orientation to 1.
pillow_heif.register_heif_opener()

_OFFSET = re.compile(r'^[+-]\d\d:\d\d$')
_TAKEN = re.compile(r'^\d{4}:\d\d:\d\d \d\d:\d\d:\d\d$')


def _text(value):
    """An EXIF text field as clean text, or None. Some apps leave binary scraps where text belongs."""
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    if not isinstance(value, str):
        return None
    value = value.strip('\x00 ').strip()
    return value if value and value.isprintable() else None


def _comment(value):
    """EXIF UserComment: 8 bytes naming the charset, then the text. iPhone screenshots say "Screenshot" here."""
    if isinstance(value, bytes):
        value = value[8:] if value[:8] in (b'ASCII\x00\x00\x00', b'UNICODE\x00', b'\x00' * 8) else value
    return _text(value)


def _degrees(parts, ref):
    try:
        d, m, s = (float(x) for x in parts)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    value = d + m / 60 + s / 3600
    return -value if ref in ('S', 'W') else value


def _gps(info):
    lat = _degrees(info.get(2), info.get(1))
    lon = _degrees(info.get(4), info.get(3))
    return [round(lat, 6), round(lon, 6)] if lat is not None and lon is not None else None


_FACE = re.compile(r'<stArea:w>([\d.]+)</stArea:w>(?:(?!</rdf:li>).)*?<mwg-rs:Type>Face</mwg-rs:Type>', re.S)


def faces(xmp) -> list:
    """Widths of the faces the camera found, as shares of the picture's width. The iPhone writes them as XMP
    regions whenever it sees a face; a file without XMP says nothing either way (None)."""
    if not xmp:
        return None
    text = xmp.decode('utf-8', 'replace') if isinstance(xmp, bytes) else str(xmp)
    return [float(w) for w in _FACE.findall(text)]


def read_photo(path: Path) -> dict:
    with Image.open(path) as im:
        exif = im.getexif()
        ifd = exif.get_ifd(ExifTags.IFD.Exif)
        width, height = im.size
        # JPEGs keep their pixels sideways and an orientation tag; HEICs arrive already upright (orientation 1).
        if exif.get(0x0112) in (5, 6, 7, 8):
            width, height = height, width
        taken = _text(ifd.get(0x9003))
        offset = _text(ifd.get(0x9011))
        return {
            'format': im.format,
            'width': width,
            'height': height,
            'make': _text(exif.get(0x010F)),
            'model': _text(exif.get(0x0110)),
            'taken': taken if taken and _TAKEN.match(taken) else None,
            'offset': offset if offset and _OFFSET.match(offset) else None,
            'gps': _gps(exif.get_ifd(ExifTags.IFD.GPSInfo)),
            'comment': _comment(ifd.get(0x9286)),
            'faces': faces(im.info.get('xmp')),
        }


def _iso6709(value):
    """QuickTime's location, "+25.0453+102.7097+1890.000/", as [lat, lon]."""
    match = re.match(r'^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)', value or '')
    return [round(float(match[1]), 6), round(float(match[2]), 6)] if match else None


def read_video(path: Path) -> dict:
    out = subprocess.run(
        [str(config.FFPROBE), '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', str(path)],
        capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout
    return video_meta(json.loads(out))


def video_meta(probe: dict) -> dict:
    """The parts of ffprobe's answer that matter here. Split out from read_video so it can be tested without ffmpeg."""
    tags = probe.get('format', {}).get('tags', {})
    video = next((s for s in probe.get('streams', []) if s.get('codec_type') == 'video'), {})
    width, height = video.get('width') or 0, video.get('height') or 0
    rotation = next((int(d.get('rotation', 0)) for d in video.get('side_data_list', []) if 'rotation' in d), 0)
    if abs(rotation) % 180 == 90:
        width, height = height, width
    return {
        'format': video.get('codec_name'),
        'width': width,
        'height': height,
        'duration': round(float(probe.get('format', {}).get('duration') or 0), 2),
        'hdr': video.get('color_transfer') in ('arib-std-b67', 'smpte2084'),
        'make': _text(tags.get('com.apple.quicktime.make')),
        'model': _text(tags.get('com.apple.quicktime.model')),
        # The iPhone's own local time with its offset. creation_time is UTC and, on a received video, the time it
        # was saved, not shot, so it isn't used.
        'created': _text(tags.get('com.apple.quicktime.creationdate')),
        'gps': _iso6709(tags.get('com.apple.quicktime.location.ISO6709')),
    }
