import logging
import random
import time
from typing import Callable, List, Optional, Tuple

import wow_process
from bite_watcher import IBiteWatcher
from bobber_finder import IBobberFinder
from models import FishingAction, FishingEvent
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
        lure_key: Optional[int] = None,
        loot_wait_min: float = LOOT_WAIT_MIN,
        loot_wait_max: float = LOOT_WAIT_MAX,
    ):
        self.bobber_finder = bobber_finder
        self.bite_watcher = bite_watcher
        self.cast_key = cast_key
        self.lure_key = lure_key
        self.loot_wait_min = loot_wait_min
        self.loot_wait_max = loot_wait_max
        self._is_enabled = False
        self._start_time = time.time()
        self._lure_time = 0.0  # force lure on first start
        self.fishing_event_handler: Callable[[FishingEvent], None] = lambda e: None
        logger.info("Laksefisk Created.")

    def start(self):
        self.bite_watcher.fishing_event_handler = self.fishing_event_handler
        self._is_enabled = True
        self._apply_lure_if_due()

        while self._is_enabled:
            try:
                logger.info(f"Pressing key {self.cast_key} to Cast.")
                self._apply_lure_if_due()
                self.fishing_event_handler(FishingEvent(action=FishingAction.Cast))
                wow_process.press_key(self.cast_key)
                self._watch(2000)
                self._wait_for_bite()
            except Exception as e:
                logger.error(str(e))
                self.sleep(2000)

        logger.error("Bot has Stopped.")

    def stop(self):
        self._is_enabled = False
        logger.error("Bot is Stopping...")

    def set_cast_key(self, key: int):
        self.cast_key = key

    def set_lure_key(self, key: Optional[int]):
        self.lure_key = key

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
        logger.info(f"Bobber start position: {bobber_pos}")

        timed_task = TimedAction(lambda a: logger.info("Fishing timed out!"), 25_000, 25)

        while self._is_enabled:
            current_pos = self._find_bobber()
            if current_pos == EMPTY or current_pos[0] == 0:
                return

            if self.bite_watcher.is_bite(current_pos):
                self._loot(current_pos)
                return

            if not timed_task.execute_if_due():
                return

    def _loot(self, bobber_position: Tuple[int, int]):
        delay = self.loot_wait_min + _rng.random() * (self.loot_wait_max - self.loot_wait_min)
        logger.info(f"Waiting {delay:.1f}s before looting...")
        time.sleep(delay)
        logger.info(f"Moving mouse to bobber at {bobber_position} and right-clicking.")
        wow_process.right_click_mouse(bobber_position)
        # Wait for loot to complete before casting again
        loot_wait = 0.3 + _rng.random() * 0.7
        logger.info(f"Waiting {loot_wait:.1f}s for loot to complete...")
        time.sleep(loot_wait)

    def _find_bobber(self) -> Tuple[int, int]:
        timer = TimedAction(lambda a: logger.info(f"Waited {a.elapsed_secs}s for target"), 1000, 5)
        while True:
            target = self.bobber_finder.find()
            if target != EMPTY or not timer.execute_if_due():
                return target

    @staticmethod
    def sleep(ms: int):
        ms += _rng.randint(0, 225)
        time.sleep(ms / 1000)
