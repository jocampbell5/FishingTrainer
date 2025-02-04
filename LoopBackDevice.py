import sounddevice as sd

def list_audio_devices():
    devices = sd.query_devices()
    print("Available audio devices:")
    for i, device in enumerate(devices):
        print(f"Device {i}: {device}")

if __name__ == "__main__":
    list_audio_devices()

