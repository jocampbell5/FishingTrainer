
# test

# FIXES RIGHT NOW:
# We want the app to say that the app has started
# We want the app to start by pressing 2 - to start the macro for adding the lure
# We want wait until the lure is attached and the fishing pole is equiped (say X seconds or so)
# We want then start the main script of looking for the splash
# 
# Lets add fishing bot initialized now,  waiting for user to press spacebar (start)

# QoL Features:

# We will need to reapply lure after 10mins.
# Really what we want, is the ability to set the border region each time we start the app.
# We also want to be able to select between Retail, Cata, and Classic splash color code
# We want the information to not be in the terminal but on the screen when an event fires (found color, didn't find color, started app, etc)
# We want to be ab
# le to play and stop the 'fishing line events' while it's running (there's a difference between stopped and exited)
# Be able to gracefully exit the application (not pressing ctrl+c to cancel)
# We want to gracefully be able to add the fishing lure anytime we want
# SPECIFICALLY FOR MIKEL - Is there a better way to find the color code for the splash animation?? (He doesn't like MSS, even though it's fucking working.)
#



# # ====================================================
# # CONFIGURATION
# # ====================================================

# DEBUG = False  # Set to True to display the screenshot (in debug mode)

# # Screen capture region (adjust as needed)
# SCREENSHOT_REGION = {"left": 700, "top": 75, "width": 450, "height": 500}

# # Splash color detection
# TARGET_COLOR = (255, 255, 245)  # Adjust per game version
# COLOR_TOLERANCE = 10

# # Timing settings
# INTERVAL = 1 / 30       # ~30 FPS
# TIMEOUT = 30            # Seconds before forcing a cast
# POST_ACTION_DELAY = 2   # Delay before next cycle
# LURE_WAIT_TIME = 5      # Time to wait after applying lure
# START_DELAY = 5         # 5-second delay before applying lure

# # Global control flag for stopping
# running = True

# # ====================================================
# # SCREENSHOT PREVIEW WINDOW (10-second duration)
# # ====================================================

# def preview_screenshot():
#     """
#     Displays a live preview of the screenshot region with a centered label "SCREEN SHOT PREVIEW".
#     The preview will auto-close after 10 seconds or if 'q' is pressed.
#     """
#     print("📷 Opening Screenshot Preview Window (10 seconds)...")
#     start_time = time.time()
    
#     with mss.mss() as sct:
#         while True:
#             # Capture the region
#             sct_img = sct.grab(SCREENSHOT_REGION)
#             frame = np.array(sct_img)
#             # Convert from RGB to BGR for OpenCV
#             frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            
#             # Define text parameters
#             text = "SCREEN SHOT PREVIEW"
#             font = cv2.FONT_HERSHEY_SIMPLEX
#             font_scale = 1.0
#             thickness = 2
            
#             # Get text size
#             text_size, _ = cv2.getTextSize(text, font, font_scale, thickness)
#             text_width, text_height = text_size
            
#             # Center the text in the frame
#             h, w, _ = frame.shape
#             text_x = (w - text_width) // 2
#             text_y = (h + text_height) // 2
            
#             # Overlay text on the frame
#             cv2.putText(frame, text, (text_x, text_y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
            
#             # Show the frame
#             cv2.imshow("Screen Shot Preview", frame)
            
#             # Close preview if 'q' is pressed
#             if cv2.waitKey(1) & 0xFF == ord('q'):
#                 break
            
#             # Auto-close after 10 seconds
#             if time.time() - start_time > 10:
#                 break

#     cv2.destroyAllWindows()
#     print("✅ Screenshot Preview Closed.")

























# New Code Here


import time
import threading
import numpy as np
import pyautogui
import cv2
from PIL import Image
import mss
import keyboard  # Using keyboard to listen for spacebar globally
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')


# Insert the project root so that 'Config' is found as a package
project_root = r'C:\Users\mikel\Documents\4klabs\FishingTrainer'
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from Config.Settings import DEBUG, SCREENSHOT_REGION, TARGET_COLOR, COLOR_TOLERANCE, INTERVAL, TIMEOUT, POST_ACTION_DELAY, LURE_WAIT_TIME, START_DELAY
from Config.PreviewSS import preview_screenshot

# Global control flag for stopping
running = True

# Define a file to act as a pause flag
PAUSE_FILE = os.path.join(project_root, 'pause_flag.txt')

def wait_for_keypress():
    """
    Wait for the user to press the spacebar globally using `keyboard`.
    """
    print("🎣 Fishing Bot Initialized. Press SPACE to start.")
    keyboard.wait('space')
    print("✅ Spacebar pressed!")
    
    # Countdown before starting the lure
    for i in range(START_DELAY, 0, -1):
        print(f"⏳ Starting in {i} seconds...")
        time.sleep(1)

def find_target_color(img, target_color, tolerance):
    """
    Search for the target color in a NumPy image array.
    """
    img_np = np.array(img)
    height, width = img_np.shape[:2]

    for y in range(height):
        for x in range(width):
            pixel = img_np[y, x]
            if all(abs(int(pixel[i]) - target_color[i]) <= tolerance for i in range(3)):
                return True, x, y

    return False, None, None

def show_debug_image(img):
    """
    Display an image for debugging.
    """
    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    cv2.imshow("Screenshot", img_cv)
    cv2.waitKey(1000)
    cv2.destroyWindow("Screenshot")

def start_fishing():
    """
    Main function to detect splash and auto-click.
    """
    global running
    paused = False  # Flag to track if we've already printed pause/resume messages
    print("🎣 Fishing bot started!")

    with mss.mss() as sct:
        while running:
            # Check for pause flag at the very start of each iteration.
            if os.path.exists(PAUSE_FILE):
                if not paused:
                    print("⏸️ Fishing paused. Waiting for resume...")
                    paused = True
                time.sleep(0.5)
                continue  # Skip the rest of the loop until unpaused
            else:
                if paused:
                    print("▶️ Resuming fishing...")
                    paused = False

            start_time = time.time()
            detection_made = False

            # Begin splash detection loop (only runs if not paused)
            while time.time() - start_time < TIMEOUT:
                if not running:
                    return

                # Double-check pause status inside the inner loop
                if os.path.exists(PAUSE_FILE):
                    if not paused:
                        print("⏸️ Fishing paused during detection. Waiting for resume...")
                        paused = True
                    time.sleep(0.5)
                    # Break out of the inner loop if paused
                    break

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
                    pyautogui.moveTo(abs_x, abs_y, duration=0.1)
                    pyautogui.rightClick()

                    # Wait 2 seconds before casting the fishing line
                    time.sleep(2)
                    pyautogui.press('1')
                    detection_made = True
                    break

                time.sleep(INTERVAL)

            # Only cast again if detection wasn't made and we're not paused.
            if not detection_made and not os.path.exists(PAUSE_FILE):
                pyautogui.press('1')
                print(f"⏳ Timeout reached ({TIMEOUT}s), casting again.")

            time.sleep(POST_ACTION_DELAY)


def main():
    """
    Wait for user input via a global spacebar press, then start lure application and the fishing loop.
    """
    global running

    # Show the screenshot preview window before starting (auto-closes after 10 seconds)
    preview_screenshot(SCREENSHOT_REGION, duration=10)

    # Wait for a global spacebar press to start the bot
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
