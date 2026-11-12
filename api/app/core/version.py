import hashlib
import json

from app.crawl.version import crawl_digest
from app.rules.catalog import RULES
from app.tools import dom_probe
from app.tools.axe import AXE_VERSION


def compute_agent_version(
    *,
    viewport: str,
    page_timeout_ms: int,
    capture_timeout_ms: int,
    user_agent: str,
) -> str:
    """Hash of everything that changes what an audit claims.

    The user agent matters because a site can serve different HTML to different agents,
    the probe digest matters because a change to the probe changes the facts a finding
    rests on, and the crawl digest matters because discovery decides which pages are
    audited at all. Prompts, models and the rule corpus join this payload in P3 and P4.
    """
    payload = {
        "rules": [rule.model_dump(mode="json") for rule in RULES],
        "axe_version": AXE_VERSION,
        "dom_probe": hashlib.sha256(dom_probe.PROBE_SCRIPT.encode("utf-8")).hexdigest()[:16],
        "crawl": crawl_digest(),
        "viewport": viewport,
        "page_timeout_ms": page_timeout_ms,
        "capture_timeout_ms": capture_timeout_ms,
        "user_agent": user_agent,
        "tools": ["axe", "dom_probe"],
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()[:16]}"
