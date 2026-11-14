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
SAVE_DIR = r"C:\Users\johnc\Documents\FishingTrainer"

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
MATCH_THRESHOLD = 0.80  # how closely the sound must match a splash recording (1.0 = exactly).
                        # Splashes scored 0.89-1.0 in tests, other game sounds up to 0.70.

# Other fishers' splashes sound just like yours. So when a splash is heard, the trainer
# also checks that YOUR bobber splashed: after each cast it finds your bobber on screen
# (the new thing with a red feather and tan cork in SCREENSHOT_REGION) and watches the
# water around it. If it can't find the bobber, it goes by the sound alone.
CHECK_MY_BOBBER = True
BOBBER_SPLASH_LINE = 0.008  # share of the water around your bobber that must turn white.
                            # Tested: bites 0.012-0.051, bobbing up to 0.003, a nameplate passing 0.007.

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
INTERACT_KEY = "["   # your Interact key binding in WoW

# The key that casts Fishing. Bind FishingInteract's Fish key to it in WoW
# (Key Bindings > FishingInteract): it puts your best lure on first when the pole
# has none. That press doesn't cast, so the trainer recasts after TIMEOUT.
CAST_KEY = "9"

running = True
paused = False
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
        y1, y2 = max(0, iy-20), min(400, iy+20)
        x1, x2 = max(0, ix-20), min(670, ix+20)
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

def scene_region():
    """SCREENSHOT_REGION (set for a 1920x1080 screen), scaled to this screen."""
    with mss.mss() as sct:
        mon = sct.monitors[1]
    sx, sy = mon["width"] / 1920, mon["height"] / 1080
    r = SCREENSHOT_REGION
    return {"left": mon["left"] + int(r["left"] * sx), "top": mon["top"] + int(r["top"] * sy),
            "width": int(r["width"] * sx), "height": int(r["height"] * sy)}

def grab(region):
    """The screen in `region`, as a BGR picture."""
    with mss.mss() as sct:
        return np.ascontiguousarray(np.array(sct.grab(region))[:, :, :3])

def new_bobber_spots(before, after):
    """Spots in `after` that weren't there `before` and have the bobber's colours
    (red feather, tan cork): (area, x, y, size), biggest first."""
    diff = cv2.absdiff(cv2.GaussianBlur(after, (5, 5), 0), cv2.GaussianBlur(before, (5, 5), 0)).max(axis=2)
    hsv = cv2.cvtColor(cv2.GaussianBlur(after, (3, 3), 0), cv2.COLOR_BGR2HSV)
    hue, sat = hsv[:, :, 0], hsv[:, :, 1]
    colour = ((hue < 30) | (hue >= 160)) & (sat >= 90)   # water and its reflections are duller
    mask = ((diff > 25) & colour).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8))   # joins the feather and the cork
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    spots = []
    for left, top, w, h, area in stats[1:]:
        if area >= 60 and 0.45 <= w / h <= 2.2:            # not the thin pole or line
            spots.append((int(area), int(left + w // 2), int(top + h // 2), int(max(w, h))))
    return sorted(spots, reverse=True)

def find_my_bobber(before, region):
    """Where your new bobber is, in screen pixels (x, y, size), or None. Looks twice,
    0.7 s apart: your bobber stays put, glints on the water don't."""
    first = new_bobber_spots(before, grab(region))
    time.sleep(0.7)
    after = grab(region)
    spots = [s for s in new_bobber_spots(before, after)
             if any(abs(s[1] - x1) <= 20 and abs(s[2] - y1) <= 20 for _, x1, y1, _ in first)]
    # WoW can float a gear icon over the bobber, in the same colours: the bobber is the spot under it
    spots = [s for s in spots
             if not any(abs(o[1] - s[1]) <= 25 and 15 < o[2] - s[2] < 250 for o in spots)]
    if DEBUG:
        pic = after.copy()
        if spots:
            cv2.circle(pic, spots[0][1:3], spots[0][3], (0, 255, 0), 2)
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
        self.frames = collections.deque(maxlen=60)   # (time, brightness, colourfulness)
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

    def add(self, t, bgr):
        grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.int16)
        sat = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, 1]
        with self._lock:
            if self.started is None:
                self.started = t
            self.frames.append((t, grey, sat))

    def splash(self, seconds=2.0, gap=0.5):
        """How much of the water turned white (share of the area, vs `gap` s earlier) at
        most in the last `seconds`. A bite throws up white water; bobbing moves the tan
        cork, nameplates passing by are yellow or thin text, so none of those count. None in the first
        SETTLE seconds, while the bobber's own landing splash may still show."""
        with self._lock:
            frames, started = list(self.frames), self.started
        if not frames or frames[-1][0] - started < self.SETTLE:
            return None
        now, best, j = frames[-1][0], 0.0, 0
        for t, grey, sat in frames:
            while j + 1 < len(frames) and frames[j + 1][0] <= t - gap:
                j += 1                   # frames[j]: the last picture at least `gap` earlier
            t0, earlier, _ = frames[j]
            if t >= now - seconds and t0 <= t - gap and t - gap - t0 < 0.2:
                white = (((grey - earlier) > 30) & (sat < 50)).astype(np.uint8)
                white = cv2.morphologyEx(white, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))   # not thin text
                best = max(best, float(white.mean()))
        return best

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
        print("⚠️ Couldn't find your bobber on screen, so other fishers' splashes may count."
              + (" See latest_bobber.png" if DEBUG else ""))
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
        if moved is None:
            print(f"💦 Splash heard (match {score:.2f}) right as your bobber landed; going by the sound")
            return True
        if moved >= BOBBER_SPLASH_LINE:
            print(f"💦 Splash heard (match {score:.2f}) and your bobber splashed ({moved:.1%})")
            return True
        print(f"🙉 Splash heard (match {score:.2f}), but your bobber didn't splash ({moved:.1%}): "
              f"another fisher's. Still listening...")
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
            sample_img = cv2.cvtColor(np.array(sct.grab(SCREENSHOT_REGION)), cv2.COLOR_BGRA2RGB)
        noise_samples.append(get_motion_score(sample_img, x, y))
        time.sleep(0.02)

    avg_noise = sum(noise_samples) / len(noise_samples)
    # Threshold must be significantly higher than background noise
    dynamic_threshold = max(65, avg_noise * MOVEMENT_SENSITIVITY)
    print(f"🎯 Locked. Noise: {int(avg_noise)} | Threshold: {int(dynamic_threshold)}")

    start_time = time.time()
    while time.time() - start_time < TIMEOUT and not paused:
        with mss.mss() as sct:
            snap = cv2.cvtColor(np.array(sct.grab(SCREENSHOT_REGION)), cv2.COLOR_BGRA2RGB)

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
    target_x = (SCREENSHOT_REGION["left"] + x) + random.randint(-2, 2)
    target_y = (SCREENSHOT_REGION["top"] + y) + random.randint(-2, 2)
    
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

def fishing_cycle():
    global running, paused, prev_frame
    while running:
        if paused: 
            time.sleep(0.5)
            continue
            
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
                img = cv2.cvtColor(np.array(sct.grab(SCREENSHOT_REGION)), cv2.COLOR_BGRA2RGB)

            res = find_bobber_procedural(img)
            if not (res and res[0] is not None):
                print("⚠️ Bobber not detected. Check latest_mask.png")
                continue
            x, y = res

        if hearing:
            watch = watch_my_bobber(before, region) if check else None
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
            if CHECK_MY_BOBBER:
                print("👀 ...and only when your own bobber splashes, so other fishers' splashes don't count")
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
    print("⌨️  Ctrl+Shift = Toggle Pause/Play")
    keyboard.add_hotkey('ctrl+shift', lambda: globals().update(paused=not paused))
    
    thread = threading.Thread(target=fishing_cycle, daemon=True)
    thread.start()
    
    try:
        while thread.is_alive(): time.sleep(1)
        print("\n❌ Fishing stopped because of the error above.")
    except KeyboardInterrupt:
        print("\nStopping...")

if __name__ == "__main__":
    main()