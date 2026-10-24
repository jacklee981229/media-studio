"""People or scenery: each gets its own trip look, and people are coloured more lightly.

Measured on the Yunnan photos (22 Oct 2026): a tourist standing small in front of the stone forest still has a face
2–3% of the picture's width; nobody posed was smaller. So a face at least 2% wide makes a photo a portrait.
"""
PORTRAIT, LANDSCAPE = 'portrait', 'landscape'
FACE_WIDTH = 0.02


def classify(meta: dict, kind: str, source: str):
    """(subject, reason) for a photo; (None, None) for a video."""
    if kind != 'photo':
        return None, None
    found = meta.get('faces')
    if found is None:
        if source == 'mine':
            return LANDSCAPE, '没拍到人脸'
        return PORTRAIT, '收到的照片里没有人脸信息，先当人像（多半是合照）'
    big = [w for w in found if w >= FACE_WIDTH]
    if big:
        return PORTRAIT, f'有 {len(big)} 张脸' if len(big) > 1 else '有人脸'
    if found:
        return LANDSCAPE, '人在远处，很小，算风景'
    return LANDSCAPE, '没拍到人脸'
