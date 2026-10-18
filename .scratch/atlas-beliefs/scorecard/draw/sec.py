import hashlib, json, os, time, urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "cache")
os.makedirs(CACHE, exist_ok=True)
UA = "Atlas Research ekenheim@gmail.com"
COUNTS = {"sec": 0, "stooq": 0}
COUNT_FILE = os.path.join(BASE, "request_count.json")
_last = [0.0]


def _load_counts():
    if os.path.exists(COUNT_FILE):
        with open(COUNT_FILE) as f:
            COUNTS.update(json.load(f))


def _save_counts():
    with open(COUNT_FILE, "w") as f:
        json.dump(COUNTS, f)


_load_counts()


def fetch(url, kind="sec", ua=UA):
    """Return bytes, or None for a 404 (cached). Counts network requests only."""
    key = hashlib.sha1(url.encode()).hexdigest()
    path = os.path.join(CACHE, key)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    if os.path.exists(path + ".404"):
        return None
    if os.environ.get("CONTROLS_ONLINE") != "1":
        raise RuntimeError("offline: not in cache (no web access allowed): " + url)
    delay = 1.0
    for attempt in range(8):
        if kind == "sec":
            wait = 0.22 - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        COUNTS[kind] += 1
        _save_counts() if COUNTS[kind] % 25 == 0 else None
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            with open(path, "wb") as f:
                f.write(data)
            with open(path + ".url", "w") as f:
                f.write(url)
            _save_counts()
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(path + ".404", "w").write(url)
                _save_counts()
                return None
            if e.code in (429, 503, 500, 502, 504):
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            _save_counts()
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(delay)
            delay = min(delay * 2, 60)
    _save_counts()
    raise RuntimeError("giving up on " + url)


def fetch_json(url):
    d = fetch(url)
    return None if d is None else json.loads(d)


def cik10(c):
    return "%010d" % int(c)
