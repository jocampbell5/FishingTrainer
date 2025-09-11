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
import random

# ====================================================
# CONFIGURATION
# ====================================================

DEBUG = True  # Debugging should be true to see screenshots

# Screen capture region
SCREENSHOT_REGION = {"left": 1650, "top": 300, "width": 670, "height": 470}

# Template matching settings for initial detection
TEMPLATE_DIR = r"d:\fishingtrainer\bobber_templates"  # Directory for multiple templates
TEMPLATE_THRESHOLD = 0.65  # Lowered slightly based on your scores

# Bobber area bounds for filtering matches
BOBBER_AREA_BOUNDS = {"min_x": 20, "max_x": 650, "min_y": 20, "max_y": 450}  # Central region, adjust if needed

# Splash detection settings (monitor pixel changes in bobber region)
BOBBER_CROP_SIZE = 70  # Size of the cropped region around initial bobber (pixels)
INTENSITY_CHANGE_THRESHOLD = 4  # Mean intensity change to detect splash
CONFIRMATION_FRAMES = 3  # Frames to confirm splash

# Timing settings with random ranges
INTERVAL = 0.1          # Slower interval to reduce jitter (~10 FPS)
TIMEOUT = 20            # Seconds before forcing a cast
POST_ACTION_DELAY = (0.1, 3.0)  # Range for delay before next cycle
START_DELAY = (0.1, 1.5)        # Range for initial delay
MOVE_DELAY_TO_BOBBER = (0.1, 1.2)  # Range for delay moving to bobber
MOVE_DELAY_TO_EDGE = (0.1, 3.0)    # Range for delay moving to any point on bounding box edge
RECAST_ATTEMPTS = 3     # Attempts if bobber not found

# New configurable variables
SESSION_LIMIT = 7200    # Session limit in seconds (default 2 hours)
RANDOM_BREAK_CHANCE = 0.10  # Chance of random break (0 to 0.5, default 10%)
BREAK_START_DELAY = 300  # Time in seconds before random breaks can start (default 5 minutes)
RANDOM_BREAK_LENGTH = (15, 120)  # Range for random break duration in seconds (default 30-60 seconds)

# Directory for saving screenshots
SAVE_DIR = r"D:\fishingtrainer"

# Global control flag for stopping
running = True

# Global for splash detection, break timer, and timing control
initial_intensity = None
break_start_time = None  # Tracks when the break delay starts
last_intensity_print = 0  # Tracks last time intensity was printed
last_time_print = 0      # Tracks last time remaining time was printed

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
    if templates:
        print(f"Loaded {len(templates)} templates")
    else:
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
                    # Save marked screenshot with bobber position and bounds
                    marked_img = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                    cv2.circle(marked_img, (best_center_x, best_center_y), 10, (0, 255, 0), 2)  # Green circle at bobber
                    # Draw red rectangle for bobber bounds
                    cv2.rectangle(marked_img, 
                                 (BOBBER_AREA_BOUNDS["min_x"], BOBBER_AREA_BOUNDS["min_y"]),
                                 (BOBBER_AREA_BOUNDS["max_x"], BOBBER_AREA_BOUNDS["max_y"]),
                                 (0, 0, 255),  # Red color in BGR
                                 2)  # Thickness
                    marked_filename = os.path.join(SAVE_DIR, "marked_screenshot.png")
                    cv2.imwrite(marked_filename, marked_img)
                    print(f"📸 Saved marked screenshot with bounds to '{marked_filename}'.")
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
    global last_intensity_print
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

    # Check change every ~2 seconds
    if time.time() - last_intensity_print >= 2.0:
        delta_intensity = abs(current_intensity - initial_intensity)
        print(f"📊 Intensity change: {delta_intensity:.2f} (threshold: {INTENSITY_CHANGE_THRESHOLD})")
        last_intensity_print = time.time()

    if abs(current_intensity - initial_intensity) > INTENSITY_CHANGE_THRESHOLD:
        return True
    return False

def save_bobber_template(img, initial_x, initial_y):
    """Save the cropped bobber as a new template."""
    img_np = np.array(img)  # Convert PIL Image to NumPy array
    crop_img = img_np[initial_y - BOBBER_CROP_SIZE // 2:initial_y + BOBBER_CROP_SIZE // 2,
                      initial_x - BOBBER_CROP_SIZE // 2:initial_x + BOBBER_CROP_SIZE // 2]
    if crop_img.size > 0:
        new_template_path = os.path.join(TEMPLATE_DIR, f"bobber_template_{int(time.time())}.png")
        cv2.imwrite(new_template_path, crop_img)
        print(f"📸 Saved new template to '{new_template_path}'.")

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
    global running, break_start_time, last_intensity_print, last_time_print
    start_time = time.time()  # Record the start time for session limit once at the beginning
    break_start_time = time.time()  # Initialize break start timer
    last_intensity_print = time.time()  # Initialize intensity print timer
    last_time_print = time.time()  # Initialize remaining time print timer

    while running:
        # Immediate pause on WASD or space
        if (keyboard.is_pressed('w') or keyboard.is_pressed('a') or keyboard.is_pressed('s') or 
            keyboard.is_pressed('d') or keyboard.is_pressed('space')):
            print("Manual input detected. Pausing bot until Ctrl+Shift is pressed again.")
            running = False  # Exit the current cycle, but bot remains ready to resume
            return

        # Session limit check
        if time.time() - start_time > SESSION_LIMIT:
            print(f"Session limit reached ({SESSION_LIMIT / 3600:.1f} hours). Exiting bot.")
            running = False
            return

        # Print remaining time every 15 seconds
        if time.time() - last_time_print >= 15.0:
            remaining_seconds = max(0, SESSION_LIMIT - (time.time() - start_time))
            hours = int(remaining_seconds // 3600)
            minutes = int((remaining_seconds % 3600) // 60)
            seconds = int(remaining_seconds % 60)
            print(f"Remaining time: {hours:02d}:{minutes:02d}:{seconds:02d}")
            last_time_print = time.time()

        # Cast the line with random delay
        cast_delay = random.uniform(START_DELAY[0], START_DELAY[1])
        print(f"Cast delay: {cast_delay:.2f} seconds")
        time.sleep(cast_delay)
        pyautogui.press('9')  # Cast fishing line
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

            local_start_time = time.time()  # Local start time for this monitoring cycle
            detection_made = False
            splash_counter = 0  # Track consecutive frames with splash

            while time.time() - local_start_time < TIMEOUT:
                # Check for 'n' to recast
                if keyboard.is_pressed('n'):
                    print("N pressed. Recasting line.")
                    break  # Break monitoring to recast

                # Check for 'y' to save template anytime during monitoring
                if keyboard.is_pressed('y'):
                    save_bobber_template(img, initial_x, initial_y)

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
                        # Move to bobber with random delay
                        move_delay_to_bobber = random.uniform(MOVE_DELAY_TO_BOBBER[0], MOVE_DELAY_TO_BOBBER[1])
                        print(f"Move delay to bobber: {move_delay_to_bobber:.2f} seconds")
                        pyautogui.moveTo(abs_x, abs_y, duration=move_delay_to_bobber)
                        pyautogui.rightClick()  # Right click at current mouse position
                        detection_made = True
                        # Move to a random point on any edge of the bounding box
                        edge_x, edge_y = get_random_edge_point()
                        abs_edge_x = SCREENSHOT_REGION["left"] + edge_x
                        abs_edge_y = SCREENSHOT_REGION["top"] + edge_y
                        move_delay_to_edge = random.uniform(MOVE_DELAY_TO_EDGE[0], MOVE_DELAY_TO_EDGE[1])
                        print(f"Move delay to edge: {move_delay_to_edge:.2f} seconds")
                        pyautogui.moveTo(abs_edge_x, abs_edge_y, duration=move_delay_to_edge)
                        break
                else:
                    splash_counter = 0  # Reset if no splash

                time.sleep(INTERVAL)

            if not detection_made:
                print(f"⏳ Timeout reached ({TIMEOUT}s), recasting.")

        # Random break between sessions if time elapsed and chance met
        if time.time() - break_start_time >= BREAK_START_DELAY and random.random() < RANDOM_BREAK_CHANCE:
            break_duration = random.uniform(RANDOM_BREAK_LENGTH[0], RANDOM_BREAK_LENGTH[1])
            print(f"On break for {break_duration:.2f} seconds")
            time.sleep(break_duration)
            break_start_time = time.time()  # Reset break timer after break
        
        # Random delay after action or timeout
        post_delay = random.uniform(POST_ACTION_DELAY[0], POST_ACTION_DELAY[1])
        print(f"Post-action delay: {post_delay:.2f} seconds")
        time.sleep(post_delay)

def get_random_edge_point():
    """Return a random point on any edge of the BOBBER_AREA_BOUNDS."""
    edge_type = random.choice(['top', 'bottom', 'left', 'right'])
    if edge_type == 'top':
        x = random.uniform(BOBBER_AREA_BOUNDS["min_x"], BOBBER_AREA_BOUNDS["max_x"])
        y = BOBBER_AREA_BOUNDS["min_y"]
    elif edge_type == 'bottom':
        x = random.uniform(BOBBER_AREA_BOUNDS["min_x"], BOBBER_AREA_BOUNDS["max_x"])
        y = BOBBER_AREA_BOUNDS["max_y"]
    elif edge_type == 'left':
        x = BOBBER_AREA_BOUNDS["min_x"]
        y = random.uniform(BOBBER_AREA_BOUNDS["min_y"], BOBBER_AREA_BOUNDS["max_y"])
    else:  # right
        x = BOBBER_AREA_BOUNDS["max_x"]
        y = random.uniform(BOBBER_AREA_BOUNDS["min_y"], BOBBER_AREA_BOUNDS["max_y"])
    return x, y

def start_fishing_thread():
    """The fishing thread that waits for hotkey to start fishing."""
    global running, break_start_time, last_intensity_print, last_time_print
    while True:  # Infinite loop to resume on Ctrl+Shift
        keyboard.wait('ctrl+shift')
        print("Ctrl+Shift pressed. Starting fishing process.")
        running = True  # Reset running to true for the next cycle
        fishing_cycle()

def main():
    """Start the fishing thread."""
    global running, break_start_time, last_intensity_print, last_time_print
    break_start_time = time.time()  # Reset break timer on application start
    last_intensity_print = time.time()  # Initialize intensity print timer
    last_time_print = time.time()  # Initialize remaining time print timer
    running = True

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