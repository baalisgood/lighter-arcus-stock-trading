"""In-memory stock decision signals. Prices and FIFO costs remain raw."""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time
from math import exp, isfinite
from zoneinfo import ZoneInfo


@dataclass
class BasisState:
    window: float = 3600.0
    warmup: float = 3600.0
    drift_window: float = 3600.0
    drift_limit: float = 0.10
    max_gap: float = 3.0
    ema: float | None = None
    started: float | None = None
    last: float | None = None
    history: deque = field(default_factory=deque)
    ready: bool = False
    stable: bool = False

    def reset(self):
        self.ema = self.started = self.last = None
        self.history.clear()
        self.ready = self.stable = False

    def observe(self, now, value):
        if value is None or not isfinite(value):
            self.reset()
            return
        if self.last is not None and (now < self.last or now - self.last > self.max_gap):
            self.reset()
        if self.last is not None and now - self.last < 1.0:
            return
        if self.last is None:
            self.started, self.ema = now, value
        else:
            self.ema += (1 - exp(-(now - self.last) / self.window)) * (value - self.ema)
        self.last = now
        self.history.append((now, self.ema))
        cutoff = now - self.drift_window
        while len(self.history) > 1 and self.history[1][0] <= cutoff:
            self.history.popleft()
        self.ready = now - self.started >= max(self.warmup, self.drift_window)
        self.stable = self.ready and abs(self.ema - self.history[0][1]) <= self.drift_limit


def cash_threshold(grid, now=None):
    schedule = grid.stock_session
    if not schedule:
        return grid.initial_spread_threshold
    local = (now or datetime.now(ZoneInfo("America/New_York"))).astimezone(ZoneInfo("America/New_York"))
    date = local.date().isoformat()
    known = local.year in schedule.get("calendar_valid_years", [])
    closed = set(schedule.get("closed_dates", [])) | set(schedule.get("closed_overrides", []))
    end = time.fromisoformat(schedule.get("early_closes", {}).get(date, "16:00"))
    regular = known and local.weekday() < 5 and date not in closed and time(9, 30) <= local.time().replace(tzinfo=None) < end
    return float(grid.initial_spread_threshold if regular else schedule.get("offhours_threshold_pct", grid.initial_spread_threshold + .06))
