"""Hear the bite: listens for the bobber's splash in WoW's own sound.

Two ways, best first:

1. Match the splash itself (SplashHearing). Windows lets a program record one
   app's audio on its own (process loopback, the same thing OBS's "Application
   Audio Capture" uses), so this hears WoW and nothing else: Discord, Spotify or a
   video don't count. Every 10 ms it compares the last 0.6 s of WoW's sound with
   a recording of the real splash (splash.wav, next to this file), band by band
   across 40 frequency bands from 500 Hz to 16 kHz, after taking away the steady
   background (music, ambient sound). The score is a correlation, so it doesn't
   care how loud the splash is: 1.0 means exactly the splash shape.
   Music and Ambient Sounds can stay on.

2. Hear WoW get louder (SplashListener). Reads WoW's volume meter, the one in
   Windows' Volume Mixer. Simpler, but any loud sound in the game counts, so it
   needs Music and Ambient Sounds off. Used when matching can't run.

Run this file on its own for a live meter (loudness and match score):

    python sound_bite.py

Make a splash recording from a video or WAV of a real bite (more recordings,
e.g. from other zones, make matching more reliable; all splash*.wav are used):

    python sound_bite.py --template "C:\\Users\\you\\Videos\\fishing.mp4" 22.74

The time is where the splash sound starts, in seconds. The tool prints a chart
of the high-pitched sound around it so you can check, and how well the new
recording separates the splash from everything else in the file.
"""

import collections
import ctypes
import math
import queue
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

BLOCK_MS = 20          # the volume meter is read every 20 ms
SILENCE_DB = -120.0    # what pure silence reads as
RESCAN_S = 5.0         # look for WoW's audio sessions again this often (WoW restarted, device changed)

# Splash matching
RATE = 48000           # samples per second, for capture and recordings
FFT = 2048             # samples per analysis frame (43 ms)
HOP = 480              # a new frame every 10 ms
BANDS = 40             # log-spaced frequency bands...
LO_HZ, HI_HZ = 500, 16000   # ...between these (music and ambience live mostly lower)
TEMPLATE_S = 0.6       # how much of the splash is compared: the first 0.6 s
BG_FRAMES = 200        # background = per-band median of the 2 s before the compared stretch
FLOOR_DB = -60.0       # the background never counts as quieter than this (see SplashMatcher)
RANGE_DB = 20.0        # compare only the top 20 dB of each stretch; quieter detail is noise
GATE_DB = 3.0          # the compared stretch must be this much louder than the background
MATCH_LINE = 0.80      # default score that counts as a splash. Tested: splashes >= 0.89 even
                       # 18 dB quieter, re-pitched 5%, music on or off (live: 0.95-0.97); other
                       # sounds <= 0.64, except one live WoW music track starting from silence: 0.70


# ====================================================
# LOUDNESS (fallback)
# ====================================================

def to_db(peak: float) -> float:
    """A meter reading (0..1) in dBFS: 0 is the loudest possible."""
    return max(SILENCE_DB, 20 * math.log10(max(peak, 1e-9)))


def noise_floor(levels: list[float]) -> float:
    """The usual background loudness: the median reading, so one stray click doesn't raise it."""
    return float(np.median(levels)) if levels else SILENCE_DB


class SplashDetector:
    """Decides when a splash happens from loudness readings.

    A splash is `blocks_needed` readings in a row at or above the line, where the
    line is `jump_db` over the background, and never below `min_db`.
    """

    def __init__(self, noise_db: float, jump_db: float, min_db: float, blocks_needed: int = 2):
        self.threshold = max(noise_db + jump_db, min_db)
        self.blocks_needed = blocks_needed
        self.run = 0
        self.peak = SILENCE_DB   # loudest reading seen, for tuning

    def feed(self, db: float) -> bool:
        self.peak = max(self.peak, db)
        self.run = self.run + 1 if db >= self.threshold else 0
        return self.run >= self.blocks_needed


def _is_app(process_name: str, app: str) -> bool:
    name = process_name.lower()
    return name.startswith(app) and "voice" not in name   # not WowVoiceProxy (voice chat)


class SplashListener:
    """Reads an app's volume meter every 20 ms on its own thread.

    `app` is the start of the process name: "wow" matches Wow.exe, WowClassic.exe...
    """

    def __init__(self, app: str = "wow"):
        self.app = app.lower()
        self.source = ""
        self._levels: queue.Queue[float] = queue.Queue()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, name="SplashListener", daemon=True)
        self._thread.start()
        self._ready.wait(10)
        if self._error:
            raise self._error

    def _find_meters(self):
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation  # pip install pycaw

        found = [(s.Process.name(), s._ctl.QueryInterface(IAudioMeterInformation))
                 for s in AudioUtilities.GetAllSessions()
                 if s.Process and _is_app(s.Process.name(), self.app)]
        return [name for name, _ in found], [meter for _, meter in found]

    def _run(self):
        import comtypes   # COM has to be set up on the thread that uses it

        comtypes.CoInitialize()
        try:
            names, meters = self._find_meters()
            if not meters:
                raise RuntimeError(f"no sound from '{self.app}' yet: start the game with sound on first")
            self.source = ", ".join(sorted(set(names)))
        except Exception as e:
            self._error = e
            self._ready.set()
            comtypes.CoUninitialize()
            return
        self._ready.set()

        next_scan = time.monotonic() + RESCAN_S
        next_read = time.monotonic()
        try:
            while not self._stop.is_set():
                try:
                    peak = max(m.GetPeakValue() for m in meters)
                except Exception:
                    peak, next_scan = 0.0, 0.0   # session went away: look again now
                self._levels.put(to_db(peak))
                if time.monotonic() >= next_scan:
                    try:
                        _, found = self._find_meters()
                        meters = found or meters
                    except Exception:
                        pass
                    next_scan = time.monotonic() + RESCAN_S
                # time.sleep has a precise timer on Windows (Python 3.11+); Event.wait
                # rounds up to the 15.6 ms system tick and would read every ~31 ms.
                next_read = max(next_read + BLOCK_MS / 1000, time.monotonic())
                time.sleep(max(0.0, next_read - time.monotonic()))
        finally:
            del meters
            comtypes.CoUninitialize()

    def flush(self) -> None:
        """Drop readings taken so far, e.g. the cast sound."""
        while True:
            try:
                self._levels.get_nowait()
            except queue.Empty:
                return

    def levels_for(self, seconds: float) -> list[float]:
        """Collect the readings taken over the next `seconds`."""
        end = time.monotonic() + seconds
        levels = []
        while (left := end - time.monotonic()) > 0:
            try:
                levels.append(self._levels.get(timeout=left))
            except queue.Empty:
                break
        return levels

    def wait_for_splash(self, detector: SplashDetector, timeout: float, keep_going=lambda: True) -> bool:
        """True as soon as `detector` hears a splash; False on timeout or when keep_going() turns False."""
        end = time.monotonic() + timeout
        while time.monotonic() < end and keep_going():
            try:
                db = self._levels.get(timeout=0.05)
            except queue.Empty:
                continue
            if detector.feed(db):
                return True
        return False

    def close(self) -> None:
        self._stop.set()
        self._thread.join(2)


# ====================================================
# SPLASH MATCHING
# ====================================================

def _band_matrix() -> np.ndarray:
    """Sums FFT bins into BANDS log-spaced bands: power_spectrum @ matrix."""
    freqs = np.fft.rfftfreq(FFT, 1 / RATE)
    band = np.digitize(freqs, np.geomspace(LO_HZ, HI_HZ, BANDS + 1)) - 1
    m = np.zeros((len(freqs), BANDS))
    inside = (band >= 0) & (band < BANDS)
    m[np.arange(len(freqs))[inside], band[inside]] = 1.0
    return m


_BAND_MATRIX = _band_matrix()
_WINDOW = np.hanning(FFT)
TEMPLATE_FRAMES = int(round(TEMPLATE_S * RATE / HOP))   # 60
_FULL_SCALE = float((np.abs(np.fft.rfft(_WINDOW)) ** 2).max() / 2)   # band power of a 0 dBFS sound
_FLOOR = np.full(BANDS, _FULL_SCALE * 10 ** (FLOOR_DB / 10) / BANDS)   # FLOOR_DB, spread evenly


def band_power(sig: np.ndarray) -> np.ndarray:
    """Power in each band, one row per 10 ms frame (row i covers samples i*HOP .. i*HOP+FFT)."""
    n = (len(sig) - FFT) // HOP + 1
    if n <= 0:
        return np.zeros((0, BANDS))
    idx = np.arange(FFT)[None, :] + HOP * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(sig[idx] * _WINDOW, axis=1)) ** 2
    return spec @ _BAND_MATRIX + 1e-10


def _shape(power: np.ndarray) -> np.ndarray:
    """A stretch of band powers as a unit vector of its top RANGE_DB, in log units."""
    power = np.maximum(power, power.max() * 10 ** (-RANGE_DB / 10))
    v = np.log10(power).ravel()
    v -= v.mean()
    return v / (np.linalg.norm(v) + 1e-12)


def template_from_clip(clip: np.ndarray) -> np.ndarray:
    """The splash's shape from a clean recording that starts just before the splash."""
    need = (TEMPLATE_FRAMES - 1) * HOP + FFT
    sig = np.zeros(need)
    sig[:min(need, len(clip))] = clip[:need]
    sig += np.random.default_rng(0).normal(0, 1e-5, need)   # so empty bands aren't log(0)
    return _shape(np.maximum(band_power(sig)[:TEMPLATE_FRAMES], 0.1 * _FLOOR))


def load_templates(folder: Path = HERE) -> list[tuple[str, np.ndarray]]:
    """Every splash*.wav in `folder`, as (file name, template)."""
    return [(p.name, template_from_clip(read_audio(p))) for p in sorted(Path(folder).glob("splash*.wav"))]


class SplashMatcher:
    """Scores, every 10 ms, how much the last 0.6 s of sound looks like a splash.

    Each band's steady background (the median of the 2 s before) is taken away
    first, so music and ambient sound don't count, then the result is correlated
    with each template. Score 1.0 = exactly a splash, 0.2-0.7 = other game
    sounds, -1 = too quiet to judge (not louder than the background).

    The background never counts as quieter than FLOOR_DB. Without that, any sound
    after true silence (Music and Ambient Sounds off) is an enormous jump from
    nothing, and that jump alone looked splash-like (scored up to 0.82).
    """

    def __init__(self, templates: list[np.ndarray]):
        if not templates:
            raise ValueError("no splash templates")
        self._templates = np.stack(templates)
        self._buf = np.zeros(0, np.float32)
        self._rows: collections.deque = collections.deque(maxlen=BG_FRAMES + TEMPLATE_FRAMES)

    def feed(self, mono: np.ndarray) -> list[tuple[float, float]]:
        """Add samples (mono, -1..1, 48 kHz). Returns (loudness dB, match score) per new 10 ms frame."""
        self._buf = np.concatenate([self._buf, mono.astype(np.float32)])
        out = []
        while len(self._buf) >= FFT:
            frame = self._buf[:FFT]
            self._rows.append((np.abs(np.fft.rfft(frame * _WINDOW)) ** 2) @ _BAND_MATRIX + 1e-10)
            newest = frame[FFT - HOP:]
            level = 10 * math.log10(float(np.mean(newest.astype(np.float64) ** 2)) + 1e-12)
            out.append((max(SILENCE_DB, level), self._score()))
            self._buf = self._buf[HOP:]
        return out

    def _score(self) -> float:
        if len(self._rows) < TEMPLATE_FRAMES + 20:
            return -1.0
        rows = np.asarray(self._rows)
        window, before = rows[-TEMPLATE_FRAMES:], rows[:-TEMPLATE_FRAMES]
        bg = np.maximum(np.median(before, axis=0), _FLOOR)
        if 10 * math.log10(window.sum() / (bg.sum() * TEMPLATE_FRAMES)) < GATE_DB:
            return -1.0
        shape = _shape(np.maximum(window - bg, 0.1 * bg))
        return float((self._templates @ shape).max())


# ====================================================
# WOW'S OWN AUDIO (Windows process loopback)
# ====================================================

_com = None


def _com_types():
    """The Windows audio interfaces process loopback needs (defined on first use)."""
    global _com
    if _com is not None:
        return _com
    from ctypes import POINTER, Structure, c_int, c_long, c_longlong, c_ubyte, c_uint32, c_ulong
    from ctypes import c_ulonglong, c_ushort, c_void_p, wintypes
    from comtypes import COMMETHOD, COMObject, GUID, HRESULT, IUnknown

    class LoopbackParams(Structure):
        _fields_ = [("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", c_int)]

    class ActivationParams(Structure):
        _fields_ = [("ActivationType", c_int), ("ProcessLoopbackParams", LoopbackParams)]

    class Blob(Structure):
        _fields_ = [("cbSize", c_ulong), ("pBlobData", c_void_p)]

    class PropVariant(Structure):
        _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort), ("blob", Blob)]

    class WaveFormatEx(Structure):
        _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                    ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                    ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
                    ("cbSize", wintypes.WORD)]

    class IActivateAudioInterfaceAsyncOperation(IUnknown):
        _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
        _methods_ = [COMMETHOD([], HRESULT, "GetActivateResult",
                               (["out"], POINTER(c_long), "activateResult"),
                               (["out"], POINTER(POINTER(IUnknown)), "activatedInterface"))]

    class IActivateAudioInterfaceCompletionHandler(IUnknown):
        _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
        _methods_ = [COMMETHOD([], HRESULT, "ActivateCompleted",
                               (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "activateOperation"))]

    class IAgileObject(IUnknown):
        _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
        _methods_ = []

    class IAudioClient(IUnknown):
        _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Initialize", (["in"], c_int, "ShareMode"),
                      (["in"], wintypes.DWORD, "StreamFlags"), (["in"], c_longlong, "hnsBufferDuration"),
                      (["in"], c_longlong, "hnsPeriodicity"), (["in"], POINTER(WaveFormatEx), "pFormat"),
                      (["in"], POINTER(GUID), "AudioSessionGuid")),
            COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "pNumBufferFrames")),
            COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_longlong), "phnsLatency")),
            COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "pNumPaddingFrames")),
            COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], c_int, "ShareMode"),
                      (["in"], POINTER(WaveFormatEx), "pFormat"),
                      (["out"], POINTER(POINTER(WaveFormatEx)), "ppClosestMatch")),
            COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WaveFormatEx)), "ppDeviceFormat")),
            COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], POINTER(c_longlong), "phnsDefault"),
                      (["out"], POINTER(c_longlong), "phnsMinimum")),
            COMMETHOD([], HRESULT, "Start"),
            COMMETHOD([], HRESULT, "Stop"),
            COMMETHOD([], HRESULT, "Reset"),
            COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wintypes.HANDLE, "eventHandle")),
            COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "riid"),
                      (["out"], POINTER(POINTER(IUnknown)), "ppv")),
        ]

    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetBuffer", (["out"], POINTER(POINTER(c_ubyte)), "ppData"),
                      (["out"], POINTER(c_uint32), "pNumFramesToRead"),
                      (["out"], POINTER(wintypes.DWORD), "pdwFlags"),
                      (["out"], POINTER(c_ulonglong), "pu64DevicePosition"),
                      (["out"], POINTER(c_ulonglong), "pu64QPCPosition")),
            COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "NumFramesRead")),
            COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
        ]

    class CompletionHandler(COMObject):
        _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

        def __init__(self):
            super().__init__()
            self.done = threading.Event()

        def ActivateCompleted(self, this, operation):
            self.done.set()
            return 0

    activate = ctypes.WinDLL("mmdevapi").ActivateAudioInterfaceAsync
    activate.restype = HRESULT
    activate.argtypes = [wintypes.LPCWSTR, POINTER(GUID), POINTER(PropVariant),
                         POINTER(IActivateAudioInterfaceCompletionHandler),
                         POINTER(POINTER(IActivateAudioInterfaceAsyncOperation))]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = [c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    _com = dict(
        LoopbackParams=LoopbackParams, ActivationParams=ActivationParams, PropVariant=PropVariant,
        WaveFormatEx=WaveFormatEx, IAudioClient=IAudioClient, IAudioCaptureClient=IAudioCaptureClient,
        IActivateAudioInterfaceAsyncOperation=IActivateAudioInterfaceAsyncOperation,
        IActivateAudioInterfaceCompletionHandler=IActivateAudioInterfaceCompletionHandler,
        CompletionHandler=CompletionHandler, activate=activate, kernel32=kernel32)
    return _com


class ProcessAudio:
    """One process's sound (and its child processes'), as 48 kHz mono.

    Needs Windows 10 2004 or later. Create and use it on one thread that has
    called comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED).
    """

    VT_BLOB = 65
    PROCESS_LOOPBACK = 1                 # AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    INCLUDE_PROCESS_TREE = 0             # PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
    STREAM_FLAGS = 0x00020000 | 0x00040000 | 0x80000000 | 0x08000000  # loopback, event, autoconvert, good SRC
    BUFFER_SILENT = 0x2

    def __init__(self, pid: int):
        from ctypes import byref, c_void_p

        c = _com_types()
        self._k32 = c["kernel32"]
        params = c["ActivationParams"](self.PROCESS_LOOPBACK, c["LoopbackParams"](pid, self.INCLUDE_PROCESS_TREE))
        pv = c["PropVariant"]()
        pv.vt = self.VT_BLOB
        pv.blob.cbSize = ctypes.sizeof(params)
        pv.blob.pBlobData = ctypes.cast(ctypes.pointer(params), c_void_p)
        handler = c["CompletionHandler"]()
        op = ctypes.POINTER(c["IActivateAudioInterfaceAsyncOperation"])()
        c["activate"]("VAD\\Process_Loopback", byref(c["IAudioClient"]._iid_), byref(pv),
                      handler.QueryInterface(c["IActivateAudioInterfaceCompletionHandler"]), byref(op))
        if not handler.done.wait(5):
            raise RuntimeError("Windows didn't answer the audio capture request")
        hr, unknown = op.GetActivateResult()
        if hr < 0:
            raise OSError(f"Windows refused to capture pid {pid}'s audio (0x{hr & 0xFFFFFFFF:08X})")
        self._client = unknown.QueryInterface(c["IAudioClient"])
        fmt = c["WaveFormatEx"](1, 2, RATE, RATE * 4, 4, 16, 0)     # PCM, stereo, 16-bit
        self._client.Initialize(0, self.STREAM_FLAGS, 2_000_000, 0, byref(fmt), None)
        self._event = self._k32.CreateEventW(None, False, False, None)
        self._client.SetEventHandle(self._event)
        self._capture = self._client.GetService(byref(c["IAudioCaptureClient"]._iid_)).QueryInterface(
            c["IAudioCaptureClient"])
        self._client.Start()

    def read(self, timeout_ms: int = 100) -> list[np.ndarray]:
        """Wait for sound (up to timeout_ms) and return the blocks that arrived."""
        self._k32.WaitForSingleObject(self._event, timeout_ms)
        blocks = []
        while self._capture.GetNextPacketSize() > 0:
            data, frames, flags, _, _ = self._capture.GetBuffer()
            if frames:
                if flags & self.BUFFER_SILENT or not data:
                    blocks.append(np.zeros(frames, np.float32))
                else:
                    pcm = np.frombuffer(ctypes.string_at(data, frames * 4), np.int16).reshape(-1, 2)
                    blocks.append(pcm.mean(axis=1, dtype=np.float32) / 32768)
            self._capture.ReleaseBuffer(frames)
        return blocks

    def close(self) -> None:
        try:
            self._client.Stop()
        finally:
            self._k32.CloseHandle(self._event)
            self._capture = self._client = None


def find_app(app: str = "wow") -> tuple[int, str]:
    """(pid, name) of the running process whose name starts with `app`."""
    import psutil   # comes with pycaw

    for p in psutil.process_iter(["name"]):
        if _is_app(p.info["name"] or "", app.lower()):
            return p.pid, p.info["name"]
    raise RuntimeError(f"'{app}' isn't running")


class SplashHearing:
    """Hears one app's sound only, and scores every 10 ms how much it sounds like the splash.

    `app` is the start of the process name ("wow" = Wow.exe), or pass `pid`.
    """

    def __init__(self, templates: list[np.ndarray], app: str = "wow", pid: int | None = None):
        self.app, self.pid, self.source = app.lower(), pid, ""
        self.problem = ""   # set while the app's sound can't be heard (e.g. the game closed)
        self._fixed_pid = pid is not None
        self._matcher = SplashMatcher(templates)
        self._out: queue.Queue[tuple[float, float]] = queue.Queue()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: Exception | None = None
        # comtypes sets up COM on whichever thread first imports it. Import it here, so the
        # capture thread is still free to set itself up the way process loopback needs.
        import comtypes  # noqa: F401
        self._thread = threading.Thread(target=self._run, name="SplashHearing", daemon=True)
        self._thread.start()
        self._ready.wait(10)
        if self._error:
            raise self._error
        if not self._ready.is_set():
            raise RuntimeError("audio capture didn't start")

    def _connect(self) -> ProcessAudio:
        if not self._fixed_pid:
            self.pid, name = find_app(self.app)
        else:
            import psutil
            name = psutil.Process(self.pid).name()
        audio = ProcessAudio(self.pid)
        self.source = name
        return audio

    def _run(self):
        import comtypes
        import psutil

        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        audio = None
        try:
            try:
                audio = self._connect()
            except Exception as e:
                self._error = e
                return
            finally:
                self._ready.set()
            next_check = time.monotonic() + 5
            while not self._stop.is_set():
                try:
                    if time.monotonic() >= next_check:
                        next_check = time.monotonic() + 5
                        if not psutil.pid_exists(self.pid):
                            raise RuntimeError(f"{self.source} closed")
                    for block in audio.read(100):
                        for reading in self._matcher.feed(block):
                            self._out.put(reading)
                except Exception as e:      # the game closed, or its audio device changed
                    self.problem = str(e)
                    if audio:
                        audio.close()
                    audio = None
                    while audio is None and not self._stop.wait(2):
                        try:
                            audio = self._connect()
                            self.problem = ""
                        except Exception as e2:
                            self.problem = str(e2)
        finally:
            if audio:
                audio.close()
            comtypes.CoUninitialize()

    def flush(self) -> None:
        """Drop readings so far, e.g. the cast's own sounds."""
        while True:
            try:
                self._out.get_nowait()
            except queue.Empty:
                return

    def readings_for(self, seconds: float) -> list[tuple[float, float]]:
        """(loudness dB, match score) readings over the next `seconds`."""
        end = time.monotonic() + seconds
        out = []
        while (left := end - time.monotonic()) > 0:
            try:
                out.append(self._out.get(timeout=left))
            except queue.Empty:
                break
        return out

    def wait_for_match(self, line: float, timeout: float, keep_going=lambda: True) -> tuple[bool, float]:
        """(True, score) as soon as a reading reaches `line`; (False, best score) on timeout or when
        keep_going() turns False."""
        end = time.monotonic() + timeout
        best = -1.0
        while time.monotonic() < end and keep_going():
            try:
                _, score = self._out.get(timeout=0.05)
            except queue.Empty:
                continue
            best = max(best, score)
            if score >= line:
                return True, score
        return False, best

    def close(self) -> None:
        self._stop.set()
        self._thread.join(2)


# ====================================================
# MAKING SPLASH RECORDINGS
# ====================================================

def read_audio(path) -> np.ndarray:
    """A WAV or video file's sound as mono float at 48 kHz."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as w:
            if w.getsampwidth() != 2:
                raise ValueError(f"{path.name}: only 16-bit WAV files are supported")
            rate, ch = w.getframerate(), w.getnchannels()
            pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, ch)
        sig = pcm.mean(axis=1) / 32768
        if rate != RATE:
            sig = np.interp(np.arange(int(len(sig) * RATE / rate)) * rate / RATE, np.arange(len(sig)), sig)
        return sig.astype(np.float32)
    import av   # pip install av (only needed to read videos)

    chunks = []
    with av.open(str(path)) as container:
        resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
        for frame in container.decode(audio=0):
            chunks += [f.to_ndarray().ravel() for f in resampler.resample(frame)]
        chunks += [f.to_ndarray().ravel() for f in resampler.resample(None)]
    return np.concatenate(chunks).astype(np.float32)


def _stft(sig, n=2048, hop=512):
    w = np.hanning(n)
    k = (len(sig) - n) // hop + 1
    idx = np.arange(n)[None, :] + hop * np.arange(k)[:, None]
    return np.fft.rfft(sig[idx] * w, axis=1)


def _istft(spec, length, n=2048, hop=512):
    w = np.hanning(n)
    out, norm = np.zeros(length), np.zeros(length)
    for i, frame in enumerate(np.fft.irfft(spec, n=n, axis=1)):
        out[i * hop:i * hop + n] += frame * w
        norm[i * hop:i * hop + n] += w ** 2
    ok = norm > 0.1 * norm.max()          # the very edges get almost no window: drop them
    return np.where(ok, out / np.where(ok, norm, 1), 0.0)


def clean_splash(audio: np.ndarray, onset: float) -> np.ndarray:
    """The splash from `onset - 0.04 s` to `onset + 1.2 s`, with the steady background
    (music, ambient sound, from the second before) subtracted out."""
    seg = audio[int((onset - 0.14) * RATE):int((onset + 1.2) * RATE)].astype(np.float64)
    bg = audio[int((onset - 1.0) * RATE):int((onset - 0.05) * RATE)].astype(np.float64)
    bg_power = np.median(np.abs(_stft(bg)) ** 2, axis=0)
    spec = _stft(seg)
    power = np.abs(spec) ** 2
    keep = np.sqrt(np.clip(power - 1.5 * bg_power, 0, None) / np.maximum(power, 1e-20))
    return _istft(spec * keep, len(seg))[int(0.10 * RATE):]


def match_scores(audio: np.ndarray, templates: list[np.ndarray]) -> np.ndarray:
    """Match score for every 10 ms of a recording; entry i is for the 0.6 s ending
    at (i * HOP + FFT) / RATE seconds."""
    m = SplashMatcher(templates)
    return np.array([score for _, score in m.feed(audio)])


def make_template(source, onset: float, folder: Path = HERE) -> Path:
    audio = read_audio(source)
    if not 1.0 <= onset <= len(audio) / RATE - 1.2:
        raise SystemExit(f"the splash needs 1 s of sound before it and 1.2 s after; the file is "
                         f"{len(audio) / RATE:.1f} s long")

    print(f"High-pitched sound (2-16 kHz) around {onset:.2f} s; the splash should start at the arrow:")
    f = np.fft.rfftfreq(1024, 1 / RATE)
    hi = (f >= 2000) & (f < 16000)
    for t in np.arange(onset - 1.0, onset + 1.5, 0.05):
        i = int(t * RATE)
        e = 10 * np.log10((np.abs(np.fft.rfft(audio[i - 512:i + 512] * np.hanning(1024))) ** 2)[hi].sum() + 1e-12)
        mark = " <-- splash starts" if abs(t - onset) < 0.025 else ""
        print(f"  {t:6.2f}s {e:6.1f} dB {'#' * max(0, int((e + 20) / 1.5))}{mark}")

    clip = clean_splash(audio, onset)
    n = 1
    out = Path(folder) / "splash.wav"
    while out.exists():
        n += 1
        out = Path(folder) / f"splash_{n}.wav"
    pcm = (np.clip(clip, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())

    # how well it separates the splash from everything else in this file
    scores = match_scores(audio, [template_from_clip(read_audio(out))])
    ends = (np.arange(len(scores)) * HOP + FFT) / RATE
    near = (ends >= onset) & (ends <= onset + TEMPLATE_S + 1.0)
    elsewhere = ~near & ((ends < onset - 0.5) | (ends > onset + 2.5))
    best_here = scores[near].max()
    print(f"\nSaved {out.name}. Match at the splash: {best_here:.2f}", end="")
    if elsewhere.any():
        i = np.argmax(np.where(elsewhere, scores, -9))
        print(f"; best match anywhere else in the file: {scores[i]:.2f} at {ends[i]:.1f} s "
              f"(the trainer counts {MATCH_LINE:.2f} as a splash)")
    else:
        print()
    return out


# ====================================================
# METER
# ====================================================

def meter(app: str = "wow") -> None:
    """Every quarter second: loudness, and the match score when matching works."""
    templates = load_templates()
    hearing = None
    if templates:
        try:
            hearing = SplashHearing([t for _, t in templates], app)
        except Exception as e:
            print(f"Can't hear {app} on its own ({e}); showing loudness only.\n")
    else:
        print("No splash*.wav recordings yet; showing loudness only.\n")

    if hearing is None:
        listener = SplashListener(app)
        print(f"Listening to {listener.source}'s volume. Ctrl+C to stop.")
        print("Cast in WoW and watch for the splash. 0 dB is the loudest possible.\n")
        try:
            while True:
                levels = listener.levels_for(0.25)
                peak = max(levels) if levels else SILENCE_DB
                print(f"{peak:7.1f} dB  {'#' * max(0, int((peak + 80) / 2))}")
        except KeyboardInterrupt:
            pass
        finally:
            listener.close()
        return

    print(f"Listening to {hearing.source} only, matching {', '.join(n for n, _ in templates)}. Ctrl+C to stop.")
    print(f"Cast and wait for a bite. Match 1.00 = exactly the splash; the trainer bites at {MATCH_LINE:.2f}.\n")
    try:
        while True:
            readings = hearing.readings_for(0.25)
            peak = max((db for db, _ in readings), default=SILENCE_DB)
            match = max((s for _, s in readings), default=-1.0)
            flag = "  <-- SPLASH" if match >= MATCH_LINE else ""
            note = f"  ({hearing.problem})" if hearing.problem else ""
            print(f"{peak:7.1f} dB  match {max(match, 0):.2f}  {'#' * int(max(match, 0) * 40):<40}{flag}{note}")
    except KeyboardInterrupt:
        pass
    finally:
        hearing.close()


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--template":
        make_template(sys.argv[2], float(sys.argv[3]))
    elif len(sys.argv) == 1:
        meter()
    else:
        print(__doc__)
