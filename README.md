# TBS Watermark (desktop app)

Drag photos onto the window. Each one is saved with the TBS watermark in the
centre, in a `Watermarked` folder next to the original. Originals are never changed.

## Quality
- Full original resolution, no resizing.
- JPEG saved at maximum quality (100, no chroma subsampling). Tested on a
  4000 x 3000 photo: outside the watermark, pixels differ by at most 1 level out of 255, which is invisible.
- PNG, TIFF and WebP are saved lossless.
- Camera data (EXIF), colour profile and DPI are kept.

## Your logo
Put your logo as `logo.png` (transparent background) in this folder before
building, and it is built into the app. You can also pick a logo inside the
app with "Choose logo…"; the app remembers it. Without a logo it uses the text "TBS".

## Build the app
- **Windows:** install Python 3.12 from python.org (tick "Add python.exe to PATH"),
  then double-click `build_windows.bat`. The app is `dist\TBS Watermark.exe`.
- **Mac:** install Python 3.12 from python.org, then run `./build_mac.sh` in Terminal.
  The app is `dist/TBS Watermark.app`.
- **No setup:** push this folder to a GitHub repo; the included workflow builds
  both the Windows .exe and the Mac app, downloadable from the Actions tab.
