import os
import time
import numpy as np
import pyautogui
import sounddevice as sd
from PIL import Image
from pydub import AudioSegment

# ====================================================
# CONFIGURABLE PARAMETERS – ADJUST THESE!
# ====================================================

# --- Audio & Reference Sound Settings ---
RATE = 44100               # Sampling rate in Hz
CHANNELS = 1               # Mono audio
CHUNK = 1024               # Number of samples to read per block from system audio

# Path to the reference sound file
REFERENCE_SOUND_FILE = "D:/FishingTrainer/Fish_Hooked.mp3"

# Normalized correlation threshold (0.0 to 1.0, where 1.0 is a perfect match).
# You may need to adjust this threshold based on testing.
CORRELATION_THRESHOLD = 0.7

# How many samples to shift in each sliding-window step (smaller = finer resolution, but more compute)
SLIDE_STEP = 500

# --- Loopback Device Settings ---
# For Windows WASAPI loopback, you must choose the proper device index.
# Run a separate script (or use the provided list_devices() function below) to list devices.
LOOPBACK_DEVICE_INDEX = 0  # <-- Replace with your WASAPI loopback device index

# --- Screenshot Settings ---
# Define the region to capture as (left, top, width, height)
SCREENSHOT_REGION = (100, 100, 300, 300)

# --- Color Settings ---
# The target color to search for (R, G, B)
TARGET_COLOR = (255, 0, 0)  # Example: pure red

# Temporary filename for the screenshot.
SCREENSHOT_PATH = "temp_screenshot.png"


# ====================================================
# HELPER FUNCTIONS
# ====================================================

def load_reference_sound(filepath):
    """
    Load the reference sound from an MP3 file using pydub,
    convert it to the desired sample rate and channels,
    and return a NumPy array of samples (dtype=np.int16).
    """
    sound = AudioSegment.from_mp3(filepath)
    # Convert to the desired frame rate and mono channel
    sound = sound.set_frame_rate(RATE).set_channels(CHANNELS)
    samples = np.array(sound.get_array_of_samples())
    return samples


def normalized_cross_correlation(x, y):
    """
    Compute the normalized cross-correlation between two signals x and y,
    where both are NumPy arrays of the same length.
    Returns a value between -1 and 1.
    """
    # Convert to float for precision and subtract mean
    x = x.astype(np.float32)
    y = y.astype(np.float32)
    x = x - np.mean(x)
    y = y - np.mean(y)
    numerator = np.sum(x * y)
    denominator = np.sqrt(np.sum(x ** 2) * np.sum(y ** 2))
    if denominator == 0:
        return 0
    return numerator / denominator


def wait_for_reference_sound(ref_signal):
    """
    Listen to system audio via WASAPI loopback and continuously check for
    a segment that matches the reference signal using normalized cross-correlation.
    When a matching segment is found, this function returns.
    """
    print(f"Listening for the reference sound '{REFERENCE_SOUND_FILE}'...")

    # Create a rolling buffer to hold recent audio samples
    buffer = np.array([], dtype=np.int16)

    # Open the input stream with loopback enabled (Windows WASAPI)
    with sd.InputStream(
            samplerate=RATE,
            channels=CHANNELS,
            blocksize=CHUNK,
            device=LOOPBACK_DEVICE_INDEX,
            dtype='int16',
            extra_settings=sd.WasapiSettings(loopback=True)
    ) as stream:
        while True:
            # Read a block of audio
            data, _ = stream.read(CHUNK)
            # data shape: (CHUNK, CHANNELS); flatten to 1D array
            data = data.flatten()
            # Append the new data to our buffer
            buffer = np.concatenate((buffer, data))
            
            # If the buffer is large enough to contain the reference signal
            ref_len = len(ref_signal)
            if len(buffer) >= ref_len:
                # Slide over the buffer in steps and check correlation
                for offset in range(0, len(buffer) - ref_len + 1, SLIDE_STEP):
                    window = buffer[offset:offset + ref_len]
                    corr = normalized_cross_correlation(ref_signal, window)
                    # Debug: Uncomment the next line to print correlation values.
                    # print(f"Offset {offset}: correlation = {corr:.3f}")
                    if corr >= CORRELATION_THRESHOLD:
                        print(f"Reference sound matched (correlation={corr:.3f})!")
                        return  # Sound detected; exit the function

                # Optionally trim the buffer to keep its size under control
                # Keep only the last 2 * ref_len samples to allow overlap.
                if len(buffer) > 2 * ref_len:
                    buffer = buffer[-2 * ref_len:]


def find_target_color_in_screenshot(image_path, target_color):
    """
    Open the screenshot and search for the target RGB color.
    Returns a tuple (found_flag, x, y), where (x, y) are coordinates relative to the screenshot.
    """
    img = Image.open(image_path)
    img_np = np.array(img)
    height, width = img_np.shape[:2]

    for y in range(height):
        for x in range(width):
            # Compare only the first three channels (RGB)
            if tuple(img_np[y, x][:3]) == target_color:
                return True, x, y
    return False, None, None


def list_devices():
    """
    Optional helper function to list available audio devices.
    """
    devices = sd.query_devices()
    print("Available audio devices:")
    for i, device in enumerate(devices):
        print(f"Device {i}: {device}")


# ====================================================
# MAIN SCRIPT
# ====================================================

def main():
    # --- (Optional) List audio devices to help choose LOOPBACK_DEVICE_INDEX ---
    # Uncomment the next two lines if you want to see the list of devices.
    # list_devices()
    # return  # Remove or comment this return once you have set your device index.

    # Load the reference sound once.
    try:
        ref_signal = load_reference_sound(REFERENCE_SOUND_FILE)
    except Exception as e:
        print(f"Error loading reference sound: {e}")
        return

    print(f"Reference sound loaded, length = {len(ref_signal)} samples.")

    while True:
        # 1. Wait until the reference sound is detected.
        wait_for_reference_sound(ref_signal)

        # 2. Take a screenshot of the defined region.
        pyautogui.screenshot(SCREENSHOT_PATH, region=SCREENSHOT_REGION)
        print("Screenshot taken.")

        # 3. Search for the target color in the screenshot.
        found, rel_x, rel_y = find_target_color_in_screenshot(SCREENSHOT_PATH, TARGET_COLOR)
        if found:
            # Convert screenshot-relative coordinates to absolute screen coordinates.
            abs_x = SCREENSHOT_REGION[0] + rel_x
            abs_y = SCREENSHOT_REGION[1] + rel_y
            print("Target color found at (x, y):", abs_x, abs_y)

            # 4. Move the mouse cursor to the target and perform a right-click.
            pyautogui.moveTo(abs_x, abs_y, duration=0.5)
            pyautogui.rightClick()
            print("Mouse moved and right-click performed.")
        else:
            print("Target color not found in the screenshot.")

        # 5. Delete the temporary screenshot file.
        if os.path.exists(SCREENSHOT_PATH):
            os.remove(SCREENSHOT_PATH)
            print("Screenshot file deleted.")

        # Optional: Wait a moment before starting over.
        time.sleep(1)


if __name__ == "__main__":
    main()
