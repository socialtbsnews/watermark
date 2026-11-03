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
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

import fingerprint
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
        root.geometry("860x860")
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
                             text="Drop photos here\n\nJPG, PNG, TIFF, WebP",
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
        row0 = tk.Frame(ctl, bg=BG)
        row0.pack(fill="x", pady=4)
        tk.Button(row0, text="Output folder…", command=self.choose_out, bg=PANEL, fg=INK,
                  activebackground=ACCENT, relief="flat", padx=12, pady=6).pack(side="left")
        self.out_lbl = tk.Label(row0, bg=BG, fg=MUTED, anchor="w")
        self.out_lbl.pack(side="left", padx=10, fill="x", expand=True)
        tk.Button(row0, text="Reset", command=self.reset_out, bg=PANEL, fg=INK,
                  relief="flat", padx=10, pady=6).pack(side="right")
        self.refresh_out_label()

        row2 = tk.Frame(ctl, bg=BG)
        row2.pack(fill="x", pady=4)
        tk.Label(row2, text="Photo by", width=8, anchor="w", bg=BG, fg=INK).pack(side="left")
        self.name_var = tk.StringVar(value=self.s.photographer)
        tk.Entry(row2, textvariable=self.name_var, bg=PANEL, fg=INK, insertbackground=INK,
                 relief="flat", font=("Segoe UI", 11)).pack(side="left", fill="x", expand=True, padx=8, ipady=4)
        self.credit_var = tk.BooleanVar(value=self.s.credit_on)
        tk.Checkbutton(row2, text="Show credit line", variable=self.credit_var, bg=BG, fg=INK,
                       selectcolor=PANEL, activebackground=BG, activeforeground=INK,
                       command=self.credit_changed).pack(side="left")
        self.name_var.trace_add("write", lambda *_: self.credit_changed())

        row3 = tk.Frame(ctl, bg=BG)
        row3.pack(fill="x", pady=4)
        tk.Label(row3, text="Credit at", width=8, anchor="w", bg=BG, fg=INK).pack(side="left")
        self.pos_var = tk.StringVar(value=self.s.credit_pos)
        for label, val in (("Top left", "top-left"), ("Top right", "top-right"),
                           ("Bottom left", "bottom-left"), ("Bottom right", "bottom-right")):
            tk.Radiobutton(row3, text=label, value=val, variable=self.pos_var, bg=BG, fg=INK,
                           selectcolor=PANEL, activebackground=BG, activeforeground=INK,
                           command=self.credit_changed).pack(side="left", padx=(8, 0))

        self._slider(ctl, "Opacity", self.op_var, 0, 100, "% (0 = invisible, 100 = solid)")

        # Protection
        prow = tk.Frame(ctl, bg=BG)
        prow.pack(fill="x", pady=(10, 4))
        tk.Label(prow, text="Protect", width=8, anchor="w", bg=BG, fg=INK).pack(side="left")
        self.protect_var = tk.BooleanVar(value=self.s.protect)
        self.hidden_var = tk.BooleanVar(value=self.s.hidden_mark)
        for text, var in (("Protective pattern (hard to remove)", self.protect_var),
                          ("Hidden fingerprint (invisible)", self.hidden_var)):
            tk.Checkbutton(prow, text=text, variable=var, bg=BG, fg=INK, selectcolor=PANEL,
                           activebackground=BG, activeforeground=INK,
                           command=self.protect_changed).pack(side="left", padx=(8, 0))
        tk.Button(prow, text="Check photo…", command=self.check_photo, bg=PANEL, fg=INK,
                  relief="flat", padx=10, pady=4).pack(side="right")
        self.prot_var = tk.DoubleVar(value=self.s.protect_pct)
        self._slider(ctl, "Pattern", self.prot_var, 4, 40, "% pattern strength")

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
            if hasattr(self, "prot_var"):
                self.s.protect_pct = round(self.prot_var.get())
            save_settings(self.s)
            self.show_sample()

        ttk.Scale(row, from_=lo, to=hi, variable=var, command=lambda _v: changed()).pack(side="left", fill="x", expand=True, padx=8)
        val.pack(side="left")
        val.config(text=f"{var.get():.0f}{unit}")

    def protect_changed(self):
        self.s.protect = bool(self.protect_var.get())
        self.s.hidden_mark = bool(self.hidden_var.get())
        save_settings(self.s)
        self.show_sample()

    def check_photo(self):
        p = filedialog.askopenfilename(title="Check if a photo carries the TBS fingerprint",
                                       filetypes=[("Photos", "*.jpg *.jpeg *.png *.tif *.tiff *.webp")])
        if not p:
            return
        self.status.config(text=f"Checking {os.path.basename(p)}…")

        def work():
            try:
                with Image.open(p) as im:
                    v = fingerprint.verdict(fingerprint.score(im))
                msg = {"yes": "TBS fingerprint FOUND: this photo came from the TBS Watermark app.",
                       "maybe": "Weak match: possibly a TBS photo that was heavily edited.",
                       "no": "No TBS fingerprint found."}[v]
            except Exception as e:
                msg = f"Could not check that file ({e})."
            self.root.after(0, lambda: (self.status.config(text=f"{os.path.basename(p)}: {msg}"),
                                        messagebox.showinfo("Check photo", msg)))
        threading.Thread(target=work, daemon=True).start()

    def credit_changed(self):
        self.s.photographer = self.name_var.get()
        self.s.credit_on = bool(self.credit_var.get())
        self.s.credit_pos = self.pos_var.get() if hasattr(self, "pos_var") else self.s.credit_pos
        save_settings(self.s)
        self.show_sample()

    # ---------- preview
    def show_sample(self, photo: Image.Image | None = None):
        if photo is not None:
            self.sample = photo
        placeholder = self.sample is None
        base = Image.new("RGB", (1600, 1067), (70, 82, 96)) if placeholder else self.sample
        w = max(200, self.drop.winfo_width() - 20)
        h = max(150, self.drop.winfo_height() - 20)
        thumb = base.copy()
        thumb.thumbnail((w, h))
        marked = apply_watermark(thumb, self.s)
        self.preview_img = ImageTk.PhotoImage(marked)
        self.drop.config(image=self.preview_img, compound="center",
                         text="Drop photos here" if placeholder else "", fg=INK)

    def refresh_logo_label(self):
        if self.s.logo_path and os.path.exists(self.s.logo_path):
            name = "Built-in TBS logo" if self.s.logo_path == resource("logo.png") else os.path.basename(self.s.logo_path)
            self.logo_lbl.config(text=name)
        else:
            self.logo_lbl.config(text="No logo chosen: using the text \"TBS\"")

    def refresh_out_label(self):
        if self.s.out_dir and os.path.isdir(self.s.out_dir):
            self.out_lbl.config(text=f"Saving to: {self.s.out_dir}")
        else:
            self.out_lbl.config(text="Saving to: a \"Watermarked\" folder next to each photo")

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
        def load_preview(path):
            # Keep the latest original photo as the live preview, so sliders
            # re-draw the watermark on the real photo.
            try:
                with Image.open(path) as im:
                    im.draft("RGB", (1600, 1600))
                    im = ImageOps.exif_transpose(im)
                    im.thumbnail((1600, 1600))
                    return im.convert("RGB")
            except Exception:
                return None

        def work():
            prev = load_preview(files[-1])
            if prev is not None:
                self.root.after(0, self.show_sample, prev)
            done, failed = 0, []
            for i, f in enumerate(files, 1):
                self.root.after(0, self.status.config, {"text": f"Watermarking {i} of {len(files)}: {os.path.basename(f)}"})
                try:
                    dst = process_file(f, self.s)
                    self.last_folder = os.path.dirname(dst)
                    done += 1
                except Exception as e:
                    failed.append(f"{os.path.basename(f)} ({e})")
            msg = f"Saved {done} photo{'s' if done != 1 else ''} to {self.last_folder}"
            if failed:
                msg += f". Failed: {', '.join(failed)}"
            self.root.after(0, self._finish, msg)
        threading.Thread(target=work, daemon=True).start()

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
