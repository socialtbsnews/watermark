"""TBS Reel - desktop app.

1. Drop photos and video clips onto the window (or click Add).
2. Put them in order, set how long each one stays on screen.
3. Click Make reel. You get a vertical 1080 x 1920 MP4 with the TBS logo,
   the credit line, optional music and the TBS end card.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import asdict
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from reel_core import (AUDIO_EXT, PHOTO_EXT, VIDEO_EXT, Cancelled, Item, ReelSettings,
                       frame_picture, load_photo, make_item, make_reel, overlay, resource, total_length,
                       video_frame)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:  # still works with the "Add" button
    HAS_DND = False

CONFIG = os.path.join(os.path.expanduser("~"), ".tbs_reel.json")
BG, PANEL, INK, MUTED, ACCENT = "#1B2128", "#232B33", "#E6EAEE", "#9AA5B1", "#F97316"
FONT = ("Segoe UI", 10)
MEDIA_TYPES = [("Photos and videos", " ".join(f"*{e}" for e in sorted(PHOTO_EXT | VIDEO_EXT))),
               ("Photos", " ".join(f"*{e}" for e in sorted(PHOTO_EXT))),
               ("Videos", " ".join(f"*{e}" for e in sorted(VIDEO_EXT)))]
MUSIC_TYPES = [("Music", " ".join(f"*{e}" for e in sorted(AUDIO_EXT)))]
FRAMING = {"blur": "Whole picture, blurred background", "fill": "Fill the screen (crops the sides)"}
MOTION = {"zoom": "Gentle zoom", "none": "Still"}


def load_settings() -> ReelSettings:
    s = ReelSettings()
    try:
        with open(CONFIG, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if hasattr(s, k):
                    setattr(s, k, v)
    except Exception:
        pass
    return s


def save_settings(s: ReelSettings) -> None:
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(asdict(s), f, indent=2)
    except Exception:
        pass


def open_path(path: str, reveal: bool = False) -> None:
    try:
        if sys.platform.startswith("win"):
            if reveal:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path] if reveal else ["open", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) if reveal else path])
    except Exception:
        pass


def fmt_secs(t: float) -> str:
    t = round(t, 1)
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}" if m else f"{s:.1f}s"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.s = load_settings()
        self.items: list[Item] = []
        self.cur = -1
        self.pic_cache: dict[tuple, Image.Image] = {}
        self.preview_img = None
        self.redraw_pending = False
        self.busy = False
        self.cancel_flag = False
        self.last_out = ""
        self._loading_item = False

        root.title("TBS Reel")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{min(1280, sw - 60)}x{min(780, sh - 90)}")
        root.minsize(980, 600)
        root.configure(bg=BG)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TScale", background=BG)
        style.configure("Horizontal.TProgressbar", troughcolor=PANEL, background=ACCENT, bordercolor=BG,
                        lightcolor=ACCENT, darkcolor=ACCENT)

        # ---------------- header
        head = tk.Frame(root, bg=BG)
        head.pack(side="top", fill="x", padx=16, pady=(12, 6))
        self._head_imgs = []
        try:
            for name, h in (("logo.png", 34), ("brand.png", 18)):
                im = Image.open(resource(name)).convert("RGBA")
                im = im.resize((round(im.width * h / im.height), h), Image.LANCZOS)
                self._head_imgs.append(ImageTk.PhotoImage(im, master=root))
            tk.Label(head, image=self._head_imgs[0], bg=BG).pack(side="left")
            tk.Label(head, image=self._head_imgs[1], bg=BG).pack(side="left", padx=(10, 0))
            tk.Label(head, text="REEL", fg=ACCENT, bg=BG,
                     font=("Segoe UI", 11, "bold")).pack(side="left", padx=(10, 0), pady=(3, 0))
        except Exception:
            tk.Label(head, text="TBS Reel", fg=INK, bg=BG, font=("Segoe UI", 18, "bold")).pack(side="left")
        try:
            self._icon = ImageTk.PhotoImage(Image.open(resource("icon.png")).resize((64, 64), Image.LANCZOS),
                                            master=root)
            root.iconphoto(True, self._icon)
        except Exception:
            pass

        # ---------------- left: the list of photos and clips
        left = tk.Frame(root, bg=BG, width=290)
        left.pack(side="left", fill="y", padx=(16, 8), pady=(0, 12))
        left.pack_propagate(False)
        self._section(left, "YOUR REEL (in this order)")
        r = tk.Frame(left, bg=BG); r.pack(fill="x", pady=(0, 4))
        self._btn(r, "Add photos / videos…", self.choose_media).pack(side="left")
        self._btn(r, "Clear", self.clear).pack(side="right")
        lf = tk.Frame(left, bg=PANEL)
        lf.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(lf, bg=PANEL, fg=INK, selectbackground=ACCENT, selectforeground="#1A0F06",
                                  activestyle="none", relief="flat", highlightthickness=0, font=FONT,
                                  exportselection=False)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        r = tk.Frame(left, bg=BG); r.pack(fill="x", pady=(6, 0))
        self._btn(r, "▲ Earlier", lambda: self.move(-1)).pack(side="left")
        self._btn(r, "▼ Later", lambda: self.move(1)).pack(side="left", padx=6)
        self._btn(r, "Remove", self.remove).pack(side="right")

        # ---------------- right: settings and export
        right = tk.Frame(root, bg=BG, width=350)
        right.pack(side="right", fill="y", padx=(8, 16), pady=(0, 12))
        right.pack_propagate(False)

        foot = tk.Frame(right, bg=BG)
        foot.pack(side="bottom", fill="x")
        self.total_lbl = tk.Label(foot, bg=BG, fg=INK, font=("Segoe UI", 10, "bold"), anchor="w")
        self.total_lbl.pack(fill="x")
        self.status = tk.Label(foot, text="", bg=BG, fg=MUTED, font=FONT, anchor="w", justify="left",
                               wraplength=330)
        self.status.pack(fill="x", pady=(2, 4))
        self.bar = ttk.Progressbar(foot, mode="determinate", maximum=1000, style="Horizontal.TProgressbar")
        self.bar.pack(fill="x", pady=(0, 6))
        r = tk.Frame(foot, bg=BG); r.pack(fill="x")
        self.export_btn = tk.Button(r, text="Make reel", command=self.export, state="disabled",
                                    bg=ACCENT, fg="#1A0F06", activebackground=ACCENT, relief="flat",
                                    font=("Segoe UI", 11, "bold"), padx=12, pady=7)
        self.export_btn.pack(side="left", fill="x", expand=True)
        self.open_btn = self._btn(r, "Show video", self.open_out)
        self.open_btn.config(state="disabled")
        self.open_btn.pack(side="left", padx=(6, 0))

        body = tk.Frame(right, bg=BG)
        body.pack(side="top", fill="both", expand=True)

        self._section(body, "LOOK")
        self.framing_menu = self._menu(body, "Framing", FRAMING, self.s.framing, self.look_changed, 30)
        self.motion_menu = self._menu(body, "Photos", MOTION, self.s.motion, self.look_changed, 14)
        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=2)
        tk.Label(r, text="Each photo", width=8, anchor="w", bg=BG, fg=INK, font=FONT).pack(side="left")
        self.photo_secs_var = tk.StringVar(self.root, value=f"{self.s.photo_secs:g}")
        self._spin(r, self.photo_secs_var, 1, 30, self.photo_secs_changed).pack(side="left")
        tk.Label(r, text="seconds", bg=BG, fg=MUTED, font=FONT).pack(side="left", padx=4)
        self._btn(r, "Apply to all", self.apply_photo_secs).pack(side="right")

        self._section(body, "LOGO")
        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=2)
        self.logo_var = tk.BooleanVar(self.root, value=self.s.logo_on)
        self._check(r, "Show TBS logo", self.logo_var, self.look_changed).pack(side="left")
        self.corner_menu = ttk.Combobox(r, state="readonly", width=10, font=FONT, values=["Top right", "Top left"])
        self.corner_menu.set("Top left" if self.s.logo_corner == "top-left" else "Top right")
        self.corner_menu.bind("<<ComboboxSelected>>", lambda e: self.look_changed())
        self.corner_menu.pack(side="right")
        self.size_var = tk.DoubleVar(self.root, value=self.s.logo_size_pct)
        self._slider(body, "Size", self.size_var, 8, 30)

        self._section(body, "CREDIT")
        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=2)
        tk.Label(r, text="Photo by", width=8, anchor="w", bg=BG, fg=INK, font=FONT).pack(side="left")
        self.name_var = tk.StringVar(self.root, value=self.s.photographer)
        tk.Entry(r, textvariable=self.name_var, bg=PANEL, fg=INK, insertbackground=INK, relief="flat",
                 font=("Segoe UI", 11)).pack(side="left", fill="x", expand=True, ipady=3)
        self.name_var.trace_add("write", lambda *_: self.look_changed())
        self.credit_var = tk.BooleanVar(self.root, value=self.s.credit_on)
        self._check(body, "Show credit line (Photo: / Video: name)", self.credit_var,
                    self.look_changed).pack(anchor="w")

        self._section(body, "SOUND")
        r = tk.Frame(body, bg=BG); r.pack(fill="x", pady=2)
        self._btn(r, "Choose music…", self.choose_music).pack(side="left")
        self._btn(r, "No music", self.clear_music).pack(side="left", padx=6)
        self.music_lbl = tk.Label(body, bg=BG, fg=MUTED, font=FONT, anchor="w", justify="left", wraplength=330)
        self.music_lbl.pack(fill="x")
        self.mvol_var = tk.DoubleVar(self.root, value=self.s.music_volume_pct)
        self._slider(body, "Music", self.mvol_var, 0, 100)
        self.clipsound_var = tk.BooleanVar(self.root, value=self.s.clip_sound)
        self._check(body, "Keep the sound of video clips", self.clipsound_var, self.look_changed).pack(anchor="w")

        self._section(body, "ENDING")
        self.end_var = tk.BooleanVar(self.root, value=self.s.end_card)
        self._check(body, "TBS end card (2.5 seconds)", self.end_var, self.look_changed).pack(anchor="w")

        # ---------------- centre: preview + selected item
        mid = tk.Frame(root, bg=BG)
        mid.pack(side="left", fill="both", expand=True, padx=8, pady=(0, 12))
        self.canvas = tk.Canvas(mid, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.refresh())
        self.canvas.bind("<Button-1>", lambda e: None if self.items else self.choose_media())
        item_row = tk.Frame(mid, bg=BG)
        item_row.pack(fill="x", pady=(8, 0))
        self.item_lbl = tk.Label(item_row, bg=BG, fg=MUTED, font=FONT, anchor="w")
        self.item_lbl.pack(fill="x")
        r = tk.Frame(item_row, bg=BG); r.pack(fill="x", pady=(4, 0))
        tk.Label(r, text="On screen for", bg=BG, fg=INK, font=FONT).pack(side="left")
        self.len_var = tk.StringVar(self.root, value="")
        self.len_spin = self._spin(r, self.len_var, 0.5, 600, self.item_changed)
        self.len_spin.pack(side="left", padx=4)
        tk.Label(r, text="s", bg=BG, fg=MUTED, font=FONT).pack(side="left")
        self.start_lbl = tk.Label(r, text="   Start clip at", bg=BG, fg=INK, font=FONT)
        self.start_var = tk.StringVar(self.root, value="0")
        self.start_spin = self._spin(r, self.start_var, 0, 36000, self.item_changed)
        self.start_s = tk.Label(r, text="s", bg=BG, fg=MUTED, font=FONT)
        self.start_lbl.pack(side="left")
        self.start_spin.pack(side="left", padx=4)
        self.start_s.pack(side="left")
        self.item_widgets = [self.len_spin, self.start_spin]

        if HAS_DND:
            for w in (self.canvas, self.listbox, root):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)

        self.refresh_music_label()
        self.update_list()
        self.set_status("Drop photos and video clips anywhere on this window, or click Add."
                        if HAS_DND else "Click Add photos / videos to begin.")

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

    def _menu(self, parent, label, options: dict, current: str, cmd, width):
        r = tk.Frame(parent, bg=BG); r.pack(fill="x", pady=2)
        tk.Label(r, text=label, width=8, anchor="w", bg=BG, fg=INK, font=FONT).pack(side="left")
        m = ttk.Combobox(r, state="readonly", width=width, font=FONT, values=list(options.values()))
        m.set(options.get(current, next(iter(options.values()))))
        m.bind("<<ComboboxSelected>>", lambda e: cmd())
        m.pack(side="left", fill="x", expand=True)
        m.options = options
        return m

    def _spin(self, parent, var, lo, hi, cmd):
        sp = tk.Spinbox(parent, from_=lo, to=hi, increment=0.5, textvariable=var, width=6, font=FONT,
                        bg=PANEL, fg=INK, buttonbackground=PANEL, insertbackground=INK, relief="flat",
                        command=cmd)
        sp.bind("<KeyRelease>", lambda e: cmd())
        sp.bind("<FocusOut>", lambda e: cmd())
        return sp

    def _slider(self, parent, label, var, lo, hi):
        r = tk.Frame(parent, bg=BG); r.pack(fill="x", pady=1)
        tk.Label(r, text=label, width=8, anchor="w", bg=BG, fg=INK, font=FONT).pack(side="left")
        val = tk.Label(r, width=5, anchor="e", bg=BG, fg=MUTED, font=FONT)

        def changed(_v=None):
            val.config(text=f"{var.get():.0f}%")
            self.look_changed()

        ttk.Scale(r, from_=lo, to=hi, variable=var, command=changed).pack(side="left", fill="x", expand=True)
        val.pack(side="left")
        val.config(text=f"{var.get():.0f}%")

    @staticmethod
    def _key(menu) -> str:
        return next(k for k, v in menu.options.items() if v == menu.get())

    def save(self):
        if getattr(self, "_save_job", None):
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(500, lambda: save_settings(self.s))

    def set_status(self, text):
        self.status.config(text=text)

    # ---------------- settings
    def look_changed(self):
        s = self.s
        s.framing = self._key(self.framing_menu)
        s.motion = self._key(self.motion_menu)
        s.logo_on = bool(self.logo_var.get())
        s.logo_corner = "top-left" if self.corner_menu.get() == "Top left" else "top-right"
        s.logo_size_pct = round(self.size_var.get(), 1)
        s.photographer = self.name_var.get()
        s.credit_on = bool(self.credit_var.get())
        s.music_volume_pct = round(self.mvol_var.get())
        s.clip_sound = bool(self.clipsound_var.get())
        s.end_card = bool(self.end_var.get())
        self.save()
        self.update_total()
        self.refresh()

    def photo_secs_changed(self):
        try:
            v = float(self.photo_secs_var.get())
        except ValueError:
            return
        if 0.5 <= v <= 60:
            self.s.photo_secs = v
            self.save()

    def apply_photo_secs(self):
        self.photo_secs_changed()
        for it in self.items:
            if it.kind == "photo":
                it.length = self.s.photo_secs
        self.update_list()
        self.load_item_fields()

    def choose_music(self):
        p = filedialog.askopenfilename(title="Choose background music", filetypes=MUSIC_TYPES)
        if p:
            self.s.music_path = p
            self.save()
            self.refresh_music_label()

    def clear_music(self):
        self.s.music_path = ""
        self.save()
        self.refresh_music_label()

    def refresh_music_label(self):
        p = self.s.music_path
        if p and os.path.exists(p):
            self.music_lbl.config(text=f"Music: {os.path.basename(p)} (repeats if shorter, fades out at the end)")
        else:
            self.music_lbl.config(text="No music")

    # ---------------- the list
    def add_files(self, files):
        known = {i.path for i in self.items}
        files = [f for f in files if f not in known]
        music = [f for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXT]
        media = [f for f in files if os.path.splitext(f)[1].lower() in PHOTO_EXT | VIDEO_EXT]
        if music:
            self.s.music_path = music[0]
            self.save()
            self.refresh_music_label()
        if not media:
            if not music:
                self.set_status("No photos or videos found in what you dropped.")
            return
        self.set_status(f"Adding {len(media)} file{'s' if len(media) != 1 else ''}…")

        def work():
            new, bad = [], []
            for f in media:
                it = make_item(f, self.s.photo_secs)
                (new if it else bad).append(it or f)
            self.root.after(0, self._added, new, bad)
        threading.Thread(target=work, daemon=True).start()

    def _added(self, new, bad):
        self.items += new
        if new:
            self.cur = len(self.items) - len(new)
        self.update_list()
        msg = f"{len(new)} added. Put them in order, then click Make reel." if new else ""
        if bad:
            msg += f" Could not read: {', '.join(os.path.basename(b) for b in bad)}"
        self.set_status(msg.strip())

    def update_list(self):
        self.listbox.delete(0, "end")
        for i, it in enumerate(self.items, 1):
            icon = "Video" if it.kind == "video" else "Photo"
            self.listbox.insert("end", f" {i}. [{icon}] {it.name}   {fmt_secs(it.length)}")
        if self.items:
            self.cur = min(max(0, self.cur), len(self.items) - 1)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(self.cur)
            self.listbox.see(self.cur)
        else:
            self.cur = -1
        self.update_total()
        self.load_item_fields()
        self.refresh()

    def update_total(self):
        n = len(self.items)
        if n:
            self.total_lbl.config(text=f"Reel length: {fmt_secs(total_length(self.items, self.s))}  "
                                       f"({n} item{'s' if n != 1 else ''})")
            if not self.busy:
                self.export_btn.config(state="normal")
        else:
            self.total_lbl.config(text="Reel length: 0s")
            self.export_btn.config(state="disabled")

    def current(self) -> Item | None:
        return self.items[self.cur] if 0 <= self.cur < len(self.items) else None

    def on_select(self, _e=None):
        sel = self.listbox.curselection()
        if sel:
            self.cur = sel[0]
            self.load_item_fields()
            self.refresh()

    def load_item_fields(self):
        it = self.current()
        self._loading_item = True
        if it is None:
            self.item_lbl.config(text="")
            self.len_var.set("")
            for w in self.item_widgets:
                w.config(state="disabled")
        else:
            self.len_spin.config(state="normal")
            self.len_var.set(f"{it.length:g}")
            if it.kind == "video":
                self.start_spin.config(state="normal")
                self.start_var.set(f"{it.start:g}")
                self.item_lbl.config(text=f"{self.cur + 1}. {it.name}  (video, {fmt_secs(it.duration)} long"
                                          f"{', with sound' if it.has_audio else ', no sound'})")
            else:
                self.start_var.set("0")
                self.start_spin.config(state="disabled")
                self.item_lbl.config(text=f"{self.cur + 1}. {it.name}  (photo)")
        self._loading_item = False

    def item_changed(self):
        it = self.current()
        if it is None or self._loading_item:
            return
        try:
            length = float(self.len_var.get())
            start = float(self.start_var.get() or 0) if it.kind == "video" else 0.0
        except ValueError:
            return
        if it.kind == "video":
            start = min(max(0.0, start), max(0.0, it.duration - 0.5))
            length = min(length, it.duration - start)
        length = max(0.5, length)
        if abs(length - it.length) > 1e-6 or abs(start - it.start) > 1e-6:
            it.length, it.start = round(length, 2), round(start, 2)
            self.listbox.delete(self.cur)
            icon = "Video" if it.kind == "video" else "Photo"
            self.listbox.insert(self.cur, f" {self.cur + 1}. [{icon}] {it.name}   {fmt_secs(it.length)}")
            self.listbox.selection_set(self.cur)
            self.update_total()
            self.refresh()

    def move(self, d):
        i = self.cur
        if 0 <= i < len(self.items) and 0 <= i + d < len(self.items):
            self.items[i], self.items[i + d] = self.items[i + d], self.items[i]
            self.cur = i + d
            self.update_list()

    def remove(self):
        if self.current():
            self.items.pop(self.cur)
            self.update_list()

    def clear(self):
        self.items, self.cur = [], -1
        self.pic_cache.clear()
        self.update_list()

    # ---------------- preview
    def refresh(self):
        if not self.redraw_pending:
            self.redraw_pending = True
            self.root.after(60, self._draw)

    def _picture(self, it: Item, w: int, h: int) -> Image.Image | None:
        key = (it.path, it.start if it.kind == "video" else 0, self.s.framing, w, h)
        pic = self.pic_cache.get(key)
        if pic is None:
            try:
                src = load_photo(it.path, 1600) if it.kind == "photo" else video_frame(it.path, it.start + 0.05)
            except Exception:
                src = None
            if src is None:
                return None
            pic = frame_picture(src, self.s.framing, w, h)
            if len(self.pic_cache) > 40:
                self.pic_cache.clear()
            self.pic_cache[key] = pic
        return pic

    def _draw(self):
        self.redraw_pending = False
        c = self.canvas
        cw, ch = max(60, c.winfo_width()), max(60, c.winfo_height())
        h = ch - 8
        w = round(h * 9 / 16)
        if w > cw - 8:
            w = cw - 8
            h = round(w * 16 / 9)
        c.delete("all")
        x0, y0 = (cw - w) // 2, (ch - h) // 2
        it = self.current()
        if it is None:
            c.create_rectangle(x0, y0, x0 + w, y0 + h, fill=PANEL, outline="")
            c.create_text(cw // 2, ch // 2, fill=MUTED, font=("Segoe UI", 13), justify="center",
                          text="Drop photos and\nvideo clips here\n\nor click Add")
            return
        pic = self._picture(it, w, h)
        if pic is None:
            img = Image.new("RGB", (w, h), (35, 43, 51))
        else:
            img = Image.alpha_composite(pic.convert("RGBA"), overlay(self.s, it.kind, w, h)).convert("RGB")
        self.preview_img = ImageTk.PhotoImage(img, master=self.root)
        c.create_image(x0, y0, image=self.preview_img, anchor="nw")
        if pic is None:
            c.create_text(cw // 2, ch // 2, fill=MUTED, font=FONT, text=f"Could not show {it.name}")

    # ---------------- files
    def choose_media(self):
        files = filedialog.askopenfilenames(title="Choose photos and video clips", filetypes=MEDIA_TYPES)
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

    # ---------------- export
    def export(self):
        if self.busy:
            self.cancel_flag = True
            self.set_status("Stopping…")
            return
        if not self.items:
            return
        start_dir = self.s.out_dir if self.s.out_dir and os.path.isdir(self.s.out_dir) else \
            os.path.dirname(self.items[0].path)
        out = filedialog.asksaveasfilename(title="Save the reel as", defaultextension=".mp4",
                                           initialdir=start_dir,
                                           initialfile=f"TBS-Reel-{time.strftime('%Y%m%d-%H%M')}.mp4",
                                           filetypes=[("MP4 video", "*.mp4")])
        if not out:
            return
        self.s.out_dir = os.path.dirname(out)
        self.save()
        items = [Item(**{**i.__dict__}) for i in self.items]
        settings = ReelSettings(**asdict(self.s))
        self.busy, self.cancel_flag = True, False
        self.export_btn.config(text="Stop")
        self.open_btn.config(state="disabled")
        self.bar["value"] = 0
        t0 = time.time()

        def prog(frac, msg):
            self.root.after(0, self._progress, frac, msg)

        def work():
            try:
                make_reel(items, settings, out, progress=prog, cancel=lambda: self.cancel_flag)
                secs = time.time() - t0
                self.root.after(0, self._finish, out, f"Saved {os.path.basename(out)} "
                                                      f"(made in {fmt_secs(secs)}).", None)
            except Cancelled:
                self.root.after(0, self._finish, "", "Stopped. Nothing was saved.", None)
            except Exception as e:
                self.root.after(0, self._finish, "", "The reel could not be made.", str(e))
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, frac, msg):
        self.bar["value"] = round(frac * 1000)
        self.set_status(f"{msg}  ({frac * 100:.0f}%)")

    def _finish(self, out, msg, err):
        self.busy = False
        self.export_btn.config(text="Make reel")
        self.update_total()
        self.set_status(msg)
        if out:
            self.last_out = out
            self.bar["value"] = 1000
            self.open_btn.config(state="normal")
        else:
            self.bar["value"] = 0
        if err:
            messagebox.showerror("TBS Reel", f"{msg}\n\n{err[-800:]}")

    def open_out(self):
        if self.last_out and os.path.exists(self.last_out):
            open_path(self.last_out, reveal=True)


def make_root() -> tk.Tk:
    global HAS_DND
    if HAS_DND:
        try:
            return TkinterDnD.Tk()
        except Exception:
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
    app = App(root)

    def on_close():
        if app.busy:
            if not messagebox.askyesno("TBS Reel", "A reel is still being made. Stop and quit?"):
                return
            app.cancel_flag = True
        save_settings(app.s)
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
