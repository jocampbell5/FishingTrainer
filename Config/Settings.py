

# Settings.py



# ====================================================
# CONFIGURATION
# ====================================================

DEBUG = False  # Set to True to display the screenshot (in debug mode)

# Screen capture region (adjust as needed)
SCREENSHOT_REGION = {"left": 700, "top": 75, "width": 450, "height": 500}

# Splash color detection
TARGET_COLOR = (255, 255, 245)  # Adjust per game version
COLOR_TOLERANCE = 10

# Timing settings
INTERVAL = 1 / 30       # ~30 FPS
TIMEOUT = 30            # Seconds before forcing a cast
POST_ACTION_DELAY = 2   # Delay before next cycle
LURE_WAIT_TIME = 5      # Time to wait after applying lure
START_DELAY = 5         # 5-second delay before applying lure

# Global control flag for stopping
running = True
