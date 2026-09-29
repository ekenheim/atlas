"""Hypotheses (spec §5.6, §8.1; Phase 4 "Thesis lifecycle", "dossier export"): an
investigation's result saved as a versioned, falsifiable research object.

`model` is what the API shows (lifecycle, immutable versions, transitions); `service` changes
it (save, transitions, corrections as new versions, publish behind the pluggable gate);
`drafting` is the `draft_hypothesis` job (the Editor drafts version 1); `findings` the rule
that a finding cites accepted Claims; `diff` compares two versions' claims; `export` writes
the dossier as JSON or Markdown with citations and run metadata.
"""

from atlas.hypotheses.diff import HypothesisDiff, diff_versions
from atlas.hypotheses.export import HypothesisExport, build_export, render_markdown
from atlas.hypotheses.handlers import register_hypothesis_handlers
from atlas.hypotheses.model import (
    DRAFT_HYPOTHESIS_KIND,
    HYPOTHESIS_STATUSES,
    TRANSITIONS,
    Hypothesis,
    HypothesisContent,
    HypothesisStatus,
    HypothesisVersion,
    Mechanism,
    get_hypothesis,
    get_version,
    list_hypotheses,
)
from atlas.hypotheses.service import (
    DEFAULT_PUBLISH_GATE,
    Correction,
    GateFailure,
    Hypotheses,
    HypothesisConflict,
    HypothesisError,
    HypothesisNotFound,
    PublishCheck,
    PublishHook,
    PublishRefused,
)

__all__ = [
    "DEFAULT_PUBLISH_GATE",
    "DRAFT_HYPOTHESIS_KIND",
    "HYPOTHESIS_STATUSES",
    "TRANSITIONS",
    "Correction",
    "GateFailure",
    "Hypotheses",
    "Hypothesis",
    "HypothesisConflict",
    "HypothesisContent",
    "HypothesisDiff",
    "HypothesisError",
    "HypothesisExport",
    "HypothesisNotFound",
    "HypothesisStatus",
    "HypothesisVersion",
    "Mechanism",
    "PublishCheck",
    "PublishHook",
    "PublishRefused",
    "build_export",
    "diff_versions",
    "get_hypothesis",
    "get_version",
    "list_hypotheses",
    "register_hypothesis_handlers",
    "render_markdown",
]
