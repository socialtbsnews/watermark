"""Core watermarking logic for TBS Watermark (no GUI code here).

Quality rules:
  * The photo keeps its original resolution; pixels are never resized.
  * PNG / TIFF output is lossless.
  * JPEG output is saved at maximum quality (100, 4:4:4 chroma, no subsampling),
    so the re-encode is visually identical to the original.
  * EXIF (camera data), ICC colour profile and DPI are carried over.
"""
from __future__ import annotations

import os
import random
import sys
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont, ImageOps

import fingerprint

SUPPORTED = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


@dataclass
class Settings:
    logo_path: str = ""          # PNG with transparency recommended; empty = text "TBS"
    text: str = "TBS"            # used only when no logo is set
    size_pct: float = 25.0       # watermark width as % of photo width
    opacity_pct: float = 60.0    # 0-100
    out_dir_name: str = "Watermarked"
    out_dir: str = ""            # chosen output folder; empty = "Watermarked" next to each photo
    suffix: str = "_TBS"
    credit_on: bool = True       # bottom-left photo credit line
    brand: str = "THE BUSINESS STANDARD"
    photographer: str = ""       # e.g. "Syed Zakir Hossain"; empty = brand only
    credit_pos: str = "bottom-left"  # top-left, top-right, bottom-left, bottom-right
    protect: bool = False        # faint randomised logo pattern over the whole photo
    protect_pct: float = 10.0    # pattern opacity
    hidden_mark: bool = True     # invisible TBS fingerprint


def _font_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "fonts", name)


def _font(name: str, size: int):
    try:
        return ImageFont.truetype(_font_path(name), max(6, size))
    except OSError:
        return ImageFont.load_default(max(6, size))


def draw_credit(img: Image.Image, settings: Settings) -> Image.Image:
    """Bottom-left credit: BRAND (small caps, bold serif) | Photo: Name (italic)."""
    if not settings.credit_on or not (settings.brand.strip() or settings.photographer.strip()):
        return img
    W, H = img.size
    cap = max(10, round(min(W, H * 1.5) * 0.026))   # full-cap height scale
    small = round(cap * 0.78)
    bold_big, bold_small = _font("PT_Serif-Web-Bold.ttf", cap), _font("PT_Serif-Web-Bold.ttf", small)
    ital = _font("PT_Serif-Web-Italic.ttf", round(cap * 0.95))

    # Brand: the TBS wordmark image if bundled, else small-caps text
    brand_img = None
    bp = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "brand.png")
    if settings.brand.strip() and os.path.exists(bp):
        bm = Image.open(bp).convert("RGBA")
        bh = round(cap * 0.85)
        brand_img = bm.resize((max(1, round(bm.width * bh / bm.height)), bh), Image.LANCZOS)

    runs = []
    brand = settings.brand.strip().upper()
    if brand and brand_img is None:
        for i, word in enumerate(brand.split()):
            if i:
                runs.append((" ", bold_small))
            runs.append((word[0], bold_big))
            if len(word) > 1:
                runs.append((word[1:], bold_small))
    name = settings.photographer.strip()
    if name:
        runs.append((" | " if brand else "", ital))
        runs.append((f"Photo: {name}", ital))

    pos = settings.credit_pos if settings.credit_pos in ("top-left", "top-right", "bottom-left", "bottom-right") else "bottom-left"
    at_top, at_right = pos.startswith("top"), pos.endswith("right")

    # Soft dark band behind the text for legibility on bright photos
    band_h = round(cap * 4.2)
    grad = Image.new("L", (1, band_h))
    for y in range(band_h):
        t = (band_h - 1 - y) if at_top else y
        grad.putpixel((0, y), round(150 * (t / band_h) ** 1.6))
    shade = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    shade.putalpha(grad.resize((W, band_h)))
    out = img.convert("RGBA")
    band = Image.new("RGBA", out.size, (0, 0, 0, 0))
    band.paste(shade, (0, 0 if at_top else H - band_h))
    out = Image.alpha_composite(out, band)

    d = ImageDraw.Draw(out)
    margin = round(W * 0.025)
    total = (brand_img.width if brand_img is not None else 0) + sum(d.textlength(t, font=f) for t, f in runs)
    x = round(W - margin - total) if at_right else margin
    baseline = round(cap * 2.0) if at_top else H - round(cap * 1.1)
    shadow = max(1, round(cap * 0.05))
    if brand_img is not None:
        sh = Image.new("RGBA", brand_img.size, (0, 0, 0, 0))
        sh.putalpha(brand_img.getchannel("A").point(lambda a: a * 110 // 255))
        top = baseline - brand_img.height
        out.alpha_composite(sh, (x + shadow, top + shadow))
        out.alpha_composite(brand_img, (x, top))
        x += brand_img.width
    for text, font in runs:
        d.text((x + shadow, baseline + shadow), text, font=font, fill=(0, 0, 0, 110), anchor="ls")
        d.text((x, baseline), text, font=font, fill=(255, 255, 255, 255), anchor="ls")
        x += d.textlength(text, font=font)
    return out


def _text_mark(text: str, width: int) -> Image.Image:
    font = None
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "Helvetica.ttc"):
        try:
            font = ImageFont.truetype(name, 400)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default(400)
    box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    pad = 40
    im = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((pad - box[0], pad - box[1]), text, font=font, fill=(255, 255, 255, 255),
           stroke_width=6, stroke_fill=(0, 0, 0, 90))
    return im


def build_mark(settings: Settings, photo_w: int) -> Image.Image:
    if settings.logo_path and os.path.exists(settings.logo_path):
        mark = Image.open(settings.logo_path).convert("RGBA")
    else:
        mark = _text_mark(settings.text or "TBS", photo_w)
    target_w = max(1, round(photo_w * settings.size_pct / 100))
    target_h = max(1, round(mark.height * target_w / mark.width))
    mark = mark.resize((target_w, target_h), Image.LANCZOS)
    if settings.opacity_pct < 100:
        alpha = mark.getchannel("A").point(lambda a: round(a * settings.opacity_pct / 100))
        mark.putalpha(alpha)
    return mark


def _place(layer: Image.Image, m: Image.Image, px: int, py: int) -> None:
    """alpha_composite m onto layer at (px, py), clipping at the edges."""
    l, t = max(0, -px), max(0, -py)
    r, b = min(m.width, layer.width - px), min(m.height, layer.height - py)
    if r > l and b > t:
        layer.alpha_composite(m.crop((l, t, r, b)), (px + l, py + t))


def protective_pattern(work: Image.Image, settings: Settings) -> Image.Image:
    """Repeat the logo faintly across the photo with random jitter per tile, so
    removing it means repainting the whole picture. New randomness every photo."""
    W, H = work.size
    s = Settings(**{**settings.__dict__, "size_pct": 11.0, "opacity_pct": settings.protect_pct})
    base = build_mark(s, W)
    rng = random.Random()
    step_x, step_y = base.width * 1.9, base.height * 1.9
    layer = Image.new("RGBA", work.size, (0, 0, 0, 0))
    row = 0
    y = -step_y / 2
    while y < H + step_y:
        x = -step_x / 2 + (step_x / 2 if row % 2 else 0)
        while x < W + step_x:
            k = rng.uniform(0.8, 1.2)
            m = base.resize((max(1, int(base.width * k)), max(1, int(base.height * k))), Image.BICUBIC)
            m = m.rotate(rng.uniform(-25, 25), resample=Image.BICUBIC, expand=True)
            jx = rng.uniform(-0.25, 0.25) * step_x
            jy = rng.uniform(-0.25, 0.25) * step_y
            _place(layer, m, int(x + jx - m.width / 2), int(y + jy - m.height / 2))
            x += step_x
        y += step_y
        row += 1
    return Image.alpha_composite(work, layer)


def apply_watermark(photo: Image.Image, settings: Settings) -> Image.Image:
    """Return a new image with the watermark centred. Same pixel size as input."""
    base = ImageOps.exif_transpose(photo)  # upright, lossless pixel reorder
    had_alpha = base.mode in ("RGBA", "LA") or "transparency" in base.info
    work = base.convert("RGBA")
    if settings.protect:
        work = protective_pattern(work, settings)
    mark = build_mark(settings, work.width)
    x = (work.width - mark.width) // 2
    y = (work.height - mark.height) // 2
    layer = Image.new("RGBA", work.size, (0, 0, 0, 0))
    layer.paste(mark, (x, y), mark)
    out = draw_credit(Image.alpha_composite(work, layer), settings)
    if settings.hidden_mark:
        alpha = out.getchannel("A")
        out = fingerprint.embed(out)
        if had_alpha:
            out.putalpha(alpha)
    return out if had_alpha else out.convert("RGB")


def output_path(src: str, settings: Settings) -> str:
    if settings.out_dir and os.path.isdir(settings.out_dir):
        folder = settings.out_dir
    else:
        folder = os.path.join(os.path.dirname(src), settings.out_dir_name)
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(src))
    path = os.path.join(folder, f"{stem}{settings.suffix}{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem}{settings.suffix}_{n}{ext}")
        n += 1
    return path


def process_file(src: str, settings: Settings) -> str:
    ext = os.path.splitext(src)[1].lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {ext}")
    with Image.open(src) as photo:
        photo.load()
        info = photo.info
        exif = photo.getexif()
        if 0x0112 in exif:
            exif[0x0112] = 1  # pixels are now upright
        out = apply_watermark(photo, settings)

    dst = output_path(src, settings)
    kw = {}
    if info.get("icc_profile"):
        kw["icc_profile"] = info["icc_profile"]
    if info.get("dpi"):
        kw["dpi"] = info["dpi"]
    exif_bytes = exif.tobytes() if len(exif) else None

    if ext in (".jpg", ".jpeg"):
        if out.mode != "RGB":
            out = out.convert("RGB")
        if exif_bytes:
            kw["exif"] = exif_bytes
        out.save(dst, "JPEG", quality=100, subsampling=0, optimize=True, **kw)
    elif ext == ".png":
        if exif_bytes:
            kw["exif"] = exif_bytes
        out.save(dst, "PNG", optimize=True, **kw)
    elif ext in (".tif", ".tiff"):
        if exif_bytes:
            kw["exif"] = exif_bytes
        out.save(dst, "TIFF", compression="tiff_lzw", **kw)
    elif ext == ".webp":
        if exif_bytes:
            kw["exif"] = exif_bytes
        out.save(dst, "WEBP", lossless=True, quality=100, **kw)
    return dst
