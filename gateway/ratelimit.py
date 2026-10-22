import time


class RateLimiter:
    def __init__(self, per_minute, clock=time.monotonic):
        self.capacity = per_minute
        self.rate = per_minute / 60
        self.clock = clock
        self.buckets = {}

    def acquire(self, client):
        now = self.clock()
        tokens, last = self.buckets.get(client, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens < 1:
            self.buckets[client] = (tokens, now)
            return round((1 - tokens) / self.rate, 2)
        self.buckets[client] = (tokens - 1, now)
        return 0.0
