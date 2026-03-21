"""
Automatic bobber colour calibration.

Multi-frame stability sweep: captures 6 frames, sweeps multiplier and closeness
values, picks thresholds with lowest centroid variance across frames.
"""

import logging
import time
from typing import List, Optional, Tuple

from PIL import Image

from pixel_classifier import ClassifierMode, PixelClassifier
from wow_screen import WowScreen

logger = logging.getLogger("Laksefisk")


def _extract_pixels(img: Image.Image, step: int = 2) -> List[Tuple[int, int, int, int, int]]:
    """Extract pixel (r, g, b, x, y) tuples from image (downsampled by step)."""
    w, h = img.size
    pixels = img.load()
    result = []
    for x in range(0, w, step):
        for y in range(0, h, step):
            r, g, b = pixels[x, y][:3]
            result.append((r, g, b, x, y))
    return result


def _precompute(pixel_data: List[Tuple[int, int, int, int, int]], is_red: bool):
    """Pre-compute dominant/other channels with positions for fast sweeping."""
    result = []
    for r, g, b, x, y in pixel_data:
        if is_red:
            dom, o1, o2 = r, g, b
        else:
            dom, o1, o2 = b, r, g
        result.append((dom, o1, o2, min(o1, o2), max(o1, o2), x, y))
    return result


def _centroid_at(precomputed, mult: float, close: float) -> Optional[Tuple[float, float, int]]:
    """Compute centroid of matching pixels. Returns (cx, cy, count) or None."""
    sum_x = 0.0
    sum_y = 0.0
    count = 0
    for dom, o1, o2, mn_o, mx_o, x, y in precomputed:
        dm = dom * mult
        if dm > o1 and dm > o2:
            if mn_o * close > mx_o - 20:
                sum_x += x
                sum_y += y
                count += 1
    if count < 10 or count > 500:
        return None
    return (sum_x / count, sum_y / count, count)


def _centroid_variance(centroids: List[Tuple[float, float, int]]) -> float:
    """Mean squared distance from mean centroid. Lower = more stable."""
    n = len(centroids)
    mx = sum(c[0] for c in centroids) / n
    my = sum(c[1] for c in centroids) / n
    return sum((c[0] - mx) ** 2 + (c[1] - my) ** 2 for c in centroids) / n


def _stability_score(frames, mult: float, close: float) -> Optional[float]:
    """Score stability across frames. Returns variance or None if too few valid."""
    centroids = []
    for frame in frames:
        c = _centroid_at(frame, mult, close)
        if c is not None:
            centroids.append(c)
    if len(centroids) < 4:
        return None
    return _centroid_variance(centroids)


def _fallback_single_frame(precomputed, mult_values, close_values):
    """Fallback: single-frame first-match logic (old behavior on frame 0)."""
    opt_mult = None
    for i, mult in enumerate(mult_values):
        count = 0
        for dom, o1, o2, mn_o, mx_o, x, y in precomputed:
            dm = dom * mult
            if dm > o1 and dm > o2:
                if mn_o * 5.0 > mx_o - 20:
                    count += 1
        if count >= 10:
            idx = min(i + 4, len(mult_values) - 1)
            opt_mult = mult_values[idx]
            break
    if opt_mult is None:
        return None

    opt_close = None
    for i, close in enumerate(close_values):
        count = 0
        for dom, o1, o2, mn_o, mx_o, x, y in precomputed:
            dm = dom * opt_mult
            if dm > o1 and dm > o2:
                if mn_o * close > mx_o - 20:
                    count += 1
        if count >= 10:
            idx = min(i + 4, len(close_values) - 1)
            opt_close = close_values[idx]
            break
    if opt_close is None:
        opt_close = 1.0

    return (opt_mult, opt_close)


def sweep_calibrate(pixel_classifier: PixelClassifier) -> bool:
    """Multi-frame stability calibration.

    Captures 6 frames, sweeps multiplier and closeness values,
    picks thresholds with lowest centroid variance across frames.
    Updates the pixel_classifier in-place. Returns True on success.
    """
    is_red = pixel_classifier.mode == ClassifierMode.Red
    mode_name = "red" if is_red else "blue"

    t0 = time.perf_counter()

    # Phase 0 — Capture 6 frames
    frames_data = []
    for i in range(6):
        img = WowScreen.get_bitmap()
        pixels = _extract_pixels(img, step=2)
        frames_data.append(_precompute(pixels, is_red))
        img.close()
        if i < 5:
            time.sleep(0.2)

    # Sweep ranges
    mult_values = [round(0.05 + i * 0.05, 2) for i in range(40)]   # 0.05 → 2.0
    close_values = [round(0.2 + i * 0.1, 1) for i in range(50)]    # 0.2 → 5.1

    # Phase 1 — Sweep multiplier (loose closeness=5.0)
    best_mult = None
    best_mult_score = None
    for mult in mult_values:
        # Quick filter: frame 0 must have valid centroid
        if _centroid_at(frames_data[0], mult, 5.0) is None:
            continue
        score = _stability_score(frames_data, mult, 5.0)
        if score is not None:
            if best_mult_score is None or score < best_mult_score:
                best_mult_score = score
                best_mult = mult

    if best_mult is None:
        # Fallback to single-frame logic on frame 0
        fallback = _fallback_single_frame(frames_data[0], mult_values, close_values)
        if fallback is None:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.warning(f"Calibration: no {mode_name} bobber found ({elapsed:.0f}ms)")
            return False
        opt_mult, opt_close = fallback
        elapsed = (time.perf_counter() - t0) * 1000
        pixel_classifier.colour_multiplier = opt_mult
        pixel_classifier.colour_closeness_multiplier = opt_close
        logger.info(
            f"Calibrated (fallback) in {elapsed:.0f}ms — "
            f"mult={opt_mult:.2f} close={opt_close:.1f}"
        )
        return True

    # Phase 2 — Sweep closeness with found multiplier
    best_close = None
    best_close_score = None
    for close in close_values:
        if _centroid_at(frames_data[0], best_mult, close) is None:
            continue
        score = _stability_score(frames_data, best_mult, close)
        if score is not None:
            if best_close_score is None or score < best_close_score:
                best_close_score = score
                best_close = close

    if best_close is None:
        best_close = 1.0
        best_close_score = None

    # Phase 3 — Apply
    pixel_classifier.colour_multiplier = best_mult
    pixel_classifier.colour_closeness_multiplier = best_close

    elapsed = (time.perf_counter() - t0) * 1000
    final_centroid = _centroid_at(frames_data[0], best_mult, best_close)
    final_matches = final_centroid[2] if final_centroid else 0
    variance_str = f"{best_close_score:.1f}" if best_close_score is not None else "n/a"

    logger.info(
        f"Calibrated in {elapsed:.0f}ms — "
        f"mult={best_mult:.2f} close={best_close:.1f} "
        f"matches={final_matches} variance={variance_str}"
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
