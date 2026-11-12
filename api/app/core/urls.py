from urllib.parse import urlsplit


def page_key(url: str) -> str:
    """Identity of a page for matching and metrics.

    Scheme, query and fragment are dropped, the trailing slash is stripped, the host is
    lowercased. Changing this function changes precision and recall, so it is an
    "ask first" change in AGENTS.md.
    """
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return f"{parts.hostname or ''}{path}"
