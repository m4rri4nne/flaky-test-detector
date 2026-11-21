"""Parsers for CI test results (currently JUnit XML)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator, Sequence


class Outcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class TestResult:
    """A single test execution in a single CI run."""

    __test__ = False  # keep pytest from trying to collect this class

    name: str  # "<classname>::<name>"
    outcome: Outcome
    commit_sha: str | None
    run_id: str | None
    time: float = 0.0
    message: str | None = None
    source: str | None = None  # file the result came from
    trace: str | None = None  # truncated stack trace of a failure, when the XML has one
    env: str | None = None  # environment key (e.g. "python=3.13,os=linux"); None = not detected

    @property
    def passed(self) -> bool:
        return self.outcome is Outcome.PASSED


class JUnitParseError(ValueError):
    """Raised when a file is not valid JUnit XML."""


class JUnitParser:
    """Parses JUnit XML files into a flat list of :class:`TestResult`.

    ``commit_sha`` and ``run_id`` are read from ``<property>`` elements of the
    ``<testsuite>`` (or of the individual ``<testcase>``, which takes priority).
    Skipped tests are dropped by default since they say nothing about flakiness.

    The environment is opt-in: pass ``env_properties`` (property names, e.g.
    ``["python", "os"]``) and each result gets ``env="python=3.13,os=linux"``
    built from those properties only. Results lacking all of them get ``env=None``.
    Nothing is auto-detected, so a volatile property can't end up in the key by accident.
    """

    COMMIT_PROPERTY = "commit_sha"
    RUN_ID_PROPERTY = "run_id"
    # Surefire / pytest-rerunfailures style: children describing earlier failed attempts.
    RETRY_TAGS = ("flakyFailure", "flakyError", "rerunFailure", "rerunError")
    MAX_TRACE_CHARS = 1000

    def __init__(
        self, include_skipped: bool = False, env_properties: Sequence[str] = ()
    ) -> None:
        self.include_skipped = include_skipped
        self.env_properties = tuple(env_properties)

    # -- public API -------------------------------------------------------

    def parse_file(self, path: str | Path) -> list[TestResult]:
        path = Path(path)
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            raise JUnitParseError(f"{path}: {exc}") from exc
        return list(self._parse_root(root, source=str(path)))

    def parse_string(
        self,
        xml: str | bytes,
        source: str | None = None,
        default_commit_sha: str | None = None,
        default_run_id: str | None = None,
        default_env: str | None = None,
    ) -> list[TestResult]:
        """Parse XML text. The ``default_*`` values fill in what the XML lacks.

        ``default_env`` is only used when no configured env property is present.
        """
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise JUnitParseError(f"{source or '<string>'}: {exc}") from exc
        defaults = {}
        if default_commit_sha:
            defaults[self.COMMIT_PROPERTY] = default_commit_sha
        if default_run_id:
            defaults[self.RUN_ID_PROPERTY] = default_run_id
        return list(
            self._parse_root(root, source=source, defaults=defaults, default_env=default_env)
        )

    def parse_files(self, paths: Iterable[str | Path]) -> list[TestResult]:
        results: list[TestResult] = []
        for path in paths:
            results.extend(self.parse_file(path))
        return results

    # -- internals --------------------------------------------------------

    def _parse_root(
        self,
        root: ET.Element,
        source: str | None,
        defaults: dict[str, str] | None = None,
        default_env: str | None = None,
    ) -> Iterator[TestResult]:
        # Root can be <testsuites> or a bare <testsuite>.
        suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
        for suite in suites:
            suite_props = {**(defaults or {}), **self._properties(suite)}
            for case in suite.findall("testcase"):
                for result in self._parse_case(case, suite_props, source, default_env):
                    if result.outcome is Outcome.SKIPPED and not self.include_skipped:
                        continue
                    yield result

    @staticmethod
    def _properties(element: ET.Element) -> dict[str, str]:
        props = element.find("properties")
        if props is None:
            return {}
        return {
            p.get("name", ""): p.get("value", "")
            for p in props.findall("property")
            if p.get("name")
        }

    def _parse_case(
        self,
        case: ET.Element,
        suite_props: dict[str, str],
        source: str | None,
        default_env: str | None = None,
    ) -> list[TestResult]:
        """One result per failed in-job retry (see ``RETRY_TAGS``), then the final outcome."""
        name = case.get("name")
        if not name:
            return []
        classname = case.get("classname")
        full_name = f"{classname}::{name}" if classname else name

        props = {**suite_props, **self._properties(case)}

        outcome, message, trace = Outcome.PASSED, None, None
        # Order matters: a case with both <error> and <failure> counts as error.
        for tag, kind in (
            ("error", Outcome.ERROR),
            ("failure", Outcome.FAILED),
            ("skipped", Outcome.SKIPPED),
        ):
            node = case.find(tag)
            if node is not None:
                outcome = kind
                message = self._message(node)
                trace = self._trace(node)
                break

        try:
            time = float(case.get("time", 0) or 0)
        except ValueError:
            time = 0.0

        common = dict(
            name=full_name,
            commit_sha=props.get(self.COMMIT_PROPERTY),
            run_id=props.get(self.RUN_ID_PROPERTY),
            source=source,
            env=self._env(props) or default_env,
        )
        # A retried-then-passed test is a failed attempt followed by a pass on the
        # same commit: exactly what flakiness is. Retry attempts carry no timing.
        attempts = [
            TestResult(
                outcome=Outcome.ERROR if tag.endswith("Error") else Outcome.FAILED,
                message=self._message(node), trace=self._trace(node), **common,
            )
            for node in case
            if (tag := node.tag) in self.RETRY_TAGS
        ]
        final = TestResult(outcome=outcome, time=time, message=message, trace=trace, **common)
        return [*attempts, final]

    @staticmethod
    def _message(node: ET.Element) -> str | None:
        return node.get("message") or (node.text or "").strip() or None

    @classmethod
    def _trace(cls, node: ET.Element | None) -> str | None:
        """Stack trace text (the element body), truncated; None if it just repeats the message."""
        text = (node.text or "").strip() if node is not None else ""
        if not text or text == node.get("message"):
            return None
        return text[: cls.MAX_TRACE_CHARS]

    def _env(self, props: dict[str, str]) -> str | None:
        """``name=value`` pairs of the configured env properties that are present."""
        parts = [f"{n}={props[n]}" for n in self.env_properties if props.get(n)]
        return ",".join(parts) or None
