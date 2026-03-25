import threading
import time
from collections import defaultdict, deque


class InMemoryRateLimiter:
    """Simple process-local rate limiter for demo use.

    Good enough for a course project prototype. For production you would replace this with
    Redis or database-backed rate limiting.
    """

    def __init__(self) -> None:
        self._events = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            queue = self._events[key]
            while queue and queue[0] <= now - window_seconds:
                queue.popleft()
            if len(queue) >= limit:
                return False
            queue.append(now)
            return True
