from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

from pydantic import BaseModel

SKIP_SCHEMES = frozenset({"mailto", "tel", "javascript", "data", "blob", "about", "file"})
SKIP_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".avif",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".mp4",
    ".mp3",
    ".webm",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".xml",
    ".txt",
    ".woff",
    ".woff2",
    ".ttf",
)


class ParsedPage(BaseModel):
    links: list[str]
    nofollow: bool
    canonical: str | None
    has_text: bool


def is_crawlable(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    if parts.hostname is None:
        return False
    path = parts.path.lower()
    return not path.endswith(SKIP_EXTENSIONS)


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.nofollow = False
        self.canonical: str | None = None
        self.base_href: str | None = None
        self.has_text = False
        self._in_body = False
        self._skip_text = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "body":
            self._in_body = True
        elif tag in ("script", "style", "template"):
            self._skip_text = True
        elif tag == "base" and values.get("href"):
            self.base_href = values["href"]
        elif tag in ("a", "area") and values.get("href"):
            if "nofollow" in values.get("rel", "").lower().split():
                self.nofollow = True
            self.hrefs.append(values["href"])
        elif tag == "meta":
            name = values.get("name", "").lower()
            content = values.get("content", "").lower()
            if name in ("robots", "googlebot") and ("nofollow" in content or "none" in content):
                self.nofollow = True
        elif (
            tag == "link"
            and "canonical" in values.get("rel", "").lower().split()
            and values.get("href")
        ):
            self.canonical = values["href"]

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "template"):
            self._skip_text = False

    def handle_data(self, data: str) -> None:
        if self._in_body and not self._skip_text and data.strip():
            self.has_text = True


def parse_html(html: str, page_url: str) -> ParsedPage:
    """Extract crawlable links, the nofollow flag and whether the body has any text.

    `has_text` is what tells an app shell from a rendered page: an empty body with no links
    is a JavaScript-rendered page, and the crawler re-reads it through the browser.
    """
    collector = _LinkCollector()
    collector.feed(html)
    base = urljoin(page_url, collector.base_href) if collector.base_href else page_url
    links: list[str] = []
    seen: set[str] = set()
    for href in collector.hrefs:
        absolute = urldefrag(urljoin(base, href))[0]
        if not is_crawlable(absolute) or absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    canonical = urljoin(base, collector.canonical) if collector.canonical else None
    return ParsedPage(
        links=links,
        nofollow=collector.nofollow,
        canonical=canonical,
        has_text=collector.has_text,
    )
