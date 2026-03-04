import time
from typing import Callable


class TimedAction:
    def __init__(self, action: Callable[["TimedAction"], None], action_timeout_ms: int, max_time_secs: int):
        self.action = action
        self.action_timeout_ms = action_timeout_ms
        self.max_time_secs = max_time_secs
        self._interval_start = time.perf_counter()
        self._total_start = time.perf_counter()

    @property
    def elapsed_secs(self) -> int:
        return int(time.perf_counter() - self._total_start)

    def execute_now(self):
        self.action(self)

    def execute_if_due(self) -> bool:
        elapsed_ms = (time.perf_counter() - self._interval_start) * 1000
        if elapsed_ms > self.action_timeout_ms:
            self.action(self)
            self._interval_start = time.perf_counter()

        return (time.perf_counter() - self._total_start) < self.max_time_secs
