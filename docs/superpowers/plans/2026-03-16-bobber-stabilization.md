# Bobber Tracking Stabilization — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three bobber tracking issues: initial lock-on targeting feather tip, missed bites from EMA dampening, and false-positive jumping when colour thresholds are loose.

**Architecture:** Replace instant X-lock with a warm-up period (median of first N frames). Split stabilized position (for preview/click) from raw position (for bite detection). Tighten search window once locked on.

**Tech Stack:** Python, existing bobber_finder.py / fishing_bot.py / bite_watcher.py

---

## File Structure

- **Modify:** `bobber_finder.py` — warm-up logic, tighter search window, expose raw Y
- **Modify:** `fishing_bot.py` — pass raw Y to bite watcher, smoothed position for loot click
- **Modify:** `models.py` — add `raw_point` to BobberBitmapEvent (optional, for bite watcher)

No new files needed.

---

## Chunk 1: All Changes

### Task 1: Warm-up period before locking X

**Files:**
- Modify: `bobber_finder.py:12-14` (constants), `bobber_finder.py:32-91` (SearchBobberFinder)

**Problem:** X locks on frame 1, which may be the feather tip. Need to collect a few frames and lock to the median.

- [ ] **Step 1: Update constants and init**

In `bobber_finder.py`, change constants and add warm-up state:

```python
SMOOTH_ALPHA = 0.6    # EMA factor — raised from 0.4 for faster bite response
MAX_JUMP = 30         # pixels — ignore detections further than this from smoothed position
WARMUP_FRAMES = 4     # frames to collect before locking X
LOCKED_SEARCH = 15    # pixels — tighter search window once locked
```

In `__init__`, add:
```python
self._warmup_xs: List[int] = []
self._warmup_ys: List[int] = []
self._raw_y: Optional[int] = None    # unsmoothed Y for bite detection
```

In `reset`, clear them:
```python
self._warmup_xs.clear()
self._warmup_ys.clear()
self._raw_y = None
```

- [ ] **Step 2: Rewrite `_stabilize` with warm-up**

Replace `_stabilize` in `bobber_finder.py:74-91`:

```python
def _stabilize(self, raw: Tuple[int, int]) -> Tuple[int, int]:
    rx, ry = raw
    self._raw_y = ry  # always store raw Y for bite detection

    # Still in warm-up phase — collect frames
    if self._locked_x is None:
        self._warmup_xs.append(rx)
        self._warmup_ys.append(ry)
        if len(self._warmup_xs) < WARMUP_FRAMES:
            return raw  # return raw during warm-up
        # Warm-up complete — lock X to median, init smooth Y
        sorted_xs = sorted(self._warmup_xs)
        self._locked_x = sorted_xs[len(sorted_xs) // 2]
        self._smooth_y = float(sorted(self._warmup_ys)[len(self._warmup_ys) // 2])
        return (self._locked_x, round(self._smooth_y))

    # Check if detection jumped too far — likely noise
    if abs(ry - self._smooth_y) > MAX_JUMP:
        self._locked_x = None
        self._smooth_y = None
        self._warmup_xs.clear()
        self._warmup_ys.clear()
        return raw

    # Apply EMA to Y, keep X locked
    self._smooth_y = SMOOTH_ALPHA * ry + (1 - SMOOTH_ALPHA) * self._smooth_y
    return (self._locked_x, round(self._smooth_y))
```

- [ ] **Step 3: Tighten search window once locked**

In `_find_red_points` (`bobber_finder.py:93-123`), change the search radius when locked:

Replace the search window calculation (lines 98-102):
```python
w, h = bmp.size
if has_prev and self._locked_x is not None:
    # Locked on — tight search window
    radius = LOCKED_SEARCH
else:
    radius = 40

min_x = max(self._previous_location[0] - radius if has_prev else 0, 0)
max_x = min(self._previous_location[0] + radius if has_prev else w, w)
min_y = max(self._previous_location[1] - radius if has_prev else 0, 0)
max_y = min(self._previous_location[1] + radius if has_prev else h, h)
```

- [ ] **Step 4: Expose raw_point on BobberBitmapEvent**

In `models.py`, add `raw_point` field:
```python
@dataclass
class BobberBitmapEvent:
    point: Tuple[int, int] = (0, 0)
    raw_point: Tuple[int, int] = (0, 0)
    bitmap: Optional[Image.Image] = None
```

In `bobber_finder.py` `find()` method, pass raw_point in the event (line 60-63):
```python
raw_pt = (self._previous_location[0], self._raw_y) if self._raw_y is not None else self._previous_location
event = BobberBitmapEvent(
    point=(self._previous_location[0], self._previous_location[1]),
    raw_point=raw_pt,
    bitmap=self._bitmap,
)
```

- [ ] **Step 5: Commit warm-up + tight search + raw_point**

```bash
git add bobber_finder.py models.py
git commit -m "feat(bobber): warm-up lock, tighter search, expose raw Y"
```

---

### Task 2: Feed raw Y to bite watcher

**Files:**
- Modify: `fishing_bot.py:181-208` (_wait_for_bite)
- Modify: `bobber_finder.py` (add property to get raw screen position)

**Problem:** The bite watcher receives EMA-smoothed Y, which dampens real bite dips. It should receive raw Y for bite detection while the smoothed position is used for the loot click.

- [ ] **Step 1: Add `find_raw` property to SearchBobberFinder**

Add after the `find()` method in `bobber_finder.py`:
```python
@property
def last_raw_screen_position(self) -> Tuple[int, int]:
    """Raw (unsmoothed) screen position from last find() — for bite detection."""
    if self._raw_y is None or self._previous_location == EMPTY:
        return EMPTY
    raw_bitmap = (self._previous_location[0], self._raw_y)
    return WowScreen.get_screen_position_from_bitmap_position(raw_bitmap)
```

- [ ] **Step 2: Update `_wait_for_bite` to use raw Y for bite detection**

In `fishing_bot.py:181-208`, change the bite check to use raw position:

```python
def _wait_for_bite(self):
    self.bobber_finder.reset()
    bobber_pos = self._find_bobber()
    if bobber_pos == EMPTY:
        return

    self.bite_watcher.reset(bobber_pos)

    timed_task = TimedAction(lambda a: logger.info("Fishing timed out!"), 25_000, 25)
    last_junk_check = 0.0

    while self._is_enabled:
        current_pos = self._find_bobber()
        if current_pos == EMPTY or current_pos[0] == 0:
            return

        # Use raw Y for bite detection (unsmoothed — preserves dip amplitude)
        raw_pos = getattr(self.bobber_finder, 'last_raw_screen_position', current_pos)
        if raw_pos == EMPTY:
            raw_pos = current_pos

        if self.bite_watcher.is_bite(raw_pos):
            self._loot(current_pos)  # loot uses smoothed position
            return

        now = time.time()
        if now - last_junk_check > 2.0:
            last_junk_check = now
            self._try_delete_junk()

        if not timed_task.execute_if_due():
            return
```

- [ ] **Step 3: Commit raw Y bite detection**

```bash
git add bobber_finder.py fishing_bot.py
git commit -m "feat(bite): use raw Y for bite detection, smoothed for loot click"
```

---

### Task 3: Verify and test

- [ ] **Step 1: Manual test checklist**

1. Start fishing — watch the preview. Bobber should settle within ~4 frames (under 1 second) without jumping to the feather tip first.
2. Let it fish for several casts — count missed bites. Should be fewer than before.
3. Intentionally set bad colour values (low multiplier) — the bobber should still stay locked once found, not jump around the screen.
4. Open settings while fishing — settings stays on top (task #43 verification).

- [ ] **Step 2: Commit any adjustments**

If WARMUP_FRAMES or LOCKED_SEARCH need tuning based on testing, adjust and commit.

---

## Summary of changes

| Change | Why |
|---|---|
| `SMOOTH_ALPHA` 0.4 → 0.6 | Faster response to real Y movement |
| `WARMUP_FRAMES = 4` | Don't lock X on first frame (feather tip) |
| `LOCKED_SEARCH = 15` | Tighter window once locked — ignore distant false positives |
| `_raw_y` field | Unsmoothed Y for bite detection |
| `last_raw_screen_position` property | Expose raw position to fishing bot |
| `_wait_for_bite` uses raw Y | Bite dips not dampened by EMA |
| `_loot` still uses smoothed position | Stable click target |
