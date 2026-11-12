"""Smoke test against the sample files in results/ (skipped if they are absent)."""

from pathlib import Path

import pytest

from flaky_detector.parsers import JUnitParser
from flaky_detector.scoring import rank_results

RESULTS = sorted((Path(__file__).resolve().parent.parent / "results").glob("*.xml"))


@pytest.mark.skipif(not RESULTS, reason="no sample files")
def test_sample_files_parse_and_rank():
    results = JUnitParser().parse_files(RESULTS)
    assert results and all(r.commit_sha for r in results)
    ranked = rank_results(results, threshold=0.1, min_commits=1)
    assert ranked == sorted(ranked, key=lambda s: (-s.lower_bound, -s.score, -s.flaky_commits, s.name)
    )
