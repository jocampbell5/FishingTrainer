# AutoFish_V8_8_1_TBCC_Final.py
import time
import threading
import numpy as np
import pyautogui
import cv2
import mss
import keyboard
import os
import pydirectinput
import win32gui
import win32con
import random
import collections
import sys
import ctypes

# Real screen pixels, so the WoW window, the screenshots and the mouse agree on 4K screens
# with Windows display scaling.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from sound_bite import SplashDetector, SplashHearing, SplashListener, load_templates, noise_floor
import install_addon

# Safety & Input
pyautogui.FAILSAFE = False
pydirectinput.FAILSAFE = False  # the mouse may rest anywhere, even the top-left corner; stop with Ctrl+C
pydirectinput.PAUSE = 0.01

# ====================================================
# CONFIGURATION
# ====================================================
DEBUG = True
SCREENSHOT_REGION = {"left": 600, "top": 70, "width": 670, "height": 400}
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")   # debug pictures

# TBCC Wide-Range Masking (Catching Dull/Shadowy Reds/Purples)
LOWER_RED1 = np.array([0, 20, 20])    
UPPER_RED1 = np.array([25, 255, 255]) 
LOWER_RED2 = np.array([130, 20, 20])  
UPPER_RED2 = np.array([180, 255, 255])

# TBCC Splash Tuning
MOVEMENT_SENSITIVITY = 1.6  # Multiplier above background noise
DIFF_SENSITIVITY = 12       # Detection depth for ripples
TIMEOUT = 22

# Bite detection, best first. If one can't run, the trainer drops to the next:
#   "match"  hears the splash sound itself, in WoW's sound only (sound_bite.py + splash*.wav)
#   "sound"  hears WoW get louder; needs Music and Ambient Sounds off
#   "motion" watches the bobber move
BITE_DETECTION = "match"
MATCH_THRESHOLD = 0.65  # how closely the sound must match a splash recording (1.0 = exactly).
                        # Splashes scored 0.89-1.0 in tests, other game sounds up to 0.70: with
                        # your bobber found, its own splash is checked too, so this can be low.

# Other fishers' splashes sound just like yours. So when a splash is heard, the trainer
# also checks that YOUR bobber splashed: after each cast it finds your bobber on screen
# (the new thing with a red feather and tan cork in SCREENSHOT_REGION) and watches the
# water around it.
CHECK_MY_BOBBER = True
# If it can't find your bobber: hook on the sound alone (True), or recast right away (False).
# The window's checkbox switches this while it runs.
SOUND_ONLY_IF_NO_BOBBER = "--recast-if-no-bobber" not in sys.argv
# Only hook when your own bobber splashed (True), or on any splash heard (False: when you
# fish alone, or where the splash hardly shows, like the ocean). The window's checkbox.
ONLY_MY_SPLASH = "--any-splash" not in sys.argv
BOBBER_SPLASH_LINE = 0.008  # share of the water around your bobber that must turn white.
                            # Tested: bites 0.012-0.051, bobbing up to 0.003, a nameplate passing 0.007.
RIPPLE_LINE = 0.015         # ...or share of the water at the cork's foot that brightens into rings,
                            # for the ocean, where a bite throws up no white water.
                            # Tested (ocean): bites 0.03-0.045, calm water and bobbing up to 0.001.

SOUND_JUMP_DB = 15   # a splash is this many dB louder than the quiet start of the cast...
SOUND_MIN_DB = -45   # ...and at least this loud. Run sound_bite.py to see your levels.
SOUND_BLOCKS = 2     # readings in a row (20 ms apart) above that line

# How to hook the fish when it bites:
#   "interact" presses WoW's Interact key, so the bobber never has to be found on screen.
#              The FishingInteract addon (addon\FishingInteract) turns soft interact on only
#              while you fish, and puts your own settings back after each cast.
#              Install it with: python install_addon.py   (then restart WoW once)
#   "click"    finds the bobber on screen and right-clicks it
HOOK_WITH = "interact"


def arg_value(flag, default):
    """The value after flag on the command line (FishingTrainer.pyw passes its settings)."""
    if flag in sys.argv[:-1]:
        return sys.argv[sys.argv.index(flag) + 1]
    return default


# The keys, as pydirectinput names them ("[", "f", "f5"...). The window sets them; the
# FishingInteract addon binds them in WoW for you (after a /reload).
INTERACT_KEY = arg_value("--interact-key", "[")   # Interact with Target in WoW

# The key that casts Fishing: FishingInteract's Fish key (Key Bindings > FishingInteract).
# It puts your best lure on first when the pole has none. That press doesn't cast, so the
# trainer recasts after TIMEOUT.
CAST_KEY = arg_value("--cast-key", "]")

# Long sessions (the window's checkboxes): stop after SESSION_HOURS, counted from the start,
# breaks and pauses included; and take a break now and then. Both are checked between
# casts, so a break never cuts into a bite.
SESSION_HOURS = 2
STOP_AFTER_SESSION = "--stop-after-session" in sys.argv
TAKE_BREAKS = "--breaks" in sys.argv
BREAK_EVERY = (20, 40)    # minutes of fishing between breaks, picked at random each time
BREAK_LENGTH = (2, 6)     # minutes a break lasts, picked at random each time

running = True
paused = False
started = None            # when fishing started (time.monotonic())
next_break = None
session_over = False
prev_frame = None
hearing = None       # SplashHearing when bites are detected by matching the splash
listener = None      # SplashListener when bites are detected by loudness

# ====================================================
# DETECTION ENGINE
# ====================================================

def find_bobber_procedural(img_np):
    """Isolates the bobber using color masking and shape analysis."""
    try:
        hsv = cv2.cvtColor(img_np, cv2.COLOR_RGB2HSV)
        
        # Create a combined mask of two red/purple hue ranges
        mask1 = cv2.inRange(hsv, LOWER_RED1, UPPER_RED1)
        mask2 = cv2.inRange(hsv, LOWER_RED2, UPPER_RED2)
        mask = cv2.bitwise_or(mask1, mask2)
        
        # Open kernel to remove vertical fishing lines
        kernel = np.ones((1, 2), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        if DEBUG:
            if not os.path.exists(SAVE_DIR): os.makedirs(SAVE_DIR)
            cv2.imwrite(os.path.join(SAVE_DIR, "latest_mask.png"), mask)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # TBCC bobber area filter
        candidates = [(cv2.contourArea(cnt), cnt) for cnt in contours if 3 < cv2.contourArea(cnt) < 600]
        
        if not candidates:
            return None, None
            
        candidates.sort(key=lambda x: x[0], reverse=True)
        x, y, w, h = cv2.boundingRect(candidates[0][1])
        return x + w//2, y + h//2
    except Exception as e:
        print(f"Find Error: {e}")
        return None, None

def get_motion_score(snap, ix, iy):
    """Calculates pixel change in the Saturation channel around the bobber."""
    global prev_frame
    try:
        hsv = cv2.cvtColor(snap, cv2.COLOR_RGB2HSV)
        s_channel = hsv[:,:,1] 
        
        # Crop tight around the bobber to ignore outside waves
        y1, y2 = max(0, iy-20), min(snap.shape[0], iy+20)
        x1, x2 = max(0, ix-20), min(snap.shape[1], ix+20)
        crop = s_channel[y1:y2, x1:x2]
        
        curr_s = cv2.GaussianBlur(crop, (3, 3), 0)
        if prev_frame is None or prev_frame.shape != curr_s.shape:
            prev_frame = curr_s
            return 0

        diff = cv2.absdiff(prev_frame, curr_s)
        _, thresh = cv2.threshold(diff, DIFF_SENSITIVITY, 255, cv2.THRESH_BINARY)
        score = np.sum(thresh) / 255
        prev_frame = curr_s
        return score
    except:
        return 0

# ----- Your own bobber: is it your splash, or another fisher's? -----

def wow_area():
    """Where WoW's game picture is on screen: (left, top, width, height), on whichever
    monitor it's on, or None when the window isn't found."""
    hwnd = win32gui.FindWindow(None, "World of Warcraft")
    if not hwnd:
        return None
    _, _, width, height = win32gui.GetClientRect(hwnd)
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    return (left, top, width, height) if width > 0 and height > 0 else None

def scene_region():
    """SCREENSHOT_REGION (set for a 1920x1080 game), placed in the WoW window and scaled to
    its size, wherever it is (any monitor). Without the window: the main monitor."""
    area = wow_area()
    if area:
        left, top, width, height = area
    else:
        with mss.mss() as sct:
            mon = sct.monitors[1]
        left, top, width, height = mon["left"], mon["top"], mon["width"], mon["height"]
    sx, sy = width / 1920, height / 1080
    r = SCREENSHOT_REGION
    return {"left": left + int(r["left"] * sx), "top": top + int(r["top"] * sy),
            "width": int(r["width"] * sx), "height": int(r["height"] * sy)}

def grab(region):
    """The screen in `region`, as a BGR picture."""
    with mss.mss() as sct:
        return np.ascontiguousarray(np.array(sct.grab(region))[:, :, :3])

def new_bobber_spots(before, after, scale=1.0):
    """Spots in `after` that weren't there `before` and have the bobber's colours
    (red feather, tan cork): (area, x, y, size), biggest first. `scale` is how much bigger
    the game is than 1920x1080 (2 on a 4K screen), so the bobber's size is judged right."""
    diff = cv2.absdiff(cv2.GaussianBlur(after, (5, 5), 0), cv2.GaussianBlur(before, (5, 5), 0)).max(axis=2)
    hsv = cv2.cvtColor(cv2.GaussianBlur(after, (3, 3), 0), cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    # warm (red feather, tan cork) and brighter than the water. In dim light the cork's colour
    # fades (saturation ~50 in a cave), so this can't ask for much: water and rock are teal and
    # green, so they still don't count, and only what's new since the cast is looked at.
    colour = ((hue < 30) | (hue >= 160)) & (sat >= 35) & (val >= 50)
    mask = ((diff > 25) & colour).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8))   # joins the feather and the cork
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    spots = []
    for left, top, w, h, area in stats[1:]:
        if area >= 60 * scale * scale and 0.45 <= w / h <= 2.2:   # not the thin pole or line
            spots.append((int(area), int(left + w // 2), int(top + h // 2), int(max(w, h))))
    return sorted(spots, reverse=True)

def find_my_bobber(before, region):
    """Where your new bobber is, in screen pixels (x, y, size), or None. Looks twice,
    0.7 s apart: your bobber stays put, glints on the water don't."""
    scale = region["width"] / SCREENSHOT_REGION["width"]
    first = new_bobber_spots(before, grab(region), scale)
    time.sleep(0.7)
    after = grab(region)
    seen = new_bobber_spots(before, after, scale)
    near = 20 * scale
    spots = [s for s in seen if any(abs(s[1] - x1) <= near and abs(s[2] - y1) <= near for _, x1, y1, _ in first)]
    # WoW can float a gear icon over the bobber, in the same colours: the bobber is the spot under it
    spots = [s for s in spots
             if not any(abs(o[1] - s[1]) <= 25 * scale and 15 * scale < o[2] - s[2] < 250 * scale for o in spots)]
    if DEBUG:
        # what it saw: your bobber circled green; other new spots in its colours in red
        pic = after.copy()
        for _, x, y, size in seen:
            cv2.circle(pic, (x, y), size, (0, 0, 255), 2)
        if spots:
            cv2.circle(pic, spots[0][1:3], spots[0][3] + 4, (0, 255, 0), 3)
        os.makedirs(SAVE_DIR, exist_ok=True)
        cv2.imwrite(os.path.join(SAVE_DIR, "latest_bobber.png"), pic)
    if not spots:
        return None
    _, x, y, size = spots[0]   # the biggest
    return region["left"] + x, region["top"] + y, size

class BobberWatch:
    """Keeps the last 3 s of the water around your bobber, 20 pictures a second."""

    SETTLE = 2.0   # seconds: the bobber's own landing splash can still be in the pictures

    def __init__(self, x, y, size, start=True):
        half = max(30, int(1.5 * size))
        with mss.mss() as sct:
            screen = sct.monitors[0]   # all screens together
        left = min(max(x - half, screen["left"]), screen["left"] + screen["width"] - 2 * half)
        top = min(max(y - half, screen["top"]), screen["top"] + screen["height"] - 2 * half)
        self.box = {"left": left, "top": top, "width": 2 * half, "height": 2 * half}
        self.frames = collections.deque(maxlen=60)   # (time, brightness, colourfulness, picture)
        self.started = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        if start:
            self._thread.start()

    def _run(self):
        with mss.mss() as sct:
            while not self._stop.is_set():
                self.add(time.monotonic(), np.array(sct.grab(self.box))[:, :, :3])
                self._stop.wait(0.05)

    # Ripples: in the ocean (and other bright, clear water) a bite throws up no white water,
    # only faint rings at the foot of the cork. They're looked for in a small picture (SMALL
    # pixels across, whatever the screen), inside an oval at the cork's foot, leaving out the
    # cork, the feather, shadows and the pole, which sway and bob all the time.
    SMALL = 160
    _yy, _xx = np.mgrid[:SMALL, :SMALL]
    _size = SMALL / 3                       # the box is 3 bobbers wide
    FOOT = ((_xx - SMALL / 2) / (0.9 * _size)) ** 2 + ((_yy - SMALL / 2 - 0.25 * _size) / (0.45 * _size)) ** 2 <= 1
    del _yy, _xx, _size

    def add(self, t, bgr):
        grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.int16)
        sat = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, 1]
        small = cv2.resize(np.ascontiguousarray(bgr), (self.SMALL, self.SMALL))
        hsv = cv2.cvtColor(cv2.GaussianBlur(small, (3, 3), 0), cv2.COLOR_BGR2HSV)
        hue, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        not_water = (((hue < 30) | (hue >= 160)) & (s >= 35) & (v >= 50)) | (v < 70)   # cork, feather, pole, shadow
        water = cv2.dilate(not_water.astype(np.uint8), np.ones((5, 5), np.uint8)) == 0
        small_grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.int16)
        with self._lock:
            if self.started is None:
                self.started = t
            self.frames.append((t, grey, sat, bgr, small_grey, water))

    def splash(self, seconds=2.0, gap=0.5):
        """(white, ripples) at most in the last `seconds`, each vs `gap` s earlier: how much of
        the water around your bobber turned white, and how much of the water at the cork's foot
        brightened into rings. A bite throws up white water, or in bright clear water, rings;
        bobbing moves the tan cork, nameplates passing by are yellow or thin text, so none of
        those count. None in the first SETTLE seconds, while the landing splash may still show."""
        with self._lock:
            frames, started = list(self.frames), self.started
        if not frames or frames[-1][0] - started < self.SETTLE:
            return None
        now, white, rings, j = frames[-1][0], 0.0, 0.0, 0
        for f in frames:
            t = f[0]
            while j + 1 < len(frames) and frames[j + 1][0] <= t - gap:
                j += 1                   # frames[j]: the last picture at least `gap` earlier
            e = frames[j]
            if t >= now - seconds and e[0] <= t - gap and t - gap - e[0] < 0.2:
                white = max(white, float(self.white(f[1], f[2], e[1]).mean()))
                rings = max(rings, float(self.ripples(f, e).sum()) / self.FOOT.sum())
        return white, rings

    @staticmethod
    def white(grey, sat, earlier):
        """Where the water turned white since `earlier`: 1 there, 0 elsewhere."""
        white = (((grey - earlier) > 30) & (sat < 50)).astype(np.uint8)
        return cv2.morphologyEx(white, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))   # not thin text

    @classmethod
    def ripples(cls, frame, earlier):
        """Where the water at the cork's foot brightened since `earlier` (small picture)."""
        brighter = frame[4] - earlier[4]
        rings = ((brighter > 12) & (brighter < 60) & cls.FOOT & frame[5] & earlier[5]).astype(np.uint8)
        return cv2.morphologyEx(rings, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    def save_picture(self, path, seconds=1.6, pictures=8, gap=0.5):
        """The water around your bobber over the last `seconds`, left to right; under each,
        what counted as turning white (red) and as rings (yellow), and where rings are
        looked for (the grey oval). To see what a bite looks like where you fish."""
        with self._lock:
            frames = list(self.frames)
        if not frames:
            return
        now = frames[-1][0]
        size = self.SMALL
        foot = cv2.findContours(self.FOOT.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
        top, bottom = [], []
        for k in range(pictures):
            when = now - seconds + seconds * k / (pictures - 1)
            i = min(range(len(frames)), key=lambda n: abs(frames[n][0] - when))
            f = frames[i]
            j = min(range(len(frames)), key=lambda n: abs(frames[n][0] - (f[0] - gap)))
            small = cv2.resize(np.ascontiguousarray(f[3]), (size, size))
            shown = (small // 3).copy()
            cv2.drawContours(shown, foot, -1, (90, 90, 90), 1)
            if frames[j][0] < f[0]:
                white = cv2.resize(self.white(f[1], f[2], frames[j][1]), (size, size),
                                   interpolation=cv2.INTER_NEAREST)
                shown[white > 0] = (0, 0, 255)
                shown[self.ripples(f, frames[j]) > 0] = (0, 255, 255)
            top.append(small)
            bottom.append(shown)
        pic = np.vstack([np.hstack(top), np.hstack(bottom)])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, pic)

    def close(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(1)

def watch_my_bobber(before, region):
    """A BobberWatch on your new bobber, or None (then the sound alone decides)."""
    if before.max() <= 5:
        print("⚠️ The picture of the screen came out black, so your bobber can't be seen and the sound"
              " alone decides. In WoW: Options > Graphics > Display Mode: Windowed (Fullscreen).")
        return None
    try:
        found = find_my_bobber(before, region)
    except Exception as e:
        print(f"⚠️ Couldn't look for your bobber ({e}). Going by the sound alone.")
        return None
    if not found:
        then = ("going by the sound alone, so other fishers' splashes may count."
                if SOUND_ONLY_IF_NO_BOBBER else "recasting.")
        print("⚠️ Couldn't find your bobber on screen: " + then
              + (" See captures/latest_bobber.png" if DEBUG else ""))
        return None
    x, y, size = found
    print(f"🎯 Your bobber is at ({x}, {y})")
    return BobberWatch(x, y, size)

def wait_for_bite_match(watch=None):
    """Listens for the splash sound itself and, with a BobberWatch, checks it was your
    bobber that splashed. True on your bite, False on timeout or pause."""
    hearing.flush()  # the cast's own sounds
    print(f"👂 Listening for the splash (match line {MATCH_THRESHOLD:.2f})")
    end = time.monotonic() + TIMEOUT
    best, others = -1.0, 0
    while not paused and (left := end - time.monotonic()) > 0:
        heard, score = hearing.wait_for_match(MATCH_THRESHOLD, left, lambda: not paused)
        best = max(best, score)
        if not heard:
            break
        if watch is None:
            print(f"💦 Splash heard (match {score:.2f})")
            return True
        time.sleep(0.3)                  # so the pictures of the splash are in
        moved = watch.splash()
        seen = "" if moved is None else f"white water {moved[0]:.1%}, rings {moved[1]:.1%}"
        if DEBUG:
            try:
                watch.save_picture(os.path.join(SAVE_DIR, "latest_splash.png"))
            except Exception:
                pass
        if not ONLY_MY_SPLASH:
            print(f"💦 Splash heard (match {score:.2f})" + (f"; at your bobber: {seen}" if seen else ""))
            return True
        if moved is None:
            print(f"💦 Splash heard (match {score:.2f}) right as your bobber landed; going by the sound")
            return True
        if moved[0] >= BOBBER_SPLASH_LINE or moved[1] >= RIPPLE_LINE:
            print(f"💦 Splash heard (match {score:.2f}) and your bobber splashed ({seen})")
            return True
        print(f"🙉 Splash heard (match {score:.2f}), but your bobber didn't splash ({seen}): "
              f"another fisher's. Still listening... See captures/latest_splash.png")
        others += 1
        time.sleep(1.0)
        hearing.flush()                  # the rest of that splash
    problem = f" | {hearing.problem}" if hearing.problem else ""
    if others:
        print(f"⌛ No bite on your bobber ({others} other fisher's splash(es) ignored){problem}")
    else:
        print(f"⌛ No splash heard (best match: {max(best, 0):.2f}){problem}")
    return False

def wait_for_bite_sound():
    """Listens for the splash. True when one is heard, False on timeout or pause."""
    listener.flush()  # the cast's own sounds
    noise = noise_floor(listener.levels_for(0.4))
    detector = SplashDetector(noise, SOUND_JUMP_DB, SOUND_MIN_DB, SOUND_BLOCKS)
    print(f"🔊 Listening. Background: {noise:.0f} dB | Splash line: {detector.threshold:.0f} dB")
    if listener.wait_for_splash(detector, TIMEOUT, lambda: not paused):
        print(f"💦 Splash heard ({detector.peak:.0f} dB)")
        return True
    print(f"⌛ No splash heard (loudest: {detector.peak:.0f} dB)")
    return False

def wait_for_bite_motion(x, y):
    """Watches the bobber for movement. True on a bite, False on timeout or pause."""
    global prev_frame
    prev_frame = None

    # Calibration: Establish the "normal" noise of the water
    print("📏 Calibrating noise floor...")
    noise_samples = []
    for _ in range(15):
        with mss.mss() as sct:
            sample_img = cv2.cvtColor(np.array(sct.grab(scene_region())), cv2.COLOR_BGRA2RGB)
        noise_samples.append(get_motion_score(sample_img, x, y))
        time.sleep(0.02)

    avg_noise = sum(noise_samples) / len(noise_samples)
    # Threshold must be significantly higher than background noise
    dynamic_threshold = max(65, avg_noise * MOVEMENT_SENSITIVITY)
    print(f"🎯 Locked. Noise: {int(avg_noise)} | Threshold: {int(dynamic_threshold)}")

    start_time = time.time()
    while time.time() - start_time < TIMEOUT and not paused:
        with mss.mss() as sct:
            snap = cv2.cvtColor(np.array(sct.grab(scene_region())), cv2.COLOR_BGRA2RGB)

        if get_motion_score(snap, x, y) > dynamic_threshold:
            return True
        time.sleep(0.02)
    return False

# ====================================================
# HUMAN BEHAVIOR SIMULATION
# ====================================================

def human_click(x, y):
    """Simulates natural reaction time and non-linear mouse movement."""
    # Randomized reaction delay (Human average + variance)
    wait_time = random.uniform(0.5, 1.3)
    print(f"🕒 Splash! Reacting in {wait_time:.2f}s...")
    time.sleep(wait_time)
    
    # Target coordinate with +/- 2 pixel variance
    region = scene_region()                  # x, y are inside it (in the WoW window)
    target_x = (region["left"] + x) + random.randint(-2, 2)
    target_y = (region["top"] + y) + random.randint(-2, 2)
    
    # Human-like mouse glide (easeOutQuad starts fast, ends slow)
    pyautogui.moveTo(target_x, target_y, 
                     duration=random.uniform(0.18, 0.35), 
                     tween=pyautogui.easeOutQuad)
    
    # Hold click slightly (40-100ms) to look like a physical button press
    pyautogui.mouseDown(button='right')
    time.sleep(random.uniform(0.04, 0.10))
    pyautogui.mouseUp(button='right')
    print("✅ Caught!")

def press_interact():
    """Hooks the fish with WoW's Interact key; soft interact has already picked the bobber."""
    pydirectinput.press(INTERACT_KEY)
    print("✅ Caught! (Interact key)")

# ====================================================
# MAIN FISHING CYCLE
# ====================================================

def schedule_break():
    global next_break
    next_break = time.monotonic() + random.uniform(*BREAK_EVERY) * 60


def time_up():
    return STOP_AFTER_SESSION and started is not None and time.monotonic() - started >= SESSION_HOURS * 3600


def between_casts():
    """Stop when the session's time is up; take a break when one is due. False once
    fishing should stop."""
    global running, session_over
    if time_up():
        print(f"⏹ {SESSION_HOURS} hours are up: stopping.", flush=True)
        running, session_over = False, True
        return False
    if TAKE_BREAKS and next_break and time.monotonic() >= next_break:
        length = random.uniform(*BREAK_LENGTH) * 60
        back = time.strftime("%H:%M", time.localtime(time.time() + length))
        print(f"☕ Taking a break: {int(length // 60)} min {int(length % 60)} s (back at {back})", flush=True)
        end = time.monotonic() + length
        while running and TAKE_BREAKS and time.monotonic() < end and not time_up():
            time.sleep(0.5)                       # switching breaks off ends this one
        schedule_break()
        if time_up():
            return between_casts()
        print("▶ Back to fishing", flush=True)
    return running


def fishing_cycle():
    global running, paused, prev_frame
    while running:
        if paused:
            time.sleep(0.5)
            continue
        if not between_casts():
            break

        # Bring WoW to focus
        hwnd = win32gui.FindWindow(None, "World of Warcraft")
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.SetForegroundWindow(hwnd)
            pydirectinput.press('alt')

        time.sleep(random.uniform(0.8, 1.5))
        # The water before the cast, so your new bobber can be found after it
        check = CHECK_MY_BOBBER and hearing is not None and BITE_DETECTION == "match"
        region = scene_region() if check else None
        before = grab(region) if check else None
        pydirectinput.press(CAST_KEY) # FishingInteract's Fish key (or a plain Cast Fishing button)
        print("\n🎣 Casting (TBCC Wide Masking)...")
        time.sleep(2.5) # Wait for bobber to land and ripples to settle

        # The bobber only has to be found on screen to click it, or to see the bite
        x = y = None
        if HOOK_WITH == "click" or not (hearing or listener):
            with mss.mss() as sct:
                img = cv2.cvtColor(np.array(sct.grab(scene_region())), cv2.COLOR_BGRA2RGB)

            res = find_bobber_procedural(img)
            if not (res and res[0] is not None):
                print("⚠️ Bobber not detected. Check latest_mask.png")
                continue
            x, y = res

        if hearing:
            watch = watch_my_bobber(before, region) if check else None
            if check and watch is None and not SOUND_ONLY_IF_NO_BOBBER:
                print("↻ No bobber found: casting again")
                continue
            try:
                bite = wait_for_bite_match(watch)
            finally:
                if watch:
                    watch.close()
        elif listener:
            bite = wait_for_bite_sound()
        else:
            bite = wait_for_bite_motion(x, y)
        if bite:
            if HOOK_WITH == "interact":
                press_interact()
            else:
                human_click(x, y)
            time.sleep(random.uniform(3.0, 5.0)) # Looting/Reset delay

def toggle_pause():
    """Ctrl+Shift, or the window's Pause button: stop or resume fishing, and say which."""
    global paused
    paused = not paused
    print("⏸ Paused (Ctrl+Shift to resume)" if paused else "▶ Fishing", flush=True)


def listen_to_window():
    """Commands from FishingTrainer.pyw, one per line on stdin."""
    global SOUND_ONLY_IF_NO_BOBBER, ONLY_MY_SPLASH, STOP_AFTER_SESSION, TAKE_BREAKS, CAST_KEY, INTERACT_KEY
    for line in sys.stdin:
        command = line.strip()
        name, _, value = command.partition(" ")
        if name in ("cast-key", "interact-key") and value:
            if name == "cast-key":
                CAST_KEY = value
            else:
                INTERACT_KEY = value
            print(keys_line(), flush=True)
        elif command == "pause":
            toggle_pause()
        elif command in ("sound-only on", "sound-only off"):
            SOUND_ONLY_IF_NO_BOBBER = command.endswith("on")
            print("👂 No bobber found: hook on the sound alone" if SOUND_ONLY_IF_NO_BOBBER
                  else "↻ No bobber found: cast again", flush=True)
        elif command in ("my-splash on", "my-splash off"):
            ONLY_MY_SPLASH = command.endswith("on")
            print(splash_line(), flush=True)
        elif command in ("stop-after on", "stop-after off"):
            STOP_AFTER_SESSION = command.endswith("on")
            print(session_line(), flush=True)
        elif command in ("breaks on", "breaks off"):
            TAKE_BREAKS = command.endswith("on")
            if TAKE_BREAKS and next_break is None:
                schedule_break()
            print(breaks_line(), flush=True)


def splash_line():
    return ("👀 Hooks only when your own bobber splashes" if ONLY_MY_SPLASH
            else "👂 Hooks on any splash heard (your bobber isn't checked)")


def keys_line():
    return f"🔑 Casts with {CAST_KEY}, hooks with {INTERACT_KEY}"


def session_line():
    if not STOP_AFTER_SESSION:
        return "⏱ No time limit"
    at = time.time() + (SESSION_HOURS * 3600 - (time.monotonic() - started if started else 0))
    return f"⏱ Stops after {SESSION_HOURS} hours (at {time.strftime('%H:%M', time.localtime(at))})"


def breaks_line():
    if not TAKE_BREAKS:
        return "☕ No breaks"
    return (f"☕ Takes a {BREAK_LENGTH[0]}-{BREAK_LENGTH[1]} minute break every "
            f"{BREAK_EVERY[0]}-{BREAK_EVERY[1]} minutes")


def main():
    global hearing, listener
    print("🚀 AutoFish V8.8.1 | TBCC Wide Range Mode")
    if BITE_DETECTION == "match":
        try:
            templates = load_templates(os.path.dirname(os.path.abspath(__file__)))
            if not templates:
                raise RuntimeError("no splash*.wav recordings next to main.py")
            hearing = SplashHearing([t for _, t in templates])
            print(f"👂 Bites by matching the splash sound ({len(templates)} recording(s)), "
                  f"from {hearing.source}'s sound only")
            print("   In WoW: Sound Effects on. Music and Ambient Sounds can stay on.")
        except Exception as e:
            print(f"⚠️ Can't match the splash sound ({e}). Trying loudness instead.")
    if hearing is None and BITE_DETECTION in ("match", "sound"):
        try:
            listener = SplashListener()
            print(f"🔊 Bites by sound, from {listener.source}'s own volume")
            print("   In WoW: Sound Effects on, Music and Ambient Sounds off.")
        except Exception as e:
            print(f"⚠️ Can't listen for the splash ({e}). Watching the bobber instead.")
    if hearing is None and listener is None:
        print("👀 Bites by bobber motion")
    if HOOK_WITH == "interact":
        print(f"🎯 Hooks with the Interact key ({INTERACT_KEY}), no bobber finding needed")
        addon = install_addon.status()
        if addon != "ok":
            print(f"⚠️ The FishingInteract addon is {addon} in WoW, so Interact may not reach the bobber.")
            print("   Run: python install_addon.py   then restart WoW (or /reload if it was already installed)")
    else:
        print("🖱️ Hooks by right-clicking the bobber")
    global started
    started = time.monotonic()
    if TAKE_BREAKS:
        schedule_break()
    print(keys_line())
    if hearing is not None and CHECK_MY_BOBBER:
        print(splash_line())
    print(session_line())
    print(breaks_line())
    print("⌨️  Ctrl+Shift = Toggle Pause/Play")
    keyboard.add_hotkey('ctrl+shift', toggle_pause)
    if "--gui" in sys.argv:
        # started by FishingTrainer.pyw: its buttons and checkboxes send commands on stdin
        threading.Thread(target=listen_to_window, daemon=True).start()

    thread = threading.Thread(target=fishing_cycle, daemon=True)
    thread.start()

    try:
        while thread.is_alive(): time.sleep(1)
        if not session_over:
            print("\n❌ Fishing stopped because of the error above.")
    except KeyboardInterrupt:
        print("\nStopping...")

if __name__ == "__main__":
    main()