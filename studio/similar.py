"""Finding photos that look almost the same, so they can be stacked.

Two prints per picture:
- a 128-bit difference hash: shrink to 9×8 grey dots and note, for each pair of neighbours across and down, which is
  brighter. Good at exact copies, but dark low-contrast scenes (a lit cave) flip many bits between two burst shots.
- a colour print: the picture blurred and shrunk to 12×12 colour dots. Burst shots of one scene stay close even in the
  dark; different scenes drift apart.
Measured on the Yunnan photos (22 Oct 2026): the same scene a second or two apart was 7–29 apart in colour, different
scenes 30 and up.
"""
from PIL import Image, ImageChops, ImageFilter, ImageStat

# Bits that may differ (of 128) for two shots taken close together to count as the same moment.
SIMILAR_BITS = 20
SIMILAR_SECONDS = 10 * 60
# Burst shots: taken within this long, with colour prints at most this far apart (0–255 per channel, averaged).
BURST_SECONDS = 2 * 60
BURST_COLOUR = 28
# A received copy of one of Jack's own photos has no time to compare, so it must match far more closely.
COPY_BITS = 6
COLOUR_DOTS = 12


def fingerprint(image: Image.Image) -> int:
    grey = image.convert('L')
    across = list(grey.resize((9, 8), Image.Resampling.LANCZOS).get_flattened_data())
    down = list(grey.resize((8, 9), Image.Resampling.LANCZOS).get_flattened_data())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = bits << 1 | (across[row * 9 + col] > across[row * 9 + col + 1])
    for row in range(8):
        for col in range(8):
            bits = bits << 1 | (down[row * 8 + col] > down[(row + 1) * 8 + col])
    return bits


def colour_print(image: Image.Image) -> str:
    """The colour print as hex, with 'w' (wide) or 't' (tall) in front: a wide and a tall shot never match."""
    rgb = image.convert('RGB')
    blurred = rgb.filter(ImageFilter.GaussianBlur(max(rgb.size) / 40))
    dots = blurred.resize((COLOUR_DOTS, COLOUR_DOTS), Image.Resampling.BOX).tobytes()
    return ('w' if rgb.width > rgb.height else 't') + dots.hex()


def distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def colour_distance(a: str, b: str) -> float:
    """How far apart two colour prints are, 0–255; infinity when one is wide and the other tall."""
    if a[0] != b[0]:
        return float('inf')
    size = (COLOUR_DOTS, COLOUR_DOTS)
    one = Image.frombytes('RGB', size, bytes.fromhex(a[1:]))
    two = Image.frombytes('RGB', size, bytes.fromhex(b[1:]))
    return sum(ImageStat.Stat(ImageChops.difference(one, two)).mean) / 3


def alike(a: dict, b: dict) -> bool:
    if a['kind'] != b['kind'] or a.get('print') is None or b.get('print') is None:
        return False
    # Same place, different people (one face, then two) are different photos, however alike the background.
    if a.get('faces') is not None and b.get('faces') is not None and a['faces'] != b['faces']:
        return False
    bits = distance(a['print'], b['print'])
    if bits <= COPY_BITS:
        return True
    if a['time'] is None or b['time'] is None:
        return False
    gap = abs(a['time'] - b['time'])
    if gap <= SIMILAR_SECONDS and bits <= SIMILAR_BITS:
        return True
    return gap <= BURST_SECONDS and bool(a.get('colour') and b.get('colour')) and colour_distance(a['colour'], b['colour']) <= BURST_COLOUR


def groups(items: list) -> list:
    """Stacks of look-alikes, as lists of ids, each in the order given. `items` are dicts with id, kind, print (a
    fingerprint or None), colour (a colour print or None) and time (seconds or None)."""
    parent = {item['id']: item['id'] for item in items}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    marked = [i for i in items if i.get('print') is not None]
    for n, a in enumerate(marked):
        for b in marked[n + 1:]:
            if alike(a, b):
                parent[root(a['id'])] = root(b['id'])

    stacks = {}
    for item in items:
        stacks.setdefault(root(item['id']), []).append(item['id'])
    return [ids for ids in stacks.values() if len(ids) > 1]
