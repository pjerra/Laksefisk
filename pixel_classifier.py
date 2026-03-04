import logging
from enum import Enum, auto

logger = logging.getLogger("Laksefisk")


class ClassifierMode(Enum):
    Red = auto()
    Blue = auto()


class PixelClassifier:
    def __init__(self):
        self.colour_multiplier: float = 0.5
        self.colour_closeness_multiplier: float = 2.0
        self.mode: ClassifierMode = ClassifierMode.Red

    def is_match(self, red: int, green: int, blue: int) -> bool:
        if self.mode == ClassifierMode.Red:
            return self._is_bigger(red, green) and self._is_bigger(red, blue) and self._are_close(blue, green)
        else:
            return self._is_bigger(blue, green) and self._is_bigger(blue, red) and self._are_close(red, green)

    def set_configuration(self, is_wow_classic: bool):
        if is_wow_classic:
            logger.info("Wow Classic configuration")
            self.colour_multiplier = 1.0
            self.colour_closeness_multiplier = 1.0
        else:
            logger.info("Wow Standard configuration")

    def _is_bigger(self, dominant: int, other: int) -> bool:
        return (dominant * self.colour_multiplier) > other

    def _are_close(self, color1: int, color2: int) -> bool:
        mx = max(color1, color2)
        mn = min(color1, color2)
        return mn * self.colour_closeness_multiplier > mx - 20
