"""
Test: Automatic bobber colour calibration via threshold sweeping.

Approach: sweep multiplier and closeness from tight → loose, count matching
pixels at each step. The bobber appears as a jump in matches. Find the
tightest values that still detect the bobber.

Run with WoW open and a fishing bobber visible on screen.
Keys: c=calibrate, a=auto, m=mode, s=sweep, q=quit
"""

import sys
import os
import time
import tkinter as tk
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mss
import win32api
from PIL import Image, ImageDraw, ImageTk

from pixel_classifier import ClassifierMode, PixelClassifier
from wow_process import _human_move_mouse
from wow_screen import WowScreen


# ---------------------------------------------------------------------------
# Screen capture
# ---------------------------------------------------------------------------

def capture_wow_region() -> Image.Image:
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        fw, fh = monitor["width"], monitor["height"]
        region = {
            "left": fw // 4,
            "top": fh // 4,
            "width": fw // 2,
            "height": fh // 2 - 100,
        }
        shot = sct.grab(region)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


# ---------------------------------------------------------------------------
# Sweep calibration
# ---------------------------------------------------------------------------

def extract_pixels(img: Image.Image, step: int = 2) -> List[Tuple[int, int, int]]:
    """Extract all pixel RGB values from image (downsampled by step)."""
    w, h = img.size
    pixels = img.load()
    result = []
    for x in range(0, w, step):
        for y in range(0, h, step):
            result.append(pixels[x, y][:3])
    return result


def sweep_both(pixel_data: List[Tuple[int, int, int]], mode: ClassifierMode,
               mult_values: List[float], close_values: List[float]
               ) -> Tuple[List[Tuple[float, int]], float, List[Tuple[float, int]]]:
    """Single-pass sweep of both parameters using cached pixel data.

    1. Sweep multiplier with loose closeness (5.0) to find optimal mult.
    2. Sweep closeness with found multiplier.

    Returns (mult_results, optimal_mult, close_results).
    """
    is_red = mode == ClassifierMode.Red

    # Pre-compute per-pixel: dominant, other1, other2, min_other, max_other
    precomputed = []
    for r, g, b in pixel_data:
        if is_red:
            dom, o1, o2 = r, g, b
        else:
            dom, o1, o2 = b, r, g
        mn_o = min(o1, o2)
        mx_o = max(o1, o2)
        precomputed.append((dom, o1, o2, mn_o, mx_o))

    # Sweep multiplier (with loose closeness=5.0)
    fixed_close = 5.0
    mult_results = []
    for mult in mult_values:
        count = 0
        for dom, o1, o2, mn_o, mx_o in precomputed:
            # is_bigger: dom * mult > o1 AND dom * mult > o2
            dm = dom * mult
            if dm > o1 and dm > o2:
                # are_close: mn_o * close > mx_o - 20
                if mn_o * fixed_close > mx_o - 20:
                    count += 1
        mult_results.append((mult, count))

    # Find optimal multiplier
    opt_mult = _find_optimal(mult_results, 10)
    if opt_mult is None:
        return mult_results, None, []

    # Sweep closeness with found multiplier
    close_results = []
    for close in close_values:
        count = 0
        for dom, o1, o2, mn_o, mx_o in precomputed:
            dm = dom * opt_mult
            if dm > o1 and dm > o2:
                if mn_o * close > mx_o - 20:
                    count += 1
        close_results.append((close, count))

    return mult_results, opt_mult, close_results


def _find_optimal(sweep_results: List[Tuple[float, int]], min_matches: int = 10) -> Optional[float]:
    """Find the tightest value where matches >= min_matches, plus one step margin."""
    for i, (val, count) in enumerate(sweep_results):
        if count >= min_matches:
            if i + 1 < len(sweep_results):
                return sweep_results[i + 1][0]
            return val
    return None


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

BAR_HEIGHT = 12
GRAPH_W = 500
GRAPH_H = 120

class CalibrationTestWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bobber Calibration — Sweep Mode")
        self.configure(bg="#1e1e1e")
        self.attributes("-topmost", True)
        self.resizable(True, True)

        self._mode = ClassifierMode.Red
        self._auto_mode = False
        self._auto_interval = 3000

        # Current classifier values
        self._mult = 0.5
        self._close = 2.0

        # Sweep ranges
        self._mult_values = [round(0.05 + i * 0.05, 2) for i in range(40)]   # 0.05 → 2.0
        self._close_values = [round(0.2 + i * 0.1, 1) for i in range(50)]    # 0.2 → 5.1

        # Sweep results
        self._mult_results: List[Tuple[float, int]] = []
        self._close_results: List[Tuple[float, int]] = []

        # --- Controls ---
        ctrl = tk.Frame(self, bg="#1e1e1e")
        ctrl.pack(fill="x", padx=8, pady=4)

        btn_kw = {"bg": "#333", "fg": "white", "relief": "flat", "padx": 8, "pady": 4}

        tk.Button(ctrl, text="Sweep (s)", command=self._sweep, **btn_kw).pack(side="left", padx=2)

        self._auto_btn = tk.Button(ctrl, text="Auto: OFF (a)", command=self._toggle_auto, **btn_kw)
        self._auto_btn.pack(side="left", padx=2)

        self._mode_btn = tk.Button(ctrl, text="Mode: RED", command=self._toggle_mode, **btn_kw)
        self._mode_btn.pack(side="left", padx=2)

        self._live_btn = tk.Button(ctrl, text="Live: OFF (l)", command=self._toggle_live, **btn_kw)
        self._live_btn.pack(side="left", padx=2)

        tk.Button(ctrl, text="Verify (v)", command=self._verify_bobber, **btn_kw).pack(side="left", padx=2)

        tk.Button(ctrl, text="Quit (q)", command=self.destroy, **btn_kw).pack(side="right", padx=2)

        # --- Current values display ---
        val_frame = tk.Frame(self, bg="#1e1e1e")
        val_frame.pack(fill="x", padx=8, pady=2)

        self._val_label = tk.Label(val_frame, text="multiplier=—  closeness=—  matches=—",
                                    bg="#1e1e1e", fg="#0f0", font=("Consolas", 11, "bold"),
                                    anchor="w")
        self._val_label.pack(fill="x")

        # --- Multiplier sweep graph ---
        tk.Label(self, text="Multiplier sweep (tight → loose):",
                 bg="#1e1e1e", fg="#888", font=("Consolas", 9), anchor="w").pack(fill="x", padx=8)
        self._mult_canvas = tk.Canvas(self, width=GRAPH_W, height=GRAPH_H,
                                       bg="#111", highlightthickness=0)
        self._mult_canvas.pack(padx=8, pady=2)
        self._mult_info = tk.Label(self, text="", bg="#1e1e1e", fg="#aaa",
                                    font=("Consolas", 9), anchor="w")
        self._mult_info.pack(fill="x", padx=8)

        # --- Closeness sweep graph ---
        tk.Label(self, text="Closeness sweep (tight → loose):",
                 bg="#1e1e1e", fg="#888", font=("Consolas", 9), anchor="w").pack(fill="x", padx=8)
        self._close_canvas = tk.Canvas(self, width=GRAPH_W, height=GRAPH_H,
                                        bg="#111", highlightthickness=0)
        self._close_canvas.pack(padx=8, pady=2)
        self._close_info = tk.Label(self, text="", bg="#1e1e1e", fg="#aaa",
                                     font=("Consolas", 9), anchor="w")
        self._close_info.pack(fill="x", padx=8)

        # --- Screenshot preview ---
        self._preview_canvas = tk.Canvas(self, width=600, height=250, bg="#111", highlightthickness=0)
        self._preview_canvas.pack(padx=8, pady=4)
        self._preview_photo = None
        self._preview_img = self._preview_canvas.create_image(0, 0, anchor="nw")

        # --- Status ---
        self._status = tk.Label(self, text="Press 's' to sweep or 'a' for auto mode",
                                 bg="#1e1e1e", fg="#888", font=("Consolas", 9))
        self._status.pack(fill="x", padx=8, pady=4)

        # --- Live mode ---
        self._live_mode = False
        self._live_interval = 200  # ms

        # Keybinds
        self.bind("<s>", lambda e: self._sweep())
        self.bind("<c>", lambda e: self._sweep())
        self.bind("<a>", lambda e: self._toggle_auto())
        self.bind("<l>", lambda e: self._toggle_live())
        self.bind("<v>", lambda e: self._verify_bobber())
        self.bind("<m>", lambda e: self._toggle_mode())
        self.bind("<q>", lambda e: self.destroy())
        self.bind("<Escape>", lambda e: self.destroy())

    def _toggle_mode(self):
        self._mode = ClassifierMode.Blue if self._mode == ClassifierMode.Red else ClassifierMode.Red
        name = "RED" if self._mode == ClassifierMode.Red else "BLUE"
        self._mode_btn.config(text=f"Mode: {name}")
        self._status.config(text=f"Switched to {name} mode")

    def _toggle_auto(self):
        self._auto_mode = not self._auto_mode
        self._auto_btn.config(text=f"Auto: {'ON' if self._auto_mode else 'OFF'} (a)")
        if self._auto_mode:
            self._status.config(text="Auto sweep ON — every 3s")
            self._auto_tick()
        else:
            self._status.config(text="Auto sweep OFF")

    def _auto_tick(self):
        if not self._auto_mode:
            return
        self._sweep()
        self.after(self._auto_interval, self._auto_tick)

    def _toggle_live(self):
        self._live_mode = not self._live_mode
        self._live_btn.config(text=f"Live: {'ON' if self._live_mode else 'OFF'} (l)")
        if self._live_mode:
            self._status.config(text="Live preview ON", fg="#0ff")
            self._live_tick()
        else:
            self._status.config(text="Live preview OFF")

    def _live_tick(self):
        if not self._live_mode:
            return
        t0 = time.perf_counter()
        img = capture_wow_region()

        pc = PixelClassifier()
        pc.mode = self._mode
        pc.colour_multiplier = self._mult
        pc.colour_closeness_multiplier = self._close

        self._show_preview(img, pc)
        elapsed = (time.perf_counter() - t0) * 1000
        self._status.config(
            text=f"Live | mult={self._mult:.2f} close={self._close:.1f} | {elapsed:.0f}ms",
            fg="#0ff"
        )
        self.after(self._live_interval, self._live_tick)

    def _find_all_clusters(self, img: Image.Image, pc: PixelClassifier,
                            min_size: int = 5) -> List[dict]:
        """Find all matching clusters, ranked by size (largest first).

        Returns list of dicts: {center: (x,y), count: int, points: [(x,y)]}
        """
        w, h = img.size
        pixels = img.load()
        matched = []
        for x in range(0, w, 2):
            for y in range(0, h, 2):
                r, g, b = pixels[x, y][:3]
                if pc.is_match(r, g, b):
                    matched.append((x, y))
        if len(matched) < min_size:
            return []

        # Group into clusters using simple flood-fill on sorted points
        used = set()
        clusters = []
        radius = 35

        for px, py in matched:
            if (px, py) in used:
                continue
            # Collect all nearby points into this cluster
            cluster_pts = []
            queue = [(px, py)]
            while queue:
                qx, qy = queue.pop()
                if (qx, qy) in used:
                    continue
                used.add((qx, qy))
                cluster_pts.append((qx, qy))
                # Find neighbours
                for mx, my in matched:
                    if (mx, my) not in used and abs(mx - qx) < radius and abs(my - qy) < radius:
                        queue.append((mx, my))

            if len(cluster_pts) >= min_size:
                avg_x = sum(x for x, _ in cluster_pts) // len(cluster_pts)
                avg_y = sum(y for _, y in cluster_pts) // len(cluster_pts)
                clusters.append({
                    "center": (avg_x, avg_y),
                    "count": len(cluster_pts),
                    "points": cluster_pts,
                })

        # Sort by size, largest first
        clusters.sort(key=lambda c: c["count"], reverse=True)
        return clusters

    def _count_cluster_matches(self, img: Image.Image, pc: PixelClassifier,
                                center: Tuple[int, int], radius: int = 35) -> int:
        """Count matches near a known cluster center."""
        cx, cy = center
        pixels = img.load()
        count = 0
        for x in range(max(0, cx - radius), min(img.size[0], cx + radius)):
            for y in range(max(0, cy - radius), min(img.size[1], cy + radius)):
                r, g, b = pixels[x, y][:3]
                if pc.is_match(r, g, b):
                    count += 1
        return count

    def _read_bobber_tooltip_flag(self) -> bool:
        """Read pixel 16 B channel from the addon pixel bridge — True if mouseover is bobber."""
        from pixel_bridge import PixelBridge
        bridge = PixelBridge()
        data = bridge.read()
        if data is None:
            return False
        # Pixel 16 B = mouseover bobber flag
        # We need to read raw pixel 16 B. The bridge doesn't expose it yet,
        # so read it directly from screen.
        pixels = bridge._last_pixels
        if pixels and len(pixels) > 16:
            _, _, b = pixels[16]
            return b > 128
        return False

    def _read_tooltip_from_screen(self) -> bool:
        """Read pixel 16 B directly from the screen pixel bar."""
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            fw = monitor["width"]
            # Pixel bar is at bottom-centre, Y offset 120 from bottom
            # Each pixel is 5x5, pixel 16 starts at offset 16*5 = 80 from bar start
            total_w = 20 * 5  # NUM_PIXELS * PIXEL_SIZE
            bar_start_x = (fw - total_w) // 2
            px_x = bar_start_x + 16 * 5 + 2  # center of pixel 16
            px_y = monitor["height"] - 120 + 2  # center of the pixel row
            region = {"left": px_x, "top": px_y, "width": 1, "height": 1}
            shot = sct.grab(region)
            # mss returns BGRA
            b = shot.pixel(0, 0)[0]  # B channel (BGRA order)
            r = shot.pixel(0, 0)[2]  # R channel
            g = shot.pixel(0, 0)[1]  # G channel
            return b > 128

    def _verify_bobber(self):
        """Verify bobber by moving mouse to each cluster and checking tooltip via addon."""
        pc = PixelClassifier()
        pc.mode = self._mode
        pc.colour_multiplier = self._mult
        pc.colour_closeness_multiplier = self._close

        self._status.config(text="Capturing clusters...", fg="#ff0")
        self.update()

        img = capture_wow_region()
        clusters = self._find_all_clusters(img, pc)

        if not clusters:
            self._status.config(text="Verify failed — no clusters found", fg="#f44")
            self._show_preview(img, pc)
            return

        # Sort clusters by distance from image center (closest first)
        img_cx, img_cy = img.size[0] // 2, img.size[1] // 2
        clusters.sort(key=lambda c: (c["center"][0] - img_cx) ** 2 + (c["center"][1] - img_cy) ** 2)

        old_pos = win32api.GetCursorPos()
        total_clusters = len(clusters)

        for i, cluster in enumerate(clusters):
            center = cluster["center"]

            self._status.config(
                text=f"Testing cluster {i+1}/{total_clusters} "
                     f"({cluster['count']} px) at ({center[0]},{center[1]})...",
                fg="#ff0"
            )
            self.update()

            # Move mouse to cluster with human-like movement
            screen_pos = WowScreen.get_screen_position_from_bitmap_position(center)
            current_pos = win32api.GetCursorPos()
            _human_move_mouse(current_pos, screen_pos)
            time.sleep(0.3)  # wait for tooltip to appear + addon to update pixel

            # Check addon tooltip flag
            is_bobber = self._read_tooltip_from_screen()

            if is_bobber:
                # Recapture with hover highlight for preview
                img2 = capture_wow_region()
                current_pos = win32api.GetCursorPos()
                _human_move_mouse(current_pos, old_pos)
                self._show_preview(img2, pc)
                img.close()
                self._status.config(
                    text=f"BOBBER FOUND (cluster {i+1}/{total_clusters}) | "
                         f"tooltip confirmed at ({center[0]},{center[1]})",
                    fg="#0f0"
                )
                return

            self._status.config(
                text=f"Cluster {i+1}/{total_clusters}: NOT bobber — trying next...",
                fg="#fa0"
            )
            self.update()

        # None passed — move mouse back
        current_pos = win32api.GetCursorPos()
        _human_move_mouse(current_pos, old_pos)
        self._show_preview(img, pc)
        self._status.config(
            text=f"NO BOBBER FOUND — tested {total_clusters} cluster(s)",
            fg="#f44"
        )

    def _sweep(self):
        self._status.config(text="Sweeping...", fg="#ff0")
        self.update()

        t0 = time.perf_counter()
        img = capture_wow_region()

        # Extract pixels once (downsampled 2x for speed)
        pixel_data = extract_pixels(img, step=2)
        t_extract = time.perf_counter()

        # Sweep both parameters in one go
        self._mult_results, opt_mult, self._close_results = sweep_both(
            pixel_data, self._mode, self._mult_values, self._close_values
        )

        if opt_mult is None:
            elapsed = (time.perf_counter() - t0) * 1000
            self._status.config(text=f"No bobber found ({elapsed:.0f}ms)", fg="#f44")
            self._draw_graph(self._mult_canvas, self._mult_results, None, "mult")
            self._mult_info.config(text="No matching pixels at any multiplier value")
            self._close_info.config(text="Skipped — no multiplier found")
            self._show_preview(img, None)
            return

        opt_close = _find_optimal(self._close_results, 10)
        if opt_close is None:
            opt_close = 2.0

        self._mult = opt_mult
        self._close = opt_close

        elapsed = (time.perf_counter() - t0) * 1000
        extract_ms = (t_extract - t0) * 1000

        # Show preview with optimal values
        pc = PixelClassifier()
        pc.mode = self._mode
        pc.colour_multiplier = opt_mult
        pc.colour_closeness_multiplier = opt_close

        self._draw_graph(self._mult_canvas, self._mult_results, opt_mult, "mult")
        self._mult_info.config(
            text=f"Optimal: {opt_mult:.2f}  (sweep with closeness=5.0)"
        )

        self._draw_graph(self._close_canvas, self._close_results, opt_close, "close")
        self._close_info.config(
            text=f"Optimal: {opt_close:.1f}  (sweep with multiplier={opt_mult:.2f})"
        )

        self._show_preview(img, pc)

        self._status.config(
            text=f"Sweep done in {elapsed:.0f}ms (capture: {extract_ms:.0f}ms) — "
                 f"mult={opt_mult:.2f} close={opt_close:.1f}",
            fg="#0f0"
        )

    def _draw_graph(self, canvas: tk.Canvas, results: List[Tuple[float, int]],
                    optimal: Optional[float], label: str):
        """Draw a bar chart of sweep results."""
        canvas.delete("all")
        if not results:
            return

        w = GRAPH_W
        h = GRAPH_H
        n = len(results)
        max_count = max(c for _, c in results) or 1
        bar_w = max(1, (w - 20) // n)

        # Draw bars
        for i, (val, count) in enumerate(results):
            x = 10 + i * bar_w
            bar_h = int((count / max_count) * (h - 25))

            # Colour: grey if before optimal, green at/after optimal
            if optimal is not None and val >= optimal:
                colour = "#2d8" if count > 0 else "#1a5"
            else:
                colour = "#555" if count > 0 else "#333"

            # Highlight the optimal bar
            if optimal is not None and abs(val - optimal) < 0.001:
                colour = "#0f0"

            canvas.create_rectangle(x, h - 5 - bar_h, x + bar_w - 1, h - 5,
                                     fill=colour, outline="")

        # Draw optimal line
        if optimal is not None:
            for i, (val, _) in enumerate(results):
                if abs(val - optimal) < 0.001:
                    x = 10 + i * bar_w + bar_w // 2
                    canvas.create_line(x, 0, x, h, fill="#ff0", width=1, dash=(3, 3))
                    canvas.create_text(x, 3, text=f"{optimal}", fill="#ff0",
                                        font=("Consolas", 8), anchor="n")
                    break

        # Draw match count labels for key bars
        label_step = max(1, n // 8)
        for i in range(0, n, label_step):
            val, count = results[i]
            x = 10 + i * bar_w + bar_w // 2
            if count > 0:
                canvas.create_text(x, h - 8 - int((count / max_count) * (h - 25)),
                                    text=str(count), fill="#aaa", font=("Consolas", 7), anchor="s")
            # Value label at bottom
            canvas.create_text(x, h - 1, text=f"{val:.1f}", fill="#666",
                                font=("Consolas", 7), anchor="s")

    def _show_preview(self, img: Image.Image, pc: Optional[PixelClassifier]):
        """Show screenshot with matched pixels highlighted and bounding box."""
        preview = img.copy()
        match_count = 0
        if pc:
            pixels = preview.load()
            w, h = preview.size
            # Collect all matched pixel positions
            matched: List[Tuple[int, int]] = []
            for x in range(w):
                for y in range(h):
                    r, g, b = pixels[x, y][:3]
                    if pc.is_match(r, g, b):
                        pixels[x, y] = (0, 255, 0)
                        matched.append((x, y))
            match_count = len(matched)

            # Find densest cluster for bounding box
            if match_count > 0:
                # Score a sample of points by neighbour density
                step = max(1, len(matched) // 100)
                sampled = matched[::step]
                best_score = 0
                best_pt = matched[0]
                for px, py in sampled:
                    score = sum(1 for mx, my in matched
                                if abs(mx - px) < 25 and abs(my - py) < 25)
                    if score > best_score:
                        best_score = score
                        best_pt = (px, py)

                # Collect cluster pixels near best point
                cx, cy = best_pt
                cluster = [(x, y) for x, y in matched
                           if abs(x - cx) < 35 and abs(y - cy) < 35]

                if cluster:
                    cl_min_x = min(x for x, _ in cluster)
                    cl_max_x = max(x for x, _ in cluster)
                    cl_min_y = min(y for _, y in cluster)
                    cl_max_y = max(y for _, y in cluster)

                    draw = ImageDraw.Draw(preview)
                    pad = 8
                    draw.rectangle(
                        [(cl_min_x - pad, cl_min_y - pad), (cl_max_x + pad, cl_max_y + pad)],
                        outline="#ffff00", width=2
                    )
                    draw.text((cl_min_x - pad, cl_min_y - pad - 12),
                              f"{len(cluster)}/{match_count}", fill="#ffff00")

        cw, ch = 600, 250
        resized = preview.resize((cw, ch), Image.NEAREST)
        self._preview_photo = ImageTk.PhotoImage(resized)
        self._preview_canvas.itemconfig(self._preview_img, image=self._preview_photo)

        # Update value label with live match count
        self._val_label.config(
            text=f"multiplier={self._mult:.2f}  closeness={self._close:.1f}  matches={match_count}"
        )

        preview.close()
        img.close()


if __name__ == "__main__":
    app = CalibrationTestWindow()
    app.mainloop()
