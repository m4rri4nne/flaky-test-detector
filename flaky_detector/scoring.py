"""Flakiness scoring and ranking.

A test is flaky on a commit when it both passed and failed on that same commit.
The score of a test is ``flaky_commits / commits`` (see README). Ranking and the
flaky threshold use the lower bound of its 95% Wilson interval instead, so tests
with few commits aren't over-reported.
"""

from __future__ import annotations

import math
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


@dataclass(frozen=True)
class TestScore:
    """Flakiness score of a single test."""

    __test__ = False  # keep pytest from trying to collect this class

    name: str
    commits: int  # commits with usable data for this test
    flaky_commits: int  # commits where the test had mixed outcomes
    commits_where_flaky: tuple[str, ...] = field(default=())
    error_messages: tuple[str, ...] = field(default=())  # distinct failure messages, first seen first

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
        # test name -> commit sha -> set of "passed" booleans seen
        outcomes: dict[str, dict[str, set[bool]]] = defaultdict(lambda: defaultdict(set))
        messages: dict[str, dict[str, None]] = defaultdict(dict)  # ordered, de-duplicated
        for r in results:
            if not r.commit_sha or r.outcome.value == "skipped":
                continue
            outcomes[r.name][r.commit_sha].add(r.passed)
            if not r.passed and r.message:
                messages[r.name][r.message] = None

        scores = []
        for name, by_commit in outcomes.items():
            flaky = tuple(sorted(sha for sha, seen in by_commit.items() if len(seen) > 1))
            scores.append(
                TestScore(
                    name=name,
                    commits=len(by_commit),
                    flaky_commits=len(flaky),
                    commits_where_flaky=flaky,
                    error_messages=tuple(messages[name]),
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
