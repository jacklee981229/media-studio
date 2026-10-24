"""Exporting the kept photos, in their look with their adjustments, carrying only the capture time (no GPS, no phone).
WebP is for the website: three widths each, plus a media.json that lists them in timeline order. JPEG is for sharing
and keeping: one file each at full size.

Everything goes into the trip's export folder, which the tool owns: a re-export rewrites it and removes files of
photos no longer kept.
"""
import subprocess
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps

from . import looks

pillow_heif.register_heif_opener()

WIDTHS = (640, 1280, 2048)
QUALITY = 82
PHOTOS = 'photos'
FORMATS = ('webp', 'jpeg')
JPEG_FOLDER = 'jpeg'
JPEG_QUALITY = 92


SMALLER = 'smaller'


def names(items: list) -> dict:
    """Each exported photo's file name, without size or extension: its number in timeline order (001, 002 …), so the
    files sort as the trip went. A photo added or taken out renumbers the ones after it."""
    digits = max(3, len(str(len(items))))
    return {item['id']: str(n).zfill(digits) for n, item in enumerate(items, 1)}


def file_name(name: str, width: int) -> str:
    """Where one size goes inside the photos folder: the largest on top, the smaller two in a folder of their own, so
    the top shows each photo once."""
    return f'{name}.webp' if width == WIDTHS[-1] else f'{SMALLER}/{name}_{width}.webp'


def photo_files(name: str) -> dict:
    """One photo's files as media.json lists them, by width."""
    return {str(width): f'{PHOTOS}/{file_name(name, width)}' for width in WIDTHS}


def capture_exif(taken, offset) -> bytes:
    """EXIF with the capture time and nothing else."""
    exif = Image.Exif()
    if taken:
        inner = exif.get_ifd(0x8769)
        inner[0x9003] = taken
        if offset:
            inner[0x9011] = offset
    return exif.tobytes()


def export_photo(src: str, folder: str, name: str, settings: tuple, taken, offset) -> dict:
    """Write one photo's three sizes; returns its entry for media.json (minus the timeline facts)."""
    with Image.open(src) as original:
        icc = original.info.get('icc_profile')
        im = ImageOps.exif_transpose(original).convert('RGB')
    largest = WIDTHS[-1]
    im.thumbnail((largest, largest), Image.Resampling.LANCZOS)
    im = looks.develop(im, *settings)
    out = Path(folder)
    (out / SMALLER).mkdir(parents=True, exist_ok=True)
    exif = capture_exif(taken, offset)
    for width in sorted(WIDTHS, reverse=True):
        sized = im.copy()
        sized.thumbnail((width, width), Image.Resampling.LANCZOS)
        file = file_name(name, width)
        temp = out / (file + '.tmp')
        # The colour profile goes along (iPhone photos are Display P3); browsers show the colours as shot.
        sized.save(temp, 'WEBP', quality=QUALITY, method=4, icc_profile=icc, exif=exif)
        temp.replace(out / file)
    return {'width': im.width, 'height': im.height, 'files': photo_files(name)}


def jpeg_name(name: str) -> str:
    return f'{name}.jpg'


def export_jpeg(src: str, folder: str, name: str, settings: tuple, taken, offset) -> dict:
    """Write one photo at full size as a JPEG. Not listed in media.json, which is the website's."""
    with Image.open(src) as original:
        icc = original.info.get('icc_profile')
        im = ImageOps.exif_transpose(original).convert('RGB')
    im = looks.develop(im, *settings)
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    file = jpeg_name(name)
    temp = out / (file + '.tmp')
    im.save(temp, 'JPEG', quality=JPEG_QUALITY, subsampling=0, icc_profile=icc, exif=capture_exif(taken, offset))
    temp.replace(out / file)
    return {}


def stale(folder: Path, keep: set) -> list:
    """Files in an export folder that belong to nothing kept any more."""
    if not folder.is_dir():
        return []
    return [p for p in folder.iterdir() if p.is_file() and p.suffix in ('.webp', '.jpg', '.mp4', '.tmp') and p.name not in keep]


# ---- videos

VIDEOS = 'videos'
CLIP_SECONDS = 7.0
LONG_SIDE = 1920
FADE = 0.5
SOUNDS = ('mute', 'original', 'music')

# HDR (HLG/PQ) shown as is looks grey: to linear light, map the range down (hable keeps detail in bright skies), back
# to BT.709; the look's colour table goes on in between, in RGB, exactly as on the photos. SDR goes straight to RGB.
_HDR = 'zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709'
_SDR = 'zscale=min=bt709:rin=tv,format=gbrpf32le'
_OUT = 'zscale=m=bt709:r=tv,format=yuv420p'


def video_filter(hdr: bool, cube_name) -> str:
    """The picture's path: 30 fps, long side at most 1920, to normal colour, the look, then 8-bit BT.709 for every
    browser. `cube_name` is a .cube in ffmpeg's working folder (a Windows path in a filter needs fragile escaping)."""
    steps = [f'fps=30,scale={LONG_SIDE}:{LONG_SIDE}:force_original_aspect_ratio=decrease:force_divisible_by=2',
             _HDR if hdr else _SDR]
    if cube_name:
        steps.append(f'lut3d=file={cube_name}')
    steps.append(_OUT)
    return ','.join(steps)


def clip_command(ffmpeg: str, src: str, out: str, start: float, length: float, hdr: bool, cube_name, sound: str,
                 music=None, music_start: float = 0.0) -> list:
    """The ffmpeg command for one clip. Location, dates and the phone's name are left out of the file."""
    cmd = [ffmpeg, '-v', 'error', '-y', '-ss', f'{start:.3f}', '-t', f'{length:.3f}', '-i', src]
    if sound == 'music':
        cmd += ['-ss', f'{music_start:.3f}', '-t', f'{length:.3f}', '-i', music]
    cmd += ['-map', '0:v:0', '-vf', video_filter(hdr, cube_name),
            '-c:v', 'libx264', '-preset', 'slow', '-crf', '23', '-maxrate', '5M', '-bufsize', '10M', '-profile:v', 'high',
            '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709']
    if sound == 'mute':
        cmd += ['-an']
    else:
        fades = f'afade=t=in:d={FADE},afade=t=out:st={max(0.0, length - FADE):.3f}:d={FADE}'
        # iPhone 16 and later add a second, spatial audio track some players can't read: only the first goes out.
        # The ? lets a clip that has no sound at all still export, silent.
        cmd += ['-map', '1:a:0' if sound == 'music' else '0:a:0?', '-af', fades, '-c:a', 'aac', '-b:a', '128k', '-ac', '2']
    return cmd + ['-map_metadata', '-1', '-map_chapters', '-1', '-movflags', '+faststart', out]


def video_files(name: str) -> dict:
    """One clip's files as media.json lists them: the clip and its cover."""
    return {'file': f'{VIDEOS}/{name}.mp4', 'poster': f'{VIDEOS}/{name}.webp'}


def export_video(ffmpeg: str, src: str, folder: str, name: str, start: float, length: float, hdr: bool,
                 cube_dir: str, cube_name, sound: str, music=None, music_start: float = 0.0) -> dict:
    """Write one clip and its cover (the clip's first frame); returns its entry for media.json."""
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    clip, poster = f'{name}.mp4', f'{name}.webp'
    temp = out / f'{name}.tmp.mp4'
    subprocess.run(clip_command(ffmpeg, src, str(temp), start, length, hdr, cube_name, sound, music, music_start),
                   cwd=cube_dir, check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    temp.replace(out / clip)
    frame = out / f'{name}.frame.png'
    try:
        subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(out / clip), '-frames:v', '1', str(frame)],
                       check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        with Image.open(frame) as im:
            size = im.size
            im.convert('RGB').save(out / poster, 'WEBP', quality=QUALITY, method=4)
    finally:
        frame.unlink(missing_ok=True)
    return {'width': size[0], 'height': size[1], 'seconds': round(length, 2), 'sound': sound, **video_files(name)}
