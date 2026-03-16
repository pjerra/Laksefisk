"""
Automatic bobber colour calibration.

Sweep-based: extracts all pixels once, then sweeps multiplier and closeness
values to find the tightest thresholds that still detect the bobber.
"""

import logging
import time
from typing import List, Optional, Tuple

from PIL import Image

from pixel_classifier import ClassifierMode, PixelClassifier
from wow_screen import WowScreen

logger = logging.getLogger("Laksefisk")


def _extract_pixels(img: Image.Image, step: int = 2) -> List[Tuple[int, int, int]]:
    """Extract pixel RGB values from image (downsampled by step for speed)."""
    w, h = img.size
    pixels = img.load()
    result = []
    for x in range(0, w, step):
        for y in range(0, h, step):
            result.append(pixels[x, y][:3])
    return result


def _precompute(pixel_data: List[Tuple[int, int, int]], is_red: bool):
    """Pre-compute dominant/other channels for fast sweeping."""
    result = []
    for r, g, b in pixel_data:
        if is_red:
            dom, o1, o2 = r, g, b
        else:
            dom, o1, o2 = b, r, g
        result.append((dom, o1, o2, min(o1, o2), max(o1, o2)))
    return result


def _count_at(precomputed, mult: float, close: float) -> int:
    """Count matching pixels for given multiplier and closeness."""
    count = 0
    for dom, o1, o2, mn_o, mx_o in precomputed:
        dm = dom * mult
        if dm > o1 and dm > o2:
            if mn_o * close > mx_o - 20:
                count += 1
    return count


def _find_optimal(results: List[Tuple[float, int]], min_matches: int = 10, margin_steps: int = 4) -> Optional[float]:
    """Find tightest value where matches >= min_matches, plus margin steps."""
    for i, (val, count) in enumerate(results):
        if count >= min_matches:
            idx = min(i + margin_steps, len(results) - 1)
            return results[idx][0]
    return None


def sweep_calibrate(pixel_classifier: PixelClassifier) -> bool:
    """Sweep-based calibration: capture screen, find optimal thresholds.

    Updates the pixel_classifier in-place. Returns True on success.
    """
    is_red = pixel_classifier.mode == ClassifierMode.Red
    mode_name = "red" if is_red else "blue"

    t0 = time.perf_counter()
    img = WowScreen.get_bitmap()
    pixel_data = _extract_pixels(img, step=2)
    img.close()

    precomputed = _precompute(pixel_data, is_red)

    # Sweep multiplier with loose closeness (5.0)
    mult_values = [round(0.05 + i * 0.05, 2) for i in range(40)]  # 0.05 → 2.0
    mult_results = []
    for mult in mult_values:
        count = _count_at(precomputed, mult, 5.0)
        mult_results.append((mult, count))

    opt_mult = _find_optimal(mult_results, min_matches=10)
    if opt_mult is None:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.warning(f"Calibration: no {mode_name} bobber found ({elapsed:.0f}ms)")
        return False

    # Sweep closeness with found multiplier
    close_values = [round(0.2 + i * 0.1, 1) for i in range(50)]  # 0.2 → 5.1
    close_results = []
    for close in close_values:
        count = _count_at(precomputed, opt_mult, close)
        close_results.append((close, count))

    opt_close = _find_optimal(close_results, min_matches=10)
    if opt_close is None:
        opt_close = 2.0

    elapsed = (time.perf_counter() - t0) * 1000

    # Apply
    pixel_classifier.colour_multiplier = opt_mult
    pixel_classifier.colour_closeness_multiplier = opt_close

    final_matches = _count_at(precomputed, opt_mult, opt_close)
    logger.info(
        f"Calibrated in {elapsed:.0f}ms — "
        f"mult={opt_mult:.2f} close={opt_close:.1f} "
        f"matches={final_matches}"
    )
    return True


def calibrate_now(pixel_classifier: PixelClassifier) -> Optional[dict]:
    """One-shot calibration (legacy). Calls sweep_calibrate internally."""
    success = sweep_calibrate(pixel_classifier)
    if success:
        return {
            "colour_multiplier": pixel_classifier.colour_multiplier,
            "colour_closeness_multiplier": pixel_classifier.colour_closeness_multiplier,
        }
    return None
