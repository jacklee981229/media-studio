"""Test files made on the spot: photos with or without camera facts, and a short HDR video."""
import subprocess
from pathlib import Path

import pillow_heif
from PIL import Image, ImageDraw

from studio import config

pillow_heif.register_heif_opener()


def picture(seed: int, size=(400, 300)) -> Image.Image:
    """A picture whose look depends on the seed: different seeds give different scenes."""
    im = Image.new('RGB', size, (40 + seed * 37 % 200, 90, 160 - seed * 13 % 120))
    draw = ImageDraw.Draw(im)
    for n in range(6):
        x = (seed * 53 + n * 97) % size[0]
        y = (seed * 31 + n * 61) % size[1]
        draw.ellipse([x - 40, y - 30, x + 40, y + 30], fill=((seed * 71 + n * 40) % 255, (n * 90) % 255, (seed * 17) % 255))
    return im


def exif_bytes(make=None, model=None, taken=None, offset=None, gps=None, comment=None) -> bytes:
    exif = Image.Exif()
    if make:
        exif[0x010F] = make
    if model:
        exif[0x0110] = model
    inner = exif.get_ifd(0x8769)
    if taken:
        inner[0x9003] = taken
    if offset:
        inner[0x9011] = offset
    if comment:
        inner[0x9286] = b'ASCII\x00\x00\x00' + comment.encode()
    if gps:
        lat, lon = gps
        where = exif.get_ifd(0x8825)
        where[1], where[2] = ('N' if lat >= 0 else 'S'), (abs(lat), 0.0, 0.0)
        where[3], where[4] = ('E' if lon >= 0 else 'W'), (abs(lon), 0.0, 0.0)
    return exif.tobytes()


def face_xmp(*widths) -> bytes:
    """XMP face regions the way an iPhone writes them."""
    regions = ''.join(
        f'<rdf:li rdf:parseType="Resource"><mwg-rs:Area rdf:parseType="Resource"><stArea:y>0.4</stArea:y>'
        f'<stArea:w>{w}</stArea:w><stArea:x>0.4</stArea:x><stArea:h>{w * 1.3}</stArea:h></mwg-rs:Area>'
        f'<mwg-rs:Type>Face</mwg-rs:Type></rdf:li>' for w in widths)
    return (f'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            f'<rdf:Description xmlns:mwg-rs="http://www.metadataworkinggroup.com/schemas/regions/" '
            f'xmlns:stArea="http://ns.adobe.com/xmp/sType/Area#"><mwg-rs:Regions rdf:parseType="Resource">'
            f'<mwg-rs:RegionList><rdf:Seq>{regions}</rdf:Seq></mwg-rs:RegionList></mwg-rs:Regions>'
            f'</rdf:Description></rdf:RDF></x:xmpmeta>').encode()


def save_photo(path: Path, image: Image.Image, fmt: str, xmp=None, **facts) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = {'xmp': xmp} if xmp else {}
    image.save(path, fmt, exif=exif_bytes(**facts), **extra) if facts else image.save(path, fmt, **extra)
    return path


def hdr_clip(path: Path, seconds=1) -> Path:
    """A short HEVC 10-bit HLG clip, like an iPhone's HDR video."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(config.FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc2=size=320x240:rate=30:duration={seconds}',
         '-c:v', 'libx265', '-x265-params', 'log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc', '-pix_fmt', 'yuv420p10le', '-color_primaries', 'bt2020',
         '-color_trc', 'arib-std-b67', '-colorspace', 'bt2020nc', '-tag:v', 'hvc1', str(path)],
        check=True, capture_output=True,
    )
    return path
