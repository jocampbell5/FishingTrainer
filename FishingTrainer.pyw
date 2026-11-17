"""FishingTrainer's window: Start, Pause and Stop buttons over a console-style log.

Double-click FishingTrainer.bat (it starts this). The trainer itself (main.py) runs as
its own process; this window shows what it prints and can pause or stop it. Ctrl+Shift
in the game still pauses and resumes too.
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont

import install_addon

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURE = os.path.join(HERE, "captures", "latest_bobber.png")   # main.py saves it after each cast
PICTURE_WIDTH = 440
NO_WINDOW = 0x08000000                     # CREATE_NO_WINDOW: no extra console for main.py

SETTINGS = os.path.join(HERE, "settings.json")   # the checkboxes, remembered between runs

# The checkboxes: (key, label). Each is a command main.py takes while it runs ("<key> on"),
# and, when off at Start, a flag that turns it off from the beginning.
OPTIONS = [
    ("my-splash", "Only my bobber's splash"),
    ("sound-only", "Hook on the sound if the bobber isn't found"),
    ("stop-after", "Stop after 2 hours"),
    ("breaks", "Take short breaks"),
]
START_FLAGS = {  # at Start: the flag for each option, when it's on / off
    "my-splash": (None, "--any-splash"),
    "sound-only": (None, "--recast-if-no-bobber"),
    "stop-after": ("--stop-after-session", None),
    "breaks": ("--breaks", None),
}

# The keys it presses in WoW: (setting, label). Recommended: ] to cast and [ to hook, keys
# WoW leaves free. The FishingInteract addon binds them in WoW for you (after a /reload).
KEYS = [("cast-key", "Cast"), ("interact-key", "Hook (Interact)")]
RECOMMENDED_KEYS = install_addon.DEFAULT_KEYS
PUNCTUATION = set("[];',./\\-=`")

BG, FG, DIM = "#1e1e1e", "#d4d4d4", "#8a8a8a"
STATUS_COLORS = {"Stopped": "#c0c0c0", "Starting": "#e5c07b", "Fishing": "#98c379", "Paused": "#e5c07b",
                 "On a break": "#61afef"}


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def key_name(event):
    """The key pressed, as main.py presses it ("]", "f", "7", "f5"), or None if it can't be used:
    letters, digits, punctuation and F1-F12 can (the number pad, modifiers and Shift+ can't)."""
    if re.fullmatch(r"F([1-9]|1[0-2])", event.keysym):
        return event.keysym.lower()
    if event.keysym.startswith("KP_"):
        return None
    ch = event.char
    if len(ch) == 1 and ch.isascii() and (ch.isalnum() or ch in PUNCTUATION):
        return ch.lower()
    return None


def shown(key):
    return key.upper() if len(key) > 1 or key.isalpha() else key

# Tk can't draw characters outside the Basic Multilingual Plane (most emoji): drop them
WIDE = re.compile("[\U00010000-\U0010FFFF]")


def console_python():
    """python.exe next to this pythonw.exe, so main.py's output can be read."""
    exe = sys.executable
    folder, name = os.path.split(exe)
    if name.lower() == "pythonw.exe":
        candidate = os.path.join(folder, "python.exe")
        if os.path.exists(candidate):
            return candidate
    return exe


class Trainer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FishingTrainer")
        self.geometry("1180x500")
        self.minsize(800, 320)
        self.configure(bg=BG)
        self.proc = None
        self.lines = queue.Queue()

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=10, pady=(10, 6))
        style = dict(width=9, relief="flat", bg="#333333", fg=FG, activebackground="#444444",
                     activeforeground=FG, disabledforeground="#666666", font=("Segoe UI", 10))
        self.start_btn = tk.Button(bar, text="Start", command=self.start, **style)
        self.pause_btn = tk.Button(bar, text="Pause", command=self.pause, state="disabled", **style)
        self.stop_btn = tk.Button(bar, text="Stop", command=self.stop, state="disabled", **style)
        for b in (self.start_btn, self.pause_btn, self.stop_btn):
            b.pack(side="left", padx=(0, 6))
        self.status = tk.Label(bar, text="Stopped", bg=BG, font=("Segoe UI", 11, "bold"))
        self.status.pack(side="right")

        # options: remembered between runs, and they switch while it fishes too
        saved = load_settings()
        options = tk.Frame(self, bg=BG)
        options.pack(fill="x", padx=10, pady=(0, 6))
        self.options = {}
        for key, text in OPTIONS:
            var = tk.BooleanVar(value=saved.get(key, True))
            self.options[key] = var
            tk.Checkbutton(options, text=text, variable=var, command=lambda k=key: self.option_changed(k),
                           bg=BG, fg=FG, selectcolor="#333333", activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 10)).pack(side="left", padx=(0, 16))

        # keys: click one, then press the key you want
        keys = tk.Frame(self, bg=BG)
        keys.pack(fill="x", padx=10, pady=(0, 6))
        self.keys, self.key_buttons, self.capturing = {}, {}, None
        tk.Label(keys, text="Keys:", bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left", padx=(0, 8))
        for key, text in KEYS:
            self.keys[key] = saved.get(key) or RECOMMENDED_KEYS[key]
            tk.Label(keys, text=text, bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left", padx=(0, 4))
            button = tk.Button(keys, width=4, relief="flat", bg="#333333", fg=FG, activebackground="#444444",
                               activeforeground=FG, font=("Consolas", 11, "bold"),
                               command=lambda k=key: self.capture_key(k))
            button.pack(side="left", padx=(0, 14))
            button.bind("<KeyPress>", lambda e, k=key: self.key_pressed(k, e))
            button.bind("<FocusOut>", lambda e, k=key: self.end_capture(k))
            self.key_buttons[key] = button
            self.show_key(key)
        tk.Button(keys, text="Use [ and ] (recommended)", relief="flat", bg="#333333", fg=FG,
                  activebackground="#444444", activeforeground=FG, font=("Segoe UI", 9),
                  command=self.recommended_keys).pack(side="left", padx=(0, 10))
        tk.Label(keys, text="Click a key box, then press the key.", bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left")

        mono = tkfont.Font(family="Consolas", size=10)
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # right: what the trainer saw after the last cast, and whether it found your bobber
        side = tk.Frame(body, bg=BG, width=PICTURE_WIDTH)
        side.pack(side="right", fill="y", padx=(8, 0))
        side.pack_propagate(False)
        self.bobber = tk.Label(side, text="Bobber: not looked for yet", bg=BG, fg=DIM, anchor="w",
                               font=("Segoe UI", 10, "bold"))
        self.bobber.pack(fill="x")
        self.picture = tk.Label(side, bg="#111111", text="The screen after your next cast\nshows here.",
                                fg=DIM, font=("Segoe UI", 9))
        self.picture.pack(fill="x", pady=(4, 2))
        tk.Label(side, text="Green circle: your bobber.  Red: other new spots in its colours.",
                 bg=BG, fg=DIM, font=("Segoe UI", 8), anchor="w", justify="left",
                 wraplength=PICTURE_WIDTH).pack(fill="x")
        self.photo = None

        frame = tk.Frame(body, bg=BG)
        frame.pack(side="left", fill="both", expand=True)
        scroll = tk.Scrollbar(frame)
        scroll.pack(side="right", fill="y")
        self.log = tk.Text(frame, bg=BG, fg=FG, insertbackground=FG, font=mono, wrap="word",
                           relief="flat", yscrollcommand=scroll.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.log.yview)
        self.log.tag_config("dim", foreground=DIM)
        self.log.tag_config("warn", foreground="#e5c07b")
        self.log.tag_config("bad", foreground="#e06c75")

        tk.Label(self, text="Ctrl+Shift in the game pauses and resumes too.  Closing this window stops fishing.",
                 bg=BG, fg=DIM, font=("Segoe UI", 9)).pack(fill="x", padx=10, pady=(0, 8))

        self.set_status("Stopped")
        self.write("Press Start, then switch to WoW.", "dim")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.pump)

    # -- the log --------------------------------------------------------------------
    def write(self, text, tag=None):
        text = WIDE.sub("", text).rstrip()
        if tag is None:
            tag = "bad" if text.startswith(("❌", "Traceback")) else "warn" if text.startswith("⚠") else None
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_status(self, text):
        self.status.configure(text=text, fg=STATUS_COLORS.get(text, FG))

    def show_capture(self, caption, color):
        """The picture main.py just saved, shrunk to fit, under whether it found the bobber."""
        self.bobber.configure(text=caption, fg=color)
        try:
            photo = tk.PhotoImage(file=CAPTURE)
        except (tk.TclError, OSError):
            self.picture.configure(image="", text="(no picture saved)")
            return
        shrink = max(1, -(-photo.width() // PICTURE_WIDTH))          # whole steps, rounding up
        self.photo = photo.subsample(shrink, shrink) if shrink > 1 else photo
        self.picture.configure(image=self.photo, text="")

    # -- the trainer process --------------------------------------------------------
    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        args = [console_python(), "-u", os.path.join(HERE, "main.py"), "--gui"]
        for key, var in self.options.items():
            flag = START_FLAGS[key][0 if var.get() else 1]
            if flag:
                args.append(flag)
        for key, value in self.keys.items():
            args += [f"--{key}", value]
        try:
            self.proc = subprocess.Popen(
                args, cwd=HERE, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=NO_WINDOW)
        except OSError as e:
            self.write(f"❌ Couldn't start main.py: {e}")
            return
        self.write("")
        self.set_status("Starting")
        self.start_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal", text="Pause")
        self.stop_btn.configure(state="normal")
        threading.Thread(target=self.read, args=(self.proc,), daemon=True).start()

    def read(self, proc):
        for line in proc.stdout:
            self.lines.put(line)
        proc.wait()
        self.lines.put(None)                     # it ended

    def pump(self):
        """Show what main.py printed (on the window's own thread), and follow its state."""
        try:
            while True:
                line = self.lines.get_nowait()
                if line is None:
                    self.ended()
                    continue
                self.write(line)
                if line.startswith("⏸"):
                    self.set_status("Paused")
                    self.pause_btn.configure(text="Resume")
                elif line.startswith("☕ Taking a break"):
                    self.set_status("On a break")
                elif line.startswith("▶") or line.startswith("⌨"):
                    self.set_status("Fishing")
                    self.pause_btn.configure(text="Pause")
                if "Your bobber is at" in line:
                    where = re.search(r"\((\d+), (\d+)\)", line)
                    self.show_capture("Bobber: found" + (f" at {where.group(1)}, {where.group(2)}" if where else ""),
                                      STATUS_COLORS["Fishing"])
                elif "Couldn't find your bobber" in line or "Couldn't look for your bobber" in line:
                    self.show_capture("Bobber: not found", "#e06c75")
        except queue.Empty:
            pass
        self.after(100, self.pump)

    def tell(self, command):
        """Send main.py a command (one line on its stdin) while it runs."""
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(command + "\n")
                self.proc.stdin.flush()
            except OSError:
                pass

    def pause(self):
        self.tell("pause")

    def option_changed(self, key):
        """A checkbox changed: tell the trainer if it's running, and remember it."""
        self.tell(f"{key} {'on' if self.options[key].get() else 'off'}")
        self.save_settings()

    def save_settings(self):
        data = {k: v.get() for k, v in self.options.items()}
        data.update(self.keys)
        try:
            with open(SETTINGS, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1)
        except OSError:
            pass

    # -- the keys ---------------------------------------------------------------------
    def show_key(self, key):
        self.key_buttons[key].configure(text=shown(self.keys[key]), fg=FG)

    def capture_key(self, key):
        """Clicked a key box: the next key pressed becomes that key."""
        if self.capturing and self.capturing != key:
            self.end_capture(self.capturing)
        self.capturing = key
        self.key_buttons[key].configure(text="...", fg=STATUS_COLORS["Starting"])
        self.key_buttons[key].focus_set()

    def end_capture(self, key):
        if self.capturing == key:
            self.capturing = None
            self.show_key(key)

    def key_pressed(self, key, event):
        if self.capturing != key:
            return None
        if event.keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"):
            return "break"                       # wait for the key itself
        name = key_name(event)
        self.end_capture(key)
        self.focus_set()
        if event.keysym == "Escape":
            return "break"
        if name is None:
            self.write("That key can't be used: pick a letter, number, punctuation key or F1-F12.", "warn")
        else:
            self.set_keys({**self.keys, key: name})
        return "break"

    def recommended_keys(self):
        self.set_keys(dict(RECOMMENDED_KEYS))

    def set_keys(self, keys):
        """New keys: use them now, remember them, and tell the WoW addon to bind them."""
        if keys["cast-key"] == keys["interact-key"]:
            self.write(f"Cast and Hook can't both be {shown(keys['cast-key'])}.", "warn")
            return
        changed = [k for k in keys if keys[k] != self.keys[k]]
        if not changed:
            return
        self.keys = keys
        for key in self.keys:
            self.show_key(key)
        for key in changed:
            self.tell(f"{key} {keys[key]}")
        self.save_settings()
        cast, hook = shown(keys["cast-key"]), shown(keys["interact-key"])
        error = None
        try:
            written = install_addon.write_keys(keys["cast-key"], keys["interact-key"])
        except OSError as e:
            written, error = None, e
        if written:
            self.write(f"Keys: cast {cast}, hook {hook}. In WoW, type /reload so FishingInteract binds them.")
        else:
            self.write(f"Keys: cast {cast}, hook {hook}. "
                       + (f"Couldn't tell the WoW addon ({error}). " if error else
                          "The FishingInteract addon isn't installed: run Install WoW addon.bat, or ")
                       + f"in WoW's Key Bindings put Fish on {cast} and Interact with Target on {hook}.",
                       "warn")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.write("Stopping...", "dim")

    def ended(self):
        code = self.proc.returncode if self.proc else None
        self.write(f"FishingTrainer stopped{'' if code in (0, 1, None) else f' (exit code {code})'}.", "dim")
        self.set_status("Stopped")
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled", text="Pause")
        self.stop_btn.configure(state="disabled")

    def on_close(self):
        self.stop()
        self.destroy()


if __name__ == "__main__":
    Trainer().mainloop()
