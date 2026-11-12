"""Command line entry point: ``python -m flaky_detector analyze <files>``."""

from __future__ import annotations

import argparse
import sys

from .github import GitHubError, fetch_junit_results
from .parsers import JUnitParseError, JUnitParser
from .report import FORMATS, Report, write_reports
from .scoring import FlakinessRanker, FlakinessScorer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flaky_detector")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Find flaky tests in JUnit XML files")
    analyze.add_argument("files", nargs="*", help="local JUnit XML files")
    analyze.add_argument("--repo", help="GitHub repository (owner/name); token read from "
                         "GITHUB_TOKEN or .env")
    analyze.add_argument("--last-runs", type=int, default=30,
                         help="number of GitHub Actions runs to analyze, default 30")
    analyze.add_argument("--threshold", type=float, default=0.1,
                         help="minimum Wilson lower bound of the flakiness score (0-1), default 0.1")
    analyze.add_argument("--min-commits", type=int, default=5,
                         help="ignore tests seen on fewer commits, default 5")
    analyze.add_argument("--output-dir", metavar="DIR",
                         help="write result files (JSON, CSV, Markdown) to this directory")
    analyze.add_argument("--formats", default=",".join(FORMATS),
                         help="comma-separated result formats for --output-dir "
                         f"({', '.join(FORMATS)}), default all")
    return parser


def expand_globs(patterns: list[str]) -> list[str]:
    """Expand wildcards ourselves: PowerShell and cmd pass ``*.xml`` through literally."""
    import glob

    files: list[str] = []
    for pattern in patterns:
        if glob.has_magic(pattern):
            matches = sorted(glob.glob(pattern, recursive=True))
            if not matches:
                raise ValueError(f"no files match {pattern}")
            files.extend(matches)
        else:
            files.append(pattern)
    return files


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.files and not args.repo:
        print("error: pass JUnit XML files and/or --repo owner/name", file=sys.stderr)
        return 2

    try:
        args.files = expand_globs(args.files)
        results = JUnitParser().parse_files(args.files)
        if args.repo:
            results += fetch_junit_results(args.repo, last_runs=args.last_runs)
        ranker = FlakinessRanker(threshold=args.threshold, min_commits=args.min_commits)
        formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
        if set(formats) - set(FORMATS):
            raise ValueError(f"--formats must be a subset of {', '.join(FORMATS)}")
    except (JUnitParseError, GitHubError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    scores = FlakinessScorer().score(results)
    flaky = ranker.flaky(scores)
    print(f"Parsed {len(results)} results from {len(args.files)} file(s)"
          + (f" and {args.repo}." if args.repo else "."))
    if args.output_dir:
        report = Report.build(scores, ranker, args.repo or "local", len(results))
        try:
            for path in write_reports(report, args.output_dir, formats):
                print(f"Wrote {path}")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if not flaky:
        print(f"No flaky tests at threshold {args.threshold} "
              f"(min commits {args.min_commits}).")
        return 0

    print(f"{len(flaky)} flaky test(s):")
    for s in flaky:
        print(f"  {s.score:.2f}  {s.name}  ({s.flaky_commits}/{s.commits} commits)")
    return 1  # non-zero so CI can fail on flaky tests


if __name__ == "__main__":
    raise SystemExit(main())
