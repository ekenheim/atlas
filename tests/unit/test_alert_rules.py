"""The alert rules file is a well-formed PrometheusRule (promtool isn't available in CI).

That each rule's metrics are ones `/metrics` exposes is checked in
`tests/integration/test_queue_pause.py`.
"""

import re
from pathlib import Path
from typing import Any, cast

import yaml

RULES = Path(__file__).parents[2] / "configs" / "prometheus" / "atlas-alerts.yaml"
DURATION = r"^\d+[smh]$"


def _rules() -> list[dict[str, Any]]:
    document = cast(dict[str, Any], yaml.safe_load(RULES.read_text(encoding="utf-8")))
    assert document["apiVersion"] == "monitoring.coreos.com/v1"
    assert document["kind"] == "PrometheusRule"
    assert document["metadata"]["name"] == "atlas"
    groups = cast(list[dict[str, Any]], document["spec"]["groups"])
    assert len({group["name"] for group in groups}) == len(groups)
    return [rule for group in groups for rule in group["rules"]]


def test_every_alert_rule_has_an_expression_severity_and_summary() -> None:
    rules = _rules()

    assert {rule["alert"] for rule in rules} == {
        "AtlasHindsightOperationsFailing",
        "AtlasJobsFailing",
        "AtlasZeroFactSpike",
        "AtlasMemoryDrift",
        "AtlasMemoryReconciliationStale",
        "AtlasMemoryReconciliationFailed",
        "AtlasFinancialNormalizationFailing",
        "AtlasQueuePausedLong",
        "AtlasStateMetricsDown",
    }
    for rule in rules:
        assert set(rule) <= {"alert", "expr", "for", "labels", "annotations"}, rule["alert"]
        assert isinstance(rule["expr"], str) and "atlas_" in rule["expr"]
        assert rule["expr"].count("(") == rule["expr"].count(")")
        assert rule["labels"]["severity"] in {"warning", "critical"}
        assert rule["annotations"]["summary"]
        if "for" in rule:
            assert re.match(DURATION, rule["for"]), rule["alert"]
