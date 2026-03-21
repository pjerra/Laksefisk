"""
Test: Screenshot preview that fits the entire search area in the canvas.

Shows a tkinter window with a black canvas. Captures the WoW search area
and scales it to fit (letterbox) inside the canvas, preserving aspect ratio.
A reticle is drawn at the centre to verify alignment.

Press 'c' to capture, 'q' to quit.
"""

import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wow_screen import WowScreen


def draw_reticle(img: Image.Image, point: tuple) -> Image.Image:
    img = img.copy()
    draw = ImageDraw.Draw(img)
    x, y = point
    if x <= 0 and y <= 0:
        return img
    cs, rs = 15, 40
    c = "white"
    w = 2

    def corner(cx, cy, dx, dy):
        draw.line([(cx + dx, cy), (cx, cy), (cx, cy + dy)], fill=c, width=w)

    corner(x - rs, y - rs, cs, cs)
    corner(x - rs, y + rs, cs, -cs)
    corner(x + rs, y - rs, -cs, cs)
    corner(x + rs, y + rs, -cs, -cs)
    draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=c)
    return img


class FitPreviewTest:
    def __init__(self):
        self._ws = WowScreen()

        self.root = tk.Tk()
        self.root.title("Fit Preview Test")
        self.root.configure(bg="black")
        self.root.geometry("600x300+50+50")
        self.root.attributes("-topmost", True)

        self._photo = None

        # Canvas
        self._canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._img_id = self._canvas.create_image(0, 0, anchor="center")

        # Info label
        self._info = tk.Label(self.root, text="Press 'c' to capture, 'q' to quit",
                              bg="black", fg="white", font=("Consolas", 10))
        self._info.pack(side="bottom", fill="x")

        self._canvas.bind("<Configure>", self._on_resize)
        self.root.bind("<c>", lambda e: self._capture())
        self.root.bind("<q>", lambda e: self.root.destroy())

        self._last_img = None

    def _on_resize(self, event):
        if self._last_img:
            self._display(self._last_img)

    def _capture(self):
        img = self._ws.get_bitmap()
        # Draw reticle at centre of image
        cx, cy = img.width // 2, img.height // 2
        img = draw_reticle(img, (cx, cy))
        self._last_img = img
        self._display(img)
        self._info.config(text=f"Captured: {img.width}x{img.height} → canvas: "
                          f"{self._canvas.winfo_width()}x{self._canvas.winfo_height()}")

    def _display(self, img: Image.Image):
        """Scale image to FIT inside the canvas (letterbox, no cropping)."""
        cw = self._canvas.winfo_width() or 600
        ch = self._canvas.winfo_height() or 300

        iw, ih = img.size
        # Fit: use min scale so entire image is visible
        scale = min(cw / iw, ch / ih)
        new_w = int(iw * scale)
        new_h = int(ih * scale)
        scaled = img.resize((new_w, new_h), Image.LANCZOS)

        self._photo = ImageTk.PhotoImage(scaled)
        self._canvas.coords(self._img_id, cw // 2, ch // 2)
        self._canvas.itemconfig(self._img_id, image=self._photo)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    FitPreviewTest().run()
