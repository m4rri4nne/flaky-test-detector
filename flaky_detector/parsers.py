"""Parsers for CI test results (currently JUnit XML)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator


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
    """

    COMMIT_PROPERTY = "commit_sha"
    RUN_ID_PROPERTY = "run_id"

    def __init__(self, include_skipped: bool = False) -> None:
        self.include_skipped = include_skipped

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
    ) -> list[TestResult]:
        """Parse XML text. The ``default_*`` values fill in what the XML lacks."""
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise JUnitParseError(f"{source or '<string>'}: {exc}") from exc
        defaults = {}
        if default_commit_sha:
            defaults[self.COMMIT_PROPERTY] = default_commit_sha
        if default_run_id:
            defaults[self.RUN_ID_PROPERTY] = default_run_id
        return list(self._parse_root(root, source=source, defaults=defaults))

    def parse_files(self, paths: Iterable[str | Path]) -> list[TestResult]:
        results: list[TestResult] = []
        for path in paths:
            results.extend(self.parse_file(path))
        return results

    # -- internals --------------------------------------------------------

    def _parse_root(
        self, root: ET.Element, source: str | None, defaults: dict[str, str] | None = None
    ) -> Iterator[TestResult]:
        # Root can be <testsuites> or a bare <testsuite>.
        suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
        for suite in suites:
            suite_props = {**(defaults or {}), **self._properties(suite)}
            for case in suite.findall("testcase"):
                result = self._parse_case(case, suite_props, source)
                if result is None:
                    continue
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
        self, case: ET.Element, suite_props: dict[str, str], source: str | None
    ) -> TestResult | None:
        name = case.get("name")
        if not name:
            return None
        classname = case.get("classname")
        full_name = f"{classname}::{name}" if classname else name

        props = {**suite_props, **self._properties(case)}

        outcome, message = Outcome.PASSED, None
        # Order matters: a case with both <error> and <failure> counts as error.
        for tag, kind in (
            ("error", Outcome.ERROR),
            ("failure", Outcome.FAILED),
            ("skipped", Outcome.SKIPPED),
        ):
            node = case.find(tag)
            if node is not None:
                outcome = kind
                message = node.get("message") or (node.text or "").strip() or None
                break

        try:
            time = float(case.get("time", 0) or 0)
        except ValueError:
            time = 0.0

        return TestResult(
            name=full_name,
            outcome=outcome,
            commit_sha=props.get(self.COMMIT_PROPERTY),
            run_id=props.get(self.RUN_ID_PROPERTY),
            time=time,
            message=message,
            source=source,
        )
