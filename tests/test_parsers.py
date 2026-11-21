import pytest

from flaky_detector.parsers import JUnitParseError, JUnitParser, Outcome

from .conftest import junit


def parse(cases, **kw):
    return JUnitParser(**kw.pop("parser_kw", {})).parse_string(junit(cases, **kw))


def test_outcomes_and_names():
    results = parse(
        '<testcase classname="m.c" name="ok" time="0.5"/>'
        '<testcase classname="m.c" name="bad"><failure message="boom">trace</failure></testcase>'
        '<testcase classname="m.c" name="err"><error message="oops"/></testcase>'
    )
    by_name = {r.name: r for r in results}
    assert by_name["m.c::ok"].outcome is Outcome.PASSED
    assert by_name["m.c::ok"].time == 0.5
    assert by_name["m.c::bad"].outcome is Outcome.FAILED
    assert by_name["m.c::bad"].message == "boom"
    assert by_name["m.c::err"].outcome is Outcome.ERROR


def test_name_without_classname():
    assert parse('<testcase name="solo"/>')[0].name == "solo"


def test_message_falls_back_to_text():
    r = parse('<testcase name="t"><failure>only text</failure></testcase>')[0]
    assert r.message == "only text"


def test_error_wins_over_failure():
    r = parse('<testcase name="t"><failure message="f"/><error message="e"/></testcase>')[0]
    assert r.outcome is Outcome.ERROR


def test_skipped_dropped_by_default_and_kept_on_request():
    case = '<testcase name="t"><skipped/></testcase>'
    assert parse(case) == []
    assert parse(case, parser_kw={"include_skipped": True})[0].outcome is Outcome.SKIPPED


def test_properties_from_suite_and_case_override():
    r = parse(
        '<testcase name="t"><properties>'
        '<property name="commit_sha" value="override"/></properties></testcase>'
    )[0]
    assert r.commit_sha == "override"
    assert r.run_id == "7"  # inherited from the suite


def test_missing_properties_are_none():
    r = parse('<testcase name="t"/>', sha=None, run_id=None)[0]
    assert r.commit_sha is None and r.run_id is None


def test_defaults_fill_only_what_xml_lacks():
    xml = junit('<testcase name="t"/>', sha=None, run_id="from-xml")
    r = JUnitParser().parse_string(xml, default_commit_sha="gh-sha", default_run_id="gh-run")[0]
    assert r.commit_sha == "gh-sha"
    assert r.run_id == "from-xml"


def test_bare_testsuite_root_and_nested_suites():
    xml = '<testsuite><testcase name="a"/></testsuite>'
    assert len(JUnitParser().parse_string(xml)) == 1
    nested = '<testsuites><testsuite><testcase name="a"/></testsuite><testsuite><testcase name="b"/></testsuite></testsuites>'
    assert {r.name for r in JUnitParser().parse_string(nested)} == {"a", "b"}


def test_invalid_time_and_nameless_case():
    results = parse('<testcase name="t" time="abc"/><testcase classname="x"/>')
    assert len(results) == 1 and results[0].time == 0.0


def test_accepts_bytes():
    assert len(JUnitParser().parse_string(junit('<testcase name="t"/>').encode())) == 1


def test_invalid_xml_raises():
    with pytest.raises(JUnitParseError):
        JUnitParser().parse_string("<not xml")


def test_parse_file_and_source(tmp_path):
    f = tmp_path / "r.xml"
    f.write_text(junit('<testcase name="t"/>'))
    r = JUnitParser().parse_file(f)[0]
    assert r.source == str(f)


def test_parse_file_missing_or_empty(tmp_path):
    with pytest.raises(JUnitParseError):
        JUnitParser().parse_file(tmp_path / "nope.xml")
    empty = tmp_path / "empty.xml"
    empty.write_text("")
    with pytest.raises(JUnitParseError):
        JUnitParser().parse_file(empty)


def test_parse_files_concatenates(tmp_path):
    paths = []
    for i in range(3):
        f = tmp_path / f"{i}.xml"
        f.write_text(junit(f'<testcase name="t{i}"/>'))
        paths.append(f)
    assert len(JUnitParser().parse_files(paths)) == 3


def test_env_is_off_unless_properties_are_configured():
    xml = junit('<testcase name="t"/>', python="3.13")
    assert JUnitParser().parse_string(xml)[0].env is None


def test_env_built_from_configured_properties_only():
    xml = junit('<testcase name="t"/>', python="3.13", os="linux", hostname="runner-42")
    r = JUnitParser(env_properties=["python", "os"]).parse_string(xml)[0]
    assert r.env == "python=3.13,os=linux"  # hostname is ignored: it was not asked for


def test_env_none_when_no_configured_property_is_present():
    xml = junit('<testcase name="t"/>')
    assert JUnitParser(env_properties=["python"]).parse_string(xml)[0].env is None


def test_default_env_only_fills_in_when_xml_has_none():
    p = JUnitParser(env_properties=["python"])
    assert p.parse_string(junit('<testcase name="t"/>'), default_env="leg-1")[0].env == "leg-1"
    xml = junit('<testcase name="t"/>', python="3.12")
    assert p.parse_string(xml, default_env="leg-1")[0].env == "python=3.12"


def test_in_job_retry_counts_as_failed_attempt_then_pass():
    from flaky_detector.parsers import JUnitParser
    from tests.conftest import junit

    xml = junit('<testcase classname="a" name="t" time="1.5">'
                '<flakyFailure message="boom">trace line</flakyFailure></testcase>')
    results = JUnitParser().parse_string(xml)
    assert [r.outcome.value for r in results] == ["failed", "passed"]
    assert results[0].message == "boom" and results[0].trace == "trace line"
    assert results[1].time == 1.5
