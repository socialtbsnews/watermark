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
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont, ImageOps

SUPPORTED = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


@dataclass
class Settings:
    logo_path: str = ""          # PNG with transparency recommended; empty = text "TBS"
    text: str = "TBS"            # used only when no logo is set
    size_pct: float = 25.0       # watermark width as % of photo width
    opacity_pct: float = 60.0    # 0-100
    out_dir_name: str = "Watermarked"
    suffix: str = "_TBS"


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


def apply_watermark(photo: Image.Image, settings: Settings) -> Image.Image:
    """Return a new image with the watermark centred. Same pixel size as input."""
    base = ImageOps.exif_transpose(photo)  # upright, lossless pixel reorder
    had_alpha = base.mode in ("RGBA", "LA") or "transparency" in base.info
    work = base.convert("RGBA")
    mark = build_mark(settings, work.width)
    x = (work.width - mark.width) // 2
    y = (work.height - mark.height) // 2
    layer = Image.new("RGBA", work.size, (0, 0, 0, 0))
    layer.paste(mark, (x, y), mark)
    out = Image.alpha_composite(work, layer)
    return out if had_alpha else out.convert("RGB")


def output_path(src: str, settings: Settings) -> str:
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
