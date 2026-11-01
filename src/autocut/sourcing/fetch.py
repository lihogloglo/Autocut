"""Polite cached HTTP: one request at a time per host, retries on 429/5xx, bodies cached on disk."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0 Safari/537.36 Edg/141.0")
# Wikimedia asks API clients for a descriptive agent.
TOOL_UA = "Autocut/0.2 (B-roll sourcing for video essays; https://github.com/lihogloglo)"
_TOOL_HOSTS = ("wikipedia.org", "wikimedia.org", "wikidata.org", "archive.org", "europeana.eu")


@dataclass
class Response:
    status: int
    url: str
    headers: dict
    content: bytes

    @property
    def text(self) -> str:
        enc = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            enc = ctype.split("charset=")[-1].split(";")[0].strip() or enc
        return self.content.decode(enc, errors="replace")

    def json(self):
        return json.loads(self.content)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400


class Fetcher:
    def __init__(self, cache_dir: Path, min_gap: float = 0.4):
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_gap = min_gap
        self._hosts: dict[str, list] = {}     # host -> [lock, last request time]
        self._hosts_lock = threading.Lock()
        self._local = threading.local()

    def _client(self) -> httpx.Client:
        if not hasattr(self._local, "client"):
            self._local.client = httpx.Client(follow_redirects=True, timeout=30,
                                              headers={"Accept-Language": "fr,en;q=0.8"})
        return self._local.client

    def _host(self, host: str) -> list:
        with self._hosts_lock:
            return self._hosts.setdefault(host, [threading.Lock(), 0.0])

    def get(self, url: str, params: dict | None = None, *, cache: bool = True, max_bytes: int | None = None,
            headers: dict | None = None, timeout: float = 30) -> Response:
        full = url + ("?" + urlencode(params) if params else "")
        key = hashlib.sha1(full.encode()).hexdigest()
        body, meta = self.cache_dir / key, self.cache_dir / f"{key}.json"
        if cache and max_bytes is None and meta.exists() and body.exists():
            m = json.loads(meta.read_text(encoding="utf-8"))
            return Response(m["status"], m["url"], m["headers"], body.read_bytes())

        host = urlparse(url).netloc
        ua = TOOL_UA if host.endswith(_TOOL_HOSTS) else BROWSER_UA
        hdrs = {"User-Agent": ua, **(headers or {})}
        if max_bytes:
            hdrs["Range"] = f"bytes=0-{max_bytes - 1}"
        slot = self._host(host)
        resp = None
        for attempt in range(4):
            with slot[0]:
                wait = slot[1] + self.min_gap - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                try:
                    # httpx timeouts are per read: a server trickling bytes would never time out,
                    # and would hold this host's slot. Enforce a deadline on the whole download.
                    deadline = time.monotonic() + timeout * (4 if max_bytes is None else 1)
                    with self._client().stream("GET", full, headers=hdrs, timeout=min(timeout, 20)) as r:
                        chunks, size = [], 0
                        for chunk in r.iter_bytes():
                            chunks.append(chunk)
                            size += len(chunk)
                            if (max_bytes and size >= max_bytes) or time.monotonic() > deadline:
                                break
                        if time.monotonic() > deadline and not max_bytes:
                            raise httpx.ReadTimeout(f"download took more than {timeout * 4:.0f} s")
                        data = b"".join(chunks)
                        resp = Response(r.status_code, str(r.url), dict(r.headers),
                                        data[:max_bytes] if max_bytes else data)
                finally:
                    slot[1] = time.monotonic()
            if resp.status in (429, 503, 502, 504) and attempt < 3:
                delay = resp.headers.get("retry-after", "")
                time.sleep(min(float(delay), 30) if delay.isdigit() else 2 * 2 ** attempt)
                continue
            break
        if cache and max_bytes is None and resp.ok:
            body.write_bytes(resp.content)
            meta.write_text(json.dumps({"status": resp.status, "url": resp.url, "headers": {
                k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "last-modified")}}),
                encoding="utf-8")
        return resp

    def json(self, url: str, params: dict | None = None, **kw):
        r = self.get(url, params, **kw)
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status} for {url}")
        return r.json()
