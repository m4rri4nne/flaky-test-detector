"""Result files: JSON, CSV and Markdown reports of one analysis."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .parsers import TestResult
from .scoring import FlakinessRanker, TestScore

FORMATS = ("json", "csv", "md")
# A flaky test is only suggested for quarantine when even the pessimistic estimate is this high.
QUARANTINE_LOWER_BOUND = 0.3
_CSV_FIELDS = ["test", "score", "lower_bound", "flaky_commits", "commits", "is_flaky", "commits_where_flaky", "runs"]


@dataclass(frozen=True)
class EnvSummary:
    """How much of the data carried an environment (only meaningful when env is enabled)."""

    with_env: int
    total: int
    distinct: int

    @classmethod
    def of(cls, results: list[TestResult]) -> "EnvSummary":
        envs = [r.env for r in results if r.env]
        return cls(len(envs), len(results), len(set(envs)))

    @property
    def coverage(self) -> float:
        return self.with_env / self.total if self.total else 0.0

    @property
    def looks_too_fine(self) -> bool:
        """Nearly every result has its own env: the key probably contains a per-run value."""
        return self.with_env >= 10 and self.distinct > self.with_env / 2


@dataclass(frozen=True)
class Report:
    """One analysis: every test with enough data (worst first) plus its settings."""

    generated_at: str
    source: str
    threshold: float
    min_commits: int
    results_parsed: int
    tests: tuple[TestScore, ...]  # all eligible tests, worst first
    flaky: tuple[TestScore, ...]  # the subset at/above the threshold
    config_dependent: tuple[TestScore, ...] = ()  # differ across envs, never flaky within one
    env: EnvSummary | None = None  # set only when environment grouping is enabled

    @classmethod
    def build(cls, scores: list[TestScore], ranker: FlakinessRanker, source: str,
              results_parsed: int, now: datetime | None = None,
              env: EnvSummary | None = None) -> "Report":
        eligible = ranker.rank(scores)
        when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return cls(
            generated_at=when.isoformat(timespec="seconds"),
            source=source,
            threshold=ranker.threshold,
            min_commits=ranker.min_commits,
            results_parsed=results_parsed,
            tests=tuple(eligible),
            flaky=tuple(ranker.flaky(eligible)),
            config_dependent=tuple(s for s in eligible if s.config_dependent_commits),
            env=env,
        )

    @property
    def quarantine(self) -> tuple[TestScore, ...]:
        """Flaky tests safe to quarantine: strong evidence and no environment explanation."""
        return tuple(
            s for s in self.flaky
            if s.lower_bound >= QUARANTINE_LOWER_BOUND and not s.config_dependent_commits
        )

    @property
    def flaky_rate(self) -> float:
        return len(self.flaky) / len(self.tests) if self.tests else 0.0


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def render_json(report: Report) -> str:
    flaky_names = {s.name for s in report.flaky}
    data = {
        "generated_at": report.generated_at,
        "source": report.source,
        "threshold": report.threshold,
        "min_commits": report.min_commits,
        "results_parsed": report.results_parsed,
        "tests_analyzed": len(report.tests),
        "flaky_count": len(report.flaky),
        "flaky_rate": round(report.flaky_rate, 4),
        **({"environment": {
            "results_with_env": report.env.with_env,
            "results_total": report.env.total,
            "coverage": round(report.env.coverage, 4),
            "distinct_envs": report.env.distinct,
            "config_dependent_count": len(report.config_dependent),
        }} if report.env else {}),
        "quarantine_suggestions": [s.name for s in report.quarantine],
        "tests": [
            {"name": s.name, "score": round(s.score, 4),
             "lower_bound": round(s.lower_bound, 4), "commits": s.commits,
             "flaky_commits": s.flaky_commits, "is_flaky": s.name in flaky_names,
             "commits_where_flaky": list(s.commits_where_flaky),
             **({"config_dependent_commits": list(s.config_dependent_commits)} if report.env else {}),
             "error_messages": list(s.error_messages),
             "runs": s.runs,
             "runs_where_flaky": dict(s.flaky_commit_runs),
             "duration_median": _round(s.duration_median),
             "duration_p95": _round(s.duration_p95),
             "sample_trace": s.sample_trace}
            for s in report.tests
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def slim_report(data: dict, include_commits: bool = False) -> dict:
    """A JSON report reduced to what the AI agent needs: flaky tests only.

    Keeps the report-level numbers, drops every non-flaky test and (unless asked)
    the per-test commit lists, so the prompt size depends on the flaky tests only.
    """
    drop = () if include_commits else ("commits_where_flaky", "runs_where_flaky")
    return {
        **{k: v for k, v in data.items() if k != "tests"},
        "tests": [
            {k: v for k, v in t.items() if k not in drop}
            for t in data.get("tests", []) if t.get("is_flaky")
        ],
    }


def write_csv(report: Report, path: Path) -> None:
    flaky_names = {s.name for s in report.flaky}
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_FIELDS)
        for s in report.tests:
            writer.writerow([s.name, f"{s.score:.4f}", f"{s.lower_bound:.4f}", s.flaky_commits, s.commits,
                             str(s.name in flaky_names).lower(), " ".join(s.commits_where_flaky), s.runs])


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Report) -> str:
    lines = [
        "# Flaky tests report",
        "",
        f"- Generated: {report.generated_at[:19].replace('T', ' ')} UTC",
        f"- Source: {report.source}",
        f"- Results parsed: {report.results_parsed}",
        f"- Tests analyzed: {len(report.tests)} "
        f"(threshold {report.threshold:g}, min commits {report.min_commits})",
        f"- **Flaky tests: {len(report.flaky)}** ({report.flaky_rate:.1%})",
        "",
    ]
    if not report.flaky:
        lines.append("No flaky tests found. 🎉")
    else:
        lines += ["| # | Test | Score | Lower bound | Flaky commits | Runs |", "|---:|---|---:|---:|---:|---:|"]
        for i, s in enumerate(report.flaky, 1):
            lines.append(f"| {i} | `{_md_cell(s.name)}` | {s.score:.0%} | {s.lower_bound:.0%} | "
                         f"{s.flaky_commits}/{s.commits} | {s.runs} |")
    if report.quarantine:
        lines += ["", "## Quarantine suggestions", "",
                  f"Flaky with a lower bound of at least {QUARANTINE_LOWER_BOUND:.0%} and no "
                  "environment explanation:", ""]
        lines += [f"- `{_md_cell(s.name)}` ({s.lower_bound:.0%}+ over {s.commits} commits)"
                  for s in report.quarantine]
    if report.env:
        lines += ["", "## Environments", "",
                  f"- Results with an environment: {report.env.with_env}/{report.env.total} "
                  f"({report.env.coverage:.0%}), {report.env.distinct} distinct"]
        if not report.config_dependent:
            lines.append("- No config-dependent tests.")
        else:
            lines += ["", "Config-dependent (consistent within each environment, different across "
                      "them; not counted as flaky):", "",
                      "| Test | Commits |", "|---|---:|"]
            for s in report.config_dependent:
                lines.append(f"| `{_md_cell(s.name)}` | {len(s.config_dependent_commits)}/{s.commits} |")
    return "\n".join(lines) + "\n"


def write_reports(report: Report, out_dir: str | Path,
                  formats: tuple[str, ...] = FORMATS) -> list[Path]:
    """Write the requested formats into ``out_dir`` (created if needed)."""
    unknown = set(formats) - set(FORMATS)
    if unknown:
        raise ValueError(f"unknown format(s): {', '.join(sorted(unknown))}")
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(report.generated_at).strftime("%Y%m%dT%H%M%SZ")
    written = []
    for fmt in formats:
        path = directory / f"flaky-report-{stamp}.{fmt}"
        if fmt == "json":
            path.write_text(render_json(report), encoding="utf-8")
        elif fmt == "csv":
            write_csv(report, path)
        else:
            path.write_text(render_markdown(report), encoding="utf-8")
        written.append(path)
    return written
