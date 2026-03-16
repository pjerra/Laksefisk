"""
Test script: Visual chat region selector + OCR.

Opens a draggable/resizable semi-transparent overlay you position over WoW's
chat area. Click "Capture & OCR" to grab that region and run OCR on it.

In the real bot, only the LAST item is extracted per loot event (no double
counting). This test shows both all items and the last-item-only result.

Usage:
    python tests/test_ocr_chat.py
"""

import asyncio
import json
import os
import re
import tkinter as tk
import unicodedata
from tkinter import ttk
from typing import List, Optional, Tuple

import mss
from PIL import Image, ImageTk

import winocr

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def capture_region(left: int, top: int, width: int, height: int) -> Image.Image:
    """Capture a specific screen region."""
    with mss.mss() as sct:
        region = {"left": left, "top": top, "width": width, "height": height}
        screenshot = sct.grab(region)
        return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")


def preprocess(img: Image.Image, threshold: int = 50) -> Image.Image:
    """Enhance chat text for OCR: scale up, keep all non-black pixels."""
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    gray = img.convert("L")
    binary = gray.point(lambda p: 255 if p > threshold else 0)
    return binary.convert("RGB")


async def ocr_image(img: Image.Image) -> str:
    result = await winocr.recognize_pil(img, lang="en")
    return result.text


# --- Item extraction logic (will be moved to fish_tracker.py) ---

_ITEM_RE = re.compile(
    r"\[?([A-Za-z\u00C0-\u024F][\w\u00C0-\u024F' ]{4,}?)\]?\s*(?:x(\d+))?\s*\.",
)


def _clean_ocr_text(text: str) -> str:
    """Clean common OCR artifacts from the item portion of chat text."""
    # Remove periods between letters (e.g. "Figli.ister's")
    text = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z])", "", text)
    # Remove short uppercase noise prefixes (e.g. "WIG ")
    text = re.sub(r"\b[A-Z]{1,4}\s+(?=[A-Z][a-z])", "", text)
    # OCR reads ] as l — fix "l." and "lx" patterns
    text = re.sub(r"l(\.\s)", r"]\1", text)
    text = re.sub(r"l(x\d)", r"]\1", text)
    return text


def _normalize_name(name: str) -> str:
    """Normalize OCR artifacts: strip accents."""
    return "".join(
        c if unicodedata.category(c) != "Mn" else ""
        for c in unicodedata.normalize("NFD", name)
    )


def _normalize_key(name: str) -> str:
    """Key for grouping: lowercase, no apostrophes, no accents."""
    return _normalize_name(name).replace("'", "").replace("\u2019", "").lower()


def _extract_item_text(ocr_text: str) -> str:
    """Extract the item-name portion from OCR text (after last 'loot:' block)."""
    last_loot = ocr_text.rfind("loot:")
    if last_loot >= 0:
        item_text = ocr_text[last_loot:]
        item_text = re.sub(r"\d{2}:\d{2}\s*[|iI]\s*You receive loot:", "", item_text)
        item_text = re.sub(r"^loot:\s*", "", item_text)
    else:
        item_text = ocr_text
    return _clean_ocr_text(item_text)


def parse_all_items(ocr_text: str) -> List[Tuple[str, int]]:
    """Parse all item names and quantities from OCR text."""
    item_text = _extract_item_text(ocr_text)
    results = {}  # normalized_key -> [display_name, total_qty]
    for m in _ITEM_RE.finditer(item_text):
        name = _normalize_name(m.group(1).strip())
        qty = int(m.group(2)) if m.group(2) else 1
        if len(name) > 4:
            key = _normalize_key(name)
            if key in results:
                results[key][1] += qty
            else:
                results[key] = [name, qty]
    return [(name, qty) for name, qty in results.values()]


def parse_last_item(ocr_text: str) -> Optional[Tuple[str, int]]:
    """Parse only the LAST item from OCR text. Used by the bot per-loot."""
    item_text = _extract_item_text(ocr_text)
    last_match = None
    for m in _ITEM_RE.finditer(item_text):
        name = _normalize_name(m.group(1).strip())
        qty = int(m.group(2)) if m.group(2) else 1
        if len(name) > 4:
            last_match = (name, qty)
    return last_match


# --- GUI ---

class RegionSelector(tk.Tk):
    """Semi-transparent overlay window you drag over WoW's chat area."""

    def __init__(self):
        super().__init__()

        self._config_path = os.path.join(_SCRIPT_DIR, "ocr_region.json")
        saved = self._load_region()

        with mss.mss() as sct:
            mon = sct.monitors[1]
            self._screen_w = mon["width"]
            self._screen_h = mon["height"]

        default_x = saved.get("x", 0)
        default_y = saved.get("y", int(self._screen_h * 0.75))
        default_w = saved.get("w", int(self._screen_w * 0.4))
        default_h = saved.get("h", int(self._screen_h * 0.25))

        self.title("OCR Region Selector")
        self.geometry(f"{default_w}x{default_h}+{default_x}+{default_y}")
        self.attributes("-alpha", 0.35)
        self.attributes("-topmost", True)
        self.configure(bg="#00ff00")
        self.overrideredirect(False)
        self.resizable(True, True)

        # Control panel
        self._panel = tk.Toplevel(self)
        self._panel.title("OCR Test Controls")
        self._panel.attributes("-topmost", True)
        self._panel.geometry(f"600x700+{default_x + default_w + 10}+{default_y}")
        self._panel.resizable(True, True)

        btn_frame = ttk.Frame(self._panel)
        btn_frame.pack(fill="x", padx=5, pady=5)

        ttk.Button(btn_frame, text="Capture & OCR", command=self._do_capture).pack(
            side="left", padx=3
        )
        ttk.Button(btn_frame, text="Save Region", command=self._save_region).pack(
            side="left", padx=3
        )

        self._region_label = ttk.Label(btn_frame, text="")
        self._region_label.pack(side="left", padx=10)

        # Preview image
        self._preview_label = ttk.Label(self._panel)
        self._preview_label.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        self._preview_photo = None

        # OCR results
        self._text = tk.Text(self._panel, height=12, wrap="word", font=("Consolas", 10))
        self._text.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        self._update_region_label()
        self.bind("<Configure>", lambda e: self._update_region_label())

    def _get_region(self) -> dict:
        return {
            "x": self.winfo_x(),
            "y": self.winfo_y(),
            "w": self.winfo_width(),
            "h": self.winfo_height(),
        }

    def _update_region_label(self):
        r = self._get_region()
        self._region_label.config(
            text=f"x={r['x']}  y={r['y']}  w={r['w']}  h={r['h']}"
        )

    def _load_region(self) -> dict:
        try:
            with open(self._config_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_region(self):
        r = self._get_region()
        with open(self._config_path, "w") as f:
            json.dump(r, f, indent=2)
        self._text.delete("1.0", "end")
        self._text.insert("end", f"Region saved: {r}\n")

    def _do_capture(self):
        r = self._get_region()

        # Temporarily hide overlay
        self.attributes("-alpha", 0.0)
        self.update()
        import time
        time.sleep(0.05)

        raw = capture_region(r["x"], r["y"], r["w"], r["h"])

        self.attributes("-alpha", 0.35)

        # Save raw image
        raw.save(os.path.join(_SCRIPT_DIR, "chat_raw.png"))

        # Preview
        panel_w = self._panel.winfo_width() - 20
        if panel_w > 50:
            ratio = panel_w / raw.width
            preview = raw.resize(
                (panel_w, max(1, int(raw.height * ratio))), Image.LANCZOS
            )
        else:
            preview = raw
        self._preview_photo = ImageTk.PhotoImage(preview)
        self._preview_label.config(image=self._preview_photo)

        # Test multiple preprocessing approaches
        thresholds = [
            ("grayscale only (no threshold)", None),
            ("threshold 50 (current)", 50),
            ("threshold 80", 80),
            ("threshold 100", 100),
            ("threshold 130", 130),
            ("threshold 160", 160),
        ]

        self._text.delete("1.0", "end")

        for label, thresh in thresholds:
            if thresh is None:
                # Grayscale + scale, no binary threshold
                scaled = raw.resize((raw.width * 2, raw.height * 2), Image.LANCZOS)
                processed = scaled.convert("L").convert("RGB")
            else:
                processed = preprocess(raw, threshold=thresh)

            text = asyncio.run(ocr_image(processed))
            last_item = parse_last_item(text)

            self._text.insert("end", f"=== {label} ===\n")
            self._text.insert("end", (text or "(nothing)") + "\n")
            if last_item:
                self._text.insert("end", f"  -> Last item: [{last_item[0]}] x{last_item[1]}\n")
            else:
                self._text.insert("end", "  -> No loot detected\n")
            self._text.insert("end", "\n")

            # Save the best candidate
            if thresh == 50:
                processed.save(os.path.join(_SCRIPT_DIR, "chat_processed.png"))


if __name__ == "__main__":
    app = RegionSelector()
    app.mainloop()
