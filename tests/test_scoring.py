import pytest

from flaky_detector.parsers import Outcome
from flaky_detector.scoring import FlakinessRanker, FlakinessScorer, TestScore, rank_results, wilson_interval

P, F, E, S = Outcome.PASSED, Outcome.FAILED, Outcome.ERROR, Outcome.SKIPPED


def score_of(results, name="a::t"):
    return {s.name: s for s in FlakinessScorer().score(results)}[name]


def test_mixed_outcomes_on_same_commit_is_flaky(make_result):
    s = score_of([make_result(outcome=P), make_result(outcome=F)])
    assert (s.commits, s.flaky_commits, s.score) == (1, 1, 1.0)
    assert s.commits_where_flaky == ("c1",)


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


def test_commits_where_flaky_sorted(make_result):
    results = []
    for sha in ("z", "a", "m"):
        results += [make_result(sha=sha, outcome=P), make_result(sha=sha, outcome=F)]
    assert score_of(results).commits_where_flaky == ("a", "m", "z")


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
    assert [s.name for s in FlakinessRanker(threshold=0.2, min_commits=1).flaky(scores)] == ["hi"]
    # threshold 0 must still not report stable tests
    assert "zero" not in [s.name for s in FlakinessRanker(threshold=0, min_commits=1).flaky(scores)]


def test_threshold_boundary_is_inclusive():
    t = TestScore("t", 10, 5)
    assert FlakinessRanker(threshold=t.lower_bound, min_commits=1).flaky([t])
    assert not FlakinessRanker(threshold=t.lower_bound + 0.01, min_commits=1).flaky([t])


# -- Wilson interval --------------------------------------------------------

def test_wilson_interval_known_values():
    lo, hi = wilson_interval(1, 5)
    assert lo == pytest.approx(0.036, abs=0.005) and hi == pytest.approx(0.624, abs=0.005)
    lo, hi = wilson_interval(200, 1000)
    assert lo == pytest.approx(0.176, abs=0.005) and hi == pytest.approx(0.226, abs=0.005)


def test_wilson_interval_edges():
    assert wilson_interval(0, 0) == (0.0, 0.0)
    lo, hi = wilson_interval(0, 5)
    assert lo == 0.0 and 0.0 < hi < 1.0
    lo, hi = wilson_interval(5, 5)
    assert 0.0 < lo < 1.0 and hi == 1.0


def test_small_sample_ranks_below_large_sample_with_same_score():
    ranked = FlakinessRanker(min_commits=1).rank([TestScore("new", 5, 1), TestScore("old", 1000, 200)])
    assert [s.name for s in ranked] == ["old", "new"]
    assert TestScore("new", 5, 1).lower_bound < TestScore("old", 1000, 200).lower_bound
    assert TestScore("x", 0, 0).lower_bound == 0.0


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


def test_error_messages_are_distinct_failures_only(make_result):
    s = score_of([
        make_result(outcome=P, message="ignored"),
        make_result(outcome=F, message="timeout"),
        make_result(outcome=E, message="boom"),
        make_result(sha="c2", outcome=F, message="timeout"),
        make_result(outcome=F),  # no message
    ])
    assert s.error_messages == ("timeout", "boom")
