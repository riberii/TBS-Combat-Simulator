"""Rebuild the R2 character busts, face portraits, and title logo from the supplied concept boards.

The boards are NOT shipped with the game; pass the folder that holds the unzipped "More Assets 1..4" folders:

    python tools/r2_build_models.py "/path/to/unzipped/boards"

Crop rectangles are in 1344-wide *display* coordinates (the size the boards were reviewed at) and scaled to the real
1536 px width. See Assets/Generated/R2/CROP_PROVENANCE.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Assets" / "Generated" / "R2"
F = 1536 / 1344

KEY_ART = "More Assets 2/Chains of the Abyssal Choir-3.png"
SHOWCASE = "More Assets 1/Fantasy RPG Anime Asset Showcase-15.png"

# class -> (board, display-space crop box, fade-left/right, fade-top, bottom-fade-start)
MODELS = {
    "warrior":      (SHOWCASE, (3, 34, 104, 226), 0.10, 0.03, 0.66),
    "tank":         (KEY_ART, (270, 395, 490, 680), 0.12, 0.03, 0.66),
    "rogue":        (SHOWCASE, (208, 34, 306, 226), 0.10, 0.03, 0.66),
    "witch":        (KEY_ART, (640, 395, 850, 680), 0.13, 0.03, 0.66),
    "fallen_angel": (KEY_ART, (30, 30, 330, 325), 0.10, 0.02, 0.68),
    "kitsune":      (KEY_ART, (380, 55, 640, 330), 0.11, 0.02, 0.68),
    "vampire":      (KEY_ART, (640, 85, 900, 335), 0.11, 0.02, 0.68),
    "dragonkin":    (KEY_ART, (810, 395, 1000, 622), 0.12, 0.03, 0.70),
}
MODEL_H = 480
LOGO_BOX = (975, 25, 1335, 228)


def smooth(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def feather(img: Image.Image, lr: float, top: float, bottom_start: float) -> Image.Image:
    w, h = img.size
    x = np.linspace(0, 1, w)[None, :]
    y = np.linspace(0, 1, h)[:, None]
    a = smooth(x / lr) * smooth((1 - x) / lr) * smooth(y / max(top, 1e-3)) * smooth((1 - y) / (1 - bottom_start))
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    arr[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def crop(board: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    return board.crop(tuple(int(v * F) for v in box)).convert("RGB")


def build(boards: Path) -> None:
    (OUT / "models").mkdir(parents=True, exist_ok=True)
    (OUT / "portraits").mkdir(parents=True, exist_ok=True)
    cache: dict[str, Image.Image] = {}
    for cls, (src, box, lr, top, bot) in MODELS.items():
        board = cache.setdefault(src, Image.open(boards / src).convert("RGB"))
        raw = crop(board, box)
        scale = MODEL_H / raw.height
        big = raw.resize((max(1, int(raw.width * scale)), MODEL_H), Image.LANCZOS).filter(
            ImageFilter.UnsharpMask(radius=1.4, percent=70, threshold=2))
        feather(big, lr, top, bot).save(OUT / "models" / f"{cls}.png")
        face = raw if min(raw.size) >= 190 else raw.resize((raw.width * 2, raw.height * 2), Image.LANCZOS)
        face.save(OUT / "portraits" / f"{cls}.png")
        print(cls, raw.size, "->", big.size)
    # title logo: key out the dark backdrop by brightness so it floats over the key art
    board = cache.setdefault(KEY_ART, Image.open(boards / KEY_ART).convert("RGB"))
    logo = crop(board, LOGO_BOX)
    arr = np.array(logo).astype(np.float32)
    lum = arr.max(axis=2)
    alpha = np.clip((lum - 38.0) / 110.0, 0.0, 1.0)
    out = np.dstack([arr, alpha * 255.0]).astype(np.uint8)
    (OUT / "ui").mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, "RGBA").save(OUT / "ui" / "title_logo.png")
    print("logo", logo.size)



def build_title(boards: Path) -> None:
    """Key art for the menu: all heroes female - the baked male Warrior is blacked out and replaced by the female Warrior bust."""
    from PIL import ImageDraw
    (OUT / "backgrounds").mkdir(parents=True, exist_ok=True)
    board=Image.open(str(boards / KEY_ART)).convert("RGBA")
    wb=Image.open(str(OUT / "models" / "warrior.png"))
    # 1. black out the baked male warrior (display x 0..290, y 360..705), feathered
    x0,y0,x1,y1=[int(v*F) for v in (0,360,292,705)]
    m=np.zeros((board.height,board.width),np.float32); m[y0:y1,x0:x1]=1
    m=np.array(Image.fromarray((m*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(22)),np.float32)/255.0
    arr=np.array(board).astype(np.float32); dark=np.array([12,7,16,255],np.float32)
    for c in range(3): arr[...,c]=arr[...,c]*(1-m*0.985)+dark[c]*m*0.985
    board=Image.fromarray(arr.astype(np.uint8),"RGBA")
    # 2. female warrior bust, smaller, bottom-left, with extra soft left/bottom fade
    bw=int(206*F); sc=bw/wb.width; w2=wb.resize((bw,int(wb.height*sc)),Image.LANCZOS)
    x=int(8*F); y=int(705*F)-w2.height+int(34*F)
    a=np.array(w2); yy=np.linspace(0,1,w2.height)[:,None]
    xx=np.linspace(0,1,w2.width)[None,:]
    a[...,3]=(a[...,3]*np.clip((1-yy)/0.08,0,1)**0.5*np.clip(yy/0.16,0,1)**1.2*np.clip(xx/0.22,0,1)**1.2*np.clip((1-xx)/0.22,0,1)**1.2).astype(np.uint8)
    board.alpha_composite(Image.fromarray(a,"RGBA"),(x,y))
    # 3. relabel: cover old Warrior plaque with a matching dark plaque + text
    d=ImageDraw.Draw(board)
    px0,py0,px1,py1=[int(v*F) for v in (40,642,200,684)]
    d.rectangle((px0,py0,px1,py1),fill=(18,12,20,235))
    try:
        from PIL import ImageFont
        f1=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",24); f2=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",15)
        d.text(((px0+px1)//2,py0+14),"Warrior",font=f1,fill=(235,228,220,255),anchor="mm")
        d.text(((px0+px1)//2,py0+38),"Blade and Momentum",font=f2,fill=(200,190,185,255),anchor="mm")
    except Exception as e: print("font",e)
    art=board.crop((0,0,1120,940)).resize((int(1120*720/940),720),Image.LANCZOS).convert("RGBA")
    w,h=art.size; px=np.array(art).astype(np.float32); fade=170
    xs=np.arange(w)[None,:]
    alpha=np.where(xs<w-fade,255.0,255.0*(w-1-xs)/fade)
    px[...,:3]*=0.82; px[...,3]=np.broadcast_to(alpha,(h,w))
    Image.fromarray(px.astype(np.uint8),"RGBA").save(str(OUT / "backgrounds" / "title_keyart_left_720.png"))
    print("title", art.size)


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    build(root)
    build_title(root)
