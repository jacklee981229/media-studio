"""Who made each file: Jack's own phone, someone else (WhatsApp and the like), or a screenshot.

Jack's phone writes its make and model into every photo and video. Messaging apps strip them, and WhatsApp also
shrinks photos to about 1280 px. So the camera that made most of a trip's files is taken to be Jack's own.
"""
from collections import Counter

MINE, RECEIVED, SCREENSHOT = 'mine', 'received', 'screenshot'

# WhatsApp sends photos at most 1600 px on the long side unless HD is chosen; then up to 4096.
WHATSAPP_LONG_SIDE = 1600


def camera(meta: dict):
    make, model = meta.get('make'), meta.get('model')
    return (make, model) if make and model else None


def own_camera(metas: list):
    """The camera that made the most files, or None when nothing names a camera."""
    counts = Counter(c for c in map(camera, metas) if c)
    return counts.most_common(1)[0][0] if counts else None


def classify(meta: dict, kind: str, own) -> tuple:
    """(source, reason): the reason is shown beside the file, so a wrong guess is easy to spot."""
    if meta.get('comment') == 'Screenshot':
        return SCREENSHOT, '截图（文件里写着 Screenshot）'
    cam = camera(meta)
    if cam and cam == own:
        return MINE, f'{cam[1]} 拍的'
    if cam:
        return RECEIVED, f'别的相机拍的：{cam[0]} {cam[1]}'
    if kind == 'photo' and meta.get('format') == 'PNG':
        return SCREENSHOT, 'PNG，没有相机信息'
    long_side = max(meta.get('width') or 0, meta.get('height') or 0)
    if kind == 'photo' and 0 < long_side <= WHATSAPP_LONG_SIDE:
        return RECEIVED, f'没有相机信息，{meta["width"]}×{meta["height"]}（WhatsApp 常见的大小）'
    return RECEIVED, '没有相机信息（被发送的 App 删掉了）'
