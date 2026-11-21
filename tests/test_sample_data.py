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


# -- generator: matrix mode ---------------------------------------------------


def _generate(tmp_path, *extra):
    import subprocess
    import sys

    script = Path(__file__).resolve().parent.parent / "scripts" / "generate_junit.py"
    out = tmp_path / "gen"
    subprocess.run([sys.executable, str(script), "--commits", "8", "--runs", "2",
                    "--out", str(out), *extra], check=True, capture_output=True)
    return sorted(out.glob("*.xml"))


def test_generator_default_output_has_no_env(tmp_path):
    files = _generate(tmp_path)
    assert len(files) == 16
    assert all(r.env is None for r in JUnitParser(env_properties=["python"]).parse_files(files))
    results = JUnitParser().parse_files(files)
    assert sum(r.passed for r in results) > 0.8 * len(results)  # most tests are stable


def test_generator_matrix_yields_config_dependent_tests_not_flaky(tmp_path):
    from flaky_detector.scoring import FlakinessScorer

    files = _generate(tmp_path, "--env", "python=3.12,3.13")
    assert len(files) == 32  # 8 commits x 2 runs x 2 legs
    scores = FlakinessScorer().score(JUnitParser(env_properties=["python"]).parse_files(files))
    # a flaky test can look config-dependent on one commit by chance (few runs per leg),
    # so only the ones that differ across envs on *every* commit are the seeded ones
    config_dependent = [s for s in scores if len(s.config_dependent_commits) == s.commits]
    assert config_dependent
    assert all(s.flaky_commits == 0 for s in config_dependent)
    # without the env dimension the same tests are false positives
    naive = FlakinessScorer().score(JUnitParser().parse_files(files))
    flagged = {s.name for s in naive if s.flaky_commits == s.commits}
    assert {s.name for s in config_dependent} <= flagged
