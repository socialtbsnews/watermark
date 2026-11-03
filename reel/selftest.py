"""Quick check that the reel engine works on this computer (used by the build).
Makes a 2-photo + 1-clip reel from generated pictures and checks the result."""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image  # noqa: E402

from reel_core import H, W, ReelSettings, ffmpeg_exe, make_item, make_reel, probe  # noqa: E402

d = tempfile.mkdtemp()
Image.new("RGB", (1600, 1000), (200, 80, 40)).save(os.path.join(d, "a.jpg"))
Image.new("RGB", (900, 1400), (40, 90, 200)).save(os.path.join(d, "b.png"))
clip = os.path.join(d, "c.mp4")
subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=2",
                "-f", "lavfi", "-i", "sine=d=2", "-c:v", "libx264", "-c:a", "aac", "-shortest", clip], check=True)
items = [make_item(os.path.join(d, n), 1.0) for n in ("a.jpg", "c.mp4", "b.png")]
assert all(items), items
out = os.path.join(d, "reel.mp4")
make_reel(items, ReelSettings(photographer="Test", end_secs=1.0), out)
info = probe(out)
print(info)
assert (info["width"], info["height"]) == (W, H), info
assert info["has_audio"] and abs(info["duration"] - 5.0) < 0.2, info
print("Reel engine OK")
