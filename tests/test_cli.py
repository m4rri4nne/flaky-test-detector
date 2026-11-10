from flaky_detector import __main__ as cli

from .conftest import junit


def write(tmp_path, name, sha, passed):
    f = tmp_path / name
    body = '<testcase classname="m" name="t"/>' if passed else \
        '<testcase classname="m" name="t"><failure message="x"/></testcase>'
    f.write_text(junit(body, sha=sha))
    return str(f)


def make_flaky_files(tmp_path, commits=5):
    files = []
    for i in range(commits):
        files.append(write(tmp_path, f"p{i}.xml", f"c{i}", True))
        files.append(write(tmp_path, f"f{i}.xml", f"c{i}", False))
    return files


def test_reports_flaky_and_exits_1(tmp_path, capsys):
    assert cli.main(["analyze", *make_flaky_files(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "1 flaky test(s)" in out and "m::t" in out and "5/5" in out


def test_no_flaky_exits_0(tmp_path, capsys):
    files = [write(tmp_path, f"{i}.xml", f"c{i}", True) for i in range(6)]
    assert cli.main(["analyze", *files]) == 0
    assert "No flaky tests" in capsys.readouterr().out


def test_min_commits_hides_small_samples(tmp_path):
    assert cli.main(["analyze", *make_flaky_files(tmp_path, 3)]) == 0
    assert cli.main(["analyze", "--min-commits", "3", *make_flaky_files(tmp_path, 3)]) == 1


def test_bad_xml_exits_2(tmp_path, capsys):
    bad = tmp_path / "bad.xml"
    bad.write_text("<nope")
    assert cli.main(["analyze", str(bad)]) == 2
    assert "error:" in capsys.readouterr().err


def test_invalid_threshold_exits_2(tmp_path, capsys):
    assert cli.main(["analyze", "--threshold", "5", *make_flaky_files(tmp_path, 1)]) == 2


def test_requires_files_or_repo(capsys):
    assert cli.main(["analyze"]) == 2
    assert "--repo" in capsys.readouterr().err


def test_repo_mode_uses_github_fetch(monkeypatch, capsys):
    from flaky_detector.parsers import Outcome, TestResult

    rows = []
    for i in range(5):
        rows += [TestResult("a::t", Outcome.PASSED, f"c{i}", "1"),
                 TestResult("a::t", Outcome.FAILED, f"c{i}", "2")]
    monkeypatch.setattr(cli, "fetch_junit_results", lambda repo, last_runs: rows)
    assert cli.main(["analyze", "--repo", "o/r", "--last-runs", "7"]) == 1
    assert "o/r" in capsys.readouterr().out


def test_github_error_exits_2(monkeypatch, capsys):
    def boom(repo, last_runs):
        raise cli.GitHubError("no token")

    monkeypatch.setattr(cli, "fetch_junit_results", boom)
    assert cli.main(["analyze", "--repo", "o/r"]) == 2
    assert "no token" in capsys.readouterr().err


def test_output_dir_writes_json_csv_markdown(tmp_path, capsys):
    import csv
    import json

    out = tmp_path / "out"
    files = make_flaky_files(tmp_path)
    assert cli.main(["analyze", "--output-dir", str(out), *files]) == 1
    assert sorted(p.name for p in out.iterdir()) == [
        "flaky-report.csv", "flaky-report.json", "flaky-report.md"]

    data = json.loads((out / "flaky-report.json").read_text(encoding="utf-8"))
    assert data["flaky_count"] == 1 and data["tests"][0]["name"] == "m::t"
    assert data["tests"][0]["is_flaky"] is True

    rows = list(csv.DictReader((out / "flaky-report.csv").open(encoding="utf-8")))
    assert rows[0]["test"] == "m::t" and rows[0]["flaky_commits"] == "5"

    assert "`m::t`" in (out / "flaky-report.md").read_text(encoding="utf-8")


def test_formats_limits_output(tmp_path):
    out = tmp_path / "out"
    cli.main(["analyze", "--output-dir", str(out), "--formats", "json",
              *make_flaky_files(tmp_path)])
    assert [p.name for p in out.iterdir()] == ["flaky-report.json"]


def test_invalid_format_exits_2(tmp_path):
    assert cli.main(["analyze", "--formats", "xml", *make_flaky_files(tmp_path, 1)]) == 2


def test_report_written_even_without_flaky(tmp_path):
    out = tmp_path / "out"
    files = [write(tmp_path, f"{i}.xml", f"c{i}", True) for i in range(6)]
    assert cli.main(["analyze", "--output-dir", str(out), *files]) == 0
    assert "No flaky tests" in (out / "flaky-report.md").read_text(encoding="utf-8")
