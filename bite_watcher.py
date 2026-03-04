import logging
from abc import ABC, abstractmethod
from typing import Callable, List, Optional, Tuple

from models import FishingAction, FishingEvent
from timed_action import TimedAction

EMPTY = (0, 0)
logger = logging.getLogger("Laksefisk")


class IBiteWatcher(ABC):
    fishing_event_handler: Callable[[FishingEvent], None]

    @abstractmethod
    def reset(self, initial_bobber_position: Tuple[int, int]):
        ...

    @abstractmethod
    def is_bite(self, current_bobber_position: Tuple[int, int]) -> bool:
        ...


class PositionBiteWatcher(IBiteWatcher):
    def __init__(self, strike_value: int):
        self.strike_value = strike_value
        self.fishing_event_handler: Callable[[FishingEvent], None] = lambda e: None
        self._y_positions: List[int] = []
        self._y_diff: int = 0
        self._timer: Optional[TimedAction] = None

    def _raise_event(self, ev: FishingEvent):
        self.fishing_event_handler(ev)

    def reset(self, initial_bobber_position: Tuple[int, int]):
        self._raise_event(FishingEvent(action=FishingAction.Reset))
        self._y_positions = [initial_bobber_position[1]]
        self._timer = TimedAction(
            lambda a: self._raise_event(FishingEvent(action=FishingAction.BobberMove, amplitude=self._y_diff)),
            500,
            25,
        )

    def is_bite(self, current_bobber_position: Tuple[int, int]) -> bool:
        y = current_bobber_position[1]

        if y not in self._y_positions:
            self._y_positions.append(y)
            self._y_positions.sort()

        median_idx = int((len(self._y_positions) + 0.5) / 2)
        self._y_diff = self._y_positions[median_idx] - y

        threshold_reached = self._y_diff <= -self.strike_value

        if self._timer:
            self._timer.execute_if_due()

        if threshold_reached:
            self._raise_event(FishingEvent(action=FishingAction.Loot))
            if self._timer:
                self._timer.execute_now()
            return True

        return False
