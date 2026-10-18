import threading
import time


class TokenBucket:
    def __init__(self, capacity: float, refill_per_sec: float, clock=time.monotonic):
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self.tokens = capacity
        self.clock = clock
        self.updated = clock()

    def _refill(self):
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill_per_sec)
        self.updated = now

    def peek(self, amount: float) -> float:
        self._refill()
        if self.tokens >= amount:
            return 0.0
        return (amount - self.tokens) / self.refill_per_sec

    def take(self, amount: float):
        self.tokens -= amount


class RateLimiter:
    def __init__(self, requests_per_minute: int, tokens_per_minute: int, clock=time.monotonic):
        self.rpm = requests_per_minute
        self.tpm = tokens_per_minute
        self.clock = clock
        self.buckets: dict[str, tuple[TokenBucket, TokenBucket]] = {}
        self.lock = threading.Lock()

    def _get(self, client: str):
        if client not in self.buckets:
            self.buckets[client] = (
                TokenBucket(self.rpm, self.rpm / 60, self.clock),
                TokenBucket(self.tpm, self.tpm / 60, self.clock),
            )
        return self.buckets[client]

    def acquire(self, client: str, tokens: int) -> float:
        """Returns 0 when allowed, otherwise seconds until retry."""
        with self.lock:
            req, tok = self._get(client)
            wait = max(req.peek(1), tok.peek(min(tokens, self.tpm)))
            if wait > 0:
                return round(wait, 2)
            req.take(1)
            tok.take(tokens)
            return 0.0

    def settle(self, client: str, estimated: int, actual: int):
        with self.lock:
            _, tok = self._get(client)
            tok.tokens = min(tok.capacity, tok.tokens + estimated - actual)
