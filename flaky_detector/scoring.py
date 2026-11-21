"""Flakiness scoring and ranking.

A test is flaky on a commit when it both passed and failed on that same commit
*in the same environment*. When results carry an ``env`` (opt-in, see
:class:`~flaky_detector.parsers.JUnitParser`), a commit where every environment is
consistent but they disagree with each other (pass on 3.12, fail on 3.13) is not
flaky: it is counted as config-dependent. Without ``env`` nothing changes.
The score of a test is ``flaky_commits / commits`` (see README). Ranking and the
flaky threshold use the lower bound of its 95% Wilson interval instead, so tests
with few commits aren't over-reported.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from .parsers import TestResult


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion (``z=1.96`` is 95% confidence)."""
    if n <= 0:
        return 0.0, 0.0
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile of an already sorted, non-empty list."""
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


@dataclass(frozen=True)
class TestScore:
    """Flakiness score of a single test."""

    __test__ = False  # keep pytest from trying to collect this class

    name: str
    commits: int  # commits with usable data for this test
    flaky_commits: int  # commits where the test had mixed outcomes
    commits_where_flaky: tuple[str, ...] = field(default=())
    # commits where each environment was consistent but environments disagreed
    config_dependent_commits: tuple[str, ...] = field(default=())
    error_messages: tuple[str, ...] = field(default=())  # distinct failure messages, first seen first
    runs: int = 0  # executions behind the score (retries inside a job count too)
    flaky_commit_runs: tuple[tuple[str, int], ...] = field(default=())  # (sha, runs) per flaky commit
    duration_median: float | None = None  # seconds, over runs that reported a time
    duration_p95: float | None = None
    sample_trace: str | None = None  # truncated stack trace of the first failure that had one

    @property
    def score(self) -> float:
        return self.flaky_commits / self.commits if self.commits else 0.0

    @property
    def confidence_interval(self) -> tuple[float, float]:
        """95% Wilson interval for the true flakiness rate."""
        return wilson_interval(self.flaky_commits, self.commits)

    @property
    def lower_bound(self) -> float:
        """Conservative score: low when there is little data, close to ``score`` when there is a lot."""
        return self.confidence_interval[0]


class FlakinessScorer:
    """Turns raw :class:`TestResult` rows into one :class:`TestScore` per test.

    Results without a ``commit_sha`` are ignored (they can't be compared), and
    skipped results never count. ``failed`` and ``error`` both count as a failure.
    """

    def score(self, results: Iterable[TestResult]) -> list[TestScore]:
        # test name -> commit sha -> env -> set of "passed" booleans seen
        outcomes: dict[str, dict[str, dict[str | None, set[bool]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(set))
        )
        messages: dict[str, dict[str, None]] = defaultdict(dict)  # ordered, de-duplicated
        runs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        times: dict[str, list[float]] = defaultdict(list)
        traces: dict[str, str] = {}
        for r in results:
            if not r.commit_sha or r.outcome.value == "skipped":
                continue
            outcomes[r.name][r.commit_sha][r.env].add(r.passed)
            runs[r.name][r.commit_sha] += 1
            if r.time > 0:
                times[r.name].append(r.time)
            if not r.passed and r.trace:
                traces.setdefault(r.name, r.trace)
            if not r.passed and r.message:
                messages[r.name][r.message] = None

        scores = []
        for name, by_commit in outcomes.items():
            flaky, config_dependent = [], []
            for sha, by_env in by_commit.items():
                if any(len(seen) > 1 for seen in by_env.values()):
                    flaky.append(sha)
                elif len(set().union(*by_env.values())) > 1:
                    config_dependent.append(sha)
            durations = sorted(times[name])
            scores.append(
                TestScore(
                    name=name,
                    commits=len(by_commit),
                    flaky_commits=len(flaky),
                    commits_where_flaky=tuple(sorted(flaky)),
                    config_dependent_commits=tuple(sorted(config_dependent)),
                    error_messages=tuple(messages[name]),
                    runs=sum(runs[name].values()),
                    flaky_commit_runs=tuple((sha, runs[name][sha]) for sha in sorted(flaky)),
                    duration_median=statistics.median(durations) if durations else None,
                    duration_p95=_percentile(durations, 0.95) if durations else None,
                    sample_trace=traces.get(name),
                )
            )
        return scores


class FlakinessRanker:
    """Ranks scores from most to least unstable.

    ``min_commits`` drops tests with too little data to be trusted;
    ``threshold`` is the minimum Wilson lower bound (see :attr:`TestScore.lower_bound`)
    for a test to be considered flaky. Ranking uses the same lower bound, so tests
    with little data don't outrank well-observed ones.
    """

    def __init__(self, threshold: float = 0.1, min_commits: int = 5) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        if min_commits < 1:
            raise ValueError("min_commits must be >= 1")
        self.threshold = threshold
        self.min_commits = min_commits

    def rank(self, scores: Iterable[TestScore]) -> list[TestScore]:
        """All tests with enough data, worst first (by lower bound; ties: score, flaky commits, name)."""
        eligible = (s for s in scores if s.commits >= self.min_commits)
        return sorted(
            eligible, key=lambda s: (-s.lower_bound, -s.score, -s.flaky_commits, s.name)
        )

    def flaky(self, scores: Iterable[TestScore]) -> list[TestScore]:
        """Ranked tests whose lower bound is at or above the threshold (and above zero)."""
        return [
            s for s in self.rank(scores) if s.lower_bound > 0 and s.lower_bound >= self.threshold
        ]


def rank_results(
    results: Iterable[TestResult], threshold: float = 0.1, min_commits: int = 5
) -> list[TestScore]:
    """Convenience: score ``results`` and return the flaky tests, worst first."""
    ranker = FlakinessRanker(threshold=threshold, min_commits=min_commits)
    return ranker.flaky(FlakinessScorer().score(results))
