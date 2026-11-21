"""Deterministic trend of flakiness scores across past JSON reports.

Catches tests that are creeping up (0.02 -> 0.05 -> 0.1) before they cross the
flaky threshold. Reads the ``flaky-report-*.json`` files written by ``analyze``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class TestTrend:
    __test__ = False

    name: str
    scores: tuple[float, ...]  # oldest -> newest, only the reports where the test appears
    slope: float  # least-squares change of score per report
    is_flaky: bool  # flagged in the newest report

    @property
    def delta(self) -> float:
        return self.scores[-1] - self.scores[0]


def load_reports(directory: str | Path, last: int = 10) -> list[dict]:
    """The ``last`` newest JSON reports in ``directory``, oldest first."""
    reports = []
    for path in Path(directory).glob("flaky-report*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        reports.append((datetime.fromisoformat(data["generated_at"]), data))
    reports.sort(key=lambda item: item[0])
    return [data for _, data in reports[-last:]]


def _slope(values: tuple[float, ...]) -> float:
    n = len(values)
    mean_x, mean_y = (n - 1) / 2, sum(values) / n
    var = sum((i - mean_x) ** 2 for i in range(n))
    return sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values)) / var if var else 0.0


def compute_trends(reports: list[dict], min_points: int = 3) -> list[TestTrend]:
    """One trend per test seen in at least ``min_points`` reports, steepest rise first."""
    series: dict[str, list[float]] = {}
    flaky_now: set[str] = set()
    for report in reports:
        for t in report.get("tests", []):
            series.setdefault(t["name"], []).append(t["score"])
    if reports:
        flaky_now = {t["name"] for t in reports[-1].get("tests", []) if t.get("is_flaky")}
    trends = [
        TestTrend(name, tuple(vals), _slope(tuple(vals)), name in flaky_now)
        for name, vals in series.items()
        if len(vals) >= min_points
    ]
    return sorted(trends, key=lambda t: (-t.slope, t.name))


def rising(trends: list[TestTrend], min_slope: float = 0.02) -> list[TestTrend]:
    """Tests whose score grows by at least ``min_slope`` per report and are not flagged yet."""
    return [t for t in trends if t.slope >= min_slope and not t.is_flaky]
