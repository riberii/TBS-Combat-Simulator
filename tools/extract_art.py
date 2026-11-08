"""Reproducible crop pipeline: cuts game-ready art out of the user's concept boards ("More Assets 1-4").

The boards themselves are NOT shipped (they are ~120 MB); the cropped outputs and this script's box table are.
Run:  python tools/extract_art.py <dir-containing-board-pngs> [out_dir]
Kitsune and Dragonkin keep their earlier portraits (cropped from the 'Chains of the Abyssal Choir-3' board). Each crop records (board file, box) so every shipped image is traceable back to its source board.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from PIL import Image, ImageFilter, ImageEnhance

# (output relative path, board filename stem, (l, t, r, b), kind)
# kind: portrait -> square-ish upscaled bust, bg -> blurred/vignetted 16:9 background, raw -> copied as-is
CROPS = [
    # --- backgrounds (tiles are ~190x100 in the boards; they are upscaled + softened into painterly backdrops)
    ("backgrounds/academy_courtyard", "Fallen Angel Game Asset Sheet-1", (16, 408, 202, 506), "bg"),
    ("backgrounds/academy_hall_night", "Fallen Angel Game Asset Sheet-1", (211, 408, 399, 506), "bg"),
    ("backgrounds/library",           "Fallen Angel Game Asset Sheet-1", (409, 408, 544, 506), "bg"),
    ("backgrounds/chapel",            "Fallen Angel Game Asset Sheet-1", (553, 408, 663, 506), "bg"),
    ("backgrounds/ruined_cathedral",  "Fallen Angel Game Asset Sheet-1", (16, 527, 202, 625), "bg"),
    ("backgrounds/forest_path",       "Fallen Angel Game Asset Sheet-1", (211, 527, 389, 625), "bg"),
    ("backgrounds/boss_arena",        "Fallen Angel Game Asset Sheet-1", (401, 527, 546, 625), "bg"),
    ("backgrounds/hidden_room",       "Fallen Angel Game Asset Sheet-1", (555, 527, 664, 625), "bg"),
    ("backgrounds/abyssal_academy",   "Dark Fantasy Anime Game Asset Sheet-7", (832, 26, 1268, 160), "bg"),
    ("backgrounds/main_hall",         "Dark Fantasy Anime Game Asset Sheet-7", (1272, 26, 1534, 160), "bg"),
    ("backgrounds/terrace",           "Dark Fantasy Anime Game Asset Sheet-7", (1068, 196, 1296, 301), "bg"),
    ("backgrounds/abyssal_realm",     "Dark Fantasy Anime Game Asset Sheet-7", (1304, 196, 1534, 301), "bg"),
    ("backgrounds/library_dark",      "Dark Fantasy Anime Game Asset Sheet-7", (832, 196, 1062, 301), "bg"),
    # --- boss / companion / card art
    ("bosses/vael_banner", "Fantasy RPG Asset Board-17", (1152, 31, 1525, 208), "raw"),
    ("companions/snow_owl", "Fallen Angel Game Asset Sheet-1", (1098, 398, 1204, 478), "fx"),
    ("cards/face_flame", "Fallen Angel Game Asset Sheet-1", (1086, 526, 1129, 599), "card"),
    ("cards/face_frost", "Fallen Angel Game Asset Sheet-1", (1135, 526, 1177, 599), "card"),
    ("cards/face_blood", "Fallen Angel Game Asset Sheet-1", (1182, 526, 1223, 599), "card"),
    ("cards/face_resonance", "Fallen Angel Game Asset Sheet-1", (1228, 526, 1269, 599), "card"),
    ("cards/face_fate", "Fallen Angel Game Asset Sheet-1", (1274, 526, 1315, 599), "card"),
    ("cards/back_red", "Fallen Angel Game Asset Sheet-1", (1089, 654, 1138, 733), "card"),
    ("cards/back_blue", "Fallen Angel Game Asset Sheet-1", (1148, 654, 1196, 733), "card"),
    ("cards/back_purple", "Fallen Angel Game Asset Sheet-1", (1206, 654, 1254, 733), "card"),
    ("cards/back_gold", "Fallen Angel Game Asset Sheet-1", (1263, 654, 1312, 733), "card"),
    # --- chain VFX (black background -> alpha-from-luminance)
    ("fx/chain_ring_red_a", "Fallen Angel Game Asset Sheet-1", (1286, 40, 1374, 106), "fx"),
    ("fx/chain_silver_vertical", "Fallen Angel Game Asset Sheet-1", (1362, 36, 1416, 116), "fx"),
    ("fx/chain_ring_red_b", "Fallen Angel Game Asset Sheet-1", (1431, 38, 1514, 104), "fx"),
    ("fx/chain_ring_silver_a", "Fallen Angel Game Asset Sheet-1", (1286, 118, 1357, 160), "fx"),
    ("fx/chain_red_diagonal", "Fallen Angel Game Asset Sheet-1", (1351, 110, 1425, 177), "fx"),
    ("fx/chain_ring_thorn", "Fallen Angel Game Asset Sheet-1", (1430, 120, 1510, 164), "fx"),
    ("fx/chain_silver_diagonal", "Fallen Angel Game Asset Sheet-1", (1286, 183, 1365, 250), "fx"),
    ("fx/chain_silver_tangle", "Fallen Angel Game Asset Sheet-1", (1346, 181, 1414, 253), "fx"),
    ("fx/chain_ring_red_c", "Fallen Angel Game Asset Sheet-1", (1416, 185, 1504, 245), "fx"),
    # --- elemental burst VFX
    ("fx/elem_fire", "Fallen Angel Game Asset Sheet-1", (1083, 281, 1141, 343), "fx"),
    ("fx/elem_ice", "Fallen Angel Game Asset Sheet-1", (1146, 281, 1205, 343), "fx"),
    ("fx/elem_lightning", "Fallen Angel Game Asset Sheet-1", (1212, 281, 1266, 343), "fx"),
    ("fx/elem_dark", "Fallen Angel Game Asset Sheet-1", (1273, 281, 1331, 343), "fx"),
    ("fx/elem_holy", "Fallen Angel Game Asset Sheet-1", (1336, 281, 1394, 343), "fx"),
    ("fx/elem_blood", "Fallen Angel Game Asset Sheet-1", (1401, 281, 1460, 343), "fx"),
    ("fx/elem_wind", "Fallen Angel Game Asset Sheet-1", (1466, 281, 1520, 343), "fx"),
]
ICON_GRID_A = [("potion_red",1358,413),("potion_blue",1404,413),("potion_purple",1454,413),("potion_pink",1504,413),
               ("key_gold",1358,457),("tome",1404,457),("mace",1454,457),("scroll_book",1504,457)]
ICON_GRID_B = [("flask_red",1360,534),("flask_cyan",1406,534),("amulet",1454,534),("wand",1500,534),
               ("scroll",1360,580),("feather",1406,580),("key_ornate",1454,580),("vial",1500,580),
               ("orb_dark",1360,627),("orb_gear",1406,627),("gem_heart",1454,627),("scroll_case",1500,627)]
for _n, _cx, _cy in ICON_GRID_A + ICON_GRID_B:
    CROPS.append((f"icons/{_n}", "Fallen Angel Game Asset Sheet-1", (_cx - 20, _cy - 20, _cx + 20, _cy + 20), "icon"))

# --- character models: GrabCut cut-outs (RGBA standees) + matching portraits. All eight are adult female characters.
# (class key, board stem, box, up-scale, grabcut iters, extra probable-foreground rects as fractions (l,t,r,b), fade bottom)
SHOWCASE = "Dark Fantasy Anime Game Asset Showcase-9"
MODELS = [
    ("warrior",      SHOWCASE, (12, 40, 138, 262), 3, 6, [], False),
    ("tank",         SHOWCASE, (402, 40, 527, 262), 3, 6, [], False),
    ("rogue",        SHOWCASE, (275, 40, 400, 262), 3, 6, [], False),
    ("witch",        SHOWCASE, (142, 24, 272, 262), 3, 8, [(0.05, 0.0, 0.95, 0.30)], False),
    ("vampire",      SHOWCASE, (652, 40, 775, 262), 3, 6, [], False),
    ("fallen_angel", "Fallen Angel Game Asset Sheet-1", (55, 15, 300, 385), 2, 8, [], False),
    ("kitsune",      "Chains of the Abyssal Choir-3", (430, 40, 730, 372), 2, 8, [], True),
    ("dragonkin",    SHOWCASE, (778, 40, 900, 262), 3, 6, [], False),
]
# class key -> (board stem, square head box) for portraits that must match the model (replaces the earlier male crops)
PORTRAITS = {
    "warrior": (SHOWCASE, (22, 38, 128, 144)),
    "tank": (SHOWCASE, (412, 38, 518, 144)),
    "rogue": (SHOWCASE, (285, 38, 391, 144)),
    "witch": (SHOWCASE, (152, 38, 262, 148)),
    "vampire": (SHOWCASE, (660, 38, 766, 144)),
    "fallen_angel": ("Fallen Angel Game Asset Sheet-1", (100, 28, 262, 190)),
    "dragonkin": (SHOWCASE, (786, 38, 892, 144)),
}


def grabcut_model(im: Image.Image, up: int, iters: int, fg_rects, fade_bottom: bool) -> Image.Image:
    """Cut a character out of a plain-ish card background (dev-time; needs opencv-python). Returns RGBA."""
    import cv2
    import numpy as np
    im = im.resize((im.width * up, im.height * up), Image.LANCZOS)
    a = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    h, w = a.shape[:2]
    mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    cv2.ellipse(mask, (w // 2, int(h * 0.55)), (int(w * 0.40), int(h * 0.55)), 0, 0, 360, cv2.GC_PR_FGD, -1)
    for l, t, r, b in fg_rects:
        cv2.rectangle(mask, (int(w * l), int(h * t)), (int(w * r), int(h * b)), cv2.GC_PR_FGD, -1)
    cv2.rectangle(mask, (int(w * 0.30), int(h * 0.2)), (int(w * 0.70), h), cv2.GC_FGD, -1)
    m = int(w * 0.04)
    mask[:, :m] = cv2.GC_BGD; mask[:, -m:] = cv2.GC_BGD; mask[:m, :] = cv2.GC_BGD
    bg = np.zeros((1, 65)); fg = np.zeros((1, 65))
    cv2.grabCut(a, mask, None, bg, fg, iters, cv2.GC_INIT_WITH_MASK)
    m2 = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    m2 = cv2.morphologyEx(m2, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    m2 = cv2.morphologyEx(m2, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m2)
    if n > 1:
        k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        m2 = np.where(lab == k, 255, 0).astype(np.uint8)
    m2 = cv2.GaussianBlur(m2, (0, 0), 2.2).astype("float32")
    if fade_bottom:  # bust-up crops: dissolve the cut edge instead of a hard line
        ramp = np.clip((h - np.arange(h)) / (h * 0.14), 0, 1)[:, None]
        m2 *= ramp
    out = np.dstack([np.asarray(im), m2.astype("uint8")])
    img = Image.fromarray(out, "RGBA")
    scale = 460 / img.height
    return img.resize((max(1, round(img.width * scale)), 460), Image.LANCZOS)


def find_board(src: Path, stem: str) -> Path:
    for p in src.rglob("*.png"):
        if p.stem == stem or p.stem.replace("#U2019", "’") == stem:
            return p
    raise FileNotFoundError(stem)


def to_portrait(im: Image.Image, size: int = 256) -> Image.Image:
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    im = im.resize((size, size), Image.LANCZOS)
    return im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=60, threshold=2))


def to_background(im: Image.Image, w: int = 1280, h: int = 720) -> Image.Image:
    """Cover-fit to 16:9, soften the upscale, add vignette; leaves foreground sprites readable."""
    iw, ih = im.size
    target = w / h
    if iw / ih > target:
        nw = int(ih * target); im = im.crop(((iw - nw) // 2, 0, (iw - nw) // 2 + nw, ih))
    else:
        nh = int(iw / target); im = im.crop((0, (ih - nh) // 2, iw, (ih - nh) // 2 + nh))
    # upscale in two steps for fewer ringing artefacts
    im = im.resize((im.width * 3, im.height * 3), Image.BICUBIC).resize((w, h), Image.LANCZOS)
    im = im.filter(ImageFilter.GaussianBlur(1.6))
    im = ImageEnhance.Contrast(im).enhance(1.08)
    import numpy as np
    a = np.asarray(im).astype("float32")
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    vig = np.clip(1.0 - 0.45 * np.clip(r - 0.45, 0, 1), 0.45, 1.0)[..., None]
    a *= vig * 0.92
    rng = np.random.default_rng(7)
    a += rng.normal(0, 2.2, a.shape[:2])[..., None]  # light grain hides upscale banding
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


def luma_alpha(im: Image.Image, scale: int = 3) -> Image.Image:
    """Black-background VFX -> RGBA (alpha from brightness) so it can be alpha-blitted or additively blended."""
    import numpy as np
    im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    a = np.asarray(im).astype("float32")
    lum = a.max(axis=2)
    alpha = np.clip((lum - 14.0) * 2.4, 0, 255)
    out = np.dstack([a, alpha]).astype("uint8")
    return Image.fromarray(out, "RGBA")


def to_icon(im: Image.Image, size: int = 96) -> Image.Image:
    """Small boxed icon -> soft circular-masked RGBA at 2.4x."""
    import numpy as np
    im = im.resize((size, size), Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.2, 55, 2))
    yy, xx = np.mgrid[0:size, 0:size]
    r = np.sqrt(((xx - size / 2) / (size / 2)) ** 2 + ((yy - size / 2) / (size / 2)) ** 2)
    alpha = np.clip((1.02 - r) / 0.16, 0, 1) * 255
    rgba = np.dstack([np.asarray(im), alpha]).astype("uint8")
    return Image.fromarray(rgba, "RGBA")


def to_card(im: Image.Image) -> Image.Image:
    return im.resize((im.width * 4, im.height * 4), Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.6, 60, 2))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__); return 2
    src = Path(argv[1]); out = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parents[1] / "Assets" / "Art"
    manifest = []
    boards: dict[str, Image.Image] = {}
    for rel, stem, box, kind in CROPS:
        if stem not in boards:
            boards[stem] = Image.open(find_board(src, stem)).convert("RGB")
        im = boards[stem].crop(box)
        if kind == "portrait":
            im = to_portrait(im)
        elif kind == "bg":
            im = to_background(im)
        elif kind == "fx":
            im = luma_alpha(im)
        elif kind == "icon":
            im = to_icon(im)
        elif kind == "card":
            im = to_card(im)
        dest = out / (f"{rel}.jpg" if kind == "bg" else f"{rel}.png")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.suffix == ".jpg":
            im.convert("RGB").save(dest, quality=90, optimize=True)
        else:
            im.save(dest, optimize=True)
        manifest.append({"file": dest.relative_to(out).as_posix(), "source_board": stem, "box": list(box), "kind": kind, "size": list(im.size)})
    def board_img(stem: str) -> Image.Image:
        if stem not in boards:
            boards[stem] = Image.open(find_board(src, stem)).convert("RGB")
        return boards[stem]

    for key, stem, box, up, iters, fg_rects, fade in MODELS:
        model = grabcut_model(board_img(stem).crop(box), up, iters, fg_rects, fade)
        dest = out / "models" / f"{key}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        model.save(dest, optimize=True)
        manifest.append({"file": f"models/{key}.png", "source_board": stem, "box": list(box), "kind": "model", "size": list(model.size)})
    for key, (stem, box) in PORTRAITS.items():
        p = to_portrait(board_img(stem).crop(box), 256)
        dest = out / "portraits" / f"{key}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        p.save(dest, optimize=True)
        manifest.append({"file": f"portraits/{key}.png", "source_board": stem, "box": list(box), "kind": "portrait", "size": list(p.size)})
    (out / "ART_SOURCES.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"wrote {len(manifest)} crops to {out}")
    from tools.cover_angel import main as cover_angel   # dress the Fallen Angel's bare chest (see tools/cover_angel.py)
    cover_angel([str(out)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
