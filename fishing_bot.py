import logging
import random
import threading
import time
from typing import Callable, List, Optional, Tuple

import wow_process
from bite_watcher import IBiteWatcher
from bobber_calibration import sweep_calibrate
from bobber_finder import IBobberFinder
from models import FishingAction, FishingEvent
from pixel_bridge import PixelBridge
from timed_action import TimedAction

EMPTY = (0, 0)
logger = logging.getLogger("Laksefisk")
_rng = random.Random()

LURE_INTERVAL = 610  # 10 minutes 10 seconds
LURE_APPLY_TIME = 5  # seconds to wait while lure is being applied

# Default loot wait range (seconds) — configurable via GUI
LOOT_WAIT_MIN = 0.5
LOOT_WAIT_MAX = 2.0


class LaksefiskBot:
    def __init__(
        self,
        bobber_finder: IBobberFinder,
        bite_watcher: IBiteWatcher,
        cast_key: int,
        wow_screen=None,
        lure_key: Optional[int] = None,
        loot_wait_min: float = LOOT_WAIT_MIN,
        loot_wait_max: float = LOOT_WAIT_MAX,
    ):
        self.bobber_finder = bobber_finder
        self.bite_watcher = bite_watcher
        self.cast_key = cast_key
        self._wow_screen = wow_screen
        self.lure_key = lure_key
        self.loot_wait_min = loot_wait_min
        self.loot_wait_max = loot_wait_max
        self._is_enabled = False
        self._start_time = time.time()
        self._lure_time = 0.0  # force lure on first start
        self.fishing_event_handler: Callable[[FishingEvent], None] = lambda e: None
        self.fish_tracker = None  # set by GUI to enable loot tracking
        self.pixel_bridge: Optional[PixelBridge] = None  # set by GUI
        self._last_loot_parity: Optional[int] = None
        self.stop_on_friendly_nearby: bool = False
        self.stop_on_enemy_nearby: bool = False
        self.stop_on_bags_full: bool = False
        self.auto_calibrate: bool = False
        self.auto_delete_junk: bool = False
        self._junk_delete_count: int = 0
        self._dc_count: int = 0
        self._pixel_classifier = None  # set by GUI for auto-calibration
        self._calibrated: bool = False  # sweep once at start
        self._last_cal_toggle: Optional[bool] = None  # track addon calibrate button
        self.debug_screenshots: bool = False
        self._paused = threading.Event()
        self._paused.set()  # starts unpaused
        logger.info("Laksefisk Created.")

    def start(self):
        self.bite_watcher.fishing_event_handler = self.fishing_event_handler
        self._is_enabled = True
        self._apply_lure_if_due()

        while self._is_enabled:
            try:
                # Wait if paused (blocks until resumed or stopped)
                self._paused.wait()
                if not self._is_enabled:
                    break

                # Check pixel bridge for stop conditions before casting
                if self.pixel_bridge and self._check_stop_conditions():
                    continue

                self._try_delete_junk()

                logger.info(f"Pressing key {self.cast_key} to Cast.")
                self._apply_lure_if_due()
                self.fishing_event_handler(FishingEvent(action=FishingAction.Cast))
                wow_process.press_key(self.cast_key)
                self._watch(2000)
                if self.auto_calibrate and self._pixel_classifier and not self._calibrated:
                    if sweep_calibrate(self._pixel_classifier, self._wow_screen):
                        self._calibrated = True
                        logger.info("Auto-calibration complete — using calibrated values")
                    else:
                        logger.warning("Auto-calibration failed — will retry next cast")
                self._wait_for_bite()
            except Exception as e:
                logger.error(str(e))
                self.sleep(2000)

        logger.error("Bot has Stopped.")

    def stop(self):
        self._is_enabled = False
        self._paused.set()  # unblock if paused so thread can exit
        logger.error("Bot is Stopping...")

    def pause(self):
        self._paused.clear()
        logger.info("Bot paused.")

    def resume(self):
        self._paused.set()
        logger.info("Bot resumed.")

    def set_cast_key(self, key: int):
        self.cast_key = key

    def set_lure_key(self, key: Optional[int]):
        self.lure_key = key

    def _apply_addon_settings(self, data):
        """Apply settings from v2 addon pixel bridge data."""
        if data.addon_version != 2:
            return
        self.stop_on_friendly_nearby = data.s_stop_friendly
        self.stop_on_enemy_nearby = data.s_stop_enemy
        self.stop_on_bags_full = data.s_stop_bags
        self.auto_delete_junk = data.s_auto_delete
        self.auto_calibrate = data.s_auto_calibrate
        if data.s_cast_key is not None:
            self.cast_key = data.s_cast_key
        if data.s_lure_key is not None:
            self.lure_key = data.s_lure_key
        else:
            self.lure_key = None
        self.loot_wait_min = data.s_loot_wait_min
        self.loot_wait_max = data.s_loot_wait_max
        # Detect calibration request from addon button
        if self._last_cal_toggle is not None and data.s_calibration_toggle != self._last_cal_toggle:
            logger.info("Addon calibration request detected")
            self._calibrated = False  # triggers re-calibration on next cast
        self._last_cal_toggle = data.s_calibration_toggle
        # Apply addon slider values only when user has explicitly moved them
        if data.s_sliders_override and self._pixel_classifier:
            self._pixel_classifier.colour_multiplier = data.s_colour_multiplier
            self._pixel_classifier.colour_closeness_multiplier = data.s_colour_closeness_multiplier

    def _read_bridge(self) -> "Optional[PixelBridgeData]":
        """Read pixel bridge, skipping slow scan if addon not found."""
        if not self.pixel_bridge:
            return None
        return self.pixel_bridge.read(allow_slow_scan=False)

    def _try_delete_junk(self):
        """Press F12 to confirm the destroy popup shown by the addon."""
        if not self.auto_delete_junk or not self.pixel_bridge:
            return
        data = self._read_bridge()
        if data is None or not data.junk_on_cursor:
            return
        logger.info("Junk on cursor — pressing F12 to confirm delete")
        # Wait for addon to show the DELETE_ITEM popup (0.1s after pickup)
        time.sleep(0.3)
        # F12 is override-bound by addon to /click StaticPopup1Button1
        wow_process.press_key(0x7B)  # VK_F12
        # Wait for addon to detect cursor cleared and reset flag (3s timeout)
        t0 = time.time()
        while time.time() - t0 < 3.0:
            time.sleep(0.2)
            data = self._read_bridge()
            if data is None or not data.junk_on_cursor:
                self._junk_delete_count += 1
                logger.info(f"Junk deleted (total: {self._junk_delete_count})")
                return
        logger.warning("Junk delete timed out — F12 may not have triggered")

    def _check_stop_conditions(self) -> bool:
        """Check pixel bridge for stop conditions. Returns True if paused/stopped."""
        try:
            data = self._read_bridge()

            # Disconnect detection: bridge was connected but now returns None
            if data is None:
                if self.pixel_bridge and self.pixel_bridge.connected is False:
                    self._dc_count += 1
                    if self._dc_count >= 5:
                        logger.error("Disconnected — stopping bot")
                        self.stop()
                        return True
                return False
            self._dc_count = 0

            # Apply addon settings if v2
            self._apply_addon_settings(data)

            # Dead / ghost — stop immediately
            if not data.alive:
                logger.error("Character died — stopping bot")
                self.stop()
                return True

            # Combat — pause until combat ends, then check if alive
            if data.combat:
                logger.warning("In combat — pausing bot")
                while self._is_enabled:
                    time.sleep(1)
                    data = self._read_bridge()
                    if data is None:
                        continue
                    if not data.alive:
                        logger.error("Died in combat — stopping bot")
                        self.stop()
                        return True
                    if not data.combat:
                        logger.info("Combat ended — resuming fishing")
                        return True
                return True

            friendly_triggered = self.stop_on_friendly_nearby and data.player_nearby
            enemy_triggered = self.stop_on_enemy_nearby and data.enemy_nearby
            if friendly_triggered or enemy_triggered:
                who = "Enemy" if enemy_triggered else "Player"
                logger.warning(f"{who} nearby — pausing fishing")
                self.fishing_event_handler(FishingEvent(action=FishingAction.Cast))
                while self._is_enabled:
                    time.sleep(3)
                    data = self._read_bridge()
                    if data is None:
                        logger.info("Player gone — resuming fishing")
                        return True
                    still_friendly = self.stop_on_friendly_nearby and data.player_nearby
                    still_enemy = self.stop_on_enemy_nearby and data.enemy_nearby
                    if not still_friendly and not still_enemy:
                        logger.info("Player gone — resuming fishing")
                        return True
                return True

            if self.stop_on_bags_full and data.bags_full:
                logger.warning("Bags full — stopping fishing")
                self.stop()
                return True

        except Exception as e:
            logger.debug(f"Stop condition check error: {e}")
        return False

    def _apply_lure_if_due(self):
        if self.lure_key is None:
            return
        elapsed = time.time() - self._lure_time
        if elapsed >= LURE_INTERVAL:
            logger.info(f"Applying lure (key {self.lure_key})...")
            self.fishing_event_handler(FishingEvent(action=FishingAction.Lure))
            wow_process.press_key(self.lure_key)
            logger.info(f"Waiting {LURE_APPLY_TIME}s for lure to apply...")
            time.sleep(LURE_APPLY_TIME)
            self._lure_time = time.time()
            logger.info("Lure applied.")

    def _watch(self, milliseconds: int):
        self.bobber_finder.reset()
        t0 = time.perf_counter()
        while (time.perf_counter() - t0) * 1000 < milliseconds:
            self.bobber_finder.find()

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

            # Periodically check for junk from previous loot (addon may be slow)
            now = time.time()
            if now - last_junk_check > 2.0:
                last_junk_check = now
                self._try_delete_junk()

            if not timed_task.execute_if_due():
                return

    def _loot(self, bobber_position: Tuple[int, int]):
        delay = self.loot_wait_min + _rng.random() * (self.loot_wait_max - self.loot_wait_min)
        logger.info(f"Waiting {delay:.1f}s before looting...")
        time.sleep(delay)
        ox, oy = _rng.randint(-5, 5), _rng.randint(-5, 5)
        click_pos = (bobber_position[0] + ox, bobber_position[1] + oy)
        logger.info(f"Looting bobber (offset {ox:+d},{oy:+d}).")
        wow_process.right_click_mouse(click_pos)
        # Wait for loot to complete before casting again
        loot_wait = 0.3 + _rng.random() * 0.7
        logger.info(f"Waiting {loot_wait:.1f}s for loot to complete...")
        time.sleep(loot_wait)
        # Read loot from pixel bridge
        if self.pixel_bridge:
            self._read_loot_from_bridge()
        # Quick poll for addon junk deletion — backup check happens during fishing
        if self.auto_delete_junk and self.pixel_bridge:
            t0 = time.time()
            while time.time() - t0 < 1.5:
                data = self._read_bridge()
                if data is not None and data.junk_on_cursor:
                    self._try_delete_junk()
                    break
                time.sleep(0.3)

    def _read_loot_from_bridge(self):
        """Read loot info from pixel bridge instead of OCR."""
        try:
            data = self._read_bridge()
            if data is None:
                logger.warning("Pixel bridge: bar not found")
                return

            # Check if loot parity changed (new loot detected)
            if self._last_loot_parity is not None and data.loot_parity == self._last_loot_parity:
                logger.debug("Pixel bridge: loot parity unchanged, no new loot")
                return

            self._last_loot_parity = data.loot_parity

            if data.item_id > 0 and self.fish_tracker:
                name = data.item_name
                logger.info(f"Pixel bridge: looted [{name}] (ID: {data.item_id})")
                self.fish_tracker.record_pixel_loot(name, data.item_id)
        except Exception as e:
            logger.warning(f"Pixel bridge read error: {e}")

    def _find_bobber(self) -> Tuple[int, int]:
        self.bobber_finder.save_debug_screenshots = self.debug_screenshots
        timer = TimedAction(lambda a: logger.info(f"Waited {a.elapsed_secs}s for target"), 1000, 5)
        while True:
            target = self.bobber_finder.find()
            if target != EMPTY or not timer.execute_if_due():
                return target

    @staticmethod
    def sleep(ms: int):
        ms += _rng.randint(0, 225)
        time.sleep(ms / 1000)
