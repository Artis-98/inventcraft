"""Write the beaver tile in each colour scheme's colour, from the navy one.

The navy tiles in datum/ui/brand are the drawn originals. Each other
colour is the same picture with only the navy moved: a pixel is shifted by
as much of the change as it has of the navy's colour in it, so the flat
background becomes the new colour exactly, the black and white engraving
is left alone, and the soft edges between them blend as before.

    python tools/make_theme_icons.py

writes datum/ui/brand/<colour>/inventcraft-<size>.png for every size.
"""
from __future__ import annotations

import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(ROOT, "datum", "ui", "brand")
NAVY = (0x26, 0x3A, 0x64)
COLOURS = {
    "copper": (0xA8, 0x56, 0x3C),
    "charcoal": (0x42, 0x4A, 0x50),
    "olive": (0x6C, 0x77, 0x3E),
}
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def recolour(image: Image.Image, colour) -> Image.Image:
    navy_chroma = max(NAVY) - min(NAVY)
    shift = [c - n for c, n in zip(colour, NAVY)]
    out = image.convert("RGBA").copy()
    pixels = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = pixels[x, y]
            if not a:
                continue
            # how much of the navy is in it: its colourfulness against the
            # navy's, the engraving being grey
            w = min(1.0, (max(r, g, b) - min(r, g, b)) / navy_chroma)
            pixels[x, y] = tuple(
                max(0, min(255, int(round(v + w * d))))
                for v, d in zip((r, g, b), shift)) + (a,)
    return out


def main() -> None:
    for name, colour in COLOURS.items():
        folder = os.path.join(BRAND, name)
        os.makedirs(folder, exist_ok=True)
        for size in SIZES:
            source = Image.open(os.path.join(
                BRAND, "inventcraft-%d.png" % size))
            recolour(source, colour).save(os.path.join(
                folder, "inventcraft-%d.png" % size))
        print("wrote", folder)


if __name__ == "__main__":
    main()
