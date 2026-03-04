"""
Laksefisk - Python port of https://github.com/julianperrott/Laksefisk

Console mode. For the GUI, run gui.py instead.

Loots by moving mouse to bobber and right-clicking (human-like movement).

Usage:
    python main.py [--blue] [--cast-key 0x34] [--loot-min 0.5] [--loot-max 2.0]
"""

import argparse
import logging
import sys
import time

import wow_process
from bite_watcher import PositionBiteWatcher
from bobber_finder import SearchBobberFinder
from fishing_bot import LaksefiskBot
from pixel_classifier import ClassifierMode, PixelClassifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("Laksefisk")


def main():
    parser = argparse.ArgumentParser(description="Laksefisk WoW fishing bot")
    parser.add_argument("--blue", action="store_true", help="Use blue bobber mode")
    parser.add_argument("--cast-key", type=lambda x: int(x, 0), default=0x34,
                        help="Virtual key code for cast key (default: 0x34 = '4')")
    parser.add_argument("--lure-key", type=lambda x: int(x, 0), default=None,
                        help="Virtual key code for lure macro (optional)")
    parser.add_argument("--loot-min", type=float, default=0.5,
                        help="Min wait before loot in seconds (default: 0.5)")
    parser.add_argument("--loot-max", type=float, default=2.0,
                        help="Max wait before loot in seconds (default: 2.0)")
    parser.add_argument("--strike", type=int, default=7, help="Bite detection threshold (default: 7)")
    args = parser.parse_args()

    pixel_classifier = PixelClassifier()
    if args.blue:
        print("Blue mode")
        pixel_classifier.mode = ClassifierMode.Blue

    pixel_classifier.set_configuration(wow_process.is_wow_classic())

    bobber_finder = SearchBobberFinder(pixel_classifier)
    bite_watcher = PositionBiteWatcher(args.strike)

    bot = LaksefiskBot(
        bobber_finder=bobber_finder,
        bite_watcher=bite_watcher,
        cast_key=args.cast_key,
        lure_key=args.lure_key,
        loot_wait_min=args.loot_min,
        loot_wait_max=args.loot_max,
    )
    bot.fishing_event_handler = lambda e: logger.info(str(e))

    wow_process.press_key(0x20)  # VK_SPACE
    time.sleep(1.5)

    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop()
        logger.info("Stopped by user.")


if __name__ == "__main__":
    main()
