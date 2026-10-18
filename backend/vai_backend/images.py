"""Faithful XWD decoding and checks against blank Cadence canvases."""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image, UnidentifiedImageError


class ImageError(ValueError):
    """Missing, corrupt, unsupported, or visually empty capture evidence."""


def _decode_xwd(path: Path) -> Image.Image:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ImageError(f'Cannot read XWD {path.name}: {exc}') from exc
    if len(data) < 100:
        raise ImageError(f'{path.name}: incomplete XWD header')
    h = struct.unpack('>25I', data[:100])
    header_size, version, pixmap_format, depth, width, height = h[:6]
    if not (100 <= header_size <= 65536 and version == 7 and pixmap_format == 2
            and depth == 24 and h[6] == 0 and h[7] in (0, 1) and h[11] == 32
            and h[13] == 4 and h[14:17] == (0xFF0000, 0xFF00, 0xFF)):
        raise ImageError(f'{path.name}: unsupported XWD format; expected 24-bit TrueColor/32bpp')
    if not (640 <= width <= 4096 and 400 <= height <= 4096):
        raise ImageError(f'{path.name}: invalid window dimensions {width}x{height}')
    stride, color_count = h[12], h[19]
    if not (width * 4 <= stride <= width * 4 + 4096 and stride % 4 == 0
            and color_count <= 65536):
        raise ImageError(f'{path.name}: invalid row stride or color table')
    offset = header_size + 12 * color_count
    if len(data) != offset + stride * height:
        raise ImageError(f'{path.name}: truncated or trailing XWD pixel data')
    if header_size > len(data) or data[header_size - 1] != 0:
        raise ImageError(f'{path.name}: invalid XWD window-name header')
    try:
        return Image.frombytes('RGB', (width, height), data[offset:], 'raw',
                               'BGRX' if h[7] == 0 else 'XRGB', stride, 1)
    except (ValueError, OSError) as exc:
        raise ImageError(f'{path.name}: cannot decode XWD pixels') from exc


def _canvas_stats(image: Image.Image, kind: str, native: bool = False) -> dict:
    width, height = image.size
    # Exclude menus/toolbars, left navigation/trace legend and ViVA overview.
    # Looking at the whole window incorrectly accepts an empty black canvas.
    if native:
        fractions = (.03, .05, .97, .95) if kind == 'schematic' else (.26, .20, .96, .88)
    else:
        fractions = (.15, .18, .98, .93) if kind == 'schematic' else (.48, .23, .97, .87)
    box = tuple(int(size * frac) for size, frac in zip((width, height, width, height), fractions))
    crop = image.convert('RGB').crop(box)
    counts = dict(cyan=0, red=0, green=0, yellow=0)
    bounds = {name: [crop.width, crop.height, -1, -1] for name in counts}
    for i, (r, g, b) in enumerate(crop.getdata()):
        color = None
        if r < 100 and g > 130 and b > 150:
            color = 'cyan'
        elif r > 150 and g < 90 and b < 90:
            color = 'red'
        elif r < 100 and g > 130 and 50 <= b <= 140:
            color = 'green'
        elif r > 150 and g > 150 and b < 100:
            color = 'yellow'
        if color:
            counts[color] += 1
            x, y = i % crop.width, i // crop.width
            bb = bounds[color]
            bb[0], bb[1], bb[2], bb[3] = min(bb[0], x), min(bb[1], y), max(bb[2], x), max(bb[3], y)
    spans = {key: {'x': max(0, bb[2]-bb[0]+1), 'y': max(0, bb[3]-bb[1]+1)}
             for key, bb in bounds.items()}
    if kind == 'schematic':
        valid = (counts['cyan'] >= 300 and counts['red'] >= 100 and counts['green'] >= 80
                 and spans['cyan']['x'] >= crop.width * .3
                 and spans['cyan']['y'] >= crop.height * .15
                 and spans['green']['x'] >= crop.width * .2)
    else:
        valid = (counts['red'] >= 150 and counts['yellow'] >= 150
                 and spans['red']['x'] >= crop.width * .25
                 and spans['yellow']['x'] >= crop.width * .25
                 and spans['yellow']['y'] >= crop.height * .15)
    if not valid:
        raise ImageError(f'{kind} {"native" if native else "window"} canvas is empty or incomplete: {counts}')
    return {'canvas_box': list(box), 'color_pixels': counts, 'color_spans': spans}


def _native_image(path: Path) -> Image.Image:
    try:
        with Image.open(path) as source:
            if source.format != 'PNG':
                raise ImageError(f'{path.name}: native image must be PNG')
            if not (320 <= source.width <= 4096 and 200 <= source.height <= 4096):
                raise ImageError(f'{path.name}: invalid native image dimensions')
            source.load()
            return source.convert('RGB')
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        if isinstance(exc, ImageError):
            raise
        raise ImageError(f'{path.name}: native image cannot be decoded') from exc


def convert_and_validate(evidence_dir: Path) -> dict:
    """Decode real XWDs losslessly and reject blank/corrupt evidence.

    This render check is for the fixed IC617 RC template and dark theme;
    it is not electrical verification or a substitute for visual review.
    """
    evidence_dir = Path(evidence_dir)
    result = {'ok': True, 'images': {}}
    for kind in ('schematic', 'waveform'):
        xwd = evidence_dir / f'{kind}_window.xwd'
        image = _decode_xwd(xwd)
        png = evidence_dir / f'{kind}_window.png'
        # No redraw, annotation, crop, resize, or synthesized pixels are saved.
        image.save(png, format='PNG')
        stats = _canvas_stats(image, kind)
        result['images'][png.name] = {'width': image.width, 'height': image.height,
                                     'bytes': png.stat().st_size, 'source': xwd.name, **stats}
        native = evidence_dir / f'{kind}_native.png'
        native_image = _native_image(native)
        native_stats = _canvas_stats(native_image, kind, native=True)
        result['images'][native.name] = {'width': native_image.width, 'height': native_image.height,
                                        'bytes': native.stat().st_size, 'source': 'Cadence native export',
                                        **native_stats}
    return result
