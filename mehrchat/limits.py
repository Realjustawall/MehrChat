"""Bounded in-memory admission limits; no IP addresses are written to disk."""
import time
from collections import OrderedDict


class AdmissionLimiter:
    def __init__(self, rate=1, burst=20, capacity=4096, idle=300):
        self.rate, self.burst, self.capacity, self.idle = rate, burst, capacity, idle
        self.entries = OrderedDict()

    def allow(self, key, now=None):
        now = time.monotonic() if now is None else now
        while self.entries and now - next(iter(self.entries.values()))[1] > self.idle:
            self.entries.popitem(last=False)
        if key not in self.entries and len(self.entries) >= self.capacity:
            return False  # Do not evict active limits and reopen their budgets.
        tokens, last = self.entries.pop(key, (float(self.burst), now))
        tokens = min(self.burst, tokens + max(0, now - last) * self.rate)
        accepted = tokens >= 1
        self.entries[key] = (tokens - 1 if accepted else tokens, now)
        return accepted
