"""Core reel-making logic for TBS Reel (no GUI code here).

A reel is a list of items (photos and video clips) turned into one vertical
1080 x 1920 MP4 (9:16, 30 fps, H.264 + AAC), ready for Instagram, Facebook,
TikTok and YouTube Shorts.

How it is made:
  1. Each item becomes a short high-quality segment: photos get a gentle zoom,
     clips are trimmed; both get the TBS logo and the credit line.
  2. The segments (and the optional TBS end card) are joined, the music is
     mixed in, and the reel is encoded once at high quality.
The bundled ffmpeg (from the imageio-ffmpeg package) does the video work.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS = 1080, 1920, 30
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mts", ".m2ts", ".3gp", ".wmv"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma"}

# Instagram / Facebook / TikTok draw their buttons and captions over the bottom
# and the right edge of a reel, so the logo and credit stay inside this area.
SAFE_TOP, SAFE_BOTTOM, SAFE_SIDE = 130, 400, 60

if sys.platform.startswith("win"):
    _NO_WINDOW = {"creationflags": 0x08000000}  # CREATE_NO_WINDOW: no black console boxes
else:
    _NO_WINDOW = {}


def base_dir() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def resource(name: str) -> str:
    """Bundled file (logo, wordmark, fonts). In the source tree they live one level up."""
    for d in (base_dir(), os.path.dirname(base_dir())):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return os.path.join(base_dir(), name)


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        raise RuntimeError("ffmpeg was not found. Reinstall the app.")


# ---------------------------------------------------------------- settings
@dataclass
class ReelSettings:
    photo_secs: float = 3.0       # default length for each new photo
    framing: str = "blur"         # "blur" = whole picture on a blurred copy; "fill" = crop to fill the screen
    motion: str = "zoom"          # "zoom" = gentle zoom on photos (alternating in / out); "none"
    logo_on: bool = True
    logo_corner: str = "top-right"   # top-left / top-right
    logo_size_pct: float = 16.0      # logo width as % of the reel width
    logo_opacity_pct: float = 100.0
    logo_path: str = ""              # empty = built-in TBS logo
    credit_on: bool = True
    photographer: str = ""
    brand: str = "THE BUSINESS STANDARD"
    music_path: str = ""
    music_volume_pct: float = 70.0
    clip_sound: bool = True          # keep the sound recorded with video clips
    clip_volume_pct: float = 100.0
    end_card: bool = True            # TBS logo end card
    end_secs: float = 2.5
    out_dir: str = ""


@dataclass
class Item:
    path: str
    kind: str                     # "photo" or "video"
    length: float = 3.0           # seconds on screen
    start: float = 0.0            # video only: where to start in the clip
    duration: float = 0.0         # video only: full clip length
    has_audio: bool = False       # video only
    meta: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


def kind_of(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    if ext in PHOTO_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    return None


# ---------------------------------------------------------------- ffmpeg helpers
def probe(path: str) -> dict:
    """Duration, size and whether there is sound, read from ffmpeg's own report."""
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True,
                       text=True, errors="replace", **_NO_WINDOW)
    txt = r.stderr
    info = {"duration": 0.0, "has_audio": False, "has_video": False, "width": 0, "height": 0}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    info["has_audio"] = bool(re.search(r"Stream #.*: Audio:", txt))
    vm = re.search(r"Stream #.*: Video:.*?(\d{2,5})x(\d{2,5})", txt)
    if vm:
        info["has_video"] = True
        info["width"], info["height"] = int(vm[1]), int(vm[2])
    return info


def make_item(path: str, photo_secs: float) -> Item | None:
    k = kind_of(path)
    if k == "photo":
        return Item(path, "photo", length=photo_secs)
    if k == "video":
        info = probe(path)
        if not info["has_video"] or info["duration"] <= 0:
            return None
        return Item(path, "video", length=round(info["duration"], 2), duration=info["duration"],
                    has_audio=info["has_audio"], meta=info)
    return None


def video_frame(path: str, t: float = 0.0) -> Image.Image | None:
    """One frame of a clip (upright), for the preview."""
    try:
        r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-ss", f"{max(0, t):.3f}",
                            "-i", path, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, timeout=30, **_NO_WINDOW)
        if r.stdout:
            from io import BytesIO
            return Image.open(BytesIO(r.stdout)).convert("RGB")
    except Exception:
        pass
    return None


def load_photo(path: str, max_side: int = 0) -> Image.Image:
    with Image.open(path) as im:
        if max_side:
            im.draft("RGB", (max_side, max_side))
        im = ImageOps.exif_transpose(im)
        if max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        return im.convert("RGB")


# ---------------------------------------------------------------- picture framing
def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img, (w, h), Image.LANCZOS, centering=(0.5, 0.5))


def frame_picture(img: Image.Image, framing: str, w: int = W, h: int = H) -> Image.Image:
    """Put a picture of any shape onto a w x h vertical canvas."""
    if framing == "fill":
        return _cover(img, w, h)
    # blurred background: a small blurred, slightly darkened copy that fills the screen
    small = _cover(img, max(8, w // 8), max(8, h // 8)).filter(ImageFilter.GaussianBlur(6))
    bg = small.resize((w, h), Image.BICUBIC).point(lambda v: int(v * 0.72))
    s = min(w / img.width, h / img.height)
    fw, fh = max(1, round(img.width * s)), max(1, round(img.height * s))
    bg.paste(img.resize((fw, fh), Image.LANCZOS), ((w - fw) // 2, (h - fh) // 2))
    return bg


# ---------------------------------------------------------------- logo + credit overlay
def _font(name: str, size: int):
    try:
        return ImageFont.truetype(resource(os.path.join("fonts", name)), max(6, size))
    except OSError:
        return ImageFont.load_default(max(6, size))


@lru_cache(maxsize=8)
def _logo(path: str) -> Image.Image | None:
    p = path if path and os.path.exists(path) else resource("logo.png")
    try:
        return Image.open(p).convert("RGBA")
    except Exception:
        return None


def overlay(s: ReelSettings, kind: str, w: int = W, h: int = H) -> Image.Image:
    """Transparent w x h layer with the TBS logo (top corner) and the credit line
    (lower left), both kept clear of the app buttons."""
    k = w / W
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if s.logo_on:
        logo = _logo(s.logo_path)
        if logo is not None:
            lw = max(1, round(w * s.logo_size_pct / 100))
            m = logo.resize((lw, max(1, round(logo.height * lw / logo.width))), Image.LANCZOS)
            if s.logo_opacity_pct < 100:
                m.putalpha(m.getchannel("A").point(lambda a: round(a * s.logo_opacity_pct / 100)))
            x = round(SAFE_SIDE * k) if s.logo_corner == "top-left" else w - lw - round(SAFE_SIDE * k)
            # soft shadow so a white logo still reads on a bright sky
            sh = Image.new("RGBA", m.size, (0, 0, 0, 0))
            sh.putalpha(m.getchannel("A").point(lambda a: a * 90 // 255))
            sh = sh.filter(ImageFilter.GaussianBlur(max(1, round(6 * k))))
            layer.alpha_composite(sh, (x + round(3 * k), round(SAFE_TOP * k) + round(4 * k)))
            layer.alpha_composite(m, (x, round(SAFE_TOP * k)))
    if s.credit_on and (s.brand.strip() or s.photographer.strip()):
        cap = round(30 * k)
        ital = _font("PT_Serif-Web-Italic.ttf", round(cap * 1.0))
        bold = _font("PT_Serif-Web-Bold.ttf", cap)
        parts: list[tuple[object, object]] = []
        try:
            bm = Image.open(resource("brand.png")).convert("RGBA")
            bh = round(cap * 0.85)
            parts.append(("img", bm.resize((max(1, round(bm.width * bh / bm.height)), bh), Image.LANCZOS)))
        except Exception:
            if s.brand.strip():
                parts.append((s.brand.strip().upper(), bold))
        name = s.photographer.strip()
        if name:
            label = "Photo" if kind == "photo" else "Video"
            parts.append((("  |  " if parts else "") + f"{label}: {name}", ital))
        d = ImageDraw.Draw(layer)
        total = sum(p[1].width if p[0] == "img" else d.textlength(p[0], font=p[1]) for p in parts)
        pad_x, pad_y = round(22 * k), round(16 * k)
        x0 = round(SAFE_SIDE * k)
        maxw = w - 2 * x0 - 2 * pad_x
        if total > maxw and len(parts) > 1:      # long name: put the credit under the wordmark
            rows = [parts[:1], [(parts[1][0].strip(" |"), parts[1][1])]]
        else:
            rows = [parts]
        row_h = round(cap * 1.55)
        box_h = row_h * len(rows) + pad_y * 2 - round(cap * 0.3)
        box_w = max(sum(p[1].width if p[0] == "img" else d.textlength(p[0], font=p[1]) for p in r) for r in rows)
        box_w = min(box_w, maxw) + 2 * pad_x
        y0 = h - round(SAFE_BOTTOM * k) - box_h
        pill = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(pill).rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), radius=round(14 * k),
                                               fill=(10, 14, 20, 150))
        layer.alpha_composite(pill)
        d = ImageDraw.Draw(layer)
        for i, r in enumerate(rows):
            x = x0 + pad_x
            base = y0 + pad_y + row_h * i + round(cap * 1.0)
            for text, font in r:
                if text == "img":
                    layer.alpha_composite(font, (x, base - font.height))
                    x += font.width
                else:
                    d.text((x, base), text, font=font, fill=(255, 255, 255, 255), anchor="ls")
                    x += round(d.textlength(text, font=font))
    return layer


def end_card_frame(t: float, total: float, logo_path: str = "") -> Image.Image:
    """TBS end card: the logo and wordmark on dark navy, easing in."""
    img = Image.new("RGB", (W, H), (14, 20, 30))
    p = min(1.0, t / 0.6)
    ease = 1 - (1 - p) ** 3
    logo = _logo(logo_path)
    if logo is not None:
        lw = round(W * (0.40 + 0.04 * ease))
        m = logo.resize((lw, round(logo.height * lw / logo.width)), Image.LANCZOS)
        m.putalpha(m.getchannel("A").point(lambda a: round(a * ease)))
        img.paste(m, ((W - lw) // 2, round(H * 0.40 - m.height / 2)), m)
        try:
            bm = Image.open(resource("brand.png")).convert("RGBA")
            bw = round(W * 0.70)
            b = bm.resize((bw, round(bm.height * bw / bm.width)), Image.LANCZOS)
            b.putalpha(b.getchannel("A").point(lambda a: round(a * ease)))
            img.paste(b, ((W - bw) // 2, round(H * 0.40 + m.height / 2 + 70)), b)
        except Exception:
            pass
    fade_out = max(0.0, min(1.0, (total - t) / 0.4))  # gentle fade to black at the very end
    if fade_out < 1:
        img = img.point(lambda v: int(v * fade_out))
    return img


# ---------------------------------------------------------------- rendering
class Cancelled(Exception):
    pass


def _ease(x: float) -> float:
    return x * x * (3 - 2 * x)


def photo_frames(item: Item, s: ReelSettings, index: int):
    """Yield the frames of a photo with an optional gentle zoom (alternating in and out)."""
    n = max(1, round(item.length * FPS))
    zoom = 1.08 if s.motion == "zoom" else 1.0
    bw, bh = round(W * zoom), round(H * zoom)
    big = frame_picture(load_photo(item.path), s.framing, bw, bh)
    if zoom == 1.0:
        data = big.tobytes()
        for _ in range(n):
            yield data
        return
    zoom_in = index % 2 == 0
    for i in range(n):
        p = _ease(i / max(1, n - 1))
        z = 1 + (zoom - 1) * (p if zoom_in else 1 - p)   # 1 = whole picture, zoom = closest
        cw, ch = bw / z, bh / z
        x0, y0 = (bw - cw) / 2, (bh - ch) / 2
        yield big.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + cw, y0 + ch)).tobytes()


def _run(cmd: list[str], log: str, stdin_frames=None, total_secs: float = 0.0,
         progress: Callable[[float], None] | None = None, cancel: Callable[[], bool] | None = None):
    """Run ffmpeg; feed raw frames on stdin if given; report progress (0..1)."""
    with open(log, "ab") as logf:
        if stdin_frames is not None:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=logf, **_NO_WINDOW)
            try:
                n = max(1, round(total_secs * FPS))
                for i, fr in enumerate(stdin_frames):
                    if cancel and cancel():
                        proc.kill()
                        raise Cancelled()
                    proc.stdin.write(fr)
                    if progress and i % 5 == 0:
                        progress(min(1.0, i / n))
                proc.stdin.close()
            except BrokenPipeError:
                pass
            rc = proc.wait()
        else:
            proc = subprocess.Popen(cmd + ["-progress", "pipe:1", "-nostats"], stdout=subprocess.PIPE,
                                    stderr=logf, text=True, errors="replace", **_NO_WINDOW)
            for line in proc.stdout:
                if cancel and cancel():
                    proc.kill()
                    proc.wait()
                    raise Cancelled()
                if line.startswith("out_time_us=") and progress and total_secs > 0:
                    try:
                        progress(min(1.0, int(line.split("=")[1]) / 1e6 / total_secs))
                    except ValueError:
                        pass
            rc = proc.wait()
    if rc != 0:
        tail = ""
        try:
            with open(log, encoding="utf-8", errors="replace") as f:
                tail = f.read()[-600:]
        except Exception:
            pass
        raise RuntimeError(f"ffmpeg failed (code {rc}).\n{tail}")


# near-lossless intermediate segments; the final encode happens once at the end
_SEG_V = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "8", "-pix_fmt", "yuv420p", "-r", str(FPS)]
_SEG_A = ["-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2"]


def render_segment(item: Item, s: ReelSettings, index: int, out: str, ov_png: str, log: str,
                   progress=None, cancel=None) -> None:
    ff = ffmpeg_exe()
    if item.kind == "photo":
        cmd = [ff, "-y", "-hide_banner", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
               "-r", str(FPS), "-i", "-", "-i", ov_png,
               "-f", "lavfi", "-t", f"{item.length:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
               "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]",
               "-map", "[v]", "-map", "2:a", *_SEG_V, *_SEG_A, "-t", f"{item.length:.3f}", out]
        _run(cmd, log, stdin_frames=photo_frames(item, s, index), total_secs=item.length,
             progress=progress, cancel=cancel)
        return
    # video clip
    if s.framing == "fill":
        vf = (f"[0:v]fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[pic]")
    else:
        vf = (f"[0:v]fps={FPS},split[a][b];"
              f"[a]scale={W // 8}:{H // 8}:force_original_aspect_ratio=increase,crop={W // 8}:{H // 8},"
              f"gblur=sigma=6,scale={W}:{H},eq=brightness=-0.09[bg];"
              f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[pic]")
    vf += ";[pic][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
    use_clip_audio = s.clip_sound and item.has_audio
    if use_clip_audio:
        vol = s.clip_volume_pct / 100
        vf += (f";[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
               f"volume={vol:.3f},apad[a]")
        amap = "[a]"
    else:
        amap = "2:a"
    cmd = [ff, "-y", "-hide_banner", "-ss", f"{item.start:.3f}", "-t", f"{item.length:.3f}", "-i", item.path,
           "-loop", "1", "-i", ov_png,
           "-f", "lavfi", "-t", f"{item.length:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
           "-filter_complex", vf, "-map", "[v]", "-map", amap, *_SEG_V, *_SEG_A,
           "-t", f"{item.length:.3f}", out]
    _run(cmd, log, total_secs=item.length, progress=progress, cancel=cancel)


def render_end_card(s: ReelSettings, out: str, log: str, progress=None, cancel=None) -> None:
    n = max(1, round(s.end_secs * FPS))
    frames = (end_card_frame(i / FPS, s.end_secs, s.logo_path).tobytes() for i in range(n))
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-f", "lavfi", "-t", f"{s.end_secs:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
           "-map", "0:v", "-map", "1:a", *_SEG_V, *_SEG_A, "-t", f"{s.end_secs:.3f}", out]
    _run(cmd, log, stdin_frames=frames, total_secs=s.end_secs, progress=progress, cancel=cancel)


def total_length(items: list[Item], s: ReelSettings) -> float:
    return sum(i.length for i in items) + (s.end_secs if s.end_card and items else 0.0)


def make_reel(items: list[Item], s: ReelSettings, out_path: str,
              progress: Callable[[float, str], None] | None = None,
              cancel: Callable[[], bool] | None = None) -> str:
    """Render the whole reel to out_path (MP4). progress(fraction, message)."""
    if not items:
        raise ValueError("Add some photos or clips first.")
    total = total_length(items, s)
    tmp = tempfile.mkdtemp(prefix="tbs_reel_")
    log = os.path.join(tmp, "ffmpeg.log")
    # time budget: segments ~60%, final encode ~40%
    seg_share = 0.6
    done_secs = 0.0

    def rep(frac, msg):
        if progress:
            progress(max(0.0, min(1.0, frac)), msg)

    try:
        ov = {}
        for kind in ("photo", "video"):
            p = os.path.join(tmp, f"overlay_{kind}.png")
            overlay(s, kind).save(p)
            ov[kind] = p
        segs = []
        for i, it in enumerate(items):
            seg = os.path.join(tmp, f"seg{i:03d}.mp4")
            label = f"Preparing {i + 1} of {len(items)}: {it.name}"
            rep(seg_share * done_secs / total, label)
            base = done_secs
            render_segment(it, s, i, seg, ov[it.kind], log,
                           progress=lambda f, b=base, L=it.length, m=label: rep(seg_share * (b + f * L) / total, m),
                           cancel=cancel)
            segs.append(seg)
            done_secs += it.length
        if s.end_card:
            seg = os.path.join(tmp, "end.mp4")
            rep(seg_share * done_secs / total, "Making the TBS end card")
            render_end_card(s, seg, log, cancel=cancel)
            segs.append(seg)

        # join, add music, final high-quality encode
        cmd = [ffmpeg_exe(), "-y", "-hide_banner"]
        for seg in segs:
            cmd += ["-i", seg]
        n = len(segs)
        fc = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][ca]"
        music = s.music_path if s.music_path and os.path.exists(s.music_path) else ""
        if music:
            cmd += ["-stream_loop", "-1", "-i", music]
            fade = min(2.0, total / 4)
            mv = s.music_volume_pct / 100
            fc += (f";[{n}:a]atrim=0:{total:.3f},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                   f"volume={mv:.3f},afade=t=in:d=0.3,afade=t=out:st={max(0, total - fade):.3f}:d={fade:.3f}[m];"
                   f"[ca][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[a]")
        else:
            fc += ";[ca]anull[a]"
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high", "-level:v", "4.2",
                "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2), "-bf", "2",
                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", "-t", f"{total:.3f}", out_path]
        rep(seg_share, "Putting the reel together (high quality)")
        _run(cmd, log, total_secs=total,
             progress=lambda f: rep(seg_share + (1 - seg_share) * f, "Putting the reel together (high quality)"),
             cancel=cancel)
        rep(1.0, "Done")
        return out_path
    except Cancelled:
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def preview_image(item: Item | None, s: ReelSettings, w: int, h: int) -> Image.Image:
    """What a frame of this item looks like in the reel, at w x h."""
    if item is None:
        return Image.new("RGB", (w, h), (35, 43, 51))
    try:
        pic = load_photo(item.path, 1600) if item.kind == "photo" else video_frame(item.path, item.start + 0.05)
    except Exception:
        pic = None
    if pic is None:
        img = Image.new("RGB", (w, h), (35, 43, 51))
    else:
        img = frame_picture(pic, s.framing, w, h)
    return Image.alpha_composite(img.convert("RGBA"), overlay(s, item.kind, w, h)).convert("RGB")
