# TBS Reel (desktop app)

Makes a vertical reel (1080 x 1920, 9:16, 30 fps MP4) for Instagram, Facebook,
TikTok and YouTube Shorts from photos and video clips.

1. Drop photos and video clips onto the window (or click **Add photos / videos…**).
   Dropping a music file sets the background music.
2. Put them in order with **▲ Earlier / ▼ Later**. Click one to see it in the preview
   and set how long it stays on screen. For a clip you can also set where it starts.
3. Type the photographer's name, then click **Make reel** and choose where to save.

## What goes into the reel
- **TBS logo** in the top corner (left or right, size adjustable).
- **Credit line**: THE BUSINESS STANDARD | Photo: Name (or Video: Name on clips).
- Logo and credit sit inside the "safe area", so the Instagram / TikTok buttons and
  captions don't cover them.
- **Framing**: "Whole picture, blurred background" (default) shows the full photo or clip
  over a blurred copy of itself; "Fill the screen" crops it to fill the frame.
- **Photos**: gentle zoom (alternating in and out) or still. Default 3 seconds each.
- **Sound**: clips keep their own sound (can be turned off). Optional music repeats
  if it's shorter than the reel and fades out at the end.
- **TBS end card**: the logo and wordmark for 2.5 seconds (can be turned off).

## Quality
H.264 High profile, CRF 16 (very high quality), AAC 256 kbps, fast-start MP4.
Pictures are scaled once, from the originals.

## Build the app
- **Windows:** install Python 3.12 from python.org (tick "Add python.exe to PATH"),
  then double-click `reel\build_windows.bat`. The app is `dist\TBS Reel.exe`.
- **Mac:** install Python 3.12 from python.org, then run `./reel/build_mac.sh` in Terminal.
  The app is `dist/TBS Reel.app`.
- The GitHub workflow builds both apps (Watermark and Reel) for Windows and Mac and
  publishes them to the latest release.
