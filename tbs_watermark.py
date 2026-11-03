"""TBS Watermark - desktop app.

Drag photos onto the window. Each one is saved with the TBS watermark in the
centre, into a "Watermarked" folder next to the original. Originals are never
touched.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import asdict
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

from watermark_core import SUPPORTED, Settings, apply_watermark, process_file

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:  # app still works with the "Choose photos" button
    HAS_DND = False

CONFIG = os.path.join(os.path.expanduser("~"), ".tbs_watermark.json")
BG, PANEL, INK, MUTED, ACCENT = "#1B2128", "#232B33", "#E6EAEE", "#9AA5B1", "#F97316"


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


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.s = load_settings()
        self.last_folder = ""
        self.preview_img = None
        self.sample = None

        root.title("TBS Watermark")
        root.geometry("760x640")
        root.minsize(560, 520)
        root.configure(bg=BG)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TScale", background=PANEL)

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(head, text="TBS", fg=ACCENT, bg=BG, font=("Segoe UI", 20, "bold")).pack(side="left")
        tk.Label(head, text=" Watermark", fg=INK, bg=BG, font=("Segoe UI", 20, "bold")).pack(side="left")

        # Drop zone / preview
        self.drop = tk.Label(root, bg=PANEL, fg=MUTED, font=("Segoe UI", 13),
                             text="Drop photos here\n\nJPG, PNG, TIFF, WebP\nSaved to a \"Watermarked\" folder next to each photo",
                             relief="flat", bd=0, cursor="hand2")
        self.drop.pack(fill="both", expand=True, padx=20, pady=8)
        self.drop.bind("<Button-1>", lambda e: self.choose_photos())
        if HAS_DND:
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self.on_drop)

        # Controls
        ctl = tk.Frame(root, bg=BG)
        ctl.pack(fill="x", padx=20, pady=4)

        row1 = tk.Frame(ctl, bg=BG)
        row1.pack(fill="x", pady=4)
        tk.Button(row1, text="Choose logo…", command=self.choose_logo, bg=PANEL, fg=INK,
                  activebackground=ACCENT, relief="flat", padx=12, pady=6).pack(side="left")
        self.logo_lbl = tk.Label(row1, bg=BG, fg=MUTED, anchor="w")
        self.logo_lbl.pack(side="left", padx=10, fill="x", expand=True)

        self.size_var = tk.DoubleVar(value=self.s.size_pct)
        self.op_var = tk.DoubleVar(value=self.s.opacity_pct)
        self._slider(ctl, "Size", self.size_var, 5, 80, "% of photo width")
        self._slider(ctl, "Opacity", self.op_var, 0, 100, "% (0 = invisible, 100 = solid)")

        bottom = tk.Frame(root, bg=BG)
        bottom.pack(fill="x", padx=20, pady=(4, 16))
        self.status = tk.Label(bottom, text="Ready.", bg=BG, fg=MUTED, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.open_btn = tk.Button(bottom, text="Open output folder", command=self.open_out, state="disabled",
                                  bg=ACCENT, fg="#1A0F06", relief="flat", padx=12, pady=6)
        self.open_btn.pack(side="right")
        tk.Button(bottom, text="Choose photos…", command=self.choose_photos, bg=PANEL, fg=INK,
                  relief="flat", padx=12, pady=6).pack(side="right", padx=8)

        if not HAS_DND:
            self.status.config(text="Drag and drop unavailable here; use Choose photos.")
        self.refresh_logo_label()
        root.after(100, self.show_sample)

    def _slider(self, parent, label, var, lo, hi, unit):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, width=8, anchor="w", bg=BG, fg=INK).pack(side="left")
        val = tk.Label(row, width=32, anchor="w", bg=BG, fg=MUTED)

        def changed(*_):
            val.config(text=f"{var.get():.0f}{unit}")
            self.s.size_pct = round(self.size_var.get())
            self.s.opacity_pct = round(self.op_var.get())
            save_settings(self.s)
            self.show_sample()

        ttk.Scale(row, from_=lo, to=hi, variable=var, command=lambda _v: changed()).pack(side="left", fill="x", expand=True, padx=8)
        val.pack(side="left")
        val.config(text=f"{var.get():.0f}{unit}")

    # ---------- preview
    def show_sample(self, photo: Image.Image | None = None):
        if photo is not None:
            self.sample = photo
        if self.sample is None:
            self.sample = Image.new("RGB", (1600, 1067), (70, 82, 96))
        w = max(200, self.drop.winfo_width() - 20)
        h = max(150, self.drop.winfo_height() - 20)
        thumb = self.sample.copy()
        thumb.thumbnail((w, h))
        marked = apply_watermark(thumb, self.s)
        self.preview_img = ImageTk.PhotoImage(marked)
        self.drop.config(image=self.preview_img, compound="center", text="")

    def refresh_logo_label(self):
        if self.s.logo_path and os.path.exists(self.s.logo_path):
            name = "Built-in TBS logo" if self.s.logo_path == resource("logo.png") else os.path.basename(self.s.logo_path)
            self.logo_lbl.config(text=name)
        else:
            self.logo_lbl.config(text="No logo chosen: using the text \"TBS\"")

    # ---------- actions
    def choose_logo(self):
        p = filedialog.askopenfilename(title="Choose watermark logo",
                                       filetypes=[("Images", "*.png *.webp *.jpg *.jpeg")])
        if p:
            self.s.logo_path = p
            save_settings(self.s)
            self.refresh_logo_label()
            self.show_sample()

    def choose_photos(self):
        files = filedialog.askopenfilenames(title="Choose photos",
                                            filetypes=[("Photos", "*.jpg *.jpeg *.png *.tif *.tiff *.webp")])
        if files:
            self.run(list(files))

    def on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        files = []
        for p in paths:
            if os.path.isdir(p):
                files += [os.path.join(p, f) for f in sorted(os.listdir(p))]
            else:
                files.append(p)
        files = [f for f in files if os.path.splitext(f)[1].lower() in SUPPORTED]
        if files:
            self.run(files)
        else:
            self.status.config(text="Those files are not photos (JPG, PNG, TIFF or WebP).")

    def run(self, files):
        def work():
            done, failed = 0, []
            for i, f in enumerate(files, 1):
                self.root.after(0, self.status.config, {"text": f"Watermarking {i} of {len(files)}: {os.path.basename(f)}"})
                try:
                    dst = process_file(f, self.s)
                    self.last_folder = os.path.dirname(dst)
                    done += 1
                    if i == len(files):
                        with Image.open(dst) as im:
                            im.thumbnail((1600, 1600))
                            prev = im.convert("RGB")
                        self.root.after(0, lambda p=prev: self._show_result(p))
                except Exception as e:
                    failed.append(f"{os.path.basename(f)} ({e})")
            msg = f"Saved {done} photo{'s' if done != 1 else ''} to {self.last_folder}"
            if failed:
                msg += f". Failed: {', '.join(failed)}"
            self.root.after(0, self._finish, msg)
        threading.Thread(target=work, daemon=True).start()

    def _show_result(self, img):
        w = max(200, self.drop.winfo_width() - 20)
        h = max(150, self.drop.winfo_height() - 20)
        img.thumbnail((w, h))
        self.preview_img = ImageTk.PhotoImage(img)
        self.drop.config(image=self.preview_img, text="")

    def _finish(self, msg):
        self.status.config(text=msg)
        if self.last_folder:
            self.open_btn.config(state="normal")

    def open_out(self):
        if self.last_folder:
            open_folder(self.last_folder)


def main():
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
