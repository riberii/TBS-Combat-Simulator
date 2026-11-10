"""Give the Fallen Angel's standee and portrait a white-lavender dress top (covers the bare chest).

Works on the *extracted* art: inside a hand-placed chest region, skin-coloured pixels are recoloured to white-lavender
dress fabric sampled from her own white dress (same lavender-white, same shading range) while keeping the original
light/dark detail, so chains, straps and shading stay on top. Run it after
``tools/extract_art.py`` (extract_art calls it automatically). It is idempotent: once the skin is gone there is nothing
left to recolour.

Usage: python tools/cover_angel.py [--src DIR_WITH_ORIGINALS --dst Assets/Art]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "Assets" / "Art"

# Chest regions in each image's own pixel space (polygon around the bust and ribcage, excluding face, neck and arms).
REGIONS = {
    "models/fallen_angel.png": [(138, 124), (172, 120), (228, 134), (230, 204), (168, 214), (138, 190)],
    "portraits/fallen_angel.png": [(116, 138), (150, 130), (218, 140), (226, 192), (208, 240), (122, 240), (116, 200)],
}
# Colours sampled from the standee's own white dress (shade ~ (146,133,149), mid ~ (170,158,173), light ~ (200,189,202)).
DRESS_SHADE = np.array([138.0, 126.0, 150.0])  # fabric in the deepest folds of the chest area
DRESS_LIGHT = np.array([240.0, 232.0, 246.0])  # lit fabric


def _skin_mask(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lum = (r + g + b) / 3.0
    return (r > 140) & (r - g > 20) & (r - b > 14) & (lum > 120)


RESIDUAL_OK = 40   # fewer skin-coloured pixels than this left in the region == covered (tests allow 60)


def _skin_left(rgb: np.ndarray, region: Image.Image) -> int:
    return int((_skin_mask(rgb) & (np.asarray(region) > 0)).sum())


def cover(path: Path) -> int:
    """Recolour skin inside the region (repeating until covered); returns the number of pixels changed.

    A file that is already covered is left byte-for-byte untouched, so running this twice is a no-op.
    """
    key = f"{path.parent.name}/{path.name}"
    im = Image.open(path)
    has_alpha = im.mode == "RGBA"
    rgba = np.asarray(im.convert("RGBA")).astype(np.float32)
    h, w = rgba.shape[:2]
    region = Image.new("L", (w, h), 0)
    ImageDraw.Draw(region).polygon(REGIONS[key], fill=255)
    if _skin_left(rgba[..., :3], region) < RESIDUAL_OK:
        return 0
    changed = 0
    for _ in range(4):
        rgba, n = _cover_once(rgba, region)
        changed = max(changed, n)
        if _skin_left(rgba[..., :3], region) < RESIDUAL_OK:
            break
    result = Image.fromarray(np.clip(np.rint(rgba), 0, 255).astype(np.uint8), "RGBA")
    if not has_alpha:
        result = result.convert("RGB")
    result.save(path)
    return changed


def _cover_once(rgba: np.ndarray, region: Image.Image) -> tuple[np.ndarray, int]:
    rgb = rgba[..., :3]
    h, w = rgb.shape[:2]
    skin = Image.fromarray((_skin_mask(rgb) & (np.asarray(region) > 0)).astype(np.uint8) * 255)
    skin = skin.filter(ImageFilter.MaxFilter(3))                       # swallow the anti-aliased skin edge
    cover_m = np.minimum(np.asarray(skin.filter(ImageFilter.GaussianBlur(1.2))).astype(np.float32) / 255.0,
                         np.asarray(region.filter(ImageFilter.GaussianBlur(1.5))).astype(np.float32) / 255.0 + 0.0)
    cover_m = np.clip(cover_m * 1.15, 0, 1)
    lum = np.clip((rgb.mean(axis=2) - 125.0) / 115.0, 0.0, 1.0)[..., None]   # 0 (shadow) .. 1 (lit skin)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    folds = (np.sin(xx * 0.55 + yy * 0.18) * 0.5 + np.sin(xx * 0.23 - yy * 0.31) * 0.5)[..., None] * 5.0   # faint cloth weave
    fabric = DRESS_SHADE + (DRESS_LIGHT - DRESS_SHADE) * (lum ** 0.9) + folds
    out = rgb * (1 - cover_m[..., None]) + fabric * cover_m[..., None]
    rgba = rgba.copy()
    rgba[..., :3] = out
    return rgba, int((cover_m > 0.5).sum())


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else ART
    total = 0
    for rel in REGIONS:
        p = root / rel
        if p.is_file():
            n = cover(p)
            total += n
            print(f"cover_angel: {rel}: {n} px recoloured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
