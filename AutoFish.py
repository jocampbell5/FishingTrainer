# Fishing bot for Mists of Pandaria Classic

import time
import threading
import numpy as np
import pyautogui
import cv2
from PIL import Image
import mss
import keyboard
import os

# ====================================================
# CONFIGURATION
# ====================================================

DEBUG = False  # Debugging should be false by default

# Screen capture region
SCREENSHOT_REGION = {"left": 1650, "top": 300, "width": 700, "height": 700}

# Template matching settings for initial detection
TEMPLATE_DIR = r"d:\fishingtrainer\bobber_templates"  # Directory for multiple templates
TEMPLATE_THRESHOLD = 0.4  # Lowered slightly based on your scores
1
# Bobber area bounds for filtering matches
BOBBER_AREA_BOUNDS = {"min_x": 20, "max_x": 650, "min_y": 20, "max_y": 450}  # Central region

# Splash detection settings (monitor pixel changes in bobber region)
BOBBER_CROP_SIZE = 70  # Size of the cropped region around initial bobber (pixels)
INTENSITY_CHANGE_THRESHOLD = 3.5  # Mean intensity change to detect splash
CONFIRMATION_FRAMES = 3  # Frames to confirm splash

# Timing settings
INTERVAL = 0.1          # Slower interval to reduce jitter (~10 FPS)
TIMEOUT = 20            # Seconds before forcing a cast
POST_ACTION_DELAY = 1   # Delay before next cycle
START_DELAY = 1         # 1-second delay before starting
RECAST_ATTEMPTS = 3     # Attempts if bobber not found
TEMPLATE_SAVE_DELAY = 0.1  # Short delay for key press check during monitoring

# Directory for saving screenshots
SAVE_DIR = r"D:\fishingtrainer"

# Global control flag for stopping
running = True

# Global for splash detection
initial_intensity = None

# ====================================================
# HELPER FUNCTIONS
# ====================================================

def ensure_save_dir():
    """Create the save directory if it doesn't exist."""
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)
        print(f"📁 Created directory {SAVE_DIR}")

def load_templates():
    """Load all template images from the directory."""
    templates = []
    if not os.path.exists(TEMPLATE_DIR):
        print(f"❌ Template directory '{TEMPLATE_DIR}' not found. Creating it now.")
        os.makedirs(TEMPLATE_DIR)
        return None
    for filename in os.listdir(TEMPLATE_DIR):
        if filename.endswith(".png"):
            template_path = os.path.join(TEMPLATE_DIR, filename)
            template = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template is not None:
                templates.append(template)
                print(f"📂 Loaded template: {filename}")
            else:
                print(f"❌ Failed to load template from '{template_path}'.")
    if not templates:
        print("❌ No valid templates found in the directory.")
    return templates if templates else None

def find_bobber(img):
    """Find the initial bobber position using multiple template matching."""
    try:
        img_np = np.array(img)
        templates = load_templates()
        if templates is None:
            print("❌ No valid templates found.")
            return False, None, None

        best_match = 0.0
        best_center_x, best_center_y = None, None
        best_template = None

        # Convert input image to grayscale
        img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

        # Match against each template
        for template in templates:
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            if template_gray.shape[0] > SCREENSHOT_REGION["height"] or template_gray.shape[1] > SCREENSHOT_REGION["width"]:
                print(f"❌ Template size ({template_gray.shape[1]}x{template_gray.shape[0]}) exceeds region size ({SCREENSHOT_REGION['width']}x{SCREENSHOT_REGION['height']}). Skipping.")
                continue

            result = cv2.matchTemplate(img_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            if max_val > best_match:
                best_match = max_val
                h, w = template_gray.shape
                best_center_x = max_loc[0] + w // 2
                best_center_y = max_loc[1] + h // 2
                best_template = template

        print(f"📊 Best match score: {best_match:.2f} (threshold: {TEMPLATE_THRESHOLD})")

        if best_match >= TEMPLATE_THRESHOLD:
            # Check if within bounds
            if (BOBBER_AREA_BOUNDS["min_x"] <= best_center_x <= BOBBER_AREA_BOUNDS["max_x"] and
                BOBBER_AREA_BOUNDS["min_y"] <= best_center_y <= BOBBER_AREA_BOUNDS["max_y"]):
                print(f"🪝 Bobber detected at ({best_center_x}, {best_center_y}) with match score {best_match:.2f}.")
                if DEBUG:
                    # Save marked screenshot with bobber position
                    marked_img = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                    cv2.circle(marked_img, (best_center_x, best_center_y), 10, (0, 255, 0), 2)  # Green circle at bobber
                    marked_filename = os.path.join(SAVE_DIR, "marked_screenshot.png")
                    cv2.imwrite(marked_filename, marked_img)
                    print(f"📸 Saved marked screenshot to '{marked_filename}'.")
                return True, best_center_x, best_center_y
            else:
                print(f"❌ Bobber at ({best_center_x}, {best_center_y}) outside bounds {BOBBER_AREA_BOUNDS}.")
        else:
            print(f"❌ No match found. Best correlation score: {best_match:.2f} (below {TEMPLATE_THRESHOLD}).")

        print("❌ No valid bobber detected.")
        return False, None, None
    
    except Exception as e:
        print(f"❌ Error in find_bobber: {e}")
        return False, None, None

def detect_splash(img, initial_x, initial_y):
    """Detect splash by checking pixel intensity change in cropped bobber region."""
    img_np = np.array(img)
    # Crop a small region around the initial bobber
    crop_left = max(0, initial_x - BOBBER_CROP_SIZE // 2)
    crop_top = max(0, initial_y - BOBBER_CROP_SIZE // 2)
    crop_right = min(img_np.shape[1], initial_x + BOBBER_CROP_SIZE // 2)
    crop_bottom = min(img_np.shape[0], initial_y + BOBBER_CROP_SIZE // 2)
    
    crop = img_np[crop_top:crop_bottom, crop_left:crop_right]
    if crop.size == 0:
        return False

    # Calculate mean intensity (grayscale)
    crop_gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    current_intensity = np.mean(crop_gray)

    # For the first frame, set initial intensity
    global initial_intensity
    if initial_intensity is None:
        initial_intensity = current_intensity
        return False

    # Check change
    delta_intensity = abs(current_intensity - initial_intensity)
    print(f"📊 Intensity change: {delta_intensity:.2f} (threshold: {INTENSITY_CHANGE_THRESHOLD})")

    if delta_intensity > INTENSITY_CHANGE_THRESHOLD:
        return True
    return False

def show_debug_image(img):
    """Display an image for debugging."""
    try:
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        cv2.imshow("Screenshot", img_cv)
        cv2.waitKey(1000)
        cv2.destroyWindow("Screenshot")
    except Exception as e:
        print(f"❌ Error displaying debug image: {e}")

def validate_region(sct, region):
    """Validate if the screenshot region is within monitor bounds."""
    monitors = sct.monitors
    print(f"ℹ️ Available monitors: {monitors}")
    for monitor in monitors[1:]:  # Skip monitor 0 (all monitors)
        mon_left, mon_top, mon_width, mon_height = monitor["left"], monitor["top"], monitor["width"], monitor["height"]
        if (region["left"] >= mon_left and 
            region["top"] >= mon_top and 
            region["left"] + region["width"] <= mon_left + mon_width and 
            region["top"] + region["height"] <= mon_top + mon_height):
            return True
    print(f"❌ SCREENSHOT_REGION {region} is outside monitor bounds!")
    return False

def fallback_capture():
    """Attempt to capture the entire primary monitor as a fallback."""
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            sct_img = sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
            if DEBUG:
                ensure_save_dir()
                fallback_filename = os.path.join(SAVE_DIR, "fallback_screenshot.png")
                cv2.imwrite(fallback_filename, cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR))
                print(f"📸 Saved fallback screenshot to '{fallback_filename}'.")
            print(f"ℹ️ Fallback capture: Entire monitor {monitor}")
            return img
    except Exception as e:
        print(f"❌ Fallback capture failed: {e}")
        return None

# ====================================================
# MAIN SCRIPT FUNCTIONS
# ====================================================

def fishing_cycle():
    """Run continuous fishing cycles until stopped."""
    global running
    while running:
        # Cast the line
        time.sleep(1)
        pyautogui.press('1')  # Cast fishing line
        time.sleep(2)  # Wait for bobber to appear

        # Capture the region
        with mss.mss() as sct:
            sct_img = sct.grab(SCREENSHOT_REGION)
            img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)

        # Save screenshot only if debugging
        if DEBUG:
            ensure_save_dir()
            screenshot_filename = os.path.join(SAVE_DIR, "cast_screenshot.png")
            cv2.imwrite(screenshot_filename, cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR))
            print(f"📸 Saved cast screenshot to '{screenshot_filename}'.")

        found, initial_x, initial_y = find_bobber(img)
        
        if found:
            print(f"🪝 Bobber found at initial position ({initial_x}, {initial_y}). Monitoring for movement.")
            # Reset initial intensity for splash detection
            global initial_intensity
            initial_intensity = None
            detect_splash(img, initial_x, initial_y)  # Set initial intensity immediately

            start_time = time.time()
            detection_made = False
            splash_counter = 0  # Track consecutive frames with splash

            while time.time() - start_time < TIMEOUT:
                if keyboard.is_pressed('w') or keyboard.is_pressed('a') or keyboard.is_pressed('s') or keyboard.is_pressed('d') or keyboard.is_pressed('space'):
                    print("Stop key pressed. Stopping fishing.")
                    return  # Exit the cycle

                # Check for 'n' to recast
                if keyboard.is_pressed('n'):
                    print("N pressed. Recasting line.")
                    break  # Break monitoring to recast

                # Check for 'y' to save template at any time during monitoring
                if keyboard.is_pressed('y'):
                    crop_img = img[initial_y - BOBBER_CROP_SIZE // 2:initial_y + BOBBER_CROP_SIZE // 2,
                                 initial_x - BOBBER_CROP_SIZE // 2:initial_x + BOBBER_CROP_SIZE // 2]
                    if crop_img.size > 0:
                        new_template_path = os.path.join(TEMPLATE_DIR, f"bobber_template_{int(time.time())}.png")
                        cv2.imwrite(new_template_path, crop_img)
                        print(f"📸 Saved new template to '{new_template_path}'.")
                    time.sleep(TEMPLATE_SAVE_DELAY)  # Brief delay to avoid multiple saves

                # Capture the region
                with mss.mss() as sct:
                    sct_img = sct.grab(SCREENSHOT_REGION)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)

                splash_detected = detect_splash(img, initial_x, initial_y)
                if splash_detected:
                    splash_counter += 1
                    print(f"⚠️ Splash detected ({splash_counter}/{CONFIRMATION_FRAMES} frames).")
                    if splash_counter >= CONFIRMATION_FRAMES:
                        abs_x = SCREENSHOT_REGION["left"] + initial_x
                        abs_y = SCREENSHOT_REGION["top"] + initial_y
                        print(f"🎯 Bite confirmed at ({abs_x}, {abs_y}) after {splash_counter} frames. Right Clicking!")
                        pyautogui.moveTo(abs_x, abs_y, duration=0.1)
                        pyautogui.rightClick()
                        detection_made = True
                        # Move mouse to bottom right corner of the screenshot region
                        bottom_right_x = SCREENSHOT_REGION["left"] + SCREENSHOT_REGION["width"] - 10
                        bottom_right_y = SCREENSHOT_REGION["top"] + SCREENSHOT_REGION["height"] - 10
                        pyautogui.moveTo(bottom_right_x, bottom_right_y, duration=0.1)
                        break
                else:
                    splash_counter = 0  # Reset if no splash

                time.sleep(INTERVAL)

            if not detection_made:
                print(f"⏳ Timeout reached ({TIMEOUT}s), recasting.")
            
            time.sleep(POST_ACTION_DELAY)

def start_fishing_thread():
    """The fishing thread that waits for hotkey to start fishing."""
    global running
    while running:
        keyboard.wait('ctrl+shift')
        print("Ctrl+Shift pressed. Starting fishing process.")
        fishing_cycle()

def main():
    """Start the fishing thread."""
    global running

    fishing_thread = threading.Thread(target=start_fishing_thread, daemon=True)
    fishing_thread.start()

    try:
        while True:
            time.sleep(1)  # Keep the main thread alive
    except KeyboardInterrupt:
        running = False
        print("\n👋 Exiting Fishing Bot...")

if __name__ == "__main__":
    main()