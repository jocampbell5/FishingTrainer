
# ====================================================
# SCREENSHOT PREVIEW WINDOW (10-second duration)
# ====================================================
# PreviewSS.py

import time
import numpy as np
import cv2
import mss

def preview_screenshot(region, duration=10):
    """
    Displays a live preview of the specified screenshot region with a centered label "SCREEN SHOT PREVIEW".
    The preview will auto-close after 'duration' seconds or if 'q' is pressed.
    
    Parameters:
        region (dict): A dictionary defining the region to capture (keys: left, top, width, height).
        duration (int, optional): Duration in seconds to show the preview. Default is 10 seconds.
    """
    print(f"📷 Opening Screenshot Preview Window ({duration} seconds)...")
    start_time = time.time()
    
    with mss.mss() as sct:
        while True:
            # Capture the region
            sct_img = sct.grab(region)
            frame = np.array(sct_img)
            # Convert from RGB to BGR for OpenCV
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            
            # Define text parameters
            text = "SCREEN SHOT PREVIEW"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 1.0
            thickness = 2
            
            # Get text size
            text_size, _ = cv2.getTextSize(text, font, font_scale, thickness)
            text_width, text_height = text_size
            
            # Center the text in the frame
            h, w, _ = frame.shape
            text_x = (w - text_width) // 2
            text_y = (h + text_height) // 2
            
            # Overlay text on the frame
            cv2.putText(frame, text, (text_x, text_y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
            
            # Show the frame
            cv2.imshow("Screen Shot Preview", frame)
            
            # Close preview if 'q' is pressed
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            
            # Auto-close after the specified duration
            if time.time() - start_time > duration:
                break

    cv2.destroyAllWindows()
    print("✅ Screenshot Preview Closed.")
