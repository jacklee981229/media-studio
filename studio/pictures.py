"""Making the small pictures the screen shows: thumbnails, large previews and a frame from each video.

These run in worker processes, so each function takes plain paths and returns plain values.
"""
import io
import os
import subprocess
import threading
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps

from . import config, looks
from .similar import colour_print, fingerprint

pillow_heif.register_heif_opener()

THUMB_SIZE = 480
PREVIEW_SIZE = 2048

# HDR video (HLG or PQ) shown as is looks grey and flat on a normal screen: turn the light linear, map its range
# down (hable keeps detail in bright skies), then back to the normal BT.709 picture.
TONE_MAP = ('zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,'
            'zscale=t=bt709:m=bt709:r=tv,format=yuv420p')


def _open_upright(path: Path, size: int) -> Image.Image:
    im = Image.open(path)
    im.draft('RGB', (size, size))  # JPEGs decode straight at a smaller size; other formats ignore this
    im = ImageOps.exif_transpose(im)
    return im


def _save_jpeg(im: Image.Image, out: Path, size: int, quality: int, icc, optimize: bool = True) -> None:
    im = im.convert('RGB')
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Its own temporary name, so two requests drawing the same picture at once don't trip over each other.
    temp = out.with_name(f'{out.name}.{os.getpid()}-{threading.get_ident()}.tmp')
    # The colour profile goes along (iPhone photos are Display P3), so Chrome shows the colours as shot.
    im.save(temp, 'JPEG', quality=quality, icc_profile=icc, optimize=optimize)
    temp.replace(out)


def photo_thumb(src: str, out: str) -> tuple:
    """Write the thumbnail and return the photo's two prints (similar.py)."""
    with Image.open(src) as original:
        icc = original.info.get('icc_profile')
    im = _open_upright(Path(src), THUMB_SIZE * 2)
    _save_jpeg(im, Path(out), THUMB_SIZE, 82, icc)
    return fingerprint(im), colour_print(im)


def photo_base(src: str, out: str) -> None:
    """The photo as shot at preview size, kept so each change to a photo's look redraws in a blink."""
    with Image.open(src) as original:
        icc = original.info.get('icc_profile')
    im = _open_upright(Path(src), PREVIEW_SIZE)
    _save_jpeg(im, Path(out), PREVIEW_SIZE, 95, icc, optimize=False)


def preview_bytes(base: str, look_id, strength: float, exposure: float, warmth: float) -> bytes:
    """The preview with the photo's look and adjustments, drawn from its base, as JPEG bytes. Kept in memory, not
    on disk: writing a new file per slider move cost more than drawing it (each new file gets virus-scanned)."""
    with Image.open(base) as im:
        icc = im.info.get('icc_profile')
        shown = looks.develop(im, look_id, strength, exposure, warmth)
    out = io.BytesIO()
    shown.save(out, 'JPEG', quality=88, icc_profile=icc)
    return out.getvalue()


LOOK_SIZE = 1400


def photo_look(src: str, out: str, look_id, strength: float = 1.0) -> None:
    """The photo in a trip look (or as shot, for look None), at a size for comparing looks side by side."""
    with Image.open(src) as original:
        icc = original.info.get('icc_profile')
    im = _open_upright(Path(src), LOOK_SIZE).convert('RGB')
    im.thumbnail((LOOK_SIZE, LOOK_SIZE), Image.Resampling.LANCZOS)
    _save_jpeg(looks.apply(im, look_id, strength), Path(out), LOOK_SIZE, 88, icc)


def video_thumb(src: str, out: str, at: float, hdr: bool) -> tuple:
    """Grab one frame (tone-mapped when the video is HDR), write the thumbnail, return its two prints."""
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame = out_path.with_name(out_path.stem + '.frame.png')
    scale = f'scale={THUMB_SIZE * 2}:{THUMB_SIZE * 2}:force_original_aspect_ratio=decrease'
    chain = f'{scale},{TONE_MAP}' if hdr else scale
    subprocess.run(
        [str(config.FFMPEG), '-v', 'error', '-y', '-ss', f'{at:.2f}', '-i', src, '-frames:v', '1', '-vf', chain,
         str(frame)],
        check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        with Image.open(frame) as im:
            im.load()
            _save_jpeg(im, out_path, THUMB_SIZE, 82, None)
            return fingerprint(im), colour_print(im)
    finally:
        frame.unlink(missing_ok=True)
