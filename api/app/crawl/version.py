import hashlib
from pathlib import Path

CRAWL_SOURCES = ("crawler.py", "links.py", "models.py", "sitemap.py", "templates.py")


def crawl_digest() -> str:
    """Digest of the discovery code, so a clustering change cannot hide in agent_version.

    Which pages get audited is part of the verdict: the same site can produce a different
    report if the crawler changes its URL normalisation or its template grouping. Hashing
    the sources makes that visible without a manual version constant. The modules are read
    from disk, not imported, so this cannot create an import cycle.
    """
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in CRAWL_SOURCES:
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()[:16]
