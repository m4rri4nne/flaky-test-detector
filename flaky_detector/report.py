"""Result files: JSON, CSV and Markdown reports of one analysis."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .scoring import FlakinessRanker, TestScore

FORMATS = ("json", "csv", "md")
_CSV_FIELDS = ["test", "score", "flaky_commits", "commits", "is_flaky", "commits_where_flaky"]


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

    @classmethod
    def build(cls, scores: list[TestScore], ranker: FlakinessRanker, source: str,
              results_parsed: int, now: datetime | None = None) -> "Report":
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
        )

    @property
    def flaky_rate(self) -> float:
        return len(self.flaky) / len(self.tests) if self.tests else 0.0


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
        "tests": [
            {"name": s.name, "score": round(s.score, 4), "commits": s.commits,
             "flaky_commits": s.flaky_commits, "is_flaky": s.name in flaky_names,
             "commits_where_flaky": list(s.commits_where_flaky),
             "error_messages": list(s.error_messages)}
            for s in report.tests
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_csv(report: Report, path: Path) -> None:
    flaky_names = {s.name for s in report.flaky}
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_FIELDS)
        for s in report.tests:
            writer.writerow([s.name, f"{s.score:.4f}", s.flaky_commits, s.commits,
                             str(s.name in flaky_names).lower(), " ".join(s.commits_where_flaky)])


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
        lines += ["| # | Test | Score | Flaky commits |", "|---:|---|---:|---:|"]
        for i, s in enumerate(report.flaky, 1):
            lines.append(f"| {i} | `{_md_cell(s.name)}` | {s.score:.0%} | "
                         f"{s.flaky_commits}/{s.commits} |")
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
