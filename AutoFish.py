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
SCREENSHOT_REGION = {"left": 1500, "top": 300, "width": 800, "height": 800}

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
    of the target_color. Returns a tuple (found_flag, x, y), where (x, y) are pixel
    coordinates relative to the image.
    """
    # Convert the PIL Image to a NumPy array.
    img_np = np.array(img)
    height, width = img_np.shape[:2]

    # Loop over pixels.
    for y in range(height):
        for x in range(width):
            # Get the pixel's (R, G, B) values (ignore alpha if present)
            pixel = tuple(img_np[y, x][:3])
            # Cast each pixel value to int to avoid overflow and compare with target_color.
            if all(abs(int(pixel[i]) - target_color[i]) <= tolerance for i in range(3)):
                return True, x, y
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
