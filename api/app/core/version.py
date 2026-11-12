import hashlib
import json

from app.crawl.version import crawl_digest
from app.rules.catalog import RULES
from app.tools import contrast, dom_probe, occlusion, performance, responsive
from app.tools.axe import AXE_VERSION

AUDIT_TOOLS = (
    "http",
    "dom",
    "axe",
    "contrast",
    "responsive",
    "occlusion",
    "performance",
    "screenshot",
)


def probe_digest(script: str) -> str:
    return hashlib.sha256(script.encode("utf-8")).hexdigest()[:16]


def compute_agent_version(
    *,
    viewports: tuple[str, ...],
    page_timeout_ms: int,
    capture_timeout_ms: int,
    user_agent: str,
) -> str:
    """Hash of everything that changes what an audit claims.

    The user agent matters because a site can serve different HTML to different agents, the
    probe digests matter because a change to a probe changes the facts a finding rests on,
    and the crawl digest matters because discovery decides which pages are audited at all.
    Prompts, models and the rule corpus join this payload in P3 and P4.
    """
    payload = {
        "rules": [rule.model_dump(mode="json") for rule in RULES],
        "axe_version": AXE_VERSION,
        "probes": {
            "dom": probe_digest(dom_probe.PROBE_SCRIPT),
            "contrast": probe_digest(contrast.COLLECT_SCRIPT),
            "responsive": probe_digest(responsive.PROBE_SCRIPT),
            "occlusion": probe_digest(occlusion.PROBE_SCRIPT),
            "performance": probe_digest(performance.PROBE_SCRIPT),
        },
        "crawl": crawl_digest(),
        "viewports": list(viewports),
        "page_timeout_ms": page_timeout_ms,
        "capture_timeout_ms": capture_timeout_ms,
        "user_agent": user_agent,
        "tools": list(AUDIT_TOOLS),
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()[:16]}"
