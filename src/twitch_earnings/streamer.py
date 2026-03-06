from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class StreamerStats:
    """Tracks live stats for a streamer from IRC events."""

    name: str
    subs_t1: int = 0
    subs_t2: int = 0
    subs_t3: int = 0
    subs_prime: int = 0
    gift_subs: int = 0
    bits: int = 0
    messages: int = 0
    viewers: int = 0
    game: str = ""
    stream_started_at: datetime | None = None
    tracking_since: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    chat_log: deque[tuple[str, str, str]] = field(default_factory=lambda: deque(maxlen=200))
    # chat_log entries: (type, user, text) where type is "msg", "sub", "system"

    @property
    def total_subs(self) -> int:
        # gift_subs are already counted in t1/t2/t3
        return self.subs_t1 + self.subs_t2 + self.subs_t3 + self.subs_prime

    def _add_to_tier(self, plan: str, count: int = 1) -> None:
        if plan.startswith("3"):
            self.subs_t3 += count
        elif plan.startswith("2"):
            self.subs_t2 += count
        else:
            self.subs_t1 += count

    def process_usernotice(self, tags: dict[str, str]) -> None:
        """Process a USERNOTICE IRC message's tags."""
        msg_id = tags.get("msg-id", "")
        plan = tags.get("msg-param-sub-plan", "1000")

        if msg_id in ("sub", "resub"):
            if plan == "Prime":
                self.subs_prime += 1
            else:
                self._add_to_tier(plan)
        elif msg_id == "subgift":
            self.gift_subs += 1
            self._add_to_tier(plan)
        elif msg_id == "submysterygift":
            count = int(tags.get("msg-param-mass-gift-count", "1"))
            self.gift_subs += count
            self._add_to_tier(plan, count)
