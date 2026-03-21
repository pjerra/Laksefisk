"""Save debug screenshots when bobber detection fails."""

import logging
import os
from datetime import datetime

from PIL import Image

logger = logging.getLogger("Laksefisk")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_FOLDER = os.path.join(_SCRIPT_DIR, "debug_screenshots")
_MAX_FILES = 50


def save_debug_screenshot(bitmap: Image.Image, reason: str) -> None:
    """Save a screenshot with highlighted pixels to debug_screenshots/."""
    try:
        os.makedirs(_FOLDER, exist_ok=True)

        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{stamp}_{reason}.png"
        path = os.path.join(_FOLDER, filename)
        bitmap.save(path)
        logger.info(f"Debug screenshot saved: {path}")

        # Cap at _MAX_FILES — delete oldest
        files = sorted(
            (os.path.join(_FOLDER, f) for f in os.listdir(_FOLDER) if f.endswith(".png")),
            key=os.path.getmtime,
        )
        while len(files) > _MAX_FILES:
            os.remove(files.pop(0))
    except Exception:
        logger.debug("Failed to save debug screenshot", exc_info=True)
