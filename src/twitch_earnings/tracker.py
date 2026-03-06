from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RevenueTracker:
    _tier_rates: dict[str, float] = field(
        default_factory=lambda: {"1000": 2.50, "2000": 5.00, "3000": 12.50}
    )
    _ad_cpm: float = 3.50
    _sub_counts: dict[str, int] = field(
        default_factory=lambda: {"1000": 0, "2000": 0, "3000": 0}
    )
    _bits_base: int = 0
    _bits_eventsub: int = 0
    _ad_breaks: list[tuple[int, int]] = field(default_factory=list)
    _started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def reset(self) -> None:
        self._sub_counts = {"1000": 0, "2000": 0, "3000": 0}
        self._bits_base = 0
        self._bits_eventsub = 0
        self._ad_breaks = []
        self._started_at = datetime.now(timezone.utc)

    def record_sub(self, tier: str, count: int = 1) -> None:
        self._sub_counts[tier] = self._sub_counts.get(tier, 0) + count

    def record_cheer(self, bits: int) -> None:
        self._bits_eventsub += bits

    def record_ad_break(self, duration: int, viewers: int) -> None:
        self._ad_breaks.append((duration, viewers))

    def bootstrap_bits(self, api_total: int) -> None:
        self._bits_base = api_total

    @property
    def total_subs(self) -> int:
        return sum(self._sub_counts.values())

    @property
    def total_bits(self) -> int:
        return self._bits_base + self._bits_eventsub

    @property
    def subs_revenue(self) -> float:
        return sum(
            count * self._tier_rates.get(tier, self._tier_rates["1000"])
            for tier, count in self._sub_counts.items()
        )

    @property
    def bits_revenue(self) -> float:
        return self.total_bits * 0.01

    @property
    def ads_revenue(self) -> float:
        total = 0.0
        for duration, viewers in self._ad_breaks:
            total += self._ad_cpm * (viewers / 1000) * (duration / 30)
        return total

    @property
    def total_revenue(self) -> float:
        return self.subs_revenue + self.bits_revenue + self.ads_revenue

    def format_chat_message(self) -> str:
        parts = [
            f"Today's estimated earnings: ${self.total_revenue:.2f}",
            f"Subs: ${self.subs_revenue:.2f} ({self.total_subs} subs)",
            f"Bits: ${self.bits_revenue:.2f} ({self.total_bits} bits)",
            f"Ads: ${self.ads_revenue:.2f} ({len(self._ad_breaks)} breaks)",
        ]
        msg = " | ".join(parts)
        if self.total_revenue == 0:
            msg += " | Note: Donations (Streamlabs, etc.) are not tracked"
        return msg
