"""Small shared helpers for adapters backed by public HTML pages."""

from __future__ import annotations

import json
import gzip
import threading
import time
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def attribute(attrs: list[tuple[str, str | None]], name: str) -> str | None:
    return next((value for key, value in attrs if key == name), None)


def class_names(attrs: list[tuple[str, str | None]]) -> set[str]:
    return set((attribute(attrs, "class") or "").split())


class PublicPageClient:
    """Rate-limited HTML client with bounded retries and a descriptive user agent."""

    def __init__(self, *, timeout: float, retries: int, delay: float) -> None:
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self._rate_lock = threading.Lock()
        self._next_request_at = 0.0

    def _wait_for_slot(self) -> None:
        with self._rate_lock:
            now = time.monotonic()
            request_at = max(now, self._next_request_at)
            self._next_request_at = request_at + self.delay
        wait = request_at - now
        if wait > 0:
            time.sleep(wait)

    def get_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_for_slot()
            request = Request(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "jobtracks-pilot/0.1 (public job data ingestion)",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    content = response.read()
                    if response.headers.get("Content-Encoding") == "gzip" or content[:2] == b"\x1f\x8b":
                        content = gzip.decompress(content)
                    return content.decode(charset, errors="replace")
            except HTTPError as exc:
                last_error = exc
                if exc.code not in RETRYABLE_STATUS_CODES or attempt >= self.retries:
                    break
            except (URLError, TimeoutError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"Request failed for {url}: {last_error}") from last_error

    def get_json(self, url: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_for_slot()
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "jobtracks-pilot/0.1 (public job data ingestion)",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    content = response.read()
                    if response.headers.get("Content-Encoding") == "gzip" or content[:2] == b"\x1f\x8b":
                        content = gzip.decompress(content)
                    payload = json.loads(content.decode(charset, errors="replace"))
                if not isinstance(payload, dict):
                    raise RuntimeError(f"Expected a JSON object from {url}")
                return payload
            except HTTPError as exc:
                last_error = exc
                if exc.code not in RETRYABLE_STATUS_CODES or attempt >= self.retries:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"Request failed for {url}: {last_error}") from last_error

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        for attempt in range(self.retries + 1):
            self._wait_for_slot()
            request = Request(
                url,
                data=encoded,
                method="POST",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "jobtracks-pilot/0.1 (public job data ingestion)",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    content = response.read()
                    if response.headers.get("Content-Encoding") == "gzip" or content[:2] == b"\x1f\x8b":
                        content = gzip.decompress(content)
                    result = json.loads(content.decode(charset, errors="replace"))
                if not isinstance(result, dict):
                    raise RuntimeError(f"Expected a JSON object from {url}")
                return result
            except HTTPError as exc:
                last_error = exc
                if exc.code not in RETRYABLE_STATUS_CODES or attempt >= self.retries:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError, gzip.BadGzipFile) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"Request failed for {url}: {last_error}") from last_error


class _ReadableHTMLParser(HTMLParser):
    block_tags = {
        "address", "article", "blockquote", "div", "h1", "h2", "h3", "h4",
        "h5", "h6", "li", "ol", "p", "section", "table", "td", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.parts.append("\n")
        elif tag in self.block_tags:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(value: Any) -> str | None:
    source = str(value or "")
    if not source:
        return None
    parser = _ReadableHTMLParser()
    parser.feed(source)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if line:
            cleaned.append(line)
        elif cleaned and cleaned[-1] != "":
            cleaned.append("")
    return "\n".join(cleaned).strip() or None
