from __future__ import annotations

import pytest

from flaky_detector.parsers import Outcome, TestResult


@pytest.fixture
def make_result():
    """Factory for TestResult rows."""

    def _make(name="a::t", outcome=Outcome.PASSED, sha="c1", run_id="1", **kw):
        return TestResult(name=name, outcome=outcome, commit_sha=sha, run_id=run_id, **kw)

    return _make


def junit(cases: str, sha: str | None = "abc", run_id: str | None = "7") -> str:
    props = ""
    if sha:
        props += f'<property name="commit_sha" value="{sha}"/>'
    if run_id:
        props += f'<property name="run_id" value="{run_id}"/>'
    return (
        f'<testsuites><testsuite name="s"><properties>{props}</properties>'
        f"{cases}</testsuite></testsuites>"
    )
