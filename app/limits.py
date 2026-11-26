"""Abuse protection for the public chat endpoint: sliding-window limits keyed by the visitor's real address
(not by a session id the browser can change on every request)."""
import os
import threading
import time
from collections import deque


class Limiter:
    """Allow at most `limit` events per `window` seconds for each key. In memory: resets when the server restarts."""

    def __init__(self, clock=time.time):
        self._hits, self._lock, self._clock = {}, threading.Lock(), clock

    def allow(self, key: str, limit: int, window: float = 60) -> bool:
        now = self._clock()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 5000:  # forget idle keys so memory stays small
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > window]:
                    del self._hits[k]
            return True


def client_ip(headers, peer_host, trust_proxy=None) -> str:
    """The visitor's address. Behind cloudflared/ngrok/nginx every request arrives from the proxy itself, so the real
    address is in a header, but headers can be forged, so they are only trusted when TRUST_PROXY=1 is set."""
    if trust_proxy is None:
        trust_proxy = os.getenv("TRUST_PROXY", "") == "1"
    if trust_proxy:
        ip = headers.get("cf-connecting-ip") or (headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if ip:
            return ip
    return peer_host or "?"
