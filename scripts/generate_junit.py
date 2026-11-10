"""Generate synthetic JUnit XML files for trying out the detector.

    python scripts/generate_junit.py --commits 40 --runs 3 --out results

Each commit gets several runs (re-runs). Tests have a hidden behaviour:
stable, flaky (random failure rate), broken-on-some-commits (fails in every
run, so it is NOT flaky) or skipped. Output is deterministic for a given --seed.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

MODULES = {
    "tests.checkout.test_payment": 14, "tests.checkout.test_cart": 12,
    "tests.login.test_session": 10, "tests.login.test_oauth": 8,
    "tests.api.test_orders": 16, "tests.api.test_users": 12,
    "tests.db.test_migrations": 6, "tests.search.test_index": 10,
    "tests.notifications.test_email": 8, "tests.utils.test_dates": 14,
}
FLAKY_MESSAGES = [
    "AssertionError: timeout waiting for gateway",
    "ConnectionError: connection reset by peer",
    "AssertionError: expected 200, got 503",
    "TimeoutError: operation timed out after 30s",
    "AssertionError: race condition on shared state",
]


def build_tests(rng: random.Random):
    tests = []
    for module, n in MODULES.items():
        for i in range(1, n + 1):
            roll = rng.random()
            if roll < 0.12:
                kind, p = "flaky", rng.choice([0.05, 0.1, 0.2, 0.35, 0.5])
            elif roll < 0.17:
                kind, p = "broken", rng.uniform(0.1, 0.3)  # share of commits it is broken on
            elif roll < 0.21:
                kind, p = "skipped", 0.0
            else:
                kind, p = "stable", 0.0
            tests.append((module, f"test_{i}", kind, p))
    return tests


def render(commit, run_id, attempt, results, ts):
    fails = sum(1 for r in results if r[1] == "failure")
    errs = sum(1 for r in results if r[1] == "error")
    skips = sum(1 for r in results if r[1] == "skipped")
    out = [
        '<?xml version="1.0" encoding="utf-8"?>', "<testsuites>",
        f'  <testsuite name="pytest" errors="{errs}" failures="{fails}" skipped="{skips}" '
        f'tests="{len(results)}" time="{sum(r[3] for r in results):.3f}" timestamp="{ts}">',
        "    <properties>",
        f'      <property name="commit_sha" value="{commit}"/>',
        f'      <property name="run_id" value="{run_id}"/>',
        "    </properties>",
    ]
    for cls, kind, msg, t, name in results:
        head = f'    <testcase classname="{cls}" name="{name}" time="{t:.3f}"'
        if kind == "pass":
            out.append(head + "/>")
        elif kind == "skipped":
            out.append(head + '><skipped message="requires external service"/></testcase>')
        else:
            out.append(f"{head}><{kind} message={quoteattr(msg)}>{escape(msg)}</{kind}></testcase>")
    out += ["  </testsuite>", "</testsuites>", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commits", type=int, default=40)
    ap.add_argument("--runs", type=int, default=3, help="runs (re-runs) per commit")
    ap.add_argument("--out", default="results")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    tests = build_tests(rng)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run_id = 20000
    written = 0

    for c in range(args.commits):
        sha = f"gen{c:03d}{rng.getrandbits(32):08x}"
        broken_here = {(m, n) for m, n, k, p in tests if k == "broken" and rng.random() < p}
        for attempt in range(1, args.runs + 1):
            run_id += 1
            results = []
            for module, name, kind, p in tests:
                t = rng.uniform(0.005, 2.5)
                if kind == "skipped":
                    results.append((module, "skipped", "", 0.0, name))
                elif (module, name) in broken_here:
                    results.append((module, "failure", "AssertionError: regression in this commit", t, name))
                elif kind == "flaky" and rng.random() < p:
                    tag = "error" if rng.random() < 0.2 else "failure"
                    results.append((module, tag, rng.choice(FLAKY_MESSAGES), t, name))
                else:
                    results.append((module, "pass", "", t, name))
            ts = f"2026-11-{1 + c % 28:02d}T{8 + attempt:02d}:00:00"
            (out / f"run_{sha}_{attempt}.xml").write_text(render(sha, run_id, attempt, results, ts))
            written += 1
    print(f"wrote {written} files ({len(tests)} tests each) to {out}/")


if __name__ == "__main__":
    main()
