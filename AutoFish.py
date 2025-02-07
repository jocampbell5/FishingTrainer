import time
import numpy as np
import pyautogui
import cv2
from PIL import Image
import mss

# ====================================================
# CONFIGURABLE PARAMETERS – ADJUST THESE!
# ====================================================

DEBUG = False  # Set to True to display the screenshot; False to hide it.

# --- Screenshot Settings ---
# Define the region to capture as a dictionary for mss.

# Screen size for 4k resolution
SCREENSHOT_REGION = {"left": 1600, "top": 400, "width": 700, "height": 700}

# Screen size for 1980 x 1024
# SCREENSHOT_REGION = {"left": 750, "top": 200, "width": 400, "height": 500}

# --- Color Settings ---
TARGET_COLOR = (255, 255, 245)  # The target color (R, G, B) e.g., pure red
COLOR_TOLERANCE = 5        # Tolerance per channel

# --- Timing Settings ---
INTERVAL = 1 / 30         # Interval between frames (~30 fps)
TIMEOUT = 30              # Maximum seconds to wait for a color detection before pressing "1"
POST_ACTION_DELAY = 2     # Delay after action before restarting the cycle
DISPLAY_TIME = 1000       # Time (in milliseconds) to display the screenshot if DEBUG is True

# ====================================================
# HELPER FUNCTIONS
# ====================================================

def find_target_color_in_image(img, target_color, tolerance):
    """
    Given a PIL Image, search for a pixel whose color is within the given tolerance
    of the target_color. Returns a tuple (found_flag, x, y).
    """
    # Convert the PIL Image to a NumPy array
    img_np = np.array(img)

    # Ensure the image has at least 3 color channels (RGB)
    if len(img_np.shape) < 3 or img_np.shape[2] < 3:
        print("Error: Image does not have enough color channels.")
        return False, None, None

    height, width = img_np.shape[:2]

    for y in range(height):
        for x in range(width):
            pixel = tuple(img_np[y, x][:3])  # Ensure we only take RGB values
            
            # Verify pixel contains valid RGB values
            if len(pixel) != 3:
                print(f"Skipping invalid pixel at ({x}, {y}): {pixel}")
                continue
            
            try:
                if all(abs(int(pixel[i]) - target_color[i]) <= tolerance for i in range(3)):
                    return True, x, y
            except IndexError:
                print(f"IndexError: Pixel data at ({x}, {y}) is invalid: {pixel}")
                continue  # Skip this pixel if there's an issue

    return False, None, None



def show_image_cv2(img, window_name="Screenshot Region", delay=DISPLAY_TIME):
    """
    Display the given PIL Image using OpenCV for a specified delay (in milliseconds).
    """
    # Convert the PIL Image to an OpenCV (BGR) image.
    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    cv2.imshow(window_name, img_cv)
    cv2.waitKey(delay)
    cv2.destroyWindow(window_name)

# ====================================================
# MAIN SCRIPT
# ====================================================


# FIXES RIGHT NOW:
# We want the app to say that the app has started
# We want the app to start by pressing 2 - to start the macro for adding the lure
# We want wait until the lure is attached and the fishing pole is equiped (say X seconds or so)
# We want then start the main script of looking for the splash
# 

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

def main():
    with mss.mss() as sct:
        while True:
            start_time = time.time()
            detection_made = False
            
            # Try to detect the target color for up to TIMEOUT seconds.
            while time.time() - start_time < TIMEOUT:
                # Capture the screenshot of the specified region using mss.
                sct_img = sct.grab(SCREENSHOT_REGION)
                # Convert the captured image to a PIL Image.
                img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                
                # If debugging is enabled, display the screenshot.
                if DEBUG:
                    show_image_cv2(img, delay=DISPLAY_TIME)
                
                # Check for the target color in the image.
                found, rel_x, rel_y = find_target_color_in_image(img, TARGET_COLOR, COLOR_TOLERANCE)
                if found:
                    # Calculate absolute screen coordinates.
                    abs_x = SCREENSHOT_REGION["left"] + rel_x
                    abs_y = SCREENSHOT_REGION["top"] + rel_y
                    print("Target color found at (x, y):", abs_x, abs_y)
                    
                    # Move the mouse to the detected location and perform a right-click.
                    pyautogui.moveTo(abs_x, abs_y, duration=0.5)
                    pyautogui.rightClick()
                    print("Mouse moved and right-click performed.")
                    
                    # Wait for 2 seconds, then press the "1" key.
                    time.sleep(2)
                    pyautogui.press('1')
                    print("Pressed the 1 key on the keyboard.")
                    
                    detection_made = True
                    break  # Exit the inner loop if detection occurred.
                
                # Wait for the next frame (~33 ms for 30 fps).
                time.sleep(INTERVAL)
            
            # If no detection was made within TIMEOUT seconds, press "1" anyway.
            if not detection_made:
                pyautogui.press('1')
                print(f"Color not found within {TIMEOUT} seconds; pressed the 1 key anyway.")

            
            # Wait a brief moment before starting the next detection cycle.
            time.sleep(POST_ACTION_DELAY)

if __name__ == "__main__":
    main()
