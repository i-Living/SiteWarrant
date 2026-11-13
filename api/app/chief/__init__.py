"""The Chief Auditor's deterministic layer: dedupe, clusters, priority.

The model-facing narrator arrives later; it explains these groups and never decides them.
"""

from app.chief.cluster import ChiefResult, cluster, dedupe, finding_priority, run_chief

__all__ = ["ChiefResult", "cluster", "dedupe", "finding_priority", "run_chief"]
