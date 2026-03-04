import logging
import time
from abc import ABC, abstractmethod
from typing import Callable, List, Optional, Tuple

from PIL import Image

from models import BobberBitmapEvent
from pixel_classifier import ClassifierMode, PixelClassifier
from wow_screen import WowScreen

EMPTY = (0, 0)
logger = logging.getLogger("Laksefisk")


class IBobberFinder(ABC):
    @abstractmethod
    def find(self) -> Tuple[int, int]:
        ...

    @abstractmethod
    def reset(self):
        ...


# ---------------------------------------------------------------------------
# SearchBobberFinder — finds the bobber by scanning for red/blue pixels
# ---------------------------------------------------------------------------

class SearchBobberFinder(IBobberFinder):
    def __init__(self, pixel_classifier: PixelClassifier):
        self.pixel_classifier = pixel_classifier
        self._previous_location: Tuple[int, int] = EMPTY
        self._bitmap: Optional[Image.Image] = None
        self.bitmap_callbacks: List[Callable[[BobberBitmapEvent], None]] = []

    def reset(self):
        self._previous_location = EMPTY

    def find(self) -> Tuple[int, int]:
        self._bitmap = WowScreen.get_bitmap()

        best = self._score_points(self._find_red_points())

        if self._previous_location != EMPTY and best is None:
            self._previous_location = EMPTY
            best = self._score_points(self._find_red_points())

        self._previous_location = EMPTY
        if best is not None:
            self._previous_location = best

        event = BobberBitmapEvent(
            point=(self._previous_location[0], self._previous_location[1]),
            bitmap=self._bitmap,
        )
        for cb in self.bitmap_callbacks:
            cb(event)

        if self._bitmap:
            self._bitmap.close()

        if self._previous_location == EMPTY:
            return EMPTY
        return WowScreen.get_screen_position_from_bitmap_position(self._previous_location)

    def _find_red_points(self) -> List[Tuple[int, int]]:
        points: List[Tuple[int, int]] = []
        bmp = self._bitmap
        has_prev = self._previous_location != EMPTY

        w, h = bmp.size
        min_x = max(self._previous_location[0] - 40 if has_prev else 0, 0)
        max_x = min(self._previous_location[0] + 40 if has_prev else w, w)
        min_y = max(self._previous_location[1] - 40 if has_prev else 0, 0)
        max_y = min(self._previous_location[1] + 40 if has_prev else h, h)

        t0 = time.perf_counter()

        pixels = bmp.load()
        for x in range(min_x, max_x):
            for y in range(min_y, max_y):
                r, g, b = pixels[x, y][:3]
                if self.pixel_classifier.is_match(r, g, b):
                    points.append((x, y))
                    highlight = (0, 0, 255) if self.pixel_classifier.mode == ClassifierMode.Blue else (255, 0, 0)
                    pixels[x, y] = highlight

        elapsed_ms = (time.perf_counter() - t0) * 1000
        if elapsed_ms > 200:
            logger.debug(f"Feather points found: {len(points)} in {elapsed_ms:.0f}ms")

        if len(points) > 1000:
            logger.error("Too much of the feather colour in this image — adjust colour configuration!")
            points.clear()

        return points

    @staticmethod
    def _score_points(points: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        if not points:
            return None

        scored = []
        for p in points:
            count = sum(
                1 for s in points
                if abs(s[0] - p[0]) < 10 and abs(s[1] - p[1]) < 10
            )
            scored.append((count, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1] if scored else None


# ---------------------------------------------------------------------------
# BobberColourPointFinder — simpler finder using a target colour directly
# ---------------------------------------------------------------------------

class BobberColourPointFinder(IBobberFinder):
    TARGET_OFFSET = 15

    def __init__(self, target_color: Tuple[int, int, int]):
        self.target_color = target_color
        self._bitmap: Optional[Image.Image] = None
        self.bitmap_callbacks: List[Callable[[BobberBitmapEvent], None]] = []

    def reset(self):
        pass

    def find(self) -> Tuple[int, int]:
        self._bitmap = WowScreen.get_bitmap()
        bmp = self._bitmap

        tr, tg, tb = self.target_color
        off = self.TARGET_OFFSET
        rl, rh = tr - off, tr + off
        gl, gh = tg - off, tg + off
        bl, bh = tb - off, tb + off

        w, h = bmp.size
        pixels = bmp.load()

        for x in range(w):
            for y in range(h):
                r, g, b = pixels[x, y][:3]
                if rl < r < rh and gl < g < gh and bl < b < bh:
                    event = BobberBitmapEvent(point=(x, y), bitmap=bmp)
                    for cb in self.bitmap_callbacks:
                        cb(event)
                    return WowScreen.get_screen_position_from_bitmap_position((x, y))

        event = BobberBitmapEvent(point=EMPTY, bitmap=bmp)
        for cb in self.bitmap_callbacks:
            cb(event)
        bmp.close()
        return EMPTY

    def get_bitmap(self) -> Optional[Image.Image]:
        return self._bitmap
