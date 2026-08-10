"""Collect and parse NYSDOL apprenticeship announcements.

The scraper discovers every results page, collects each announcement, and (by
default) visits each detail page for its location, summary, full text, and
requirements. It uses only Python's standard library.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from html.parser import HTMLParser
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_URL = "https://dol.ny.gov/apprenticeship/apprenticeship-announcements"
USER_AGENT = "NYSDOL-Apprenticeship-Scraper/1.0 (+personal data collection)"
RETRYABLE_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}
DATE_RE = re.compile(
    r"Opening\s*Date\s*([^\s]+).*?Closing\s*Date\s*([^\s]+)", re.IGNORECASE
)


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: "Node | None" = None
    children: list["Node | str"] = field(default_factory=list)

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def descendants(self, include_self: bool = False) -> Iterator["Node"]:
        if include_self:
            yield self
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.descendants()

    def find_all(
        self,
        tag: str | None = None,
        class_name: str | None = None,
    ) -> list["Node"]:
        return [
            node
            for node in self.descendants()
            if (tag is None or node.tag == tag)
            and (class_name is None or class_name in node.classes())
        ]

    def find(
        self,
        tag: str | None = None,
        class_name: str | None = None,
    ) -> "Node | None":
        return next(iter(self.find_all(tag, class_name)), None)

    def text(self) -> str:
        return "".join(
            child if isinstance(child, str) else child.text() for child in self.children
        )


class DOMParser(HTMLParser):
    """Small, forgiving DOM builder sufficient for the server-rendered pages."""

    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.current = self.root

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        node = Node(tag.lower(), {key: value or "" for key, value in attrs}, self.current)
        self.current.children.append(node)
        if tag.lower() not in self.VOID_TAGS:
            self.current = node

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        node: Node | None = self.current
        while node is not None and node is not self.root:
            if node.tag == tag:
                self.current = node.parent or self.root
                return
            node = node.parent

    def handle_data(self, data: str) -> None:
        self.current.children.append(data)


def parse_html(html: str) -> Node:
    parser = DOMParser()
    parser.feed(html)
    parser.close()
    return parser.root


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def node_text(node: Node | None) -> str:
    return clean_text(node.text()) if node else ""


def formatted_text(node: Node | None) -> str:
    """Render body HTML as readable plain text while preserving lists/paragraphs."""
    if node is None:
        return ""

    chunks: list[str] = []
    block_tags = {"p", "div", "section", "article", "h1", "h2", "h3", "ul", "ol"}

    def walk(current: Node | str) -> None:
        if isinstance(current, str):
            chunks.append(current)
            return
        if current.tag == "br":
            chunks.append("\n")
            return
        is_block = current.tag in block_tags
        if is_block and chunks and not chunks[-1].endswith("\n"):
            chunks.append("\n")
        if current.tag == "li":
            if chunks and not chunks[-1].endswith("\n"):
                chunks.append("\n")
            chunks.append("- ")
        for child in current.children:
            walk(child)
        if (is_block or current.tag == "li") and chunks and not chunks[-1].endswith("\n"):
            chunks.append("\n")

    walk(node)
    lines = [clean_text(line) for line in "".join(chunks).splitlines()]
    return "\n".join(line for line in lines if line)


def inner_html(node: Node | None) -> str:
    if node is None:
        return ""

    def render(item: Node | str) -> str:
        if isinstance(item, str):
            return escape(item, quote=False)
        attrs = "".join(
            f' {escape(key)}="{escape(value, quote=True)}"'
            for key, value in item.attrs.items()
        )
        if item.tag in DOMParser.VOID_TAGS:
            return f"<{item.tag}{attrs}>"
        content = "".join(render(child) for child in item.children)
        return f"<{item.tag}{attrs}>{content}</{item.tag}>"

    return "".join(render(child) for child in node.children)


class HTTPClient:
    def __init__(self, timeout: float, retries: int, delay: float) -> None:
        self.timeout = timeout
        self.retries = retries
        self.delay = max(0.0, delay)
        self._rate_lock = threading.Lock()
        self._next_request_at = 0.0

    def _wait_for_rate_limit(self) -> None:
        with self._rate_lock:
            wait = self._next_request_at - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._next_request_at = time.monotonic() + self.delay

    def get(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.8",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.read().decode(charset, errors="replace")
            except HTTPError as exc:
                last_error = exc
                if exc.code not in RETRYABLE_HTTP_CODES or attempt >= self.retries:
                    raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
                retry_after = exc.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise RuntimeError(f"Could not fetch {url}: {exc}") from exc
                wait = 2**attempt
            logging.warning("Fetch failed; retrying %s in %.1fs", url, wait)
            time.sleep(wait)
        raise RuntimeError(f"Could not fetch {url}: {last_error}")


def page_url(base_url: str, page_number: int) -> str:
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page_number)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def iso_date(raw: str) -> str | None:
    value = raw.strip().rstrip(".,")
    for date_format in ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            pass
    return None


def parse_listing_page(html: str, base_url: str) -> tuple[list[dict[str, Any]], int, int | None]:
    root = parse_html(html)
    records: list[dict[str, Any]] = []

    for article in root.find_all("article"):
        if "teaser--type--webny-news" not in article.classes():
            continue
        title_wrapper = article.find(class_name="webny-teaser-title")
        title_link = title_wrapper.find("a") if title_wrapper else None
        href = title_link.attrs.get("href", "") if title_link else ""
        if not href:
            continue

        regions_text = node_text(article.find(class_name="webny-teaser-filter-terms"))
        posted_raw = node_text(article.find(class_name="news-listing-date"))
        teaser = node_text(article.find(class_name="webny-card-teaser"))
        opening_raw = closing_raw = ""
        match = DATE_RE.search(teaser)
        if match:
            opening_raw, closing_raw = match.group(1), match.group(2)

        records.append(
            {
                "id": article.attrs.get("data-history-node-id", ""),
                "title": node_text(title_link),
                "regions": [part.strip() for part in regions_text.split(",") if part.strip()],
                "posted_date": iso_date(posted_raw),
                "posted_date_raw": posted_raw,
                "posted_time": node_text(article.find(class_name="news-listing-time")),
                "opening_date": iso_date(opening_raw),
                "opening_date_raw": opening_raw,
                "closing_date": iso_date(closing_raw),
                "closing_date_raw": closing_raw,
                "listing_summary": teaser,
                "url": urljoin(base_url, href),
            }
        )

    page_numbers = [0]
    for link in root.find_all("a"):
        href = link.attrs.get("href", "")
        query = parse_qs(urlparse(urljoin(base_url, href)).query)
        for value in query.get("page", []):
            if value.isdigit():
                page_numbers.append(int(value))

    total_node = root.find(class_name="results-total-number")
    total_text = node_text(total_node)
    expected_total = int(total_text) if total_text.isdigit() else None
    return records, max(page_numbers), expected_total


def parse_detail_page(html: str) -> dict[str, Any]:
    root = parse_html(html)
    press_body = root.find(class_name="press-body")
    body = None
    if press_body:
        # NYSDOL uses either class across otherwise identical announcement pages.
        body = press_body.find(class_name="webny-card-description")
        body = body or press_body.find(class_name="webny-card-teaser") or press_body
    requirements: list[str] = []
    if body:
        for item in body.find_all("li"):
            # Keep only top-level list items to avoid repeating nested bullets.
            ancestor = item.parent
            nested_in_li = False
            while ancestor is not None and ancestor is not body:
                if ancestor.tag == "li":
                    nested_in_li = True
                    break
                ancestor = ancestor.parent
            if not nested_in_li:
                text = node_text(item)
                if text:
                    requirements.append(text)

    title_wrapper = root.find(class_name="hero-news-title")
    title = title_wrapper.find("h1") if title_wrapper else None
    return {
        "title": node_text(title),
        "detail_posted_date": iso_date(node_text(root.find(class_name="webny-card-date"))),
        "location": node_text(root.find(class_name="hero-news-location")),
        "subtitle": node_text(root.find(class_name="press-teaser")),
        "description": formatted_text(body),
        "description_html": inner_html(body),
        "requirements": requirements,
    }


def scrape_detail(client: HTTPClient, record: dict[str, Any]) -> dict[str, Any]:
    logging.info("Detail: %s", record["url"])
    detail = parse_detail_page(client.get(record["url"]))
    # The listing title is authoritative for output; retain differences for diagnostics.
    detail_title = detail.pop("title", "")
    if detail_title and detail_title != record["title"]:
        detail["detail_title"] = detail_title
    return {**record, **detail}


def scrape(
    client: HTTPClient,
    base_url: str,
    include_details: bool,
    limit: int | None,
    workers: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    logging.info("Listing page: %s", base_url)
    first_html = client.get(base_url)
    first_records, last_page, expected_total = parse_listing_page(first_html, base_url)
    records = first_records

    for page_number in range(1, last_page + 1):
        if limit is not None and len(records) >= limit:
            break
        url = page_url(base_url, page_number)
        logging.info("Listing page: %s", url)
        page_records, discovered_last, page_total = parse_listing_page(client.get(url), base_url)
        records.extend(page_records)
        last_page = max(last_page, discovered_last)
        if expected_total is None:
            expected_total = page_total

    # Preserve site order while removing any duplicate URLs caused by live updates.
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        unique.setdefault(record["url"], record)
    records = list(unique.values())
    if limit is not None:
        records = records[:limit]

    if include_details and records:
        completed: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = {executor.submit(scrape_detail, client, item): item for item in records}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    completed[item["url"]] = future.result()
                except Exception as exc:
                    logging.error("Detail failed for %s: %s", item["url"], exc)
                    completed[item["url"]] = {**item, "detail_error": str(exc)}
        records = [completed[item["url"]] for item in records]

    metadata = {
        "source_url": base_url,
        "scraped_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "record_count": len(records),
        "site_reported_count": expected_total,
        "details_included": include_details,
    }
    return records, metadata
