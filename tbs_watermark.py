"""TBS Watermark - desktop app.

1. Drop photos (or a folder) onto the window.
2. Check each one in the preview; drag the logo anywhere on the photo.
3. Click Export. Every photo is saved with the watermark, credit line and
   protection, into the chosen output folder. Originals are never touched.
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import asdict
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

import fingerprint
from watermark_core import SUPPORTED, Settings, apply_watermark, build_mark, mark_origin, process_file

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:  # app still works with the "Add photos" button
    HAS_DND = False

CONFIG = os.path.join(os.path.expanduser("~"), ".tbs_watermark.json")
BG, PANEL, INK, MUTED, ACCENT = "#1B2128", "#232B33", "#E6EAEE", "#9AA5B1", "#F97316"
FONT = ("Segoe UI", 10)
PHOTO_TYPES = [("Photos", "*.jpg *.jpeg *.png *.tif *.tiff *.webp")]


def resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def load_settings() -> Settings:
    s = Settings()
    try:
        with open(CONFIG, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if hasattr(s, k):
                    setattr(s, k, v)
    except Exception:
        pass
    if not (s.logo_path and os.path.exists(s.logo_path)) and os.path.exists(resource("logo.png")):
        s.logo_path = resource("logo.png")
    return s


def save_settings(s: Settings) -> None:
    data = asdict(s)
    if data["logo_path"] == resource("logo.png"):
        data["logo_path"] = ""  # built-in logo: its temp path changes every launch
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def open_folder(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def load_preview(path: str) -> Image.Image | None:
    try:
        with Image.open(path) as im:
            im.draft("RGB", (1600, 1600))
            im = ImageOps.exif_transpose(im)
            im.thumbnail((1600, 1600))
            return im.convert("RGB")
    except Exception:
        return None


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.s = load_settings()
        self.files: list[str] = []          # photos waiting to be exported
        self.pos: dict[str, tuple[float, float]] = {}  # per-photo logo position
        self.cur = 0
        self.full_preview: Image.Image | None = None   # current photo, up to 1600 px
        self.thumb: Image.Image | None = None          # current photo at display size
        self.preview_img = None
        self.drag = None
        self.redraw_pending = False
        self.last_folder = ""

        root.title("TBS Watermark")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{min(1180, sw - 60)}x{min(720, sh - 90)}")
        root.minsize(820, 520)
        root.configure(bg=BG)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TScale", background=BG)

        # ---------------- left: preview
        left = tk.Frame(root, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(16, 8), pady=12)
        head = tk.Frame(left, bg=BG)
        head.pack(fill="x", pady=(0, 8))
        tk.Label(head, text="TBS", fg=ACCENT, bg=BG, font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(head, text=" Watermark", fg=INK, bg=BG, font=("Segoe UI", 18, "bold")).pack(side="left")

        self.canvas = tk.Canvas(left, bg=PANEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.refresh(resize=True))
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        if HAS_DND:
            for w in (self.canvas, root):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)

        nav = tk.Frame(left, bg=BG)
        nav.pack(fill="x", pady=(8, 0))
        self._btn(nav, "◀ Prev", self.prev).pack(side="left")
        self._btn(nav, "Next ▶", self.next).pack(side="left", padx=6)
        self.nav_lbl = tk.Label(nav, bg=BG, fg=MUTED, font=FONT, anchor="w")
        self.nav_lbl.pack(side="left", padx=8, fill="x", expand=True)
        self._btn(nav, "Centre logo", self.centre).pack(side="right")
        self._btn(nav, "Remove photo", self.remove).pack(side="right", padx=6)

        # ---------------- right: controls
        right = tk.Frame(root, bg=BG, width=360)
        right.pack(side="right", fill="y", padx=(8, 16), pady=12)
        right.pack_propagate(False)

        # bottom of the panel first, so it is always visible
        foot = tk.Frame(right, bg=BG)
        foot.pack(side="bottom", fill="x")
        self.status = tk.Label(foot, text="", bg=BG, fg=MUTED, font=FONT, anchor="w",
                               justify="left", wraplength=340)
        self.status.pack(fill="x", pady=(0, 6))
        row = tk.Frame(foot, bg=BG)
        row.pack(fill="x")
        self.export_btn = tk.Button(row, text="Export", command=self.export, state="disabled",
                                    bg=ACCENT, fg="#1A0F06", activebackground=ACCENT, relief="flat",
                                    font=("Segoe UI", 11, "bold"), padx=12, pady=7)
        self.export_btn.pack(side="left", fill="x", expand=True)
        self.open_btn = self._btn(row, "Open folder", self.open_out)
        self.open_btn.config(state="disabled")
        self.open_btn.pack(side="left", padx=(6, 0))

        body = tk.Frame(right, bg=BG)
        body.pack(side="top", fill="both", expand=True)

        self._section(body, "PHOTOS")
        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=2)
        self._btn(r, "Add photos…", self.choose_photos).pack(side="left")
        self._btn(r, "Clear all", self.clear).pack(side="left", padx=6)
        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=2)
        self._btn(r, "Output folder…", self.choose_out).pack(side="left")
        self._btn(r, "Default folder", self.reset_out).pack(side="left", padx=6)
        self.out_lbl = tk.Label(body, bg=BG, fg=MUTED, font=FONT, anchor="w", justify="left", wraplength=340)
        self.out_lbl.pack(fill="x")

        self._section(body, "LOGO")
        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=2)
        self._btn(r, "Choose logo…", self.choose_logo).pack(side="left")
        self.logo_lbl = tk.Label(r, bg=BG, fg=MUTED, font=FONT, anchor="w")
        self.logo_lbl.pack(side="left", padx=8)
        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=2)
        tk.Label(r, text="Look", width=8, anchor="w", bg=BG, fg=INK, font=FONT).pack(side="left")
        self.style_menu = ttk.Combobox(r, state="readonly", width=24, font=FONT,
                                       values=["Dark glass", "Plain logo"])
        self.style_menu.set("Plain logo" if self.s.style == "plain" else "Dark glass")
        self.style_menu.bind("<<ComboboxSelected>>", lambda e: self.style_changed())
        self.style_menu.pack(side="left")
        self.size_var = tk.DoubleVar(self.root, value=self.s.size_pct)
        self.op_var = tk.DoubleVar(self.root, value=self.s.opacity_pct)
        self._slider(body, "Size", self.size_var, 5, 80)
        self._slider(body, "Opacity", self.op_var, 0, 100)

        self._section(body, "CREDIT")
        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=2)
        tk.Label(r, text="Photo by", width=8, anchor="w", bg=BG, fg=INK, font=FONT).pack(side="left")
        self.name_var = tk.StringVar(self.root, value=self.s.photographer)
        tk.Entry(r, textvariable=self.name_var, bg=PANEL, fg=INK, insertbackground=INK,
                 relief="flat", font=("Segoe UI", 11)).pack(side="left", fill="x", expand=True, ipady=3)
        self.name_var.trace_add("write", lambda *_: self.credit_changed())
        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=2)
        self.credit_var = tk.BooleanVar(self.root, value=self.s.credit_on)
        self._check(r, "Show", self.credit_var, self.credit_changed).pack(side="left")
        self.pos_var = tk.StringVar(self.root, value=self.s.credit_pos)
        self.pos_menu = ttk.Combobox(r, state="readonly", width=14, font=FONT,
                                     values=["Bottom left", "Bottom right", "Top left", "Top right"])
        self.pos_menu.set(self.s.credit_pos.replace("-", " ").capitalize())
        self.pos_menu.bind("<<ComboboxSelected>>", lambda e: self.credit_changed())
        self.pos_menu.pack(side="left", padx=8)

        self._section(body, "PROTECTION")
        self.hidden_var = tk.BooleanVar(self.root, value=self.s.hidden_mark)
        self.protect_var = tk.BooleanVar(self.root, value=self.s.protect)
        r = tk.Frame(body, bg=BG); r.pack(fill="x")
        self._check(r, "Hidden fingerprint", self.hidden_var, self.protect_changed).pack(side="left")
        self._btn(r, "Check photo…", self.check_photo).pack(side="right")
        self._check(body, "Protective pattern", self.protect_var, self.protect_changed).pack(anchor="w")
        self.prot_var = tk.DoubleVar(self.root, value=self.s.protect_pct)
        self._slider(body, "Pattern", self.prot_var, 4, 40)

        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=(12, 0))
        self._btn(r, "Reset all settings", self.reset_all).pack(side="left")

        self.refresh_logo_label()
        self.refresh_out_label()
        self.update_nav()
        self.set_status("Drop photos anywhere on this window, or click Add photos."
                        if HAS_DND else "Click Add photos to begin.")

    # ---------------- widget helpers
    def _btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=PANEL, fg=INK, activebackground=ACCENT,
                         activeforeground="#1A0F06", relief="flat", font=FONT, padx=10, pady=4)

    def _check(self, parent, text, var, cmd):
        return tk.Checkbutton(parent, text=text, variable=var, command=cmd, bg=BG, fg=INK, font=FONT,
                              selectcolor=PANEL, activebackground=BG, activeforeground=INK)

    def _section(self, parent, title):
        tk.Label(parent, text=title, bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x", pady=(10, 2))

    def _slider(self, parent, label, var, lo, hi):
        r = tk.Frame(parent, bg=BG)
        r.pack(fill="x", pady=1)
        tk.Label(r, text=label, width=8, anchor="w", bg=BG, fg=INK, font=FONT).pack(side="left")
        val = tk.Label(r, width=5, anchor="e", bg=BG, fg=MUTED, font=FONT)

        def changed(_v=None):
            val.config(text=f"{var.get():.0f}%")
            self.s.size_pct = round(self.size_var.get())
            self.s.opacity_pct = round(self.op_var.get())
            if hasattr(self, "prot_var"):
                self.s.protect_pct = round(self.prot_var.get())
            save_settings(self.s)
            self.refresh()

        ttk.Scale(r, from_=lo, to=hi, variable=var, command=changed).pack(side="left", fill="x", expand=True)
        val.pack(side="left")
        val.config(text=f"{var.get():.0f}%")
        if not hasattr(self, "_slider_labels"):
            self._slider_labels = []
        self._slider_labels.append(lambda: val.config(text=f"{var.get():.0f}%"))

    def set_status(self, text):
        self.status.config(text=text)

    # ---------------- settings callbacks
    def credit_changed(self):
        self.s.photographer = self.name_var.get()
        self.s.credit_on = bool(self.credit_var.get())
        if hasattr(self, "pos_menu"):
            self.s.credit_pos = self.pos_menu.get().lower().replace(" ", "-")
        save_settings(self.s)
        self.refresh()

    def style_changed(self):
        self.s.style = "plain" if self.style_menu.get() == "Plain logo" else "glass"
        save_settings(self.s)
        self.refresh(resize=False)

    def reset_all(self):
        """Back to the factory look. Keeps the photographer name, logo and output folder."""
        keep = {k: getattr(self.s, k) for k in ("photographer", "logo_path", "out_dir")}
        self.s = Settings(**keep)
        if not (self.s.logo_path and os.path.exists(self.s.logo_path)) and os.path.exists(resource("logo.png")):
            self.s.logo_path = resource("logo.png")
        self.size_var.set(self.s.size_pct)
        self.op_var.set(self.s.opacity_pct)
        self.prot_var.set(self.s.protect_pct)
        self.credit_var.set(self.s.credit_on)
        self.hidden_var.set(self.s.hidden_mark)
        self.protect_var.set(self.s.protect)
        self.pos_menu.set(self.s.credit_pos.replace("-", " ").capitalize())
        self.style_menu.set("Plain logo" if self.s.style == "plain" else "Dark glass")
        for f in self.files:
            self.pos[f] = (0.5, 0.5)
        for refresh_label in getattr(self, "_slider_labels", []):
            refresh_label()
        save_settings(self.s)
        self.refresh()
        self.set_status("Settings reset: logo centred, size 25%, opacity 60%, dark glass look.")

    def protect_changed(self):
        self.s.protect = bool(self.protect_var.get())
        self.s.hidden_mark = bool(self.hidden_var.get())
        save_settings(self.s)
        self.refresh()

    # ---------------- photo list
    def add_files(self, files):
        new = [f for f in files if os.path.splitext(f)[1].lower() in SUPPORTED and f not in self.files]
        if not new:
            self.set_status("No new photos found (JPG, PNG, TIFF or WebP).")
            return
        for f in new:
            self.pos[f] = (self.s.pos_x, self.s.pos_y)
        self.files += new
        self.cur = len(self.files) - len(new)
        self.load_current()
        self.set_status(f"{len(new)} photo{'s' if len(new) != 1 else ''} added. "
                        "Drag the logo to place it, then click Export.")

    def current(self):
        return self.files[self.cur] if self.files else None

    def load_current(self):
        f = self.current()
        self.full_preview = load_preview(f) if f else None
        if f and self.full_preview is None:
            self.set_status(f"Could not open {os.path.basename(f)}.")
        self.update_nav()
        self.refresh(resize=True)

    def update_nav(self):
        n = len(self.files)
        if n:
            self.nav_lbl.config(text=f"{self.cur + 1} of {n}:  {os.path.basename(self.files[self.cur])}")
            self.export_btn.config(state="normal", text=f"Export {n} photo{'s' if n != 1 else ''}")
        else:
            self.nav_lbl.config(text="No photos yet")
            self.export_btn.config(state="disabled", text="Export")

    def prev(self):
        if self.files:
            self.cur = (self.cur - 1) % len(self.files)
            self.load_current()

    def next(self):
        if self.files:
            self.cur = (self.cur + 1) % len(self.files)
            self.load_current()

    def remove(self):
        f = self.current()
        if f:
            self.files.remove(f)
            self.pos.pop(f, None)
            self.cur = min(self.cur, max(0, len(self.files) - 1))
            self.load_current()

    def clear(self):
        self.files, self.pos, self.cur = [], {}, 0
        self.load_current()

    def centre(self):
        f = self.current()
        if f:
            self.pos[f] = (0.5, 0.5)
            self.s.pos_x, self.s.pos_y = 0.5, 0.5
            save_settings(self.s)
            self.refresh()

    # ---------------- preview drawing
    def settings_for(self, f):
        px, py = self.pos.get(f, (self.s.pos_x, self.s.pos_y))
        return dataclasses.replace(self.s, pos_x=px, pos_y=py)

    def refresh(self, resize=False):
        """Redraw the preview, at most once per idle cycle (keeps dragging smooth)."""
        if resize:
            self.thumb = None
        if not self.redraw_pending:
            self.redraw_pending = True
            self.root.after_idle(self._draw)

    def _draw(self):
        self.redraw_pending = False
        c = self.canvas
        cw, ch = max(50, c.winfo_width()), max(50, c.winfo_height())
        c.delete("all")
        if self.full_preview is None:
            c.create_text(cw // 2, ch // 2, fill=MUTED, font=("Segoe UI", 14), justify="center",
                          text="Drop photos here\n\nor click Add photos")
            self.img_box = None
            return
        if self.thumb is None:
            self.thumb = self.full_preview.copy()
            self.thumb.thumbnail((cw - 16, ch - 16))
        st = self.settings_for(self.current())
        marked = apply_watermark(self.thumb, st)
        self.preview_img = ImageTk.PhotoImage(marked, master=self.root)
        x0, y0 = (cw - marked.width) // 2, (ch - marked.height) // 2
        c.create_image(x0, y0, image=self.preview_img, anchor="nw")
        self.img_box = (x0, y0, marked.width, marked.height)
        # outline the logo so people see it can be dragged
        mark = build_mark(st, marked.width)
        mx, my = mark_origin(marked.width, marked.height, mark.width, mark.height, st)
        c.create_rectangle(x0 + mx, y0 + my, x0 + mx + mark.width, y0 + my + mark.height,
                           outline=ACCENT, dash=(4, 3))
        self.mark_box = (x0 + mx, y0 + my, mark.width, mark.height)
        c.config(cursor="fleur")

    # ---------------- dragging the logo
    def on_press(self, e):
        if not self.files or not getattr(self, "img_box", None):
            self.choose_photos()
            return
        x0, y0, w, h = self.img_box
        px, py = self.pos[self.current()]
        # grab offset: keep the logo under the cursor where it was grabbed
        self.drag = (px * w + x0 - e.x, py * h + y0 - e.y)
        self.on_move(e)

    def on_move(self, e):
        if not self.drag or not self.files:
            return
        x0, y0, w, h = self.img_box
        _, _, mw, mh = self.mark_box
        cx = e.x + self.drag[0] - x0
        cy = e.y + self.drag[1] - y0
        # keep the whole logo inside the photo
        cx = min(max(mw / 2, cx), w - mw / 2) if w > mw else w / 2
        cy = min(max(mh / 2, cy), h - mh / 2) if h > mh else h / 2
        self.pos[self.current()] = (cx / w, cy / h)
        self.refresh()

    def on_release(self, _e):
        if self.drag and self.files:
            self.s.pos_x, self.s.pos_y = self.pos[self.current()]
            save_settings(self.s)  # new photos start where you last placed the logo
        self.drag = None

    # ---------------- files and folders
    def refresh_logo_label(self):
        if self.s.logo_path and os.path.exists(self.s.logo_path):
            name = "Built-in TBS logo" if self.s.logo_path == resource("logo.png") else os.path.basename(self.s.logo_path)
        else:
            name = "Text \"TBS\" (no logo chosen)"
        self.logo_lbl.config(text=name)

    def refresh_out_label(self):
        if self.s.out_dir and os.path.isdir(self.s.out_dir):
            self.out_lbl.config(text=f"Saving to {self.s.out_dir}")
        else:
            self.out_lbl.config(text="Saving to a \"Watermarked\" folder next to each photo")

    def choose_out(self):
        p = filedialog.askdirectory(title="Choose where to save watermarked photos")
        if p:
            self.s.out_dir = p
            save_settings(self.s)
            self.refresh_out_label()

    def reset_out(self):
        self.s.out_dir = ""
        save_settings(self.s)
        self.refresh_out_label()

    def choose_logo(self):
        p = filedialog.askopenfilename(title="Choose watermark logo",
                                       filetypes=[("Images", "*.png *.webp *.jpg *.jpeg")])
        if p:
            self.s.logo_path = p
            save_settings(self.s)
            self.refresh_logo_label()
            self.refresh()

    def choose_photos(self):
        files = filedialog.askopenfilenames(title="Choose photos", filetypes=PHOTO_TYPES)
        if files:
            self.add_files(list(files))

    def on_drop(self, event):
        files = []
        for p in self.root.tk.splitlist(event.data):
            if os.path.isdir(p):
                files += [os.path.join(p, f) for f in sorted(os.listdir(p))]
            else:
                files.append(p)
        self.add_files(files)

    def check_photo(self):
        p = filedialog.askopenfilename(title="Check if a photo carries the TBS fingerprint", filetypes=PHOTO_TYPES)
        if not p:
            return
        self.set_status(f"Checking {os.path.basename(p)}…")

        def work():
            try:
                with Image.open(p) as im:
                    v = fingerprint.verdict(fingerprint.score(im))
                msg = {"yes": "TBS fingerprint FOUND: this photo came from the TBS Watermark app.",
                       "maybe": "Weak match: possibly a TBS photo that was heavily edited.",
                       "no": "No TBS fingerprint found."}[v]
            except Exception as e:
                msg = f"Could not check that file ({e})."
            self.root.after(0, lambda: (self.set_status(f"{os.path.basename(p)}: {msg}"),
                                        messagebox.showinfo("Check photo", msg)))
        threading.Thread(target=work, daemon=True).start()

    # ---------------- export
    def export(self):
        jobs = [(f, self.settings_for(f)) for f in self.files]
        if not jobs:
            return
        self.export_btn.config(state="disabled")

        def work():
            done, failed = 0, []
            for i, (f, st) in enumerate(jobs, 1):
                self.root.after(0, self.set_status, f"Exporting {i} of {len(jobs)}: {os.path.basename(f)}")
                try:
                    self.last_folder = os.path.dirname(process_file(f, st))
                    done += 1
                except Exception as e:
                    failed.append(f"{os.path.basename(f)} ({e})")
            msg = f"Saved {done} photo{'s' if done != 1 else ''} to {self.last_folder}"
            if failed:
                msg += f". Failed: {', '.join(failed)}"
            self.root.after(0, self._finish, msg)
        threading.Thread(target=work, daemon=True).start()

    def _finish(self, msg):
        self.set_status(msg)
        self.export_btn.config(state="normal")
        if self.last_folder:
            self.open_btn.config(state="normal")

    def open_out(self):
        if self.last_folder:
            open_folder(self.last_folder)


def make_root() -> tk.Tk:
    global HAS_DND
    if HAS_DND:
        try:
            return TkinterDnD.Tk()
        except Exception:  # drag-and-drop library failed to load: run without it
            HAS_DND = False
            stray = getattr(tk, "_default_root", None)
            if stray is not None:
                try:
                    stray.destroy()
                except Exception:
                    pass
                tk._default_root = None
    return tk.Tk()


def main():
    root = make_root()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
