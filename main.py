# AutoFish.py - Fishing bot for Mists of Pandaria Classic (2026 fixes)
import time
import threading
import numpy as np
import pyautogui
import cv2
from PIL import Image
import mss
import keyboard
import os
import random
import pydirectinput
import win32gui
import win32con

pyautogui.FAILSAFE = False
pydirectinput.PAUSE = 0.04
pydirectinput.FAILSAFE = False

def print_window_titles():
    def callback(hwnd, windows):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if "Warcraft" in title or "World" in title:
                print(f"Possible WoW window: '{title}' (hwnd: {hwnd})")
    win32gui.EnumWindows(callback, None)

print_window_titles()

# ====================================================
# CONFIGURATION
# ====================================================
DEBUG = True
SCREENSHOT_REGION = {"left": 1650, "top": 300, "width": 670, "height": 470}
TEMPLATE_DIR = r"d:\fishingtrainer\bobber_templates"
TEMPLATE_THRESHOLD = 0.52
SCREENSHOT_HEIGHT = SCREENSHOT_REGION["height"]
BOBBER_AREA_BOUNDS = {
    "min_x": 30,
    "max_x": SCREENSHOT_REGION["width"] - 30,
    "min_y": 10,
    "max_y": SCREENSHOT_HEIGHT - 10
}
BOBBER_CROP_SIZE = 70
INTENSITY_CHANGE_THRESHOLD = 4
CONFIRMATION_FRAMES = 3
INTERVAL = 0.1
TIMEOUT = 20
SESSION_LIMIT = 14200
RANDOM_BREAK_CHANCE = 0.10
BREAK_START_DELAY = 300
RANDOM_BREAK_LENGTH = (15, 120)
SAVE_DIR = r"D:\fishingtrainer"
POSITION_AGREEMENT_PX = 30
MIN_AGREEING_TEMPLATES = 2
MOUSE_MOVE_DURATION = 0.15
SQDIFF_ACCEPT = 0.85
MIN_RED_PIXELS_FOR_MATCH = 50  # Raised to kill false positives

running = True
paused = False
initial_intensity = None
break_start_time = None
last_intensity_print = 0
last_time_print = 0

def activate_wow_window():
    hwnd = win32gui.FindWindow(None, "World of Warcraft")
    if hwnd:
        print(f"  → Found WoW hwnd: {hwnd}")
        placement = win32gui.GetWindowPlacement(hwnd)
        is_maximized = placement[1] == win32con.SW_SHOWMAXIMIZED
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.1)
        if is_maximized:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
            time.sleep(0.05)
        pydirectinput.keyDown('alt')
        time.sleep(0.05)
        pydirectinput.keyUp('alt')
        time.sleep(0.1)
    else:
        print("❌ WoW window NOT found! Check title.")

# ====================================================
# HELPER FUNCTIONS
# ====================================================
def ensure_save_dir():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)

def load_templates():
    templates = []
    if not os.path.exists(TEMPLATE_DIR):
        print(f"❌ Template dir missing: {TEMPLATE_DIR}")
        os.makedirs(TEMPLATE_DIR)
        return []
    for filename in os.listdir(TEMPLATE_DIR):
        if filename.lower().endswith(".png"):
            path = os.path.join(TEMPLATE_DIR, filename)
            template = cv2.imread(path, cv2.IMREAD_COLOR)
            if template is not None:
                templates.append((template, filename))
    print(f"🔍 Loaded {len(templates)} templates")
    return templates

def find_bobber(img):
    try:
        img_np = np.array(img)
        print("DEBUG: Entering find_bobber - img shape:", img_np.shape if img_np is not None else "None!")
        
        templates = load_templates()
        print("DEBUG: Loaded templates count:", len(templates))
        if not templates:
            print("❌ No templates loaded!")
            return False, None, None, img_np, None
        
        hsv_img = cv2.cvtColor(img_np, cv2.COLOR_RGB2HSV)
        
        # Stricter purple focus, high saturation to exclude red/brown water
        mask_feather_purple = cv2.inRange(hsv_img, np.array([135, 90, 80]), np.array([185, 255, 255]))
        mask_tip_orange = cv2.inRange(hsv_img, np.array([5, 110, 110]), np.array([35, 255, 255]))
        
        red_mask = cv2.bitwise_or(mask_feather_purple, mask_tip_orange)
        
        # Strict SV floor
        sv_mask = cv2.inRange(hsv_img, np.array([0, 80, 80]), np.array([180, 255, 255]))
        red_mask = cv2.bitwise_and(red_mask, sv_mask)
        
        # Clean-up
        kernel_small = np.ones((2,2), np.uint8)
        red_mask = cv2.erode(red_mask, kernel_small, iterations=1)
        red_mask = cv2.dilate(red_mask, kernel_small, iterations=1)
        
        highlighted_pixels = cv2.countNonZero(red_mask)
        quality_note = "(good - strong feather)" if highlighted_pixels >= 50 else "(weak - tune ranges?)"
        print(f"Highlighted red/orange pixels: {highlighted_pixels} {quality_note}")
        
        if highlighted_pixels < 15:
            print("⚠️ Very few red/orange pixels — bobber feather probably NOT detected.")
        elif highlighted_pixels < 50:
            print("🟡 Weak feather detection — consider widening HSV ranges slightly.")
        
        if highlighted_pixels > 0:
            masked_hsv = hsv_img[red_mask > 0]
            if len(masked_hsv) > 0:
                avg_h = np.mean(masked_hsv[:,0])
                avg_s = np.mean(masked_hsv[:,1])
                avg_v = np.mean(masked_hsv[:,2])
                print(f"Feather HSV avg (for tuning): H={avg_h:.1f}, S={avg_s:.1f}, V={avg_v:.1f}")
        
        if highlighted_pixels == 0:
            hues = hsv_img[:,:,0].flatten()
            print(f"DEBUG: Max hue in screenshot: {np.max(hues)}")
        
        # Debug: white feather on black background
        debug_vis = np.zeros_like(img_np)
        debug_vis[red_mask > 0] = [255, 255, 255]
        
        masked_fn = os.path.join(SAVE_DIR, "latest_masked.png")
        if cv2.imwrite(masked_fn, cv2.cvtColor(debug_vis, cv2.COLOR_RGB2BGR)):
            print(f"📸 MASK DEBUG (white = detected feather): {masked_fn}")
        
        img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        matches = []
        for template, fname in templates:
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            if template_gray.shape[0] > SCREENSHOT_REGION["height"] or template_gray.shape[1] > SCREENSHOT_REGION["width"]:
                continue
            result = cv2.matchTemplate(img_gray, template_gray, cv2.TM_SQDIFF_NORMED)
            min_val, _, min_loc, _ = cv2.minMaxLoc(result)
            if min_val < SQDIFF_ACCEPT:
                h, w = template_gray.shape
                match_mask = red_mask[min_loc[1]:min_loc[1]+h, min_loc[0]:min_loc[0]+w]
                red_in_match = cv2.countNonZero(match_mask)
                center_x = min_loc[0] + w // 2
                center_y = min_loc[1] + h // 2
                if red_in_match >= MIN_RED_PIXELS_FOR_MATCH and BOBBER_AREA_BOUNDS["min_x"] <= center_x <= BOBBER_AREA_BOUNDS["max_x"] and BOBBER_AREA_BOUNDS["min_y"] <= center_y <= BOBBER_AREA_BOUNDS["max_y"]:
                    matches.append((min_val, center_x, center_y, fname, red_in_match))
                    print(f"✅ Accepted match from {fname}: score {min_val:.3f}, red pixels {red_in_match}, pos ({center_x}, {center_y})")
                else:
                    print(f"❌ Discarded match from {fname}: only {red_in_match} red pixels (need >= {MIN_RED_PIXELS_FOR_MATCH})")
        
        cast_fn = os.path.join(SAVE_DIR, "latest_cast.png")
        if cv2.imwrite(cast_fn, cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)):
            print(f"📸 Raw cast saved: {cast_fn}")
        
        if not matches:
            print("❌ No matches found (after red pixel filter)")
            return False, None, None, img_np, None
        
        # Sort by min_val (lower = better), then by red pixels descending
        matches.sort(key=lambda x: (x[0], -x[4]))
        best_score, best_x, best_y, best_fname, best_red = matches[0]
        print(f"Best match: {best_score:.3f} from {best_fname} with {best_red} red pixels")
        
        agreeing = [m for m in matches if abs(m[1] - best_x) <= POSITION_AGREEMENT_PX and abs(m[2] - best_y) <= POSITION_AGREEMENT_PX]
        agree_count = len(agreeing)
        print(f"🔍 {agree_count} templates agree near ({best_x}, {best_y})")
        
        latest_success_path = None
        
        if agree_count >= MIN_AGREEING_TEMPLATES:
            print(f"🪝 Bobber LOCKED at ({best_x}, {best_y})")
            
            crop = img_np[max(0, best_y - BOBBER_CROP_SIZE//2):best_y + BOBBER_CROP_SIZE//2,
                          max(0, best_x - BOBBER_CROP_SIZE//2):best_x + BOBBER_CROP_SIZE//2]
            if crop.size > 0:
                ts = time.strftime("%Y%m%d_%H%M%S")
                path = os.path.join(TEMPLATE_DIR, f"bobber_success_{ts}.png")
                cv2.imwrite(path, cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
                print(f"💾 Auto-saved: {path}")
                latest_success_path = path
            
            if DEBUG:
                marked_img = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                for _, ax, ay, afname, _ in agreeing:
                    cv2.circle(marked_img, (ax, ay), 10, (0, 0, 255), 2)
                    short_name = os.path.splitext(afname)[0][:12]
                    cv2.putText(marked_img, short_name, (ax + 12, ay), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                cv2.circle(marked_img, (best_x, best_y), 15, (0, 255, 0), 3)
                cv2.rectangle(marked_img,
                              (BOBBER_AREA_BOUNDS["min_x"], BOBBER_AREA_BOUNDS["min_y"]),
                              (BOBBER_AREA_BOUNDS["max_x"], BOBBER_AREA_BOUNDS["max_y"]),
                              (255, 0, 0), 2)
                comparison_fn = os.path.join(SAVE_DIR, "latest_comparison.png")
                if cv2.imwrite(comparison_fn, marked_img):
                    print(f"📸 Comparison debug saved: {comparison_fn}")
            
            return True, best_x, best_y, img_np, latest_success_path
        else:
            print(f"⚠️ Not enough agreement ({agree_count}/{MIN_AGREEING_TEMPLATES})")
            return False, None, None, img_np, None
    except Exception as e:
        print(f"❌ find_bobber error: {e}")
        return False, None, None, None, None

def detect_splash(img, initial_x, initial_y):
    global last_intensity_print, initial_intensity
    img_np = np.array(img)
    crop_left = max(0, initial_x - BOBBER_CROP_SIZE // 2)
    crop_top = max(0, initial_y - BOBBER_CROP_SIZE // 2)
    crop = img_np[crop_top:min(img_np.shape[0], initial_y + BOBBER_CROP_SIZE // 2),
                  crop_left:min(img_np.shape[1], initial_x + BOBBER_CROP_SIZE // 2)]
    if crop.size == 0:
        return False
    crop_gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    current = np.mean(crop_gray)
    if initial_intensity is None:
        initial_intensity = current
        return False
    delta = abs(current - initial_intensity)
    if time.time() - last_intensity_print >= 2.0:
        print(f"🌊 Intensity Δ: {delta:.2f}")
        last_intensity_print = time.time()
    return delta > INTENSITY_CHANGE_THRESHOLD

def save_bobber_template(img, x, y):
    img_np = np.array(img)
    crop = img_np[max(0, y - BOBBER_CROP_SIZE//2):y + BOBBER_CROP_SIZE//2,
                  max(0, x - BOBBER_CROP_SIZE//2):x + BOBBER_CROP_SIZE//2]
    if crop.size > 0:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(TEMPLATE_DIR, f"bobber_manual_{ts}.png")
        cv2.imwrite(path, cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
        print(f"💾 Saved MANUAL template: {path}")

def toggle_pause():
    global paused
    paused = not paused
    print(f"{'▶ Resumed' if not paused else '⏸ Paused'}")

def emergency_keys_listener():
    def pause_on_key():
        global paused
        paused = True
        print("⏸ Paused by movement key")
    keyboard.add_hotkey('w', pause_on_key)
    keyboard.add_hotkey('a', pause_on_key)
    keyboard.add_hotkey('s', pause_on_key)
    keyboard.add_hotkey('d', pause_on_key)
    keyboard.add_hotkey('space', pause_on_key)
    keyboard.add_hotkey('ctrl+shift', toggle_pause)
    print("🛑 WASD/Space = quick pause | Ctrl+Shift = toggle pause/resume")

# ====================================================
# MAIN FISHING CYCLE
# ====================================================
def fishing_cycle():
    global running, paused, initial_intensity, break_start_time, last_intensity_print, last_time_print
    
    start_time = time.time()
    break_start_time = time.time()
    last_intensity_print = time.time()
    last_time_print = time.time()
    
    while running:
        if paused:
            time.sleep(0.5)
            continue
        if time.time() - start_time > SESSION_LIMIT:
            print("⏰ Session limit reached.")
            running = False
            return
        if time.time() - last_time_print >= 15:
            rem = max(0, SESSION_LIMIT - (time.time() - start_time))
            h, m, s = int(rem // 3600), int((rem % 3600) // 60), int(rem % 60)
            print(f"⏳ Remaining: {h:02d}:{m:02d}:{s:02d}")
            last_time_print = time.time()
        
        print("🎣 Casting...")
        print("  → Forcing WoW window focus...")
        activate_wow_window()
        time.sleep(0.3)
        pydirectinput.keyDown('9')
        time.sleep(random.uniform(0.07, 0.12))
        pydirectinput.keyUp('9')
        time.sleep(random.uniform(1.8, 2.6))
        print("Capturing...")
        
        with mss.mss() as sct:
            sct_img = sct.grab(SCREENSHOT_REGION)
            img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        
        found, x, y, img_np, latest_success_path = find_bobber(img)
        
        if found:
            print(f"🪝 Monitoring bobber at ({x}, {y})")
            initial_intensity = None
            local_start = time.time()
            splash_count = 0
            while time.time() - local_start < TIMEOUT and not paused:
                if keyboard.is_pressed('n'):
                    print("🔄 Manual recast (N pressed)")
                    if latest_success_path and os.path.exists(latest_success_path):
                        try:
                            os.remove(latest_success_path)
                            print(f"🗑️ Deleted unwanted success template: {latest_success_path}")
                        except Exception as e:
                            print(f"⚠️ Failed to delete {latest_success_path}: {e}")
                    break
                if keyboard.is_pressed('y'):
                    save_bobber_template(img, x, y)
                with mss.mss() as sct:
                    sct_img = sct.grab(SCREENSHOT_REGION)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                splash_detected = detect_splash(img, x, y)
                if splash_detected:
                    splash_count += 1
                    print(f"🌊 Splash detected ({splash_count}/{CONFIRMATION_FRAMES})")
                    if splash_count >= CONFIRMATION_FRAMES:
                        abs_x = SCREENSHOT_REGION["left"] + x
                        abs_y = SCREENSHOT_REGION["top"] + y
                        print("🎯 BITE! Right-clicking")
                        pyautogui.moveTo(abs_x, abs_y, duration=MOUSE_MOVE_DURATION)
                        pyautogui.rightClick()
                        ex, ey = get_random_edge_point()
                        pyautogui.moveTo(SCREENSHOT_REGION["left"] + ex, SCREENSHOT_REGION["top"] + ey, duration=MOUSE_MOVE_DURATION)
                        break
                else:
                    splash_count = 0
                time.sleep(INTERVAL)
            if splash_count < CONFIRMATION_FRAMES:
                print("⏳ Timeout → recast")
        
        if time.time() - break_start_time >= BREAK_START_DELAY and random.random() < RANDOM_BREAK_CHANCE:
            dur = random.uniform(*RANDOM_BREAK_LENGTH)
            print(f"☕ Taking human break: {dur:.1f}s")
            time.sleep(dur)
            break_start_time = time.time()
        
        print("─── Cycle done ───\n")

def get_random_edge_point():
    edge = random.choice(['top', 'bottom', 'left', 'right'])
    b = BOBBER_AREA_BOUNDS
    if edge == 'top':    return random.uniform(b["min_x"], b["max_x"]), b["min_y"]
    if edge == 'bottom': return random.uniform(b["min_x"], b["max_x"]), b["max_y"]
    if edge == 'left':   return b["min_x"], random.uniform(b["min_y"], b["max_y"])
    return b["max_x"], random.uniform(b["min_y"], b["max_y"])

def start_fishing_thread():
    global running, paused
    emergency_keys_listener()
    while True:
        keyboard.wait('ctrl+shift')
        running = True
        paused = False
        print("▶ AutoFish started / resumed")
        fishing_cycle()

def main():
    global running, paused
    ensure_save_dir()
    print("🚀 AutoFish ready | Ctrl+Shift = start/resume | WASD/Space = quick pause")
    print("   Press 'y' during monitoring to save new template manually")
    thread = threading.Thread(target=start_fishing_thread, daemon=True)
    thread.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        running = False
        print("\n👋 Shutting down...")

if __name__ == "__main__":
    main()