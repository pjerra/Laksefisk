from typing import Tuple
import mss
import mss.tools
from PIL import Image


class WowScreen:
    @staticmethod
    def get_bitmap() -> Image.Image:
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            full_w = monitor["width"]
            full_h = monitor["height"]

            # Capture the centre half of the screen (same logic as original C#)
            region = {
                "left": full_w // 4,
                "top": full_h // 4,
                "width": full_w // 2,
                "height": full_h // 2 - 100,
            }
            screenshot = sct.grab(region)
            return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

    @staticmethod
    def get_color_at(pos: Tuple[int, int], bmp: Image.Image) -> Tuple[int, int, int]:
        return bmp.getpixel(pos)[:3]

    @staticmethod
    def get_screen_position_from_bitmap_position(pos: Tuple[int, int]) -> Tuple[int, int]:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            full_w = monitor["width"]
            full_h = monitor["height"]
        return (pos[0] + full_w // 4, pos[1] + full_h // 4)
