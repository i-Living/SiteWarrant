import hashlib
import json

from app.rules.catalog import RULES
from app.tools.axe import AXE_VERSION


def compute_agent_version(viewport: str, page_timeout_ms: int) -> str:
    """Hash of everything that changes what an audit claims.

    Prompts, models and the rule corpus join this payload in P3 and P4. Until then the
    catalog and the tool configuration are the whole story.
    """
    payload = {
        "rules": [rule.model_dump(mode="json") for rule in RULES],
        "axe_version": AXE_VERSION,
        "viewport": viewport,
        "page_timeout_ms": page_timeout_ms,
        "tools": ["axe", "dom_probe"],
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()[:16]}"
