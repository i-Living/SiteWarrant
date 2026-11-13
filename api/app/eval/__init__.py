"""Evals: the frozen corpus, the runner that audits it, and the metrics it produces.

The corpus is `benchmark/dataset.json` plus the generated sites it points at. A finding is matched
to a label by rule and page path — the granularity the deterministic layer works at — so precision
and recall have honest denominators: every planted defect is a label, every reported finding is a
prediction, and the pages that were planted clean are the control for false positives.
"""

from app.eval.compare import Comparison, compare_runs
from app.eval.dataset import Dataset, SiteLabels, dataset_digest, load_dataset
from app.eval.metrics import Metrics, RuleMetrics, measure
from app.eval.models import EvalRun
from app.eval.runner import run_eval

__all__ = [
    "Comparison",
    "Dataset",
    "EvalRun",
    "Metrics",
    "RuleMetrics",
    "SiteLabels",
    "compare_runs",
    "dataset_digest",
    "load_dataset",
    "measure",
    "run_eval",
]
