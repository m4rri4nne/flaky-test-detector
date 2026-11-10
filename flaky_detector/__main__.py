"""Command line entry point: ``python -m flaky_detector analyze <files>``."""

from __future__ import annotations

import argparse
import sys

from .github import GitHubError, fetch_junit_results
from .history import HistoryStore
from .parsers import JUnitParseError, JUnitParser
from .scoring import FlakinessRanker, FlakinessScorer
from .trend import render_html, render_text, summary_line


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
                         help="minimum flakiness score (0-1), default 0.1")
    analyze.add_argument("--min-commits", type=int, default=5,
                         help="ignore tests seen on fewer commits, default 5")
    analyze.add_argument("--save-history", metavar="DB",
                         help="append a snapshot of this analysis to a SQLite file")

    trend = sub.add_parser("trend", help="Show how flakiness evolves across saved snapshots")
    trend.add_argument("--db", required=True, help="SQLite history file")
    trend.add_argument("--format", choices=["text", "html"], default="text")
    trend.add_argument("-o", "--output", help="write the report to this file")
    trend.add_argument("--source", help="only snapshots of this source (e.g. owner/repo)")
    return parser


def run_trend(args: argparse.Namespace) -> int:
    from pathlib import Path

    if not Path(args.db).is_file():
        print(f"error: history file not found: {args.db}", file=sys.stderr)
        return 2
    with HistoryStore(args.db) as store:
        render = render_html if args.format == "html" else render_text
        text = render(store, args.source)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "trend":
        return run_trend(args)

    if not args.files and not args.repo:
        print("error: pass JUnit XML files and/or --repo owner/name", file=sys.stderr)
        return 2

    try:
        results = JUnitParser().parse_files(args.files)
        if args.repo:
            results += fetch_junit_results(args.repo, last_runs=args.last_runs)
        ranker = FlakinessRanker(threshold=args.threshold, min_commits=args.min_commits)
    except (JUnitParseError, GitHubError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    scores = FlakinessScorer().score(results)
    flaky = ranker.flaky(scores)
    if args.save_history:
        with HistoryStore(args.save_history) as store:
            previous = store.snapshots(args.repo or "local")
            snap = store.save(scores, ranker, source=args.repo or "local")
        print(f"Saved snapshot #{snap.id} to {args.save_history}: "
              + summary_line(previous[-1] if previous else None, snap))
    print(f"Parsed {len(results)} results from {len(args.files)} file(s)"
          + (f" and {args.repo}." if args.repo else "."))
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
