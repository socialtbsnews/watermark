# TBS Watermark (desktop app)

Drag photos onto the window. Each one is saved with the TBS watermark in the
centre, in a `Watermarked` folder next to the original, or in any folder you pick with "Output folder…". Originals are never changed.

## Photo credit
Type the photographer's name in "Photo by". Every photo gets a credit line, in the
corner you pick under "Credit at" (top left, top right, bottom left or bottom right): **THE BUSINESS STANDARD | Photo: Name**, white on a soft dark fade.
Untick "Show credit line" to leave it off. Font: PT Serif (SIL Open Font License, see `fonts/OFL.txt`).

## Protection
- **Protective pattern** (off by default): a faint TBS logo repeated across the whole
  photo, with a new random position, size and angle for every tile and every photo.
  Removing it means repainting the entire picture. "Pattern" sets its strength.
- **Hidden fingerprint** (on by default): an invisible TBS code (each pixel changes by
  at most about 5 levels out of 255). It survives resizing, JPEG re-saving, screenshots and crops of up to
  about 20% per side. Use **Check photo…** on any image to see if it came from TBS.
  Rotation, very large crops or heavy edits can defeat it. No watermark is impossible to remove.

## Quality
- Full original resolution, no resizing.
- JPEG saved at maximum quality (100, no chroma subsampling). Tested on a
  4000 x 3000 photo: outside the watermark, pixels differ by at most 1 level out of 255, which is invisible (up to about 5 levels with the hidden fingerprint on, still invisible).
- PNG, TIFF and WebP are saved lossless.
- Camera data (EXIF), colour profile and DPI are kept.

## Your logo
The TBS logo (`logo.png`) is built into the app.
building, and it is built into the app. You can also pick a logo inside the
app with "Choose logo…"; the app remembers it. Without a logo it uses the text "TBS".

## Build the app
- **Windows:** install Python 3.12 from python.org (tick "Add python.exe to PATH"),
  then double-click `build_windows.bat`. The app is `dist\TBS Watermark.exe`.
- **Mac:** install Python 3.12 from python.org, then run `./build_mac.sh` in Terminal.
  The app is `dist/TBS Watermark.app`.
- **No setup:** push this folder to a GitHub repo; the included workflow builds
  both the Windows .exe and the Mac app, downloadable from the Actions tab.
