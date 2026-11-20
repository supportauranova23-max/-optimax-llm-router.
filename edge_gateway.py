import time, hashlib
from collections import deque
from typing import Dict, Tuple, Optional

# In-memory sliding-window rate limiter: { "workspace:device_id": deque([timestamps]) }
DEVICE_WINDOWS: Dict[str, deque] = {}
ROGUE_LOOPS_BLOCKED = 0

# In-memory 24h TTL cache: { "sha256(workspace_id + prompt)": (reply_text, expires_at_ts) }
EDGE_TTL_CACHE: Dict[str, Tuple[str, float]] = {}
TTL_SECONDS = 86400  # 24 hours

def check_device_rate_limit(workspace_id: str, device_id: str, rpm_limit: int = 60) -> bool:
    global ROGUE_LOOPS_BLOCKED
    now = time.time()
    bucket_key = f"{workspace_id}:{device_id}"
    q = DEVICE_WINDOWS.setdefault(bucket_key, deque())
    while q and now - q[0] > 60.0:
        q.popleft()
    if len(q) >= rpm_limit:
        ROGUE_LOOPS_BLOCKED += 1
        return False
    q.append(now)
    return True

def _cache_key(workspace_id: str, prompt: str) -> str:
    norm = " ".join(prompt.strip().lower().split())
    return hashlib.sha256(f"{workspace_id}:{norm}".encode()).hexdigest()

def get_edge_cache(workspace_id: str, prompt: str) -> Optional[str]:
    k = _cache_key(workspace_id, prompt)
    entry = EDGE_TTL_CACHE.get(k)
    if not entry:
        return None
    reply, expires_at = entry
    if time.time() > expires_at:
        EDGE_TTL_CACHE.pop(k, None)
        return None
    return reply

def set_edge_cache(workspace_id: str, prompt: str, reply: str):
    k = _cache_key(workspace_id, prompt)
    EDGE_TTL_CACHE[k] = (reply, time.time() + TTL_SECONDS)
