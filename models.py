from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple
from PIL import Image


class FishingAction(Enum):
    BobberMove = auto()
    Reset = auto()
    Loot = auto()
    Cast = auto()
    Lure = auto()


@dataclass
class FishingEvent:
    action: FishingAction = FishingAction.Cast
    amplitude: int = 0

    def __str__(self):
        if self.action == FishingAction.BobberMove:
            return f"{self.action.name} {self.amplitude}"
        return self.action.name


@dataclass
class BobberBitmapEvent:
    point: Tuple[int, int] = (0, 0)
    bitmap: Optional[Image.Image] = None
