"""sport名からCollectorクラスを解決するレジストリ。"""

from __future__ import annotations

from rin_garden.collectors.base import BaseCollector
from rin_garden.collectors.boat.collector import BoatCollector
from rin_garden.collectors.jra.collector import JraCollector
from rin_garden.collectors.keirin.collector import KeirinCollector
from rin_garden.collectors.nar.collector import NarCollector

_REGISTRY: dict[str, type[BaseCollector]] = {
    "jra": JraCollector,
    "nar": NarCollector,
    "boat": BoatCollector,
    "keirin": KeirinCollector,
}


def get_collector(sport: str) -> BaseCollector:
    key = sport.strip().lower()
    if key not in _REGISTRY:
        raise ValueError(f"unknown sport: {sport!r} (expected one of {sorted(_REGISTRY)})")
    return _REGISTRY[key]()
