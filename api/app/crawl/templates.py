import re
from urllib.parse import urlsplit

# A segment that identifies one record rather than one template: an id, a hex hash, a
# UUID. Slug-with-id ("post-1") is handled separately, because the words stay meaningful.
UUID_SEGMENT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
HEX_SEGMENT = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)
NUMERIC_SEGMENT = re.compile(r"^(?P<id>\d+)(?P<extension>\.[A-Za-z0-9]+)?$")
SLUG_WITH_ID = re.compile(r"^(?P<prefix>.+?)-(?P<id>\d+)(?P<extension>\.[A-Za-z0-9]+)?$")


def normalise_segment(segment: str) -> str:
    if UUID_SEGMENT.match(segment) or HEX_SEGMENT.match(segment):
        return "*"
    numeric = NUMERIC_SEGMENT.match(segment)
    if numeric:
        return f"*{numeric.group('extension') or ''}"
    slug = SLUG_WITH_ID.match(segment)
    if slug:
        return f"{slug.group('prefix')}-*{slug.group('extension') or ''}"
    return segment


def template_pattern(url: str) -> str:
    """Path pattern that groups pages built from the same template.

    Deterministic on purpose: no model call decides a cluster, because the cluster key ends
    up in published metrics. Ids become "*", words stay, so /blog/post-1.html and
    /blog/post-2.html share /blog/post-*.html while /about.html stays itself.
    """
    path = urlsplit(url).path or "/"
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return "/"
    return "/" + "/".join(normalise_segment(segment) for segment in segments)
