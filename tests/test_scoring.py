import pytest

from flaky_detector.parsers import Outcome
from flaky_detector.scoring import FlakinessRanker, FlakinessScorer, TestScore, rank_results

P, F, E, S = Outcome.PASSED, Outcome.FAILED, Outcome.ERROR, Outcome.SKIPPED


def score_of(results, name="a::t"):
    return {s.name: s for s in FlakinessScorer().score(results)}[name]


def test_mixed_outcomes_on_same_commit_is_flaky(make_result):
    s = score_of([make_result(outcome=P), make_result(outcome=F)])
    assert (s.commits, s.flaky_commits, s.score) == (1, 1, 1.0)
    assert s.flaky_shas == ("c1",)


def test_consistent_outcomes_are_not_flaky(make_result):
    s = score_of([make_result(outcome=F), make_result(outcome=F)])
    assert s.flaky_commits == 0 and s.score == 0.0


def test_failure_and_error_count_as_the_same_failure(make_result):
    s = score_of([make_result(outcome=F), make_result(outcome=E)])
    assert s.flaky_commits == 0


def test_pass_vs_error_is_flaky(make_result):
    assert score_of([make_result(outcome=P), make_result(outcome=E)]).flaky_commits == 1


def test_different_commits_do_not_mix(make_result):
    s = score_of([make_result(sha="c1", outcome=P), make_result(sha="c2", outcome=F)])
    assert s.commits == 2 and s.flaky_commits == 0


def test_ratio_matches_readme_example(make_result):
    results = []
    for i in range(10):
        results.append(make_result(sha=f"c{i}", outcome=P))
        if i < 3:
            results.append(make_result(sha=f"c{i}", outcome=F))
    s = score_of(results)
    assert s.commits == 10 and s.flaky_commits == 3
    assert s.score == pytest.approx(0.3)


def test_skipped_and_missing_sha_are_ignored(make_result):
    results = [
        make_result(outcome=S),
        make_result(sha=None, outcome=P),
        make_result(sha=None, outcome=F),
        make_result(sha="", outcome=F),
    ]
    assert FlakinessScorer().score(results) == []


def test_empty_input():
    assert FlakinessScorer().score([]) == []
    assert TestScore("x", 0, 0).score == 0.0


def test_scores_are_per_test(make_result):
    scores = FlakinessScorer().score([
        make_result(name="a", outcome=P), make_result(name="a", outcome=F),
        make_result(name="b", outcome=P),
    ])
    by = {s.name: s for s in scores}
    assert by["a"].flaky_commits == 1 and by["b"].flaky_commits == 0


def test_flaky_shas_sorted(make_result):
    results = []
    for sha in ("z", "a", "m"):
        results += [make_result(sha=sha, outcome=P), make_result(sha=sha, outcome=F)]
    assert score_of(results).flaky_shas == ("a", "m", "z")


# -- ranking ---------------------------------------------------------------

def test_rank_order_and_tiebreaks():
    scores = [
        TestScore("b", 10, 2), TestScore("a", 10, 2),   # tie -> by name
        TestScore("c", 5, 2),                           # 0.4 -> first
        TestScore("d", 20, 4),                          # 0.2, more flaky commits than a/b
    ]
    ranked = FlakinessRanker(min_commits=1).rank(scores)
    assert [s.name for s in ranked] == ["c", "d", "a", "b"]


def test_min_commits_filters():
    scores = [TestScore("few", 2, 2), TestScore("many", 10, 5)]
    assert [s.name for s in FlakinessRanker(min_commits=5).rank(scores)] == ["many"]


def test_flaky_applies_threshold_and_excludes_zero():
    scores = [TestScore("hi", 10, 5), TestScore("lo", 10, 1), TestScore("zero", 10, 0)]
    assert [s.name for s in FlakinessRanker(threshold=0.3, min_commits=1).flaky(scores)] == ["hi"]
    # threshold 0 must still not report stable tests
    assert "zero" not in [s.name for s in FlakinessRanker(threshold=0, min_commits=1).flaky(scores)]


def test_threshold_boundary_is_inclusive():
    assert FlakinessRanker(threshold=0.5, min_commits=1).flaky([TestScore("t", 10, 5)])


@pytest.mark.parametrize("kw", [{"threshold": -0.1}, {"threshold": 1.1}, {"min_commits": 0}])
def test_ranker_validates_arguments(kw):
    with pytest.raises(ValueError):
        FlakinessRanker(**kw)


def test_rank_results_end_to_end(make_result):
    results = []
    for i in range(5):
        results += [make_result(sha=f"c{i}", outcome=P), make_result(sha=f"c{i}", outcome=F)]
    out = rank_results(results, threshold=0.1, min_commits=5)
    assert [s.name for s in out] == ["a::t"] and out[0].score == 1.0
