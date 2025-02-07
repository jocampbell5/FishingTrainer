
# test

# FIXES RIGHT NOW:
# We want the app to say that the app has started
# We want the app to start by pressing 2 - to start the macro for adding the lure
# We want wait until the lure is attached and the fishing pole is equiped (say X seconds or so)
# We want then start the main script of looking for the splash
# 
# Lets add fishing bot initialized now,  waiting for user to press spacebar (start)

# QoL Features:
# Really what we want, is the ability to set the border region each time we start the app.
# We also want to be able to select between Retail, Cata, and Classic splash color code
# We want the information to not be in the terminal but on the screen when an event fires (found color, didn't find color, started app, etc)
# We want to be able to play and stop the 'fishing line events' while it's running (there's a difference between stopped and exited)
# Be able to gracefully exit the application (not pressing ctrl+c to cancel)
# We want to gracefully be able to add the fishing lure anytime we want
# SPECIFICALLY FOR MIKEL - Is there a better way to find the color code for the splash animation?? (He doesn't like MSS, even though it's fucking working.)
#
# 
import time
import threading
import numpy as np
import pyautogui
import cv2
from PIL import Image
import mss
import keyboard  # Using keyboard to listen for spacebar globally

# ====================================================
# CONFIGURATION
# ====================================================

DEBUG = False  # Set to True to display the screenshot.

# Screen capture region
SCREENSHOT_REGION = {"left": 1600, "top": 400, "width": 700, "height": 700}

# Splash color detection
TARGET_COLOR = (255, 255, 245)  # Adjust per game version
COLOR_TOLERANCE = 5

# Timing settings
INTERVAL = 1 / 30       # ~30 FPS
TIMEOUT = 30            # Seconds before forcing a cast
POST_ACTION_DELAY = 2   # Delay before next cycle
LURE_WAIT_TIME = 5      # Time to wait after applying lure
START_DELAY = 5         # 5-second delay before applying lure

# Global control flag for stopping
running = True

# ====================================================
# FIXED KEY PRESS DETECTION FUNCTION
# ====================================================

def wait_for_keypress():
    """Wait for the user to press the spacebar globally using `keyboard`."""
    print("🎣 Fishing Bot Initialized. Press SPACE to start.")

    # Wait for spacebar press globally
    keyboard.wait('space')

    print("✅ Spacebar pressed!")
    
    # Countdown before starting the lure
    for i in range(START_DELAY, 0, -1):
        print(f"⏳ Starting in {i} seconds...")
        time.sleep(1)

# ====================================================
# HELPER FUNCTIONS
# ====================================================

def find_target_color(img, target_color, tolerance):
    """Search for the target color in a NumPy image array."""
    img_np = np.array(img)
    height, width = img_np.shape[:2]

    for y in range(height):
        for x in range(width):
            pixel = tuple(img_np[y, x][:3])  # Extract RGB values
            if all(abs(int(pixel[i]) - target_color[i]) <= tolerance for i in range(3)):
                return True, x, y

    return False, None, None

def show_debug_image(img):
    """Display an image for debugging."""
    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    cv2.imshow("Screenshot", img_cv)
    cv2.waitKey(1000)
    cv2.destroyWindow("Screenshot")

# ====================================================
# MAIN SCRIPT FUNCTIONS
# ====================================================

def start_fishing():
    """Main function to detect splash and auto-click."""
    global running
    print("🎣 Fishing bot started!")

    with mss.mss() as sct:
        while running:
            start_time = time.time()
            detection_made = False

            while time.time() - start_time < TIMEOUT:
                if not running:
                    return

                # Capture the region
                sct_img = sct.grab(SCREENSHOT_REGION)
                img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)

                if DEBUG:
                    show_debug_image(img)

                found, rel_x, rel_y = find_target_color(img, TARGET_COLOR, COLOR_TOLERANCE)
                if found:
                    abs_x = SCREENSHOT_REGION["left"] + rel_x
                    abs_y = SCREENSHOT_REGION["top"] + rel_y

                    print(f"🎯 Splash detected at ({abs_x}, {abs_y}). Clicking!")
                    pyautogui.moveTo(abs_x, abs_y, duration=0.5)
                    pyautogui.rightClick()

                    time.sleep(2)
                    pyautogui.press('1')  # Cast fishing line
                    detection_made = True
                    break

                time.sleep(INTERVAL)

            if not detection_made:
                pyautogui.press('1')  # Cast again if no splash detected
                print(f"⏳ Timeout reached ({TIMEOUT}s), casting again.")

            time.sleep(POST_ACTION_DELAY)

def main():
    """Wait for user input via a global spacebar press, then start lure application and the fishing loop."""
    global running

    # Wait for a global spacebar press
    wait_for_keypress()

    print("🎣 Pressing '2' to start lure macro.")
    pyautogui.press('2')  # Start lure macro
    print("🕒 Waiting for lure to apply...")
    time.sleep(LURE_WAIT_TIME)  # Ensure lure is applied

    print("✅ Lure applied! Starting fishing script...")
    fishing_thread = threading.Thread(target=start_fishing, daemon=True)
    fishing_thread.start()

    try:
        while True:
            time.sleep(1)  # Keep the main thread alive
    except KeyboardInterrupt:
        running = False
        print("\n👋 Exiting Fishing Bot...")

if __name__ == "__main__":
    main()
