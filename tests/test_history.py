from datetime import datetime, timedelta, timezone

from flaky_detector.__main__ import main
from flaky_detector.history import HistoryStore
from flaky_detector.scoring import FlakinessRanker, TestScore
from flaky_detector.trend import render_html, render_text

RANKER = FlakinessRanker(threshold=0.1, min_commits=5)
T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def score(name, flaky, commits=10):
    return TestScore(name=name, commits=commits, flaky_commits=flaky)


def make_store(tmp_path):
    store = HistoryStore(tmp_path / "h.db")
    store.save([score("a", 3), score("b", 0), score("tiny", 1, commits=2)],
               RANKER, "repo", T0)
    store.save([score("a", 4), score("b", 2), score("c", 5)],
               RANKER, "repo", T0 + timedelta(days=7))
    return store


def test_save_counts_only_eligible_and_flaky(tmp_path):
    store = make_store(tmp_path)
    first, second = store.snapshots()
    assert (first.tests_total, first.flaky_count) == (2, 1)  # "tiny" has too little data
    assert (second.tests_total, second.flaky_count) == (3, 3)


def test_diff_new_and_fixed(tmp_path):
    store = make_store(tmp_path)
    first, second = store.snapshots()
    d = store.diff(first.id, second.id)
    assert d.new == ("b", "c") and d.fixed == ()
    assert store.diff(second.id, first.id).fixed == ("b", "c")


def test_test_history_has_none_for_missing(tmp_path):
    store = make_store(tmp_path)
    ids = [s.id for s in store.snapshots()]
    assert store.test_history(ids, ["c"])["c"] == [None, 0.5]


def test_source_filter(tmp_path):
    store = make_store(tmp_path)
    store.save([score("a", 1)], RANKER, "other", T0)
    assert len(store.snapshots()) == 3 and len(store.snapshots("repo")) == 2


def test_reports_render(tmp_path):
    store = make_store(tmp_path)
    text, html = render_text(store), render_html(store)
    assert "up" in text and "+2" in text
    assert "<svg" in html and "Flaky tests trend" in html


def test_empty_history_reports(tmp_path):
    store = HistoryStore(tmp_path / "e.db")
    assert "No snapshots" in render_text(store)
    assert "No snapshots" in render_html(store)


def test_cli_save_history_and_trend(tmp_path, capsys):
    db = tmp_path / "h.db"
    import glob
    files = sorted(glob.glob("results/*.xml"))
    main(["analyze", *files, "--save-history", str(db)])
    main(["analyze", *files, "--save-history", str(db)])
    out = tmp_path / "t.html"
    assert main(["trend", "--db", str(db), "--format", "html", "-o", str(out)]) == 0
    assert out.read_text().count("<polyline") >= 2
    assert main(["trend", "--db", str(tmp_path / "missing.db")]) == 2
    with HistoryStore(db) as store:
        assert len(store.snapshots("local")) == 2
