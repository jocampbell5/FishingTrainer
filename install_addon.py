"""Copy the FishingInteract addon into WoW Forever's AddOns folder.

    python install_addon.py

Then restart WoW once: it only finds a new addon when the game starts. After the
addon changes, run this again and type /reload in game. Set WOW_ADDONS to use
another AddOns folder.
"""

import filecmp
import os
import shutil
import sys
from pathlib import Path

NAME = "FishingInteract"
OLD_NAME = "FishingTrainer"      # what this addon was called before
SOURCE = Path(__file__).resolve().parent / "addon" / NAME
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
               for f in SOURCE.iterdir() if f.is_file())
    return "ok" if same else "outdated"


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
    print(f"Installed {target}")
    old = folder / OLD_NAME
    if _is_old_copy(old):
        shutil.rmtree(old)
        print(f"Removed the old copy under its earlier name: {old}")
    print("Restart WoW once so it loads the addon. Later updates only need /reload in game.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
