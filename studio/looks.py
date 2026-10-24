"""The trip looks. Each look is a colour recipe turned into a 3D colour table (LUT), so one table can colour both the
photos (Pillow) and, later, the videos (ffmpeg's lut3d): the same look everywhere in a trip.

Recipes work on the picture's own encoded values (0–1), as the eye sees them, and stay gentle: iPhone photos are
already well exposed, so a look only shifts mood.
"""
import colorsys
from functools import lru_cache

from PIL import Image, ImageFilter

SIZE = 33  # table points per colour; the usual size for photo and video LUTs

# People need little colouring (Jack, 22 Oct 2026: "人像的话，不需要怎么调色"), so portraits get each look at
# a fraction of its strength; landscapes get it whole.
STRENGTH = {'portrait': 0.4, 'landscape': 1.0}

LOOKS = {
    'A': {'name': '清透', 'idea': '像天气更好的那天：通透、干净，颜色稍微鲜一点，最接近原片。',
          'contrast': 0.10, 'vibrance': 0.22, 'warmth': 0.008},
    'B': {'name': '暖胶片', 'idea': '柔和、温暖，暗部微微发灰，绿色偏橄榄，像老胶片。',
          'contrast': 0.16, 'black': 0.05, 'white': 0.975, 'saturation': 0.9, 'warmth': 0.035,
          'shadow_tint': (0.53, 0.49, 0.45), 'highlight_tint': (0.53, 0.51, 0.47), 'tint_amount': 0.35, 'olive': True},
    'C': {'name': '冷调电影', 'idea': '阴影带一点青，肤色和灯光偏暖，饱和低一些，安静的电影感。',
          'contrast': 0.22, 'black': 0.02, 'saturation': 0.84,
          'shadow_tint': (0.44, 0.52, 0.55), 'highlight_tint': (0.55, 0.51, 0.46), 'tint_amount': 0.5},
    'D': {'name': '淡雅', 'idea': '明亮、低对比、有空气感，红色淡一点，暗部带一点青绿。',
          'gain': 1.05, 'contrast': -0.14, 'black': 0.075, 'saturation': 0.86, 'calm_reds': True,
          'shadow_tint': (0.47, 0.52, 0.50), 'tint_amount': 0.3},
}


def _luma(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _clamp(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _s_curve(x, amount):
    """Contrast around the middle grey: amount > 0 deepens, < 0 flattens."""
    smooth = x * x * (3 - 2 * x)
    return x + amount * (smooth - x)


def recipe(look: dict):
    """The look as a function from one colour (r, g, b in 0–1) to another."""
    def colour(r, g, b):
        # Brightening lifts the middle but keeps white at white, so skies don't burn out.
        gain = look.get('gain', 1.0)
        r, g, b = (x * gain / (1 + (gain - 1) * x) for x in (r, g, b))
        warmth = look.get('warmth', 0.0)
        r, g, b = r * (1 + warmth), g, b * (1 - warmth)
        r, g, b = (_s_curve(_clamp(x), look.get('contrast', 0.0)) for x in (r, g, b))
        light = _luma(r, g, b)
        saturation = look.get('saturation', 1.0)
        vibrance = look.get('vibrance', 0.0)
        if vibrance:
            # Pale colours gain more than strong ones, so skin and red signs don't go loud.
            saturation *= 1 + vibrance * (1 - (max(r, g, b) - min(r, g, b)))
        r, g, b = (light + (x - light) * saturation for x in (r, g, b))
        if look.get('olive') or look.get('calm_reds'):
            h, s, v = colorsys.rgb_to_hsv(_clamp(r), _clamp(g), _clamp(b))
            degrees = h * 360
            if look.get('olive') and 70 <= degrees <= 170:
                h, s = (degrees - 10 * (1 - abs(degrees - 120) / 50)) / 360, s * 0.88
            if look.get('calm_reds') and (degrees <= 25 or degrees >= 335):
                s *= 0.85
            r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
        amount = look.get('tint_amount', 0.0)
        if amount:
            light = _luma(r, g, b)
            low, high = (1 - light) ** 2 * amount, light ** 2 * amount
            shadow, highlight = look.get('shadow_tint', (0.5, 0.5, 0.5)), look.get('highlight_tint', (0.5, 0.5, 0.5))
            r, g, b = (x + (s - 0.5) * low + (h_ - 0.5) * high for x, s, h_ in zip((r, g, b), shadow, highlight))
        black, white = look.get('black', 0.0), look.get('white', 1.0)
        return tuple(_clamp(black + (white - black) * _clamp(x)) for x in (r, g, b))
    return colour


@lru_cache(maxsize=16)
def table(look_id: str, strength: float = 1.0) -> ImageFilter.Color3DLUT:
    """The look's colour table, mixed with the untouched colours by `strength` (0–1)."""
    colour = recipe(LOOKS[look_id])

    def mixed(r, g, b):
        out = colour(r, g, b)
        return tuple(x + (o - x) * strength for x, o in zip((r, g, b), out))

    return ImageFilter.Color3DLUT.generate(SIZE, mixed)


def apply(image: Image.Image, look_id, strength: float = 1.0) -> Image.Image:
    if not look_id:
        return image
    return image.convert('RGB').filter(table(look_id, round(strength, 2)))


def _to_light(v: float) -> float:
    """sRGB and Display P3 share this curve: encoded value to linear light."""
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _to_value(light: float) -> float:
    light = 0.0 if light < 0 else 1.0 if light > 1 else light
    return light * 12.92 if light <= 0.0031308 else 1.055 * light ** (1 / 2.4) - 0.055


@lru_cache(maxsize=64)
def _adjust_table(exposure: float, warmth: float) -> list:
    """Per-channel tables for one photo's brightness (stops) and warmth (-1 cool to 1 warm), in linear light."""
    gain = 2 ** exposure
    table = []
    for channel_gain in (1 + 0.1 * warmth, 1.0, 1 - 0.1 * warmth):
        for v in range(256):
            light = _to_light(v / 255) * channel_gain
            # Brightening lifts the middle and keeps white at white; darkening scales everything down.
            light = light * gain / (1 + (gain - 1) * light) if gain >= 1 else light * gain
            table.append(round(_to_value(light) * 255))
    return table


def develop(image: Image.Image, look_id, strength: float, exposure: float = 0, warmth: float = 0) -> Image.Image:
    """The photo as it will be published: its own brightness and warmth first, then the trip's look over it. The
    preview and the export both come from here, so what Jack sees is what goes out."""
    image = image.convert('RGB')
    if exposure or warmth:
        image = image.point(_adjust_table(round(exposure, 2), round(warmth, 2)))
    return apply(image, look_id, strength)


def cube(look_id, strength: float = 1.0) -> str:
    """The look as a .cube file for ffmpeg's lut3d, so videos get exactly the photos' colours. Pillow's table and
    the .cube format both run red fastest, then green, then blue."""
    values = table(look_id, round(strength, 2)).table
    rows = (f'{values[n]:.6f} {values[n + 1]:.6f} {values[n + 2]:.6f}' for n in range(0, len(values), 3))
    return f'LUT_3D_SIZE {SIZE}\n' + '\n'.join(rows) + '\n'


def summary() -> list:
    return [{'id': k, 'name': v['name'], 'idea': v['idea']} for k, v in LOOKS.items()]
