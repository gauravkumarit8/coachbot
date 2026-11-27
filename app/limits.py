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


def _mode(trust_proxy) -> str:
    if trust_proxy is None:
        v = os.getenv("TRUST_PROXY", "").strip().lower()
    else:
        v = "1" if trust_proxy is True else "" if trust_proxy is False else str(trust_proxy).strip().lower()
    return "xff" if v == "xff" else "1" if v in ("1", "true", "yes") else ""


def client_ip(headers, peer_host, trust_proxy=None, hops=None) -> str:
    """The visitor's address. Behind a tunnel or web server every request arrives from that proxy, so the real address
    is in a header, but headers can be forged, so they are only trusted when TRUST_PROXY is set:
      TRUST_PROXY=1    a Cloudflare tunnel (cloudflared) or similar: use CF-Connecting-IP, else X-Forwarded-For
      TRUST_PROXY=xff  your own nginx/Caddy or a platform such as Render: use X-Forwarded-For only
    X-Forwarded-For is counted from the RIGHT: each proxy adds the address it saw on the right-hand end, so the left-hand
    entries may have been typed by the visitor. PROXY_HOPS = how many proxies of yours are in front (default 1)."""
    mode = _mode(trust_proxy)
    if mode:
        if mode == "1":
            ip = (headers.get("cf-connecting-ip") or "").strip()
            if ip:
                return ip
        parts = [p.strip() for p in (headers.get("x-forwarded-for") or "").split(",") if p.strip()]
        if parts:
            try:
                n = max(1, min(int(os.getenv("PROXY_HOPS", "1")) if hops is None else int(hops), 5))
            except ValueError:
                n = 1
            return parts[-n] if len(parts) >= n else parts[0]
    return peer_host or "?"
