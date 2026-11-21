from flaky_detector.report import slim_report
from flaky_detector.trend import compute_trends, rising


def _report(score, flaky=False):
    return {"generated_at": "2026-01-01T00:00:00+00:00",
            "tests": [{"name": "a::t", "score": score, "is_flaky": flaky, "commits_where_flaky": ["x"]},
                      {"name": "a::ok", "score": 0.0, "is_flaky": False}]}


def test_rising_test_is_reported_before_it_is_flaky():
    trends = compute_trends([_report(0.02), _report(0.05), _report(0.09)])
    assert [t.name for t in rising(trends)] == ["a::t"]


def test_already_flaky_or_flat_tests_are_not_rising():
    assert rising(compute_trends([_report(0.1), _report(0.2), _report(0.3, flaky=True)])) == []
    assert rising(compute_trends([_report(0.05)] * 3)) == []


def test_slim_report_keeps_only_flaky_and_drops_commits():
    slim = slim_report(_report(0.3, flaky=True))
    assert [t["name"] for t in slim["tests"]] == ["a::t"]
    assert "commits_where_flaky" not in slim["tests"][0]
