"""Copy the FishingInteract addon into WoW Forever's AddOns folder.

    python install_addon.py

Then restart WoW once: it only finds a new addon when the game starts. After the
addon changes, run this again and type /reload in game. Set WOW_ADDONS to use
another AddOns folder.

The addon binds the keys FishingTrainer presses, from its Keys.lua. FishingTrainer's
window rewrites that file (write_keys) when you change the keys there.
"""

import filecmp
import json
import os
import shutil
import sys
from pathlib import Path

NAME = "FishingInteract"
OLD_NAME = "FishingTrainer"      # what this addon was called before
SOURCE = Path(__file__).resolve().parent / "addon" / NAME
KEYS_FILE = "Keys.lua"           # the keys FishingTrainer presses; yours, so not compared
SETTINGS = Path(__file__).resolve().parent / "settings.json"   # FishingTrainer window's settings
DEFAULT_KEYS = {"cast-key": "]", "interact-key": "["}
WOW_ROOTS = [r"C:\Program Files (x86)\World of Warcraft", r"C:\Program Files\World of Warcraft",
             r"D:\World of Warcraft"]


def addons_folder() -> Path | None:
    if os.environ.get("WOW_ADDONS"):
        return Path(os.environ["WOW_ADDONS"])
    for root in WOW_ROOTS:
        path = Path(root) / "_forever_" / "Interface" / "AddOns"
        if path.is_dir():
            return path
    return None


def status() -> str:
    """"ok", "outdated" (installed copy differs from this folder's) or "missing"."""
    folder = addons_folder()
    target = folder / NAME if folder else None
    if not target or not (target / f"{NAME}.toc").is_file():
        return "missing"
    same = all((target / f.name).is_file() and filecmp.cmp(f, target / f.name, shallow=False)
               for f in SOURCE.iterdir() if f.is_file() and f.name != KEYS_FILE)
    return "ok" if same else "outdated"


def lua_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def keys_lua(cast: str, interact: str) -> str:
    """Keys.lua for these keys (as pydirectinput names them: "]", "f", "f5"...)."""
    head = (SOURCE / KEYS_FILE).read_text(encoding="utf-8").split("FishingInteract_Keys")[0]
    return (f"{head}FishingInteract_Keys = {{ fish = {lua_string(cast.upper())}, "
            f"interact = {lua_string(interact.upper())} }}\n")


def saved_keys() -> dict:
    """The keys chosen in FishingTrainer's window, or the recommended ones."""
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {k: data.get(k) or v for k, v in DEFAULT_KEYS.items()}


def write_keys(cast: str, interact: str) -> Path | None:
    """Tell the installed addon which keys to bind. None when it isn't installed."""
    folder = addons_folder()
    target = folder / NAME if folder else None
    if not target or not (target / f"{NAME}.toc").is_file():
        return None
    path = target / KEYS_FILE
    path.write_bytes(keys_lua(cast, interact).encode("utf-8"))
    return path


def _is_old_copy(path: Path) -> bool:
    """The same addon under its old name, installed by an earlier version of this script."""
    toc = path / f"{OLD_NAME}.toc"
    if not toc.is_file():
        return False
    text = toc.read_text(encoding="utf-8", errors="replace")
    return f"## Title: {OLD_NAME}" in text and "## Author: jocampbell5" in text


def main() -> int:
    folder = addons_folder()
    if folder is None:
        raise SystemExit("WoW Forever's AddOns folder not found; set WOW_ADDONS to it")
    target = folder / NAME
    shutil.copytree(SOURCE, target, dirs_exist_ok=True)
    keys = saved_keys()
    write_keys(keys["cast-key"], keys["interact-key"])
    print(f"Installed {target}")
    print(f"It binds Fish to {keys['cast-key']} and Interact with Target to {keys['interact-key']} "
          "(change them in FishingTrainer's window)")
    old = folder / OLD_NAME
    if _is_old_copy(old):
        shutil.rmtree(old)
        print(f"Removed the old copy under its earlier name: {old}")
    print("Restart WoW once so it loads the addon. Later updates only need /reload in game.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
