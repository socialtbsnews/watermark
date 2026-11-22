"""Invisible TBS fingerprint.

Version 2 (used for every new photo): a fine TBS-keyed pattern added to the
brightness: about a quarter of a level (out of 255) on smooth areas such as sky,
skin or a blurred background, and up to 3 levels only where the photo has fine
texture, which hides it.
Random dithering spreads it out, so it never forms visible blocks or bands.
People can't see it; "Check photo" can. It survives resizing, JPEG re-saving
(Facebook, WhatsApp), screenshots and cropping up to about a third of each
side. Rotation, mirroring or heavy edits can still remove it.

Version 1 (older exports: larger, +/-3 level blocks) is still recognised by
"Check photo", so photos made with earlier versions of the app still check.
"""
import numpy as np
from PIL import Image

T = 32                                   # the pattern repeats every T x T cells


def _hp(a):
    """Remove the picture itself, keep fine detail (where the pattern lives)."""
    b = np.zeros_like(a)
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            b += np.roll(np.roll(a, dy, 0), dx, 1)
    return a - b / 25


class _Key:
    def __init__(self, seed: int, grid: int):
        self.G = grid                    # the pattern has grid x grid cells across the whole photo
        self.tile = np.random.default_rng(seed).choice([-1.0, 1.0], size=(T, T))
        self.ref = np.conj(np.fft.fft2(_hp(np.tile(self.tile, (3, 3)))[T:2 * T, T:2 * T]))

    def pattern(self, w: int, h: int) -> np.ndarray:
        full = np.tile(self.tile, (self.G // T, self.G // T)).astype(np.float32)
        return np.asarray(Image.fromarray(full, mode="F").resize((w, h), Image.BICUBIC), np.float32)

    def _z(self, L: Image.Image, sx: float, sy: float) -> float:
        w, h = int(round(self.G / sx)), int(round(self.G / sy))
        a = np.asarray(L.resize((w, h), Image.BOX), np.float64)
        a = _hp(a)[2:-2, 2:-2]
        a -= a.mean()
        hh, ww = a.shape
        pad = np.zeros((-(-hh // T) * T, -(-ww // T) * T))
        pad[:hh, :ww] = a
        F = pad.reshape(pad.shape[0] // T, T, pad.shape[1] // T, T).sum((0, 2))
        c = np.real(np.fft.ifft2(np.fft.fft2(F) * self.ref))
        return float((c.max() - c.mean()) / (c.std() + 1e-9))

    def score(self, img: Image.Image, lo: float = 1.0, hi: float = 1.6, step: float = 0.02) -> float:
        """Search the scale the photo was cropped at (1 = not cropped, 1.6 = a third cut off)."""
        L = img.convert("L")
        top = 2 * self.G * hi
        if max(L.size) > top:
            k = top / max(L.size)
            L = L.resize((max(1, round(L.width * k)), max(1, round(L.height * k))), Image.BOX)
        grid = np.arange(lo, hi + 1e-9, step)
        z, bx, by = max((self._z(L, sx, sy), sx, sy) for sx in grid for sy in grid)
        fine = np.arange(-step, step + 1e-9, step / 10)
        for dx in fine:
            for dy in fine:
                z = max(z, self._z(L, bx + dx, by + dy))
        return z


V2 = _Key(0xC0DE, 256)
V1 = _Key(0x7B5, 128)


def _local_mean(a: np.ndarray, r: int) -> np.ndarray:
    p = np.pad(a, r + 1, mode="edge")
    c = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s[: a.shape[0], : a.shape[1]] / (k * k)


def _texture_mask(rgb: np.ndarray, floor: float) -> np.ndarray:
    """0..1 per pixel: low on smooth areas (sky, skin, walls), 1 where there is texture."""
    h, w = rgb.shape[:2]
    Y = Image.fromarray(rgb).convert("L")
    s = max(1, round(max(w, h) / 1024))        # work on a small copy: fast even for 50 MP photos
    sw, sh = max(8, w // s), max(8, h // s)
    y1 = np.asarray(Y.resize((sw, sh), Image.BOX), np.float64)
    y2 = np.asarray(Image.fromarray(np.asarray(Y, np.float32) ** 2, mode="F").resize((sw, sh), Image.BOX),
                    np.float64)
    r = max(2, round(max(sw, sh) / V2.G))      # about one pattern cell
    m1, m2 = _local_mean(y1, r), _local_mean(y2, r)
    sd = np.sqrt(np.maximum(0.0, m2 - m1 * m1))
    mask = np.clip(sd / 6.0, floor, 1.0)
    mask = _local_mean(_local_mean(mask, r), r)                 # soft edges
    return np.asarray(Image.fromarray(mask.astype(np.float32), mode="F").resize((w, h), Image.BILINEAR),
                      np.float32)


def embed(img: Image.Image, amp: float = 3.0, floor: float = 0.1) -> Image.Image:
    """Add the invisible fingerprint. amp = strength in levels where the photo has texture;
    floor = the share of it used on smooth areas."""
    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    d = V2.pattern(w, h) * np.float32(amp) * _texture_mask(rgb, floor)
    d += np.random.default_rng(0x5EED).random((h, w), dtype=np.float32) - np.float32(0.5)   # dither
    step = np.floor(d + np.float32(0.5)).astype(np.int16)
    out = rgb.astype(np.int16) + step[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def score(img: Image.Image) -> float:
    """Higher = stronger match. Unmarked photos score about 4 to 5; marked ones 9 and up."""
    return max(V2.score(img), V1.score(img, 1.0, 1.31, 0.025))


def verdict(z: float) -> str:
    if z >= 8:
        return "yes"
    if z >= 6.5:
        return "maybe"
    return "no"
